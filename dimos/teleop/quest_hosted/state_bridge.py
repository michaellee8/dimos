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

"""Teleop control-plane bridge (transport-world).

Two jobs, both translating between the operator's JSON control plane and DimOS:

* **Inbound state plane** (``state_reliable`` JSON): ``video_stats`` →
  typed ``Out[VideoStats]`` (recorders pick it up); ``clock_report`` logged.
  Clock-sync ``ping`` is answered inline by ``BrokerProvider`` (lower latency
  than a module hop), not here.

* **Command-plane health** (robot → operator): a raw-bytes tap on
  ``cmd_unreliable`` reads the wire ``Header`` (``stamp`` + ``seq`` + size —
  no change to ``TwistStamped``) into a rolling ``LiveStreamStats`` window;
  a timer publishes ``robot_telemetry`` JSON on ``state_reliable_back`` so the
  operator HUD can show latency/jitter/loss the operator can't measure from
  its own send side.

Blueprint wiring::

    autoconnect(..., TeleopStateBridge.blueprint()).transports({
        ("state_json",    bytes): CloudflareTransport("state_reliable"),
        ("cmd_raw",       bytes): CloudflareTransport("cmd_unreliable"),
        ("telemetry_out", bytes): CloudflareTransport("state_reliable_back"),
    })

Together with the deprecated ``HostedTeleopModule``'s removal this restores
the full ``state_reliable``/``state_reliable_back`` parity in the transport
world.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.teleop.utils.stream_stats import LiveStreamStats
from dimos.teleop.utils.video_stats import VideoStats
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class TeleopStateBridgeConfig(ModuleConfig):
    telemetry_hz: float = 3.0  # robot → operator HUD command-plane stats


class TeleopStateBridge(Module):
    """Operator JSON control plane ↔ typed DimOS streams + command-plane health."""

    config: TeleopStateBridgeConfig

    # Inbound state plane (operator → robot), raw JSON bytes.
    state_json: In[bytes]
    # Raw command bytes (operator → robot) — stats tap only; the typed cmd_vel
    # decode is a separate transport on the same channel.
    cmd_raw: In[bytes]
    # Republished operator video health (recorders subscribe).
    video_stats: Out[VideoStats]
    # robot → operator telemetry JSON (state_reliable_back).
    telemetry_out: Out[bytes]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cmd_stats = LiveStreamStats()
        self._telemetry_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @rpc
    def start(self) -> None:
        super().start()
        self._stop_event.clear()
        # Manual sync subscribes (not async handle_*): the keep-latest mailbox
        # would drop messages when several land close together, and parsing /
        # header-peeking is cheap enough for the transport callback.
        for stream, cb in ((self.state_json, self._on_state_json), (self.cmd_raw, self._on_cmd_raw)):
            unsub = stream.subscribe(cb)
            self.register_disposable(Disposable(unsub))
        self._start_telemetry()

    @rpc
    def stop(self) -> None:
        self._stop_event.set()
        if self._telemetry_thread is not None:
            self._telemetry_thread.join(timeout=2.0)
            self._telemetry_thread = None
        super().stop()

    # ─── Inbound state plane ─────────────────────────────────────────

    def _on_state_json(self, data: Any) -> None:
        if isinstance(data, str):
            data = data.encode()
        if not data.startswith(b"{"):
            return  # not JSON (future LCM telemetry on this channel)
        try:
            msg = json.loads(data)
        except ValueError:
            logger.warning("state_reliable: malformed JSON: %r", data[:80])
            return

        kind = msg.get("type")
        if kind == "video_stats":
            self.video_stats.publish(VideoStats.from_dict(msg))
        elif kind == "clock_report":
            rtt = msg.get("rtt_ms")
            off = msg.get("offset_ms")
            logger.info(
                "clock-sync: operator rtt=%.1fms offset=%.1fms",
                float(rtt) if rtt is not None else float("nan"),
                float(off) if off is not None else float("nan"),
            )
        # ping is answered by BrokerProvider; anything else is a future
        # control-plane message this version doesn't know — ignore.

    # ─── Command-plane health ────────────────────────────────────────

    def _on_cmd_raw(self, data: Any) -> None:
        """Peek the wire Header (stamp + seq) for command-plane stats.

        Reads what the operator already puts on the wire — no TwistStamped
        change. ``ts`` is operator-clock-corrected (so recv minus ts = one-way
        latency); ``seq`` drives loss/reorder.
        """
        if isinstance(data, str):
            data = data.encode()
        try:
            from dimos_lcm.geometry_msgs import TwistStamped as LCMTwistStamped

            lcm = LCMTwistStamped.lcm_decode(data)
            ts = lcm.header.stamp.sec + lcm.header.stamp.nsec / 1_000_000_000
            seq = lcm.header.seq
        except Exception:
            return  # foreign / undecodable frame on the channel — skip
        self._cmd_stats.record(ts, seq=seq, nbytes=len(data))

    def _start_telemetry(self) -> None:
        def runner() -> None:
            interval = 1.0 / max(self.config.telemetry_hz, 0.1)
            while not self._stop_event.is_set():
                snap = self._cmd_stats.snapshot()
                if snap is not None:
                    payload = json.dumps(
                        {"type": "robot_telemetry", "cmd": snap, "robot_ts": time.time()}
                    )
                    try:
                        self.telemetry_out.publish(payload.encode())
                    except Exception:
                        logger.debug("telemetry publish failed", exc_info=True)
                self._stop_event.wait(interval)

        self._telemetry_thread = threading.Thread(
            target=runner, daemon=True, name="TeleopStateBridgeTelemetry"
        )
        self._telemetry_thread.start()


__all__ = ["TeleopStateBridge", "TeleopStateBridgeConfig"]
