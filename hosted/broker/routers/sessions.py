# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal
import uuid

from config import settings
from fastapi import APIRouter, Depends, HTTPException
from metrics import OPERATOR_EVICTIONS, ROBOT_EVICTIONS, SESSIONS_BY_STATE
from models.database import async_session, get_db
from models.session import TeleopSession
from pydantic import BaseModel
from services import livekit
from services.auth import get_current_user, get_operator_or_robot, get_robot_owner
from services.cloudflare import CloudflareRealtimeError, CloudflareSessionGoneError, cf_client
from services.livekit import LiveKitError
from services.sdp_utils import extract_audio_track, extract_video_track
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

CMD_CHANNEL_NAME = "cmd_unreliable"
STATE_CHANNEL_NAME = "state_reliable"
# Robot publishes pongs on this channel — CF datachannel routing is strict
# publisher → subscriber per name, so the reverse direction needs its own name
# rather than reusing `state_reliable`.
STATE_BACK_CHANNEL_NAME = "state_reliable_back"
# Own channel so large/bursty map payloads don't head-of-line-block the reliable
# state_back plane (pongs, telemetry).
MAP_CHANNEL_NAME = "map_unreliable"

# channel-name → robot-side SCTP id. Holds both the ids the robot subscribes to
# (cmd, state) and the ids it publishes (state_back, map); heartbeat surfaces
# each under a role-appropriate field name.
_robot_channel_ids: dict[str, dict[str, int]] = {}

# Pending CF renegotiation offers for the ROBOT (audio pull inverts the offerer
# role). Set by the bridge's operator-audio pull, handed out exactly once on the
# next heartbeat ack, answered via /renegotiate-robot. Transient per bridge.
_pending_robot_renegotiations: dict[str, str] = {}

# setdefault is GIL-atomic; never deleted (sessions are bounded).
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    return _session_locks.setdefault(session_id, asyncio.Lock())


_pending_video_renegotiations: set[str] = set()

# Operator liveness: client heartbeats every 5s; reaper drops binding after 20s
# silent (covers ~4 missed heartbeats).
OP_HEARTBEAT_TIMEOUT_SEC = 20
OP_REAPER_INTERVAL_SEC = 10

# Robot liveness: robot heartbeats every ~1s; disconnect after 30s silent.
# Covers blueprint termination without graceful DELETE (process kill, crash).
ROBOT_HEARTBEAT_TIMEOUT_SEC = 30


def _utc(dt: datetime | None) -> datetime | None:
    """Tag naive datetimes as UTC. SQLite doesn't persist tz, so
    DateTime(timezone=True) round-trips as naive; without this the reaper's
    `now(utc) - naive` subtraction TypeErrors and evicts nothing."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


class CreateSessionRequest(BaseModel):
    robot_id: str | None = None
    robot_name: str
    transport: Literal["cloudflare", "livekit"] = "cloudflare"
    sdp_offer: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    cf_session_id: str
    sdp_answer: str
    ice_servers: list[dict]


class LiveKitSessionResponse(BaseModel):
    session_id: str
    transport: str = "livekit"
    url: str
    token: str
    room: str
    role: str | None = None


class JoinSessionRequest(BaseModel):
    role: str = "operator"
    sdp_offer: str | None = None


class JoinSessionResponse(BaseModel):
    cf_session_id: str
    sdp_answer: str
    robot_cf_session_id: str
    ice_servers: list[dict]
    role: str


class BridgeDatachannelResponse(BaseModel):
    cmd_channel_id: int
    state_channel_id: int
    state_back_channel_id: int
    map_channel_id: int
    # Operator answers this via /renegotiate-answer.
    video_offer: str | None = None
    video_status: str = "ok"


class RenegotiateAnswerRequest(BaseModel):
    sdp_answer: str


class HeartbeatRequest(BaseModel):
    rtt_ms: float | None = None
    packet_loss_pct: float | None = None
    video_bitrate_kbps: int | None = None
    command_rate_hz: float | None = None
    safety_state: str = "nominal"


class SessionInfo(BaseModel):
    session_id: str
    robot_id: str
    robot_name: str
    state: str
    transport: str = "cloudflare"
    operator_id: str | None
    rtt_ms: float | None
    packet_loss_pct: float | None
    created_at: datetime


class LeaveRequest(BaseModel):
    reason: str = "user_initiated"


class TurnCredentialsResponse(BaseModel):
    ice_servers: list[dict]


ICE_SERVERS = [{"urls": "stun:stun.cloudflare.com:3478"}]


async def _mint_ice_servers() -> list[dict]:
    if not settings.cf_turn_key_id or not settings.cf_turn_api_token:
        return ICE_SERVERS
    try:
        return await cf_client.generate_ice_servers()
    except Exception:
        log.exception("TURN credential mint failed; falling back to STUN only")
        return ICE_SERVERS


@router.get("/turn-credentials", response_model=TurnCredentialsResponse)
async def turn_credentials(identity: dict = Depends(get_operator_or_robot)):
    return TurnCredentialsResponse(ice_servers=await _mint_ice_servers())


async def _create_livekit_session(
    body: CreateSessionRequest,
    owner_id: str,
    robot_id: str,
    db: AsyncSession,
) -> LiveKitSessionResponse:
    if not settings.livekit_configured:
        raise HTTPException(status_code=503, detail="LiveKit backend not configured")

    session = TeleopSession(
        id=str(uuid.uuid4()),
        robot_id=robot_id,
        owner_id=owner_id,
        robot_name=body.robot_name,
        state="idle",
        transport="livekit",
        last_heartbeat=datetime.now(timezone.utc),  # so reaper's grace window starts now
    )
    room = livekit.room_name(session.id)

    try:
        token = livekit.mint_token(
            identity=f"robot-{session.id}",
            name=body.robot_name,
            room=room,
            can_publish=True,
        )
    except LiveKitError as e:
        raise HTTPException(status_code=503, detail=str(e))

    db.add(session)
    await db.commit()

    return LiveKitSessionResponse(
        session_id=session.id,
        url=settings.livekit_url,
        token=token,
        room=room,
    )


@router.post(
    "",
    response_model=CreateSessionResponse | LiveKitSessionResponse,
    status_code=201,
)
async def create_session(
    body: CreateSessionRequest,
    owner_id: str = Depends(get_robot_owner),
    db: AsyncSession = Depends(get_db),
):
    robot_id = body.robot_id or ""

    # Same robot reconnecting → close its stale session. Scoped to (owner,
    # robot_id) so one robot can't disconnect another's; skipped for unnamed
    # robots (would collapse distinct ones).
    if robot_id:
        existing = await db.execute(
            select(TeleopSession).where(
                TeleopSession.owner_id == owner_id,
                TeleopSession.robot_id == robot_id,
                TeleopSession.state != "disconnected",
            )
        )
        for old in existing.scalars():
            old.state = "disconnected"

    if body.transport == "livekit":
        return await _create_livekit_session(body, owner_id, robot_id, db)

    if not body.sdp_offer:
        raise HTTPException(status_code=422, detail="sdp_offer required for cloudflare transport")

    # CF ignores a `tracks` array on /sessions/new, so only stash the ids here;
    # the actual publish happens later via /tracks/new in bridge_datachannel.
    published_mid: str | None = None
    published_track_name: str | None = None
    video = extract_video_track(body.sdp_offer)
    if video is not None:
        published_mid, published_track_name = video

    try:
        cf_result = await cf_client.create_session(body.sdp_offer)
    except CloudflareRealtimeError as e:
        raise HTTPException(status_code=502, detail=f"Cloudflare error: {e.detail}")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare session create failed ({type(e).__name__}): {e}",
        )

    session = TeleopSession(
        robot_id=robot_id,
        owner_id=owner_id,
        robot_name=body.robot_name,
        state="idle",
        cf_session_id=cf_result["cf_session_id"],
        published_video_mid=published_mid,
        published_video_track_name=published_track_name,
        last_heartbeat=datetime.now(timezone.utc),  # reaper's grace window starts now
    )
    db.add(session)
    try:
        await db.commit()
        await db.refresh(session)
    except Exception:
        # CF has no delete-session; log the leak (auto-reaped when tracks GC).
        log.exception(
            "DB commit failed; leaking cf_session=%s robot=%s owner=%s",
            cf_result["cf_session_id"],
            robot_id,
            owner_id,
        )
        raise HTTPException(status_code=502, detail="Session persist failed")

    return CreateSessionResponse(
        session_id=session.id,
        cf_session_id=cf_result["cf_session_id"],
        sdp_answer=cf_result["sdp_answer"],
        ice_servers=ICE_SERVERS,
    )


@router.post("/{session_id}/heartbeat")
async def heartbeat(
    session_id: str,
    body: HeartbeatRequest,
    owner_id: str = Depends(get_robot_owner),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Session not found")

    session.rtt_ms = body.rtt_ms
    session.packet_loss_pct = body.packet_loss_pct
    session.video_bitrate_kbps = body.video_bitrate_kbps
    session.command_rate_hz = body.command_rate_hz
    session.last_heartbeat = datetime.now(timezone.utc)
    await db.commit()

    if session.transport == "livekit":
        return {"ack": True}

    chan_ids = _robot_channel_ids.get(session_id, {})
    return {
        "ack": True,
        "cmd_channel_subscriber_id": chan_ids.get(CMD_CHANNEL_NAME),
        "state_channel_subscriber_id": chan_ids.get(STATE_CHANNEL_NAME),
        "state_back_channel_publisher_id": chan_ids.get(STATE_BACK_CHANNEL_NAME),
        "map_channel_publisher_id": chan_ids.get(MAP_CHANNEL_NAME),
        # Operator-audio pull offer, handed over once; robot answers via /renegotiate-robot.
        "renegotiate_offer": _pending_robot_renegotiations.pop(session_id, None),
    }


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    owner_id: str = Depends(get_robot_owner),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Session not found")

    async with _session_lock(session_id):
        # CF has no session-delete; close the state_back push (else next
        # reconnect hits repeated_local_track).
        if session.transport == "cloudflare":
            back_ids = [
                i for i in (session.state_back_channel_id, session.map_channel_id) if i is not None
            ]
            if back_ids and session.cf_session_id:
                await cf_client.close_datachannels(session.cf_session_id, back_ids)
            if session.cf_session_id or session.operator_cf_session_id:
                log.info(
                    "delete_session: orphaning CF sessions robot_cf=%s operator_cf=%s",
                    session.cf_session_id,
                    session.operator_cf_session_id,
                )
        session.state = "disconnected"
        session.operator_id = None
        session.operator_cf_session_id = None
        session.state_back_channel_id = None
        session.map_channel_id = None
        session.operator_audio_mid = None
        session.operator_audio_track_name = None
        _robot_channel_ids.pop(session_id, None)
        _pending_video_renegotiations.discard(session_id)
        _pending_robot_renegotiations.pop(session_id, None)
        await db.commit()


def _owns(session: TeleopSession, user: dict) -> bool:
    return user.get("role") == "admin" or session.owner_id == user["sub"]


@router.get("", response_model=list[SessionInfo])
async def list_sessions(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Filtering on freshness here closes the window between robot silence and
    # the reaper flipping state to disconnected.
    fresh = datetime.now(timezone.utc) - timedelta(seconds=ROBOT_HEARTBEAT_TIMEOUT_SEC)
    q = select(TeleopSession).where(
        TeleopSession.state.in_(["idle", "active"]),
        TeleopSession.last_heartbeat.is_not(None),
        TeleopSession.last_heartbeat >= fresh,
    )
    if user.get("role") != "admin":
        q = q.where(TeleopSession.owner_id == user["sub"])
    result = await db.execute(q)
    sessions = result.scalars().all()
    return [
        SessionInfo(
            session_id=s.id,
            robot_id=s.robot_id,
            robot_name=s.robot_name,
            state=s.state,
            transport=s.transport,
            operator_id=s.operator_id,
            rtt_ms=s.rtt_ms,
            packet_loss_pct=s.packet_loss_pct,
            created_at=s.created_at,
        )
        for s in sessions
    ]


async def _claim_operator_slot(db: AsyncSession, session_id: str, user_id: str) -> bool:
    stmt = (
        update(TeleopSession)
        .where(
            TeleopSession.id == session_id,
            TeleopSession.state != "disconnected",
            or_(
                TeleopSession.operator_id.is_(None),
                TeleopSession.operator_id == user_id,
            ),
        )
        .values(
            operator_id=user_id,
            state="active",
            last_operator_heartbeat=datetime.now(timezone.utc),
        )
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def _release_operator_slot(db: AsyncSession, session_id: str, user_id: str) -> None:
    await db.execute(
        update(TeleopSession)
        .where(
            TeleopSession.id == session_id,
            TeleopSession.operator_id == user_id,
        )
        .values(operator_id=None, state="idle")
    )
    await db.commit()


@router.post(
    "/{session_id}/join",
    response_model=JoinSessionResponse | LiveKitSessionResponse,
)
async def join_session(
    session_id: str,
    body: JoinSessionRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or session.state == "disconnected" or not _owns(session, user):
        raise HTTPException(status_code=404, detail="Session not found")
    last_hb = _utc(session.last_heartbeat)
    if last_hb is None or (
        datetime.now(timezone.utc) - last_hb > timedelta(seconds=ROBOT_HEARTBEAT_TIMEOUT_SEC)
    ):
        raise HTTPException(status_code=404, detail="Robot heartbeat stale — reconnect required")
    # cf_session_id can be None while heartbeats still land (post-410
    # invalidation); robot_cf_session_id is typed str, so returning None would
    # trip pydantic → 500. Fail fast with 409.
    if session.transport == "cloudflare" and not session.cf_session_id:
        raise HTTPException(status_code=409, detail="Robot CF session not established")

    user_id = user["sub"]

    # Claim before any transport-layer work; a losing concurrent /join
    # otherwise creates a CF/LiveKit session it can't use.
    if body.role == "operator":
        if not await _claim_operator_slot(db, session_id, user_id):
            current = await db.get(TeleopSession, session_id)
            if not current or current.state == "disconnected":
                raise HTTPException(status_code=404, detail="Session not found")
            raise HTTPException(
                status_code=409,
                detail=f"Session already has operator: {current.operator_id}",
            )
        await db.refresh(session)

    if session.transport == "livekit":
        if not settings.livekit_configured:
            if body.role == "operator":
                await _release_operator_slot(db, session_id, user_id)
            raise HTTPException(status_code=503, detail="LiveKit backend not configured")
        room = livekit.room_name(session.id)
        # LiveKit force-disconnects an existing participant when a second joins
        # with the same identity; the per-viewer uuid suffix keeps a viewer tab
        # from kicking the live operator.
        if body.role == "operator":
            identity = f"op-{user_id}"
        else:
            identity = f"viewer-{user_id}-{uuid.uuid4().hex[:8]}"
        try:
            token = livekit.mint_token(
                identity=identity,
                name=user_id,
                room=room,
                can_publish=False,
            )
        except LiveKitError as e:
            if body.role == "operator":
                await _release_operator_slot(db, session_id, user_id)
            raise HTTPException(status_code=503, detail=str(e))
        return LiveKitSessionResponse(
            session_id=session.id,
            url=settings.livekit_url,
            token=token,
            room=room,
            role=body.role,
        )

    if not body.sdp_offer:
        if body.role == "operator":
            await _release_operator_slot(db, session_id, user_id)
        raise HTTPException(status_code=422, detail="sdp_offer required for cloudflare transport")

    try:
        cf_result = await cf_client.create_session(body.sdp_offer)
    except CloudflareRealtimeError as e:
        if body.role == "operator":
            await _release_operator_slot(db, session_id, user_id)
        raise HTTPException(status_code=502, detail=f"Cloudflare error: {e.detail}")
    except Exception as e:
        if body.role == "operator":
            await _release_operator_slot(db, session_id, user_id)
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare session create failed ({type(e).__name__}): {e}",
        )

    operator_cf_id = cf_result["cf_session_id"]

    if body.role == "operator":
        session.operator_cf_session_id = operator_cf_id
        audio = extract_audio_track(body.sdp_offer)
        session.operator_audio_mid = audio[0] if audio else None
        session.operator_audio_track_name = audio[1] if audio else None
        try:
            await db.commit()
        except Exception:
            log.exception(
                "DB commit failed; leaking operator cf_session=%s session=%s operator=%s",
                operator_cf_id,
                session_id,
                user_id,
            )
            await _release_operator_slot(db, session_id, user_id)
            raise HTTPException(status_code=502, detail="Join persist failed")

    return JoinSessionResponse(
        cf_session_id=operator_cf_id,
        sdp_answer=cf_result["sdp_answer"],
        robot_cf_session_id=session.cf_session_id,
        ice_servers=ICE_SERVERS,
        role=body.role,
    )


# Backoff for the operator video pull. CF's tracks/new returns a per-track
# not_found_track_error when the robot's RTP hasn't reached the SFU yet (a
# propagation race right after connect); retry until the packets are visible.
_PULL_RETRY_DELAYS = (0.3, 0.6, 1.0, 1.5, 2.0)


async def _pull_robot_video(session: TeleopSession) -> tuple[str | None, str]:
    # CF silently ignores a `tracks` array on /sessions/new, so the publisher is
    # registered here via /tracks/new before the operator can pull it. All
    # best-effort — degrade to no-video on failure rather than failing the bridge.
    if not session.published_video_track_name:
        return None, "no_published_track"

    try:
        await cf_client.add_tracks(
            session.cf_session_id,
            [
                {
                    "location": "local",
                    "mid": session.published_video_mid,
                    "trackName": session.published_video_track_name,
                }
            ],
        )
    except Exception as e:
        log.error("video: publish robot track failed session=%s: %r", session.id, e)
        return None, "publish_error"

    for attempt in range(1 + len(_PULL_RETRY_DELAYS)):
        try:
            pull = await cf_client.add_tracks(
                session.operator_cf_session_id,
                [
                    {
                        "location": "remote",
                        "sessionId": session.cf_session_id,
                        "trackName": session.published_video_track_name,
                    }
                ],
            )
        except Exception as e:
            log.error("video: pull failed session=%s: %r", session.id, e)
            return None, "pull_error"

        sd = pull.get("sessionDescription") or {}
        if sd.get("sdp"):
            # Don't gate on requiresImmediateRenegotiation — CF omits it when the
            # operator's recvonly m=video section already existed.
            return sd["sdp"], "ok"

        track_errs = [t.get("errorCode") for t in pull.get("tracks", []) if t.get("errorCode")]
        if "not_found_track_error" in track_errs and attempt < len(_PULL_RETRY_DELAYS):
            await asyncio.sleep(_PULL_RETRY_DELAYS[attempt])
            continue

        log.warning("video: pull gave no offer session=%s errs=%s", session.id, track_errs)
        return None, "no_offer"

    return None, "no_offer"


async def _pull_operator_audio(session: TeleopSession) -> str | None:
    if not session.operator_audio_track_name:
        return None
    try:
        await cf_client.add_tracks(
            session.operator_cf_session_id,
            [
                {
                    "location": "local",
                    "mid": session.operator_audio_mid,
                    "trackName": session.operator_audio_track_name,
                }
            ],
        )
    except Exception as e:
        log.error("audio: publish operator track failed session=%s: %r", session.id, e)
        return None

    for attempt in range(1 + len(_PULL_RETRY_DELAYS)):
        try:
            pull = await cf_client.add_tracks(
                session.cf_session_id,
                [
                    {
                        "location": "remote",
                        "sessionId": session.operator_cf_session_id,
                        "trackName": session.operator_audio_track_name,
                    }
                ],
            )
        except Exception as e:
            log.error("audio: pull onto robot failed session=%s: %r", session.id, e)
            return None

        sd = pull.get("sessionDescription") or {}
        if sd.get("sdp"):
            return sd["sdp"]

        track_errs = [t.get("errorCode") for t in pull.get("tracks", []) if t.get("errorCode")]
        if "not_found_track_error" in track_errs and attempt < len(_PULL_RETRY_DELAYS):
            await asyncio.sleep(_PULL_RETRY_DELAYS[attempt])
            continue

        log.warning("audio: pull gave no offer session=%s errs=%s", session.id, track_errs)
        return None

    return None


@router.post(
    "/{session_id}/bridge-datachannel",
    response_model=BridgeDatachannelResponse,
)
async def bridge_datachannel(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Call after the operator's PC is 'connected' — CF rejects
    /datachannels/new on a half-negotiated session."""
    session = await db.get(TeleopSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.transport != "cloudflare":
        raise HTTPException(status_code=409, detail="bridge-datachannel is cloudflare-only")
    if session.operator_id != user["sub"]:
        raise HTTPException(status_code=403, detail="Not the bound operator")
    if not session.operator_cf_session_id or not session.cf_session_id:
        raise HTTPException(status_code=409, detail="CF sessions not ready")

    async with _session_lock(session_id):
        return await _bridge_datachannel_locked(session, db)


async def _bridge_datachannel_locked(
    session: TeleopSession, db: AsyncSession
) -> BridgeDatachannelResponse:
    # CF requires each /datachannels/new call to be one direction (all local
    # OR all remote) — hence 4 separate calls, don't re-bundle.
    forward_names = [CMD_CHANNEL_NAME, STATE_CHANNEL_NAME]
    # Close prior robot→operator pushes; CF doesn't auto-reap, so re-push would
    # hit repeated_local_track_error.
    stale_back_ids = [
        i for i in (session.state_back_channel_id, session.map_channel_id) if i is not None
    ]
    if stale_back_ids:
        await cf_client.close_datachannels(session.cf_session_id, stale_back_ids)
        session.state_back_channel_id = None
        session.map_channel_id = None
    # Only locals need rollback tracking — remotes don't block re-push with
    # repeated_local_track.
    created_pushes: list[tuple[str, list[int]]] = []

    async def _rollback_pushes() -> None:
        for sid, ids in created_pushes:
            await cf_client.close_datachannels(sid, ids)

    try:
        op_pub = await cf_client.add_datachannels(
            session.operator_cf_session_id,
            [{"location": "local", "dataChannelName": name} for name in forward_names],
        )
        op_pub_ids = {e["dataChannelName"]: int(e["id"]) for e in op_pub}
        created_pushes.append((session.operator_cf_session_id, list(op_pub_ids.values())))

        robot_sub = await cf_client.add_datachannels(
            session.cf_session_id,
            [
                {
                    "location": "remote",
                    "sessionId": session.operator_cf_session_id,
                    "dataChannelName": name,
                }
                for name in forward_names
            ],
        )
        robot_sub_ids = {e["dataChannelName"]: int(e["id"]) for e in robot_sub}

        back_names = [STATE_BACK_CHANNEL_NAME, MAP_CHANNEL_NAME]
        robot_pub = await cf_client.add_datachannels(
            session.cf_session_id,
            [{"location": "local", "dataChannelName": name} for name in back_names],
        )
        robot_pub_ids = {e["dataChannelName"]: int(e["id"]) for e in robot_pub}
        created_pushes.append((session.cf_session_id, list(robot_pub_ids.values())))

        op_sub = await cf_client.add_datachannels(
            session.operator_cf_session_id,
            [
                {
                    "location": "remote",
                    "sessionId": session.cf_session_id,
                    "dataChannelName": name,
                }
                for name in back_names
            ],
        )
        op_sub_ids = {e["dataChannelName"]: int(e["id"]) for e in op_sub}
    except CloudflareSessionGoneError as e:
        # CF reaped a session. Clear the stale id so the next bridge short-circuits
        # on "CF sessions not ready" instead of round-tripping to CF for another
        # 410; return 409 so the client re-provisions rather than treating it as a
        # generic backend failure.
        await _rollback_pushes()
        if e.session_id == session.cf_session_id:
            session.cf_session_id = None
            session.state_back_channel_id = None
            session.map_channel_id = None
            await db.commit()
            log.warning("bridge: robot CF session gone session=%s", session.id)
            raise HTTPException(
                status_code=409,
                detail="Robot CF session expired — waiting for robot to reconnect",
            )
        if e.session_id == session.operator_cf_session_id:
            session.operator_cf_session_id = None
            await db.commit()
            log.warning("bridge: operator CF session gone session=%s", session.id)
            raise HTTPException(
                status_code=409,
                detail="Operator CF session expired — rejoin",
            )
        # Session-gone matching neither stored id: still a re-provision case,
        # not a broker fault — 409 (was an opaque 502; DM-6).
        log.warning(
            "bridge: unmatched CF session gone (cf=%s) session=%s: %s",
            e.session_id,
            session.id,
            e.detail[:200],
        )
        raise HTTPException(
            status_code=409,
            detail="CF session expired — rejoin (robot may need to reconnect)",
        )
    except CloudflareRealtimeError as e:
        await _rollback_pushes()
        # Log server-side — the detail otherwise only reaches the browser console
        # (made the 2026-07-01 bridge 502 hard to attribute).
        log.warning(
            "bridge: CF datachannel bridge failed session=%s: %s", session.id, e.detail[:200]
        )
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare datachannel bridge failed: {e.detail}",
        )
    except (KeyError, TypeError, ValueError) as e:
        await _rollback_pushes()
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare returned malformed DataChannel entry: {e}",
        )
    except Exception as e:
        await _rollback_pushes()
        raise HTTPException(
            status_code=502,
            detail=f"Datachannel bridge failed ({type(e).__name__}): {e}",
        )

    missing = [n for n in forward_names if n not in op_pub_ids or n not in robot_sub_ids]
    for name in (STATE_BACK_CHANNEL_NAME, MAP_CHANNEL_NAME):
        if name not in robot_pub_ids or name not in op_sub_ids:
            missing.append(name)
    if missing:
        await _rollback_pushes()
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare missing DataChannel id for: {', '.join(missing)}",
        )

    _robot_channel_ids[session.id] = {
        **robot_sub_ids,
        STATE_BACK_CHANNEL_NAME: robot_pub_ids[STATE_BACK_CHANNEL_NAME],
        MAP_CHANNEL_NAME: robot_pub_ids[MAP_CHANNEL_NAME],
    }
    # Persist on the row (unlike _robot_channel_ids, these survive operator leave)
    # so the NEXT reconnect can close these stale pushes before re-pushing.
    session.state_back_channel_id = robot_pub_ids[STATE_BACK_CHANNEL_NAME]
    session.map_channel_id = robot_pub_ids[MAP_CHANNEL_NAME]
    await db.commit()

    video_offer, video_status = await _pull_robot_video(session)
    if video_offer:
        _pending_video_renegotiations.add(session.id)
    else:
        _pending_video_renegotiations.discard(session.id)

    # CF's renegotiation offer here is for the ROBOT — stash it for the next
    # heartbeat ack to hand over.
    audio_offer = await _pull_operator_audio(session)
    if audio_offer:
        _pending_robot_renegotiations[session.id] = audio_offer
    else:
        _pending_robot_renegotiations.pop(session.id, None)

    return BridgeDatachannelResponse(
        cmd_channel_id=op_pub_ids[CMD_CHANNEL_NAME],
        state_channel_id=op_pub_ids[STATE_CHANNEL_NAME],
        state_back_channel_id=op_sub_ids[STATE_BACK_CHANNEL_NAME],
        map_channel_id=op_sub_ids[MAP_CHANNEL_NAME],
        video_offer=video_offer,
        video_status=video_status,
    )


@router.post("/{session_id}/renegotiate-answer")
async def renegotiate_answer(
    session_id: str,
    body: RenegotiateAnswerRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.transport != "cloudflare":
        raise HTTPException(status_code=409, detail="renegotiate-answer is cloudflare-only")
    if session.operator_id != user["sub"]:
        raise HTTPException(status_code=403, detail="Not the bound operator")
    if not session.operator_cf_session_id:
        raise HTTPException(status_code=409, detail="Operator CF session not ready")
    if session_id not in _pending_video_renegotiations:
        raise HTTPException(
            status_code=409,
            detail="No pending video renegotiation — re-bridge to get a fresh offer",
        )

    # Consume the marker either way — a stale answer won't pass CF on retry.
    _pending_video_renegotiations.discard(session_id)
    try:
        await cf_client.renegotiate(session.operator_cf_session_id, body.sdp_answer)
    except CloudflareRealtimeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare renegotiate failed: {e.detail}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare renegotiate failed ({type(e).__name__}): {e}",
        )
    return {"ok": True}


@router.post("/{session_id}/renegotiate-robot")
async def renegotiate_robot(
    session_id: str,
    body: RenegotiateAnswerRequest,
    owner_id: str = Depends(get_robot_owner),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or session.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.transport != "cloudflare":
        raise HTTPException(status_code=409, detail="renegotiate-robot is cloudflare-only")
    if not session.cf_session_id:
        raise HTTPException(status_code=409, detail="Robot CF session not ready")
    try:
        await cf_client.renegotiate(session.cf_session_id, body.sdp_answer)
    except CloudflareRealtimeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare renegotiate failed: {e.detail}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Cloudflare renegotiate failed ({type(e).__name__}): {e}",
        )
    return {"ok": True}


@router.post("/{session_id}/op-heartbeat")
async def op_heartbeat(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.operator_id != user["sub"]:
        raise HTTPException(status_code=403, detail="Not the bound operator")
    session.last_operator_heartbeat = datetime.now(timezone.utc)
    await db.commit()
    return {"ack": True}


@router.post("/{session_id}/leave")
async def leave_session(
    session_id: str,
    body: LeaveRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or not _owns(session, user):
        raise HTTPException(status_code=404, detail="Session not found")

    user_id = user["sub"]

    if session.operator_id == user_id:
        # reason distinguishes the disconnect button (user_initiated) from a page
        # reload (pagehide) in the journal — needed for the 2026-07-01 churn hunt.
        log.info(
            "operator leave: session=%s operator=%s reason=%s",
            session_id,
            user_id,
            body.reason,
        )
        async with _session_lock(session_id):
            session.operator_id = None
            session.operator_cf_session_id = None
            session.operator_audio_mid = None
            session.operator_audio_track_name = None
            session.state = "idle"
            _robot_channel_ids.pop(session_id, None)
            _pending_video_renegotiations.discard(session_id)
            _pending_robot_renegotiations.pop(session_id, None)
            await db.commit()

    return {"session_id": session_id, "state": session.state}


@router.get("/{session_id}/status", response_model=SessionInfo)
async def session_status(
    session_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(TeleopSession, session_id)
    if not session or not _owns(session, user):
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionInfo(
        session_id=session.id,
        robot_id=session.robot_id,
        robot_name=session.robot_name,
        state=session.state,
        transport=session.transport,
        operator_id=session.operator_id,
        rtt_ms=session.rtt_ms,
        packet_loss_pct=session.packet_loss_pct,
        created_at=session.created_at,
    )


async def _reap_stale_operators() -> None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=OP_HEARTBEAT_TIMEOUT_SEC)
    async with async_session() as db:
        stale = (
            (
                await db.execute(
                    select(TeleopSession).where(
                        TeleopSession.state == "active",
                        TeleopSession.last_operator_heartbeat.is_not(None),
                        TeleopSession.last_operator_heartbeat < threshold,
                    )
                )
            )
            .scalars()
            .all()
        )
        for s in stale:
            async with _session_lock(s.id):
                # Re-read under the lock: an op-heartbeat can land between the
                # SELECT and here on a different db session. Without this
                # refresh + re-check we'd commit the stale row and evict a live
                # operator.
                await db.refresh(s)
                last_hb = _utc(s.last_operator_heartbeat)
                if s.state != "active" or last_hb is None or last_hb >= threshold:
                    continue
                idle = (datetime.now(timezone.utc) - last_hb).total_seconds()
                log.warning(
                    "reaping stale operator session=%s operator=%s idle_for=%.1fs",
                    s.id,
                    s.operator_id,
                    idle,
                )
                s.operator_id = None
                s.operator_cf_session_id = None
                s.operator_audio_mid = None
                s.operator_audio_track_name = None
                s.state = "idle"
                s.last_operator_heartbeat = None
                _robot_channel_ids.pop(s.id, None)
                _pending_video_renegotiations.discard(s.id)
                _pending_robot_renegotiations.pop(s.id, None)
                await db.commit()
                OPERATOR_EVICTIONS.inc()


async def _reap_stale_robots() -> None:
    threshold = datetime.now(timezone.utc) - timedelta(seconds=ROBOT_HEARTBEAT_TIMEOUT_SEC)
    async with async_session() as db:
        stale = (
            (
                await db.execute(
                    select(TeleopSession).where(
                        TeleopSession.state != "disconnected",
                        TeleopSession.last_heartbeat.is_not(None),
                        TeleopSession.last_heartbeat < threshold,
                    )
                )
            )
            .scalars()
            .all()
        )
        for s in stale:
            async with _session_lock(s.id):
                # Re-read under the lock (see _reap_stale_operators): without it
                # we'd disconnect a live robot, and since heartbeat never resets
                # state it would stay 'disconnected' (invisible in list_sessions)
                # forever while still heartbeating 200.
                await db.refresh(s)
                last_hb = _utc(s.last_heartbeat)
                if s.state == "disconnected" or last_hb is None or last_hb >= threshold:
                    continue
                idle = (datetime.now(timezone.utc) - last_hb).total_seconds()
                log.warning(
                    "reaping stale robot session=%s robot=%s idle_for=%.1fs",
                    s.id,
                    s.robot_id,
                    idle,
                )
                reap_ids = [i for i in (s.state_back_channel_id, s.map_channel_id) if i is not None]
                if s.transport == "cloudflare" and reap_ids and s.cf_session_id:
                    await cf_client.close_datachannels(s.cf_session_id, reap_ids)
                s.state = "disconnected"
                s.operator_id = None
                s.operator_cf_session_id = None
                s.state_back_channel_id = None
                s.map_channel_id = None
                s.operator_audio_mid = None
                s.operator_audio_track_name = None
                s.last_operator_heartbeat = None
                _robot_channel_ids.pop(s.id, None)
                _pending_video_renegotiations.discard(s.id)
                _pending_robot_renegotiations.pop(s.id, None)
                await db.commit()
                ROBOT_EVICTIONS.inc()


async def _refresh_session_gauge() -> None:
    async with async_session() as db:
        rows = (
            await db.execute(
                select(TeleopSession.state, func.count()).group_by(TeleopSession.state)
            )
        ).all()
    counts = dict(rows)
    for state_name in ("idle", "active", "disconnected"):
        SESSIONS_BY_STATE.labels(state_name).set(counts.get(state_name, 0))


async def operator_reaper_loop() -> None:
    """Launched from main.py lifespan."""
    while True:
        try:
            await _reap_stale_operators()
            await _reap_stale_robots()
            await _refresh_session_gauge()
        except Exception:
            log.exception("session reaper failed")
        await asyncio.sleep(OP_REAPER_INTERVAL_SEC)
