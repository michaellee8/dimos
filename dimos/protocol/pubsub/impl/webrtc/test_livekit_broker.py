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

"""Unit tests for the livekit_broker pieces that don't need the SDK.

The provider itself requires the optional ``livekit`` package and a broker —
covered by the opt-in hardware/e2e path. The frame conversion is pure numpy
and runs everywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.protocol.pubsub.impl.webrtc.providers.livekit_broker import (
    LIVEKIT_AVAILABLE,
    LiveKitBrokerConfig,
    _image_to_rgba,
)


def _img(data: np.ndarray, fmt: ImageFormat) -> Image:
    return Image(data=data, format=fmt, frame_id="t")


def test_rgb_gains_opaque_alpha() -> None:
    rgb = np.zeros((2, 3, 3), np.uint8)
    rgb[..., 0] = 10  # R
    w, h, buf = _image_to_rgba(_img(rgb, ImageFormat.RGB))
    assert (w, h) == (3, 2)
    assert len(buf) == 2 * 3 * 4
    assert buf[0] == 10 and buf[3] == 255  # R kept, alpha added


def test_bgra_channels_swap_to_rgba() -> None:
    bgra = np.zeros((1, 1, 4), np.uint8)
    bgra[0, 0] = (1, 2, 3, 4)  # B G R A
    _, _, buf = _image_to_rgba(_img(bgra, ImageFormat.BGRA))
    assert buf == bytes((3, 2, 1, 4))  # → R G B A


def test_bgr_default_path_swaps_to_rgb() -> None:
    bgr = np.zeros((1, 1, 3), np.uint8)
    bgr[0, 0] = (5, 6, 7)  # B G R
    _, _, buf = _image_to_rgba(_img(bgr, ImageFormat.BGR))
    assert buf == bytes((7, 6, 5, 255))


def test_gray_replicates_channels() -> None:
    g = np.full((2, 2), 9, np.uint8)
    _, _, buf = _image_to_rgba(_img(g, ImageFormat.GRAY))
    assert buf[:4] == bytes((9, 9, 9, 255))


def test_gray16_scales_not_truncates() -> None:
    g16 = np.full((1, 1), 0xFF00, np.uint16)
    _, _, buf = _image_to_rgba(_img(g16, ImageFormat.GRAY16))
    assert buf[0] == 0xFF  # >>8, not & 0xFF (which would give 0)


def test_float_image_scales_not_truncates() -> None:
    f = np.full((1, 1, 3), 1.0, np.float32)  # normalized white
    _, _, buf = _image_to_rgba(_img(f, ImageFormat.RGB))
    assert buf[:3] == bytes((255, 255, 255))  # scaled, not truncated to 0


@pytest.mark.skipif(not LIVEKIT_AVAILABLE, reason="livekit extra not installed")
def test_provider_requires_api_key() -> None:
    with pytest.raises(RuntimeError, match="api_key required"):
        LiveKitBrokerConfig()._create()


def _bare_provider() -> object:
    """A provider with just the state _dispatch touches (no room / SDK)."""
    import threading

    from dimos.protocol.pubsub.impl.webrtc.providers.livekit_broker import LiveKitBrokerProvider

    p = object.__new__(LiveKitBrokerProvider)
    p._lock = threading.RLock()
    p._callbacks = {}
    return p


def test_dispatch_drops_non_inbound_topic() -> None:
    """A remote packet on a robot-outbound topic must not reach subscribers."""
    p = _bare_provider()
    got: list[bytes] = []
    p._callbacks = {"state_reliable_back": [lambda data, _t: got.append(data)]}
    packet = SimpleNamespace(topic="state_reliable_back", data=b"spoofed")

    p._dispatch(packet)  # type: ignore[attr-defined]

    assert got == []  # dropped, never fanned out


def test_dispatch_delivers_inbound_topic() -> None:
    p = _bare_provider()
    got: list[bytes] = []
    p._callbacks = {"cmd_unreliable": [lambda data, _t: got.append(data)]}
    packet = SimpleNamespace(topic="cmd_unreliable", data=b"drive")

    p._dispatch(packet)  # type: ignore[attr-defined]

    assert got == [b"drive"]


@pytest.mark.skipif(not LIVEKIT_AVAILABLE, reason="livekit extra not installed")
def test_video_encoding_copyfrom_does_not_raise() -> None:
    """TrackPublishOptions.video_encoding is a protobuf field — CopyFrom works,
    direct assignment raises. Guards against regressing to the broken form."""
    from livekit import rtc

    opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
    opts.video_encoding.CopyFrom(rtc.VideoEncoding(max_bitrate=3_000_000, max_framerate=30.0))
    assert opts.video_encoding.max_bitrate == 3_000_000
