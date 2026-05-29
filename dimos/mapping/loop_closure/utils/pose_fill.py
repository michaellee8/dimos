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

"""Stamp observations with poses pulled from another stream by nearest timestamp.

Some recorders store raw sensor streams (``lidar``, images) without baking the
trajectory into each frame — the pose lives in a separate odometry stream
(``odom``, ``fastlio_odometry``). PGO and the voxel rebuild skip pose-less
frames, so such a recording yields an empty map. :func:`pose_fill` re-attaches
poses by nearest-in-time match (via :meth:`Stream.align`) so those tools work
again. Frames stay in whatever coordinate frame they were stored in — only the
pose *metadata* is added.

:func:`pose_fill_db` runs the same fill while copying a whole SQLite dataset to
a new file, baking the pulled poses into the target stream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from dimos.memory2.backend import Backend
from dimos.memory2.stream import Stream
from dimos.memory2.type.observation import Observation


def pose_fill(
    stream: Stream[Any], pose_stream: Stream[Any], *, tolerance: float = 0.1
) -> Stream[Any]:
    """Re-pose each observation in *stream* from the nearest entry in *pose_stream*.

    Pairs are formed by :meth:`Stream.align` (nearest ``|Δts| <= tolerance``);
    primaries with no match in tolerance are dropped. The pose is read from the
    matched pose observation's *payload* (``PoseStamped`` / ``Odometry`` / any
    object exposing ``.position`` + ``.orientation``) because pose-message
    streams carry the pose in the value, not the indexed pose columns. The
    target stream's payload stays lazy.
    """

    def _fill(pair_obs: Observation[Any]) -> Observation[Any]:
        primary, secondary = cast(
            "tuple[Observation[Any], Observation[Any]]", pair_obs.data
        )  # AlignedPair(primary, secondary)
        return primary.with_pose(secondary.data)

    return stream.align(pose_stream, tolerance=tolerance).map(_fill)


def pose_fill_db(
    src_path: str | Path,
    dest_path: str | Path,
    *,
    target: str = "lidar",
    pose_source: str = "odom",
    tolerance: float = 0.1,
    streams: list[str] | None = None,
) -> dict[str, int]:
    """Copy a SQLite dataset to *dest_path*, baking *pose_source* poses into *target*.

    Every stream in *streams* (default: all streams in the source) is copied
    with its original payload type and codec. The *target* stream is re-posed
    via :func:`pose_fill` from the *pose_source* stream; all others are copied
    verbatim. Returns a per-stream count of observations written.
    """
    from dimos.memory2.store.sqlite import SqliteStore

    src = SqliteStore(path=str(src_path), must_exist=True)
    dest = SqliteStore(path=str(dest_path))
    names = streams if streams is not None else src.list_streams()
    if target not in names:
        raise ValueError(f"target stream {target!r} not in {names}")
    if pose_source not in src.list_streams():
        raise ValueError(f"pose_source stream {pose_source!r} not found in source dataset")

    written: dict[str, int] = {}
    for name in names:
        src_stream: Stream[Any] = src.stream(name)
        backend = src_stream._source  # bare store stream → source is the Backend
        assert isinstance(backend, Backend)
        dest_stream: Stream[Any] = dest.stream(name, backend.data_type, codec=backend.codec)
        if name == target:
            filled = pose_fill(src_stream, src.stream(pose_source), tolerance=tolerance)
            written[name] = filled.save(dest_stream).drain()
        else:
            written[name] = src_stream.save(dest_stream).drain()

    src.stop()
    dest.stop()
    return written
