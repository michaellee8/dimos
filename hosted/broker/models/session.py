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

from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped

from models.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TeleopSession(Base):
    __tablename__ = "teleop_sessions"

    id: Mapped[str] = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    robot_id: Mapped[str] = Column(String, nullable=False, index=True)
    robot_name: Mapped[str] = Column(String, nullable=False)
    # Tenant boundary: the API key's owner. Visibility/auth filter on this.
    owner_id: Mapped[str | None] = Column(String, nullable=True, index=True)
    state: Mapped[str] = Column(String, default="idle")  # idle | active | disconnected
    # Backend for this session: "cloudflare" (default) | "livekit". Set at
    # create_session; drives the transport-specific branches.
    transport: Mapped[str] = Column(String, nullable=False, default="cloudflare")
    cf_session_id: Mapped[str] = Column(String, nullable=True)

    published_video_mid: Mapped[str | None] = Column(String, nullable=True)
    published_video_track_name: Mapped[str | None] = Column(String, nullable=True)

    # Set on the first bridge and reused on operator reconnect — CF keeps the
    # local push alive on the (persistent) robot session, so re-pushing errors
    # repeated_local_track. Lives here (not the operator-cleared
    # _robot_channel_ids map) so it survives operator leave/rejoin.
    state_back_channel_id: Mapped[int | None] = Column(Integer, nullable=True)
    # Same stale-push story as state_back for the robot→operator map channel.
    map_channel_id: Mapped[int | None] = Column(Integer, nullable=True)
    operator_audio_mid: Mapped[str | None] = Column(String, nullable=True)
    operator_audio_track_name: Mapped[str | None] = Column(String, nullable=True)

    operator_id: Mapped[str | None] = Column(String, nullable=True)
    operator_cf_session_id: Mapped[str | None] = Column(String, nullable=True)

    rtt_ms: Mapped[float | None] = Column(Float, nullable=True)
    packet_loss_pct: Mapped[float | None] = Column(Float, nullable=True)
    video_bitrate_kbps: Mapped[int | None] = Column(Integer, nullable=True)
    command_rate_hz: Mapped[float | None] = Column(Float, nullable=True)

    created_at: Mapped[datetime] = Column(DateTime(timezone=True), default=_utcnow)
    last_heartbeat: Mapped[datetime | None] = Column(DateTime(timezone=True), nullable=True)
    # Refreshed by /op-heartbeat; a reaper evicts silent-drop operators.
    last_operator_heartbeat: Mapped[datetime | None] = Column(
        DateTime(timezone=True), nullable=True
    )
