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

"""Record live FAST-LIO output into a .db while a virtual sensor replays a pcap.

FastLio2 runs in **live SDK mode** and this tool records its two output streams
into a memory2 SQLite database for ``--duration`` seconds:

* ``fastlio_odometry`` -- the IESKF pose at the native odom rate (~30 Hz).
* ``fastlio_lidar`` -- the registered (deskewed, odom-frame) point cloud at the
  native pointcloud rate (~10 Hz).

There is no in-process pcap reader: the packets come from the live Livox SDK
path, fed by ``virtual_mid360`` — a fake Mid-360 on a virtual NIC that replays a
recorded pcap with a synthesized SDK2 handshake. FastLio2 connects to it exactly
as it would to real hardware and never knows the sensor is synthetic. The netns
setup + sensor are orchestrated by ``tools/replay_via_virtual_mid360.sh``, which
drives this tool as its consumer; that wrapper is the normal entry point.

The db is appended in place: the two fastlio streams are time-aligned onto the
db's existing clock (so they line up with whatever else it holds), and an
existing ``fastlio_odometry`` / ``fastlio_lidar`` pair aborts the run unless
``--force`` is given. ``--time-offset`` overrides the auto-derived clock shift.

Usage (normally via the wrapper)::

    bash tools/replay_via_virtual_mid360.sh <pcap> <out.db> <duration> [config.yaml]

Direct (only useful inside the consumer netns, fed by an external sensor)::

    python -m dimos.hardware.sensors.lidar.fastlio2.tools.pcap_to_db \
        --db /path/to/memory.db --duration 200
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sqlite3
import sys
import time

from dimos.hardware.sensors.lidar.fastlio2.recorder import FastLio2Recorder

# Below this an absolute timestamp is sensor-boot seconds, not unix wall time.
_SENSOR_CLOCK_MAX = 1e8
# Poll cadence while recording the live stream.
_POLL_SEC = 1.0


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
            try:
                # vec0/rtree virtual tables (sqlite-vec etc.) raise "no such
                # module" here when the extension isn't loaded -- skip them.
                cols = [c[1] for c in con.execute(f"PRAGMA table_info('{table}')").fetchall()]
                if "ts" not in cols:
                    continue
                row = con.execute(f"SELECT MIN(ts) FROM '{table}'").fetchone()
            except sqlite3.OperationalError:
                continue
            if row and row[0] is not None:
                best = row[0] if best is None else min(best, row[0])
        return best if best is not None else -1.0
    finally:
        con.close()


def _table_stats(db_path: Path, table: str) -> tuple[int, float, float]:
    """(count, min_ts, max_ts) for a stream table; zeros if absent."""
    if not db_path.exists():
        return 0, 0.0, 0.0
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    try:
        try:
            row = con.execute(f"SELECT COUNT(*), MIN(ts), MAX(ts) FROM '{table}'").fetchone()
        except sqlite3.OperationalError:
            return 0, 0.0, 0.0
        cnt = row[0] or 0
        return cnt, row[1] or 0.0, row[2] or 0.0
    finally:
        con.close()


def _run(args: argparse.Namespace) -> int:
    # FastLio2 runs in live SDK mode, fed by an external sensor — virtual_mid360
    # replaying a pcap over a veth (see tools/replay_via_virtual_mid360.sh). We
    # record whatever the SDK receives into the db for --duration seconds.
    if not args.db:
        print("[pcap_to_db] --db is required", file=sys.stderr)
        return 2
    if args.duration <= 0:
        print("[pcap_to_db] --duration must be > 0", file=sys.stderr)
        return 2
    db_path = Path(args.db).expanduser().resolve()
    db_existed = db_path.exists()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    from dimos.core.coordination.blueprints import autoconnect
    from dimos.core.coordination.module_coordinator import ModuleCoordinator
    from dimos.hardware.sensors.lidar.fastlio2.module import FastLio2
    from dimos.memory2.store.sqlite import SqliteStore

    fastlio_streams = ("fastlio_odometry", "fastlio_lidar")
    store = SqliteStore(path=str(db_path))
    try:
        existing = sorted(set(store.list_streams()) & set(fastlio_streams))
        if existing and not args.force:
            print(
                f"[pcap_to_db] {db_path.name} already has {existing}; pass --force to overwrite",
                file=sys.stderr,
            )
            return 2
        for name in existing:
            store.delete_stream(name)
        if existing:
            print(f"[pcap_to_db] --force: dropped existing {existing}", flush=True)
    finally:
        store.stop()

    ref_start_ts = _db_ref_start_ts(db_path)
    time_offset = float("nan") if args.time_offset is None else args.time_offset
    if not math.isnan(time_offset):
        offset_desc = f"explicit {time_offset:+.3f}s"
    elif ref_start_ts < 0.0:
        offset_desc = "auto: db empty -> 0"
    elif ref_start_ts < _SENSOR_CLOCK_MAX:
        offset_desc = f"auto: db sensor-clock (R0={ref_start_ts:.2f})"
    else:
        offset_desc = f"auto: db wall-clock (R0={ref_start_ts:.2f})"
    print(
        f"[pcap_to_db] src=virtual_mid360 (live SDK) db={db_path.name} "
        f"({'append' if db_existed else 'new'}) "
        f"odom_freq={args.odom_freq}Hz offset={offset_desc}",
        flush=True,
    )

    fastlio_kwargs: dict[str, object] = dict(
        frame_id="world",
        odom_freq=args.odom_freq,
        debug=False,
    )
    # Omit config to fall back to the module default (config/mid360.yaml).
    if args.config:
        fastlio_kwargs["config"] = Path(args.config)
    fastlio = FastLio2.blueprint(**fastlio_kwargs).remappings(
        [
            (FastLio2, "odometry", "fastlio_odometry"),
            (FastLio2, "lidar", "fastlio_lidar"),
        ]
    )
    blueprint = autoconnect(
        fastlio,
        FastLio2Recorder.blueprint(
            db_path=str(db_path),
            ref_start_ts=ref_start_ts,
            time_offset=time_offset,
        ),
    ).global_config(n_workers=4, robot_model="mid360_fastlio2_pcap_to_db")
    coord = ModuleCoordinator.build(blueprint)

    t0 = time.time()
    try:
        while time.time() - t0 < args.duration:
            time.sleep(_POLL_SEC)
        print(f"[pcap_to_db] reached --duration={args.duration:.1f}s", flush=True)
    finally:
        coord.stop()

    o_cnt, o_min, o_max = _table_stats(db_path, "fastlio_odometry")
    l_cnt = _table_stats(db_path, "fastlio_lidar")[0]
    span = o_max - o_min
    print(
        f"[pcap_to_db] done odom={o_cnt} lidar={l_cnt} "
        f"ts=[{o_min:.3f}, {o_max:.3f}] span={span:.1f}s "
        f"wall={time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        required=True,
        help="target memory2 SQLite db. fastlio streams are appended + time-aligned "
        "onto its clock (or it's created fresh if absent).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        required=True,
        help="record for this many seconds of wall time, then stop",
    )
    parser.add_argument(
        "--odom-freq",
        type=float,
        default=30.0,
        help="FAST-LIO odometry publish rate in Hz (default 30)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="FAST-LIO yaml (relative to config/ or absolute); omit for the module default",
    )
    parser.add_argument(
        "--time-offset",
        type=float,
        default=None,
        help="seconds added to every output ts; omit to auto-derive from the db clock",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing fastlio_odometry/fastlio_lidar streams in the db",
    )
    return _run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
