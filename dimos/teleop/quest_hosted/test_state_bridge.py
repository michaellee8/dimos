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

"""Unit tests for TeleopStateBridge's JSON → typed-stream dispatch."""

from __future__ import annotations

import json
import time
from typing import cast
from unittest.mock import MagicMock

import pytest

from dimos.teleop.quest_hosted.state_bridge import TeleopStateBridge
from dimos.teleop.utils.stream_stats import LiveStreamStats
from dimos.teleop.utils.video_stats import VideoStats


@pytest.fixture
def bridge() -> TeleopStateBridge:
    """Bare bridge with mocked Out streams + a real stats accumulator."""
    b = TeleopStateBridge.__new__(TeleopStateBridge)
    b.video_stats = MagicMock()  # type: ignore[assignment]
    b.telemetry_out = MagicMock()  # type: ignore[assignment]
    b._cmd_stats = LiveStreamStats()
    return b


def _publish_mock(bridge: TeleopStateBridge) -> MagicMock:
    return cast("MagicMock", bridge.video_stats).publish  # type: ignore[no-any-return]


def _lcm_twist_bytes(ts: float, seq: int) -> bytes:
    """Encode a TwistStamped on the wire the way the operator does — with seq
    in the Header (which the dimos TwistStamped doesn't surface)."""
    from dimos_lcm.geometry_msgs import TwistStamped as LCMTwistStamped

    m = LCMTwistStamped()
    m.header.stamp.sec = int(ts)
    m.header.stamp.nsec = int((ts - int(ts)) * 1_000_000_000)
    m.header.frame_id = "keyboard"
    m.header.seq = seq
    return m.lcm_encode()  # type: ignore[no-any-return]


def test_video_stats_republished_typed(bridge: TeleopStateBridge) -> None:
    payload = {
        "type": "video_stats",
        "ts": 123.0,
        "fps": 29.5,
        "kbps": 2100.0,
        "width": 1280,
        "height": 720,
    }
    bridge._on_state_json(json.dumps(payload).encode())

    _publish_mock(bridge).assert_called_once()
    stats = _publish_mock(bridge).call_args[0][0]
    assert isinstance(stats, VideoStats)
    assert stats.fps == 29.5
    assert stats.width == 1280


def test_str_payload_accepted(bridge: TeleopStateBridge) -> None:
    """aiortc may deliver str on a DataChannel; both must work."""
    bridge._on_state_json('{"type":"video_stats","fps":15.0}')
    assert _publish_mock(bridge).call_args[0][0].fps == 15.0


def test_clock_report_logged_not_published(bridge: TeleopStateBridge) -> None:
    bridge._on_state_json(b'{"type":"clock_report","rtt_ms":42.0,"offset_ms":-3.0}')
    _publish_mock(bridge).assert_not_called()


def test_ping_ignored(bridge: TeleopStateBridge) -> None:
    """Pings are the provider's job — the bridge must not react."""
    bridge._on_state_json(b'{"type":"ping","client_ts":1.0}')
    _publish_mock(bridge).assert_not_called()


def test_unknown_type_ignored(bridge: TeleopStateBridge) -> None:
    bridge._on_state_json(b'{"type":"mode_switch","mode":"arm"}')
    _publish_mock(bridge).assert_not_called()


def test_non_json_binary_ignored(bridge: TeleopStateBridge) -> None:
    bridge._on_state_json(b"\x00\x01lcm-ish")
    _publish_mock(bridge).assert_not_called()


def test_malformed_json_dropped(bridge: TeleopStateBridge) -> None:
    bridge._on_state_json(b"{not json")
    _publish_mock(bridge).assert_not_called()


# ─── command-plane stats (cmd_raw tap) ──────────────────────────────


def test_cmd_raw_reads_wire_header(bridge: TeleopStateBridge) -> None:
    """Header seq+stamp are read off the wire — no TwistStamped change."""
    now = time.time()
    for i in range(5):
        bridge._on_cmd_raw(_lcm_twist_bytes(now + i * 0.05, seq=i))
    snap = bridge._cmd_stats.snapshot()
    assert snap is not None
    assert snap["loss_pct"] == 0.0  # contiguous seqs
    assert snap["rate_hz"] is not None
    assert snap["throughput_bps"] is not None


def test_cmd_raw_loss_from_seq_gap(bridge: TeleopStateBridge) -> None:
    now = time.time()
    for seq in (0, 1, 3, 4, 5):  # seq 2 dropped → 1/6 missing in [0,5]
        bridge._on_cmd_raw(_lcm_twist_bytes(now + seq * 0.05, seq=seq))
    snap = bridge._cmd_stats.snapshot()
    assert snap is not None
    assert snap["loss_pct"] == pytest.approx(100.0 / 6.0, abs=0.1)


def test_cmd_raw_str_payload_accepted(bridge: TeleopStateBridge) -> None:
    bridge._on_cmd_raw(_lcm_twist_bytes(time.time(), seq=0))
    bridge._on_cmd_raw(_lcm_twist_bytes(time.time(), seq=1))
    assert bridge._cmd_stats.snapshot() is not None


def test_cmd_raw_garbage_ignored(bridge: TeleopStateBridge) -> None:
    """Undecodable frame must not raise or pollute the window."""
    bridge._on_cmd_raw(b"\xff\xfe not lcm")
    assert bridge._cmd_stats.snapshot() is None  # nothing recorded


def test_telemetry_payload_shape(bridge: TeleopStateBridge) -> None:
    """robot_telemetry JSON matches what the web HUD parses."""
    now = time.time()
    for i in range(4):
        bridge._on_cmd_raw(_lcm_twist_bytes(now + i * 0.05, seq=i))
    snap = bridge._cmd_stats.snapshot()
    assert snap is not None
    payload = json.dumps({"type": "robot_telemetry", "cmd": snap})
    parsed = json.loads(payload)
    assert parsed["type"] == "robot_telemetry"
    assert "latency_ms" in parsed["cmd"]
    assert "loss_pct" in parsed["cmd"]
