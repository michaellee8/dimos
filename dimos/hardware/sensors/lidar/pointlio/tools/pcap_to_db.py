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

"""Run Point-LIO over a .pcap and append the odometry into an existing .db.

Given a Livox Mid-360 pcap capture and a memory2 SQLite database, this streams
the pcap through the Point-LIO native module (deterministic clock, single feeder
-> never loads the whole pcap into memory) and writes a ``pointlio_odometry``
stream into the database at the native publish rate (~30 Hz).

Timing conversion
-----------------
Point-LIO's deterministic output timestamps are in *sensor-boot seconds* (the
Livox packet clock, small values like 1588.x). The target db may use a different
clock for its existing streams:

* db already on the sensor clock (e.g. a fastlio replay db, min ts < 1e8):
  offset 0 -- both replay the same pcap packet clock, so they line up exactly.
* db on wall-clock unix time (min ts > 1e9): start-align by shifting Point-LIO's
  first odom ts onto the db's earliest existing ts.
* db has no existing timestamped rows: offset 0.

Pass ``--time-offset`` to override the auto choice.

Usage (from the dimos6 venv)::

    source .venv/bin/activate
    python -m dimos.hardware.sensors.lidar.pointlio.tools.pcap_to_db \
        --pcap /path/to/capture.pcap --db /path/to/memory.db
"""

from __future__ import annotations

import argparse
from collections.abc import AsyncIterator
import math
from pathlib import Path
import sqlite3
import sys
import time

from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.msgs.nav_msgs.Odometry import Odometry

# Below this the db's existing timestamps are sensor-boot seconds, not unix time.
_SENSOR_CLOCK_MAX = 1e8
# Strictly-increasing tie-breaker so two odom samples never collide on ts.
_EPS = 1e-9
# Poll the db on this cadence while the replay drains the pcap.
_POLL_SEC = 1.0
# Stop after the odom stream has been stagnant this long (pcap fully drained).
_STAGNANT_SEC = 4.0


class RecConfig(ModuleConfig):
    """Configures the recorder with the target db and timing conversion."""

    db_path: str = ""
    # Earliest existing ts in the db, or -1.0 if the db has no timestamped rows.
    ref_start_ts: float = -1.0
    # Explicit offset override; NaN means auto-derive from ref_start_ts.
    time_offset: float = float("nan")


class Rec(Module):
    """Append Point-LIO odometry into an existing SQLite db with ts conversion."""

    config: RecConfig
    pointlio_odometry: In[Odometry]
    _offset: float | None = None
    _last_ts: float = 0.0
    _count: int = 0

    async def main(self) -> AsyncIterator[None]:
        from dimos.memory2.store.sqlite import SqliteStore

        self._store = SqliteStore(path=self.config.db_path)
        self._os = self._store.stream("pointlio_odometry", Odometry)
        yield
        self._store.stop()

    def _resolve_offset(self, first_ts: float) -> float:
        override = self.config.time_offset
        if not math.isnan(override):
            return override
        ref = self.config.ref_start_ts
        if ref < 0.0 or ref < _SENSOR_CLOCK_MAX:
            # Empty db, or db already on the sensor clock -> exact alignment.
            return 0.0
        # db on wall-clock time -> start-align Point-LIO onto the db's earliest ts.
        return ref - first_ts

    async def handle_pointlio_odometry(self, v: Odometry) -> None:
        raw_ts = getattr(v, "ts", None) or time.time()
        if self._offset is None:
            self._offset = self._resolve_offset(raw_ts)
        ts = max(raw_ts + self._offset, self._last_ts + _EPS)
        self._last_ts = ts
        pose = getattr(v, "pose", None)
        pose_inner = getattr(pose, "pose", None) if pose is not None else None
        self._os.append(v, ts=ts, pose=pose_inner)
        self._count += 1


def _db_ref_start_ts(db_path: Path) -> float:
    """Min ts across the db's existing streams, or -1.0 if none/absent."""
    if not db_path.exists():
        return -1.0
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        tables = [
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        best: float | None = None
        for table in tables:
            if table.startswith("_") or table.startswith("sqlite_"):
                continue
            cols = [c[1] for c in con.execute(f"PRAGMA table_info('{table}')").fetchall()]
            if "ts" not in cols:
                continue
            row = con.execute(f"SELECT MIN(ts) FROM '{table}'").fetchone()
            if row and row[0] is not None:
                best = row[0] if best is None else min(best, row[0])
        return best if best is not None else -1.0
    finally:
        con.close()


def _odom_stats(db_path: Path) -> tuple[int, float, float]:
    """(count, min_ts, max_ts) for the pointlio_odometry table; zeros if absent."""
    if not db_path.exists():
        return 0, 0.0, 0.0
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        try:
            row = con.execute("SELECT COUNT(*), MIN(ts), MAX(ts) FROM pointlio_odometry").fetchone()
        except sqlite3.OperationalError:
            return 0, 0.0, 0.0
        cnt = row[0] or 0
        return cnt, row[1] or 0.0, row[2] or 0.0
    finally:
        con.close()


def _run(args: argparse.Namespace) -> int:
    pcap_path = Path(args.pcap).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    if not pcap_path.exists():
        print(f"[pcap_to_db] missing pcap: {pcap_path}", file=sys.stderr)
        return 2
    if args.max_sensor_sec < 0:
        print("[pcap_to_db] --max-sensor-sec must be >= 0", file=sys.stderr)
        return 2

    from dimos.core.coordination.blueprints import autoconnect
    from dimos.core.coordination.module_coordinator import ModuleCoordinator
    from dimos.hardware.sensors.lidar.pointlio.module import PointLio

    ref_start_ts = _db_ref_start_ts(db_path)
    time_offset = float("nan") if args.time_offset is None else args.time_offset
    if not math.isnan(time_offset):
        offset_desc = f"explicit {time_offset:+.3f}s"
    elif ref_start_ts < 0.0:
        offset_desc = "auto: db empty -> 0"
    elif ref_start_ts < _SENSOR_CLOCK_MAX:
        offset_desc = f"auto: db sensor-clock (R0={ref_start_ts:.2f}) -> 0"
    else:
        offset_desc = f"auto: db wall-clock (R0={ref_start_ts:.2f}) -> start-align"
    print(
        f"[pcap_to_db] pcap={pcap_path.name} db={db_path.name} "
        f"odom_freq={args.odom_freq}Hz offset={offset_desc}",
        flush=True,
    )

    blueprint = autoconnect(
        PointLio.blueprint(
            frame_id="world",
            map_freq=-1,
            odom_freq=args.odom_freq,
            replay_pcap=pcap_path,
            deterministic_clock=True,
            replay_dual_thread=False,
            debug=False,
        ).remappings([(PointLio, "odometry", "pointlio_odometry")]),
        Rec.blueprint(
            db_path=str(db_path),
            ref_start_ts=ref_start_ts,
            time_offset=time_offset,
        ),
    ).global_config(n_workers=4, robot_model="mid360_pointlio_pcap_to_db")
    coord = ModuleCoordinator.build(blueprint)

    t0 = time.time()
    last_max = 0.0
    first_max: float | None = None
    stagnant_since: float | None = None
    try:
        while True:
            time.sleep(_POLL_SEC)
            cnt, min_ts, max_ts = _odom_stats(db_path)
            if cnt == 0:
                continue
            if first_max is None:
                first_max = min_ts
            if args.max_sensor_sec > 0 and (max_ts - first_max) >= args.max_sensor_sec:
                print(
                    f"[pcap_to_db] reached --max-sensor-sec={args.max_sensor_sec:.1f}s",
                    flush=True,
                )
                break
            if max_ts == last_max:
                if stagnant_since is None:
                    stagnant_since = time.time()
                elif time.time() - stagnant_since > _STAGNANT_SEC:
                    break
            else:
                last_max = max_ts
                stagnant_since = None
    finally:
        coord.stop()

    cnt, min_ts, max_ts = _odom_stats(db_path)
    span = max_ts - min_ts
    print(
        f"[pcap_to_db] done rows={cnt} ts=[{min_ts:.3f}, {max_ts:.3f}] "
        f"span={span:.1f}s wall={time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcap", required=True, help="Livox Mid-360 pcap capture")
    parser.add_argument("--db", required=True, help="target memory2 SQLite db (appended to)")
    parser.add_argument(
        "--odom-freq",
        type=float,
        default=30.0,
        help="Point-LIO odometry publish rate in Hz (default 30)",
    )
    parser.add_argument(
        "--max-sensor-sec",
        type=float,
        default=0.0,
        help="stop after this many seconds of sensor time (0 = whole pcap)",
    )
    parser.add_argument(
        "--time-offset",
        type=float,
        default=None,
        help="seconds added to every odom ts; omit to auto-derive from the db clock",
    )
    return _run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
