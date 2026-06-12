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

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from dimos.memory2.backend import Backend
from dimos.memory2.blobstore.sqlite import SqliteBlobStore
from dimos.memory2.codecs.pickle import PickleCodec
from dimos.memory2.observationstore.sqlite import SqliteObservationStore
from dimos.memory2.store.sqlite import SqliteStore
from dimos.memory2.type.observation import _UNLOADED
from dimos.memory2.video.h264 import (
    H264FrameIndexStore,
    H264ImagePayloadStrategy,
    H264ImageStorageConfig,
    h264_image_payload_strategy_from_any,
    storage_config_from_any,
)
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.VideoPacket import VideoPacket
from dimos.protocol.video.h264 import UnsupportedVideoImageError, VideoDecodeGapError


class FakeH264CodecAdapter:
    def encode_image(self, image: Image, *, force_keyframe: bool) -> tuple[bytes, int]:
        return image.data.tobytes(), int(image.ts * 1000)

    def decode_packet(self, packet: VideoPacket) -> Image:
        channels = 1 if packet.format == ImageFormat.GRAY.value else 3
        shape = (
            (packet.height, packet.width)
            if channels == 1
            else (packet.height, packet.width, channels)
        )
        arr = np.frombuffer(packet.data, dtype=np.uint8).copy().reshape(shape)
        return Image.from_numpy(
            arr, format=ImageFormat(packet.format), frame_id=packet.frame_id, ts=packet.ts
        )


def _image(seq: int, fmt: ImageFormat = ImageFormat.RGB) -> Image:
    data = np.full((2, 2, 3), seq, dtype=np.uint8)
    if fmt == ImageFormat.GRAY:
        data = np.full((2, 2), seq, dtype=np.uint8)
    return Image.from_numpy(data, format=fmt, frame_id="cam", ts=float(seq))


def _make_backend(
    conn: sqlite3.Connection, *, config: H264ImageStorageConfig | None = None
) -> Backend[Image]:
    frame_index = H264FrameIndexStore(conn)
    strategy = H264ImagePayloadStrategy(
        storage_config=config or H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter()),
        frame_index=frame_index,
    )
    blob_store = SqliteBlobStore(conn=conn)
    obs_store = SqliteObservationStore(
        conn=conn, name="cam", codec=PickleCodec(), blob_store_conn_match=False, page_size=256
    )
    backend = Backend(
        metadata_store=obs_store,
        codec=PickleCodec(),
        data_type=Image,
        blob_store=blob_store,
        payload_strategy=strategy,
    )
    backend.start()
    return backend


def test_storage_config_parse_and_serialize() -> None:
    config = H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
    raw = config.serialize()
    parsed = H264ImageStorageConfig.parse(raw)
    assert parsed.mode == "h264"
    assert parsed.codec == config.codec
    assert storage_config_from_any(raw) == H264ImageStorageConfig(codec=config.codec)
    assert isinstance(h264_image_payload_strategy_from_any(raw), H264ImagePayloadStrategy)
    assert storage_config_from_any({"mode": "jpeg", "codec": raw["codec"]}) is None


def test_store_creates_h264_backend_from_config(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "h264.db"))
    backend = store._create_backend(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(
            storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
        ),
    )
    assert isinstance(backend, Backend)
    assert isinstance(backend.payload_strategy, H264ImagePayloadStrategy)
    assert backend.payload_strategy.storage_config.mode == "h264"
    assert isinstance(backend.payload_strategy.storage_config.codec_adapter, FakeH264CodecAdapter)


def test_h264_image_stream_keeps_default_jpeg_compatibility(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "jpeg.db"))
    stream = store.stream("rgb", Image)
    obs = stream.append(_image(1))
    assert obs.data.format == ImageFormat.RGB
    assert store.stream("rgb").count() == 1


def test_h264_one_observation_and_one_blob_per_frame(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "frames.db"))
    backend = _make_backend(conn)
    from dimos.memory2.type.observation import Observation

    stored = backend.append(Observation(data_type=Image, _data=_image(1)))
    assert stored.id == 1
    assert backend.blob_store is not None
    assert backend.blob_store.get("cam", 1)
    assert isinstance(backend.payload_strategy, H264ImagePayloadStrategy)
    assert backend.payload_strategy.frame_index is not None
    assert len(backend.payload_strategy.frame_index.rows("cam")) == 1


def test_h264_persistent_gop_index_and_lazy_decode(tmp_path) -> None:
    db = tmp_path / "gop.db"
    with SqliteStore(path=str(db)) as store:
        stream = store.stream(
            "cam",
            Image,
            payload_strategy=H264ImagePayloadStrategy(
                storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
            ),
        )
        stream.append(_image(1), ts=1.0)
        stream.append(_image(2), ts=2.0)
        observations = list(stream)
        obs = observations[1]
        assert obs._loader is not None
        assert obs._data is _UNLOADED
        assert obs.id == 2
        assert obs.ts == 2.0
        assert observations[0].data.data.shape == (2, 2, 3)
        assert obs.data.data.shape == (2, 2, 3)
        backend = stream._source
        assert isinstance(backend.payload_strategy, H264ImagePayloadStrategy)
        assert backend.payload_strategy.frame_index is not None
        assert len(backend.payload_strategy.frame_index.rows("cam")) == 2

    with SqliteStore(path=str(db), must_exist=True) as reopened:
        stream = reopened.stream("cam", Image)
        assert stream.count() == 2
        backend = stream._source
        assert isinstance(backend.payload_strategy, H264ImagePayloadStrategy)
        assert backend.payload_strategy.storage_config.mode == "h264"
        backend.payload_strategy.storage_config = H264ImageStorageConfig(
            codec_adapter=FakeH264CodecAdapter()
        )
        assert reopened.streams.cam.first().data.data.shape == (2, 2, 3)


def test_h264_reopen_append_uses_nearest_reset_sequence_keyframe(tmp_path) -> None:
    db = tmp_path / "reopen_append.db"
    conn = sqlite3.connect(str(db))
    backend = _make_backend(conn)
    from dimos.memory2.type.observation import Observation

    backend.append(Observation(ts=1.0, data_type=Image, _data=_image(1)))
    backend.append(Observation(ts=2.0, data_type=Image, _data=_image(2)))
    backend.stop()
    conn.close()

    reopened_conn = sqlite3.connect(str(db))
    reopened_backend = _make_backend(reopened_conn)
    reopened_backend.append(Observation(ts=3.0, data_type=Image, _data=_image(3)))
    reopened_backend.append(Observation(ts=4.0, data_type=Image, _data=_image(4)))

    assert isinstance(reopened_backend.payload_strategy, H264ImagePayloadStrategy)
    assert reopened_backend.payload_strategy.frame_index is not None
    rows = reopened_backend.payload_strategy.frame_index.rows("cam")
    assert [(row.observation_id, row.seq, row.keyframe_observation_id) for row in rows] == [
        (1, 0, 1),
        (2, 1, 1),
        (3, 0, 3),
        (4, 1, 3),
    ]


def test_h264_mid_gop_decode_and_missing_gop_failure(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "gap.db"))
    stream = store.stream(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(
            storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
        ),
    )
    stream.append(_image(1))
    stream.append(_image(2))
    stream.append(_image(3))
    observations = list(stream)
    assert [obs.data.data[0, 0, 0] for obs in observations] == [1, 2, 3]

    backend = stream._source
    assert isinstance(backend.payload_strategy, H264ImagePayloadStrategy)
    assert backend.payload_strategy.frame_index is not None
    assert backend.blob_store is not None
    backend.blob_store.delete("cam", 2)
    gap_observations = list(stream)
    assert gap_observations[0].data.data[0, 0, 0] == 1
    with pytest.raises(KeyError):
        _ = gap_observations[1].data
    gap_obs = gap_observations[2]
    with pytest.raises(VideoDecodeGapError):
        _ = gap_obs.data


def test_h264_replay_seek_suppresses_delta_until_next_keyframe(tmp_path) -> None:
    config = H264ImageStorageConfig(
        codec_adapter=FakeH264CodecAdapter(),
        codec=H264ImageStorageConfig().codec,
    )
    store = SqliteStore(path=str(tmp_path / "seek.db"))
    stream = store.stream(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(storage_config=config),
    )
    for seq in range(1, 34):
        stream.append(_image(seq), ts=float(seq))

    replay = store.replay(from_timestamp=2.0)
    images = list(replay.streams.cam.iterate())

    assert images[0].ts == 31.0
    assert [img.data[0, 0, 0] for img in images[:3]] == [31, 32, 33]


def test_replay_iterate_returns_decoded_images(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "replay.db"))
    stream = store.stream(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(
            storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
        ),
    )
    stream.append(_image(1), ts=1.0)
    stream.append(_image(2), ts=2.0)

    replay = store.replay()
    images = list(replay.streams.cam.iterate())
    assert [img.ts for img in images] == [1.0, 2.0]
    assert [img.data[0, 0, 0] for img in images] == [1, 2]


def test_h264_rejects_unsupported_formats(tmp_path) -> None:
    store = SqliteStore(path=str(tmp_path / "bad.db"))
    stream = store.stream(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(
            storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
        ),
    )
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    with pytest.raises(UnsupportedVideoImageError):
        stream.append(Image.from_numpy(rgba, format=ImageFormat.RGBA))


def test_sqlite_delete_stream_removes_h264_frame_index_rows(tmp_path) -> None:
    db = tmp_path / "delete.db"
    store = SqliteStore(path=str(db))
    stream = store.stream(
        "cam",
        Image,
        payload_strategy=H264ImagePayloadStrategy(
            storage_config=H264ImageStorageConfig(codec_adapter=FakeH264CodecAdapter())
        ),
    )
    stream.append(_image(1))
    store.delete_stream("cam")

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM h264_frames WHERE stream_name = 'cam'").fetchone()[0]
    assert count == 0
