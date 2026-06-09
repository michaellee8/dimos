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

"""Render a ray-traced voxel map from a recorded lidar stream into rerun.

Usage:
    uv run python -m dimos.mapping.ray_tracing.utils.raytrace_rrd mid360_sample
    uv run python -m dimos.mapping.ray_tracing.utils.raytrace_rrd mid360_sample --out map.rrd && rerun map.rrd
"""

from __future__ import annotations

from pathlib import Path

import rerun as rr
import typer

from dimos.mapping.ray_tracing.transformer import RayTraceMap
from dimos.memory2.store.sqlite import SqliteStore
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2, register_colormap_annotation
from dimos.utils.data import resolve_named_path

TIMELINE = "ts"


def main(
    dataset: str = typer.Argument(..., help="Dataset .db: bare name (cwd or data/) or path"),
    out: Path | None = typer.Option(
        None, "--out", help="Output .rrd path. If omitted, spawn rerun live."
    ),
    stream: str = typer.Option(
        "fastlio_lidar", "--stream", help="Lidar stream name in the recording"
    ),
    voxel_size: float = typer.Option(0.1, "--voxel-size", help="Raycaster voxel edge length (m)"),
    max_range: float = typer.Option(
        30.0, "--max-range", help="Max ray cast distance (m); 0 = no limit"
    ),
    ray_subsample: int = typer.Option(1, "--ray-subsample", help="Keep every Nth ray for clearing"),
    shadow_depth: float = typer.Option(
        0.2, "--shadow-depth", help="Ray extension past endpoint (m)"
    ),
    grace_depth: float = typer.Option(
        0.2, "--grace-depth", help="Spare voxels within this dist of endpoint (m)"
    ),
    min_health: int = typer.Option(-2, "--min-health", help="Voxel removal threshold"),
    max_health: int = typer.Option(1, "--max-health", help="Voxel saturation cap"),
    emit_every: int = typer.Option(1, "--emit-every", help="Yield the current map every N frames"),
    render_voxel: float = typer.Option(
        0.05, "--render-voxel", help="Voxel size for rerun rendering (m)"
    ),
) -> None:
    db_path = resolve_named_path(dataset, ".db")

    rr.init("raytrace_rrd", recording_id=db_path.stem)
    if out is not None:
        rr.save(str(out))
    else:
        rr.spawn()
    register_colormap_annotation("turbo")

    store = SqliteStore(path=str(db_path))
    with store:
        pipeline = store.stream(stream, PointCloud2).transform(
            RayTraceMap(
                voxel_size=voxel_size,
                max_range=max_range,
                ray_subsample=ray_subsample,
                shadow_depth=shadow_depth,
                grace_depth=grace_depth,
                min_health=min_health,
                max_health=max_health,
                emit_every=emit_every,
            )
        )
        for obs in pipeline:
            rr.set_time(TIMELINE, timestamp=obs.ts)
            rr.log("world/raytrace_map", obs.data.to_rerun(voxel_size=render_voxel))
            print(f"frame_count={obs.tags['frame_count']}", end="\r", flush=True)
        print()

    if out is not None:
        print(f"wrote {out}")
        print(f"open with: rerun {out}")


if __name__ == "__main__":
    typer.run(main)
