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

from dataclasses import asdict, dataclass, replace
import sqlite3
from typing import TYPE_CHECKING, Any

from dimos.memory2.type.observation import _UNLOADED
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.VideoPacket import VideoPacket
from dimos.protocol.video.h264 import (
    H264CodecAdapter,
    H264Config,
    H264Decoder,
    H264Encoder,
    VideoDecodeGapError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dimos.memory2.blobstore.base import BlobStore
    from dimos.memory2.type.observation import Observation


@dataclass(frozen=True)
class H264ImageStorageConfig:
    """Per-stream memory2 image storage mode for H.264-backed observations."""

    codec: H264Config = H264Config()
    mode: str = "h264"
    codec_adapter: H264CodecAdapter | None = None

    def serialize(self) -> dict[str, Any]:
        cfg = asdict(self.codec)
        cfg["supported_formats"] = [fmt.value for fmt in self.codec.supported_formats]
        return {"mode": self.mode, "codec": cfg}

    @classmethod
    def parse(cls, raw: H264ImageStorageConfig | dict[str, Any]) -> H264ImageStorageConfig:
        if isinstance(raw, cls):
            return raw
        if not isinstance(raw, dict):
            raise TypeError(f"Cannot parse H.264 image storage config from {type(raw).__name__}")
        mode = raw.get("mode", "h264")
        codec_raw = raw.get("codec", {})
        if isinstance(codec_raw, H264Config):
            codec = codec_raw
        else:
            codec_dict = dict(codec_raw)
            formats = codec_dict.get("supported_formats")
            if formats is not None:
                codec_dict["supported_formats"] = tuple(ImageFormat(fmt) for fmt in formats)
            codec = H264Config(**codec_dict)
        return cls(codec=codec, mode=mode)


@dataclass(frozen=True)
class H264FrameIndexRow:
    stream_name: str
    observation_id: int
    seq: int
    keyframe_observation_id: int
    is_keyframe: bool
    pts: int
    width: int
    height: int
    format: str
    codec: str
    bitstream: str


class H264FrameIndexStore:
    """Persistent GOP/keyframe index for H.264-backed image streams."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def start(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS h264_frames (
                stream_name TEXT NOT NULL,
                observation_id INTEGER NOT NULL,
                seq INTEGER NOT NULL,
                keyframe_observation_id INTEGER NOT NULL,
                is_keyframe INTEGER NOT NULL,
                pts INTEGER NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                format TEXT NOT NULL,
                codec TEXT NOT NULL,
                bitstream TEXT NOT NULL,
                PRIMARY KEY (stream_name, observation_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_h264_frames_stream_keyframe
            ON h264_frames(stream_name, is_keyframe, observation_id)
            """
        )

    def stop(self) -> None:
        pass

    def delete_stream(self, stream_name: str) -> None:
        self._conn.execute("DELETE FROM h264_frames WHERE stream_name = ?", (stream_name,))

    def insert(self, stream_name: str, observation_id: int, packet: VideoPacket) -> None:
        keyframe_observation_id = (
            observation_id
            if packet.is_keyframe
            else self._keyframe_observation_id(
                stream_name,
                packet.keyframe_seq,
                current_observation_id=observation_id,
            )
        )
        self._conn.execute(
            """
            INSERT INTO h264_frames (
                stream_name, observation_id, seq, keyframe_observation_id, is_keyframe,
                pts, width, height, format, codec, bitstream
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stream_name,
                observation_id,
                packet.seq,
                keyframe_observation_id,
                int(packet.is_keyframe),
                packet.pts,
                packet.width,
                packet.height,
                packet.format,
                packet.codec,
                packet.bitstream,
            ),
        )

    def packet_ids_for_decode(self, stream_name: str, observation_id: int) -> list[int]:
        row = self._conn.execute(
            """
            SELECT keyframe_observation_id FROM h264_frames
            WHERE stream_name = ? AND observation_id = ?
            """,
            (stream_name, observation_id),
        ).fetchone()
        if row is None:
            raise VideoDecodeGapError(f"No H.264 GOP index for observation {observation_id}")
        keyframe_id = int(row[0])
        rows = self._conn.execute(
            """
            SELECT observation_id FROM h264_frames
            WHERE stream_name = ? AND observation_id BETWEEN ? AND ?
            ORDER BY observation_id ASC
            """,
            (stream_name, keyframe_id, observation_id),
        ).fetchall()
        ids = [int(item[0]) for item in rows]
        if not ids or ids[0] != keyframe_id or ids[-1] != observation_id:
            raise VideoDecodeGapError(
                f"Incomplete H.264 GOP index for observation {observation_id}"
            )
        return ids

    def rows(self, stream_name: str) -> list[H264FrameIndexRow]:
        rows = self._conn.execute(
            """
            SELECT stream_name, observation_id, seq, keyframe_observation_id, is_keyframe,
                   pts, width, height, format, codec, bitstream
            FROM h264_frames WHERE stream_name = ? ORDER BY observation_id ASC
            """,
            (stream_name,),
        ).fetchall()
        return [
            H264FrameIndexRow(
                stream_name=row[0],
                observation_id=int(row[1]),
                seq=int(row[2]),
                keyframe_observation_id=int(row[3]),
                is_keyframe=bool(row[4]),
                pts=int(row[5]),
                width=int(row[6]),
                height=int(row[7]),
                format=row[8],
                codec=row[9],
                bitstream=row[10],
            )
            for row in rows
        ]

    def _keyframe_observation_id(
        self,
        stream_name: str,
        keyframe_seq: int,
        *,
        current_observation_id: int,
    ) -> int:
        row = self._conn.execute(
            """
            SELECT observation_id FROM h264_frames
            WHERE stream_name = ? AND seq = ? AND is_keyframe = 1 AND observation_id <= ?
            ORDER BY observation_id DESC
            LIMIT 1
            """,
            (stream_name, keyframe_seq, current_observation_id),
        ).fetchone()
        if row is None:
            raise VideoDecodeGapError(f"No H.264 keyframe index for seq {keyframe_seq}")
        return int(row[0])


class H264ImagePayloadStrategy:
    """Stateful H.264 payload strategy for logical ``Stream[Image]`` storage."""

    codec_id = "h264"

    def __init__(
        self,
        *,
        storage_config: H264ImageStorageConfig | dict[str, Any] | None = None,
        frame_index: H264FrameIndexStore | None = None,
    ) -> None:
        self.storage_config = (
            H264ImageStorageConfig.parse(storage_config)
            if storage_config is not None
            else H264ImageStorageConfig()
        )
        self.frame_index = frame_index
        self._encoder: H264Encoder | None = None

    def bind_frame_index(self, frame_index: H264FrameIndexStore) -> None:
        self.frame_index = frame_index

    def bind_sqlite(self, conn: sqlite3.Connection) -> None:
        self.bind_frame_index(H264FrameIndexStore(conn))

    def start(self) -> None:
        if self.frame_index is None:
            raise RuntimeError("H.264 image payload strategy requires a frame index store")
        self.frame_index.start()

    def stop(self) -> None:
        pass

    def encode(self, value: Image) -> bytes:
        if not isinstance(value, Image):
            raise TypeError(
                f"H.264 image payload strategy expects Image, got {type(value).__name__}"
            )
        if self._encoder is None:
            self._encoder = H264Encoder(
                self.storage_config.codec,
                codec=self.storage_config.codec_adapter,
            )
        return self._encoder.encode(value).lcm_encode()

    def after_blob_put(self, stream_name: str, row_id: int, encoded: bytes) -> None:
        frame_index = self.frame_index
        if frame_index is None:
            raise RuntimeError("H.264 image payload strategy requires a frame index store")
        frame_index.insert(stream_name, row_id, VideoPacket.lcm_decode(encoded))

    def make_loader(self, stream_name: str, row_id: int, blob_store: BlobStore) -> Any:
        storage_config = self.storage_config

        def loader() -> Image:
            decoder = H264Decoder(storage_config.codec, codec=storage_config.codec_adapter)
            packet = VideoPacket.lcm_decode(blob_store.get(stream_name, row_id))
            return decoder.decode(packet)

        return loader

    def attach_loaders(
        self,
        stream_name: str,
        observations: Iterator[Observation[Image]],
        blob_store: BlobStore,
    ) -> Iterator[Observation[Image]]:
        decoder = H264Decoder(self.storage_config.codec, codec=self.storage_config.codec_adapter)

        for obs in observations:
            obs.data_type = Image
            if obs._loader is None and isinstance(obs._data, type(_UNLOADED)):
                row_id = obs.id

                def loader(row_id: int = row_id) -> Image:
                    packet = VideoPacket.lcm_decode(blob_store.get(stream_name, row_id))
                    return decoder.decode(packet)

                obs._loader = loader
            yield obs

    def should_suppress_decode_error(self, error: BaseException) -> bool:
        return isinstance(error, VideoDecodeGapError)

    def delete_stream(self, stream_name: str) -> None:
        if self.frame_index is not None:
            self.frame_index.delete_stream(stream_name)

    def serialize(self) -> dict[str, Any]:
        return {
            "class": f"{type(self).__module__}.{type(self).__qualname__}",
            "config": {"storage_config": self.storage_config.serialize()},
        }


def h264_image_payload_strategy_from_any(raw: Any) -> H264ImagePayloadStrategy | None:
    storage_config = storage_config_from_any(raw)
    if storage_config is None:
        return None
    return H264ImagePayloadStrategy(storage_config=storage_config)


def bind_sqlite_frame_index(strategy: Any, conn: sqlite3.Connection) -> Any:
    if isinstance(strategy, H264ImagePayloadStrategy):
        strategy.bind_frame_index(H264FrameIndexStore(conn))
    return strategy


def storage_config_from_any(raw: Any) -> H264ImageStorageConfig | None:
    if raw is None:
        return None
    config = H264ImageStorageConfig.parse(raw)
    if config.mode != "h264":
        return None
    return config


def storage_config_with_adapter(
    config: H264ImageStorageConfig,
    adapter: H264CodecAdapter | None,
) -> H264ImageStorageConfig:
    return replace(config, codec_adapter=adapter)


__all__ = [
    "H264FrameIndexRow",
    "H264FrameIndexStore",
    "H264ImagePayloadStrategy",
    "H264ImageStorageConfig",
    "bind_sqlite_frame_index",
    "h264_image_payload_strategy_from_any",
    "storage_config_from_any",
    "storage_config_with_adapter",
]
