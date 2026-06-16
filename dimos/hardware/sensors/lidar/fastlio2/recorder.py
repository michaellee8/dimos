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

"""Record FAST-LIO's odometry + lidar into a memory2 SQLite db, rewriting only
those streams' timestamps onto the db clock so offline pcap replay lines up with
a live recording. Used by tools/pcap_to_db.py."""

from __future__ import annotations

from collections.abc import AsyncIterator
import math
import time

from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2

# Below this an absolute timestamp is sensor-boot seconds, not unix wall time.
_SENSOR_CLOCK_MAX = 1e8
# Strictly-increasing tie-breaker so two samples never collide on ts.
_EPS = 1e-9


class FastLio2RecorderConfig(ModuleConfig):
    """Target db and the timestamp-conversion policy for fastlio streams."""

    db_path: str = ""
    # Earliest existing ts in the db, or -1.0 if the db has no timestamped rows.
    ref_start_ts: float = -1.0
    # Explicit offset override; NaN means auto-derive from ref_start_ts.
    time_offset: float = float("nan")


class FastLio2Recorder(Module):
    """Offset auto-derives: same clock family -> 0; cross-clock -> start-align."""

    config: FastLio2RecorderConfig
    fastlio_odometry: In[Odometry]
    fastlio_lidar: In[PointCloud2]
    _offset: float | None = None
    _last_odom_ts: float = 0.0
    _last_lidar_ts: float = 0.0
    _last_pose: object = None
    _odom_count: int = 0
    _lidar_count: int = 0

    async def main(self) -> AsyncIterator[None]:
        from dimos.memory2.store.sqlite import SqliteStore

        self._store = SqliteStore(path=self.config.db_path)
        self._os = self._store.stream("fastlio_odometry", Odometry)
        self._ls = self._store.stream("fastlio_lidar", PointCloud2)
        yield
        self._store.stop()

    def _resolve_offset(self, first_ts: float) -> float:
        override = self.config.time_offset
        if not math.isnan(override):
            return override
        ref = self.config.ref_start_ts
        if ref < 0.0:
            return 0.0
        # Same clock family -> aligned; cross-clock -> start-align onto db's first.
        if (first_ts > _SENSOR_CLOCK_MAX) == (ref > _SENSOR_CLOCK_MAX):
            return 0.0
        return ref - first_ts

    def _aligned_ts(self, raw_ts: float, last_ts: float) -> float:
        """Convert a replay ts onto the db clock, kept strictly above last_ts."""
        if self._offset is None:
            self._offset = self._resolve_offset(raw_ts)
        return max(raw_ts + self._offset, last_ts + _EPS)

    @staticmethod
    def _raw_ts(v: object) -> float:
        # Guard on None: a genuine 0.0 ts is falsy, so `ts or time.time()` would drop it.
        ts = getattr(v, "ts", None)
        return ts if ts is not None else time.time()

    async def handle_fastlio_odometry(self, v: Odometry) -> None:
        ts = self._aligned_ts(self._raw_ts(v), self._last_odom_ts)
        self._last_odom_ts = ts
        pose = getattr(v, "pose", None)
        self._last_pose = getattr(pose, "pose", None) if pose is not None else None
        self._os.append(v, ts=ts, pose=self._last_pose)
        self._odom_count += 1

    async def handle_fastlio_lidar(self, v: PointCloud2) -> None:
        ts = self._aligned_ts(self._raw_ts(v), self._last_lidar_ts)
        self._last_lidar_ts = ts
        self._ls.append(v, ts=ts, pose=self._last_pose)
        self._lidar_count += 1
