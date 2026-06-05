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

"""Live Mid-360 smoke test for the Point-LIO module.

Runs the PointLio module against the physically-connected lidar for a short
window, mirrors odometry into a sqlite db, then prints a summary so we can
confirm the EKF stays bounded (stationary ⇒ near-origin, no satu_acc runaway).

    cd ~/repos/dimos6 && source .venv/bin/activate
    python -m dimos.hardware.sensors.lidar.pointlio.tools.demo_live_test
"""

from __future__ import annotations

from collections.abc import AsyncIterator
import os
from pathlib import Path
import sqlite3
import sys
import time

from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.msgs.nav_msgs.Odometry import Odometry

RUN_SEC = float(os.environ.get("RUN_SEC", "25.0"))
DB_PATH = Path("/tmp/pointlio_live.db")

_EPS = 1e-9


class RecConfig(ModuleConfig):
    db_path: str = ""


class Rec(Module):
    config: RecConfig
    pointlio_odometry: In[Odometry]
    _last_o: float = 0.0

    async def main(self) -> AsyncIterator[None]:
        from dimos.memory2.store.sqlite import SqliteStore

        self._store = SqliteStore(path=self.config.db_path)
        self._os = self._store.stream("pointlio_odometry", Odometry)
        yield
        self._store.stop()

    async def handle_pointlio_odometry(self, v: Odometry) -> None:
        ts = max(getattr(v, "ts", None) or time.time(), self._last_o + _EPS)
        self._last_o = ts
        pose = getattr(v, "pose", None)
        pose_inner = getattr(pose, "pose", None) if pose is not None else None
        self._os.append(v, ts=ts, pose=pose_inner)


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from dimos.core.coordination.blueprints import autoconnect
    from dimos.core.coordination.module_coordinator import ModuleCoordinator
    from dimos.hardware.sensors.lidar.pointlio.module import PointLio

    bp = autoconnect(
        PointLio.blueprint(frame_id="world", map_freq=-1, debug=False).remappings(
            [(PointLio, "odometry", "pointlio_odometry")]
        ),
        Rec.blueprint(db_path=str(DB_PATH)),
    ).global_config(n_workers=2, robot_model="mid360_pointlio_live_test")
    coord = ModuleCoordinator.build(bp)

    t0 = time.time()
    try:
        while time.time() - t0 < RUN_SEC:
            time.sleep(1.0)
    finally:
        coord.stop()

    if not DB_PATH.exists():
        print("[live_test] NO DB — module never produced odometry", file=sys.stderr)
        return 1
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = list(con.execute("SELECT ts,pose_x,pose_y,pose_z FROM pointlio_odometry ORDER BY ts"))
    con.close()
    print(f"[live_test] odometry rows: {len(rows)}")
    if not rows:
        print("[live_test] NO ROWS — lidar likely not streaming", file=sys.stderr)
        return 1
    import math

    t0r = rows[0][0]
    xs = [r[1] for r in rows]
    ys = [r[2] for r in rows]
    zs = [r[3] for r in rows]
    dmax = max(math.sqrt(x * x + y * y + z * z) for x, y, z in zip(xs, ys, zs, strict=False))
    print(
        f"[live_test] dur={rows[-1][0] - t0r:.1f}s  rate≈{len(rows) / max(rows[-1][0] - t0r, 1e-3):.1f}Hz"
    )
    print(
        f"[live_test] x=({min(xs):.3f},{max(xs):.3f}) y=({min(ys):.3f},{max(ys):.3f}) z=({min(zs):.3f},{max(zs):.3f})"
    )
    print(f"[live_test] max |pos| from origin: {dmax:.3f} m")
    print(f"[live_test] final pos: ({xs[-1]:.3f},{ys[-1]:.3f},{zs[-1]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
