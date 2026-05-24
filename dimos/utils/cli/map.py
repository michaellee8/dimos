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

from collections.abc import Callable
import time
from typing import Any

import rerun as rr
import rerun.blueprint as rrb
import typer

from dimos.mapping.voxels import VoxelMapTransformer
from dimos.memory2.store.sqlite import SqliteStore
from dimos.memory2.type.observation import Observation
from dimos.utils.data import resolve_named_path
from dimos.visualization.rerun.init import rerun_init


def progress(total: int, label: str = "") -> Callable[[Observation[Any]], None]:
    seen = 0
    wall_start: float | None = None
    last_wall: float | None = None
    first_ts: float | None = None

    def _progress(obs: Observation[Any]) -> None:
        nonlocal seen, wall_start, last_wall, first_ts
        now = time.monotonic()
        if wall_start is None:
            wall_start = now
            first_ts = obs.ts
        assert first_ts is not None  # narrowed by the same `if` above
        frame_ms = (now - last_wall) * 1000 if last_wall is not None else 0.0
        last_wall = now
        seen += 1
        pct = 100 * seen // total if total else 100
        wall = now - wall_start
        data = obs.ts - first_ts
        speed = data / wall if wall > 0 else 0.0
        end = "\n" if seen >= total else ""
        prefix = f"{label} " if label else ""
        print(
            f"\r{prefix}{pct:>3}% [{seen}/{total}] {data:.1f}s ({speed:.1f} x rt) {frame_ms:.0f}ms/frame",
            end=end,
            flush=True,
        )

    return _progress


def main(
    dataset: str = typer.Argument(..., help="Dataset .db: bare name (cwd or data/) or path"),
    voxel: float = typer.Option(0.05, "--voxel", help="Voxel size for the rebuild"),
    device: str = typer.Option(
        "CUDA:0", "--device", help="Open3D compute device (e.g. CUDA:0, CPU:0)"
    ),
    pgo: bool = typer.Option(
        False,
        "--pgo",
        help="Run pose graph optimization and rebuild from spatially-deduped frames",
    ),
    pgo_tol: float = typer.Option(
        0.3, "--pgo-tol", help="Spatial dedup tolerance for --pgo (meters)"
    ),
    block_count: int = typer.Option(
        2_000_000, "--block-count", help="VoxelBlockGrid capacity (--pgo only)"
    ),
    export: bool = typer.Option(
        False,
        "--export",
        help="Export PGO map to ./<dataset>.pc2.lcm in cwd (implies --pgo)",
    ),
    full_pgo: bool = typer.Option(
        False,
        "--full-pgo",
        help="Also build a full-replay PGO map (every frame) for comparison (implies --pgo)",
    ),
    no_gui: bool = typer.Option(False, "--no-gui", help="Skip rerun visualization"),
) -> None:
    db_path = resolve_named_path(dataset, ".db")
    if export or full_pgo:
        pgo = True

    store = SqliteStore(path=db_path)
    lidar = store.streams.lidar

    print(lidar.summary())

    path: list[tuple[float, float, float]] = []

    def collect_path(obs: Observation[Any]) -> None:
        if obs.pose is None:
            return
        # Reject placeholder poses at the world origin (translation = 0,0,0).
        if obs.pose[0] == 0 and obs.pose[1] == 0 and obs.pose[2] == 0:
            return
        path.append((obs.pose[0], obs.pose[1], obs.pose[2]))

    pgo_map = None
    pgo_path: list[tuple[float, float, float]] = []
    if pgo:
        from dimos.mapping.relocalization.pgo import (
            LoopClosure,
            keyframes_to_corrections,
            make_interpolator,
            pgo_keyframes,
        )
        from dimos.mapping.voxels import VoxelGrid

        total = lidar.count()
        print("running PGO twopass map...")
        loops: list[LoopClosure] = []
        keyframes = pgo_keyframes(
            lidar,
            on_frame=progress(total, "pgo pass 1 (optimizing)"),
            loop_closures_out=loops,
        )
        corrections = keyframes_to_corrections(keyframes)
        interp = make_interpolator(corrections)

        for kf_obs in keyframes:
            kf_t = kf_obs.data.optimized.translation
            pgo_path.append((kf_t.x, kf_t.y, kf_t.z))

        # Canonical PGO rebuild: bucket frames by spatial cell using the raw
        # odom pose, keep the latest per cell, transform with the interpolated
        # correction. obs.data is not touched in the dedup loop so it stays
        # cheap (no pointcloud loading).
        seen: dict[tuple[int, int, int], Any] = {}
        for obs in lidar:
            if obs.pose is None:
                continue
            if obs.pose[0] == 0 and obs.pose[1] == 0 and obs.pose[2] == 0:
                continue
            cell = (
                int(obs.pose[0] / pgo_tol),
                int(obs.pose[1] / pgo_tol),
                int(obs.pose[2] / pgo_tol),
            )
            seen[cell] = obs

        n_kept = len(seen)
        pct = 100 * n_kept / total if total else 0
        print(f"pgo rebuild: kept [{n_kept}/{total}] frames ({pct:.1f}%) at tol={pgo_tol}m")

        pass2_pb = progress(n_kept, "pgo pass 2 (rebuilding)")
        grid = VoxelGrid(voxel_size=voxel, block_count=block_count, device=device)
        try:
            for obs in seen.values():
                pass2_pb(obs)
                if len(obs.data) == 0:
                    continue
                grid.add_frame(obs.data.transform(interp(obs.ts)))
            pgo_map = grid.get_global_pointcloud2()
        finally:
            grid.dispose()

    full_pgo_map = None
    if full_pgo:
        full_pb = progress(total, "full pgo (rebuilding)")
        full_grid = VoxelGrid(voxel_size=voxel, block_count=block_count, device=device)
        try:
            for obs in lidar:
                full_pb(obs)
                if obs.pose is None or len(obs.data) == 0:
                    continue
                full_grid.add_frame(obs.data.transform(interp(obs.ts)))
            full_pgo_map = full_grid.get_global_pointcloud2()
        finally:
            full_grid.dispose()

    global_map = (
        lidar.tap(collect_path)
        .transform(VoxelMapTransformer(voxel_size=voxel, device=device))
        .tap(progress(lidar.count(), "reconstructing global map"))
        .last()
        .data
    )

    if not no_gui:
        rerun_init("dimos map tool", spawn=True)
        rr.send_blueprint(rrb.Blueprint(rrb.Spatial3DView(origin="world")))
        rr.log("world/raw_map/pointcloud", global_map.to_rerun(size=voxel), static=True)
        if path:
            rr.log(
                "world/raw_map/path",
                rr.LineStrips3D(strips=[path], colors=[[231, 76, 60]], radii=[0.05]),
                static=True,
            )
        if pgo_map is not None:
            rr.log("world/pgo_map/pointcloud", pgo_map.to_rerun(size=voxel), static=True)
        if full_pgo_map is not None:
            rr.log(
                "world/full_pgo_map/pointcloud",
                full_pgo_map.to_rerun(size=voxel),
                static=True,
            )
        STEM_HEIGHT = 2.0  # lift pose-graph viz above the map for legibility
        if pgo_path:
            rr.log(
                "world/pgo_map/path",
                rr.LineStrips3D(strips=[pgo_path], colors=[[255, 255, 255]], radii=[0.05]),
                static=True,
            )
            hovered = [(x, y, z + STEM_HEIGHT) for (x, y, z) in pgo_path]
            rr.log(
                "world/pgo_map/keyframes",
                rr.Points3D(positions=hovered, colors=[[255, 255, 255]], radii=[0.05]),
                static=True,
            )
        if pgo and loops:
            loop_strips = [
                [
                    (
                        lc.source.translation.x,
                        lc.source.translation.y,
                        lc.source.translation.z + STEM_HEIGHT,
                    ),
                    (
                        lc.target.translation.x,
                        lc.target.translation.y,
                        lc.target.translation.z + STEM_HEIGHT,
                    ),
                ]
                for lc in loops
            ]
            rr.log(
                "world/pgo_map/loop_closures",
                rr.LineStrips3D(strips=loop_strips, colors=[[231, 76, 60]], radii=[0.05]),
                static=True,
            )

    if export and pgo_map is not None:
        from pathlib import Path

        out_path = Path.cwd() / f"{db_path.stem}.pc2.lcm"
        print(f"exporting PGO twopass map to {out_path}...")
        out_path.write_bytes(pgo_map.lcm_encode())
        print(f"wrote {out_path}")
        print()
        print("load back with:")
        print("    from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2")
        print(f'    pcd = PointCloud2.lcm_decode(open("{out_path.name}", "rb").read())')


if __name__ == "__main__":
    typer.run(main)
