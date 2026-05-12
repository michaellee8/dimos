#!/usr/bin/env python3
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

"""Fast iteration loop: PGO vs voxels-only on a small slice, single quality print.

Usage:
    uv run python scripts/pgo_iterate.py [slice_seconds] [loop_time_thresh]

Reports four numbers per run:
  - n_points (voxels-only and pgo)         — point counts
  - knn_mean_cm (voxels-only and pgo)      — sharpness (lower=better walls)
  - max_pose_jump_m                        — biggest single PGO correction
  - n_loops                                — number of loop closures fired
"""

from __future__ import annotations

import sys

from dimos.mapping.pgo import PGOMapTransformer, map_quality, pgo_then_voxels
from dimos.mapping.voxels import VoxelMapTransformer
from dimos.memory2.store.memory import MemoryStore
from dimos.memory2.store.sqlite import SqliteStore
from dimos.utils.data import get_data

SLICE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 90.0
LOOP_TIME_THRESH = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0

store = SqliteStore(path=get_data("go2_hongkong_office.db"))
lidar = store.streams.lidar
t0 = lidar.first().ts
slice_lidar = lidar.before(t0 + SLICE_S)
n_in = slice_lidar.count()
print(f"slice: {n_in} frames over {SLICE_S}s   loop_time_thresh={LOOP_TIME_THRESH}s")
print()

print("[1/2] voxels-only baseline...")
vmap = slice_lidar.transform(VoxelMapTransformer(device="CUDA:0", emit_every=0)).last().data

print("[2/2] PGO...")
mem = MemoryStore()
loop_score = mem.stream("loop_score", float)
pose_jump = mem.stream("pose_jump_m", float)
pgo_map = (
    slice_lidar.transform(
        PGOMapTransformer(
            emit_every=0,
            loop_time_thresh=LOOP_TIME_THRESH,
            global_map_voxel_size=0.05,  # match VoxelMapTransformer for fair knn comparison
            loop_score=loop_score,
            pose_jump=pose_jump,
        )
    )
    .last()
    .data
)

print("[3/3] PGO trajectory + voxel rebuild (two-pass)...")
twopass_map = pgo_then_voxels(slice_lidar, voxel_size=0.05, loop_time_thresh=LOOP_TIME_THRESH)

from dimos.memory2.vis.space.space import Space

Space().add(vmap).to_svg("scripts/results/voxels_map.svg")
Space().add(pgo_map).to_svg("scripts/results/pgo_map.svg")
Space().add(twopass_map).to_svg("scripts/results/pgo_twopass_map.svg")

vq = map_quality(vmap)
pq = map_quality(pgo_map)
tq = map_quality(twopass_map)
jumps = [o.data for o in pose_jump]
scores = [o.data for o in loop_score]

print()
print("=" * 60)
#  voxels  = no PGO baseline (drifted)
#  pgo     = PGOMapTransformer (re-projects cached body clouds)
#  twopass = pgo_then_voxels (PGO trajectory + per-frame voxel rebuild)
print(f"{'metric':<22} {'voxels':>12} {'pgo':>12} {'twopass':>12}")
print("-" * 72)
for k in ("n_points", "knn_mean_cm", "bbox_m3"):
    v, p, t = vq[k], pq[k], tq[k]
    print(f"{k:<22} {v:>12.2f} {p:>12.2f} {t:>12.2f}")
print(f"{'  knn ratio vs voxels':<22} {'1.000':>12}", end="")
for cur in (pq, tq):
    print(f" {cur['knn_mean_cm'] / vq['knn_mean_cm']:>12.3f}", end="")
print()
print(f"{'  npts ratio vs voxels':<22} {'1.000':>12}", end="")
for cur in (pq, tq):
    print(f" {cur['n_points'] / vq['n_points']:>12.3f}", end="")
print()
print("-" * 72)
if jumps:
    print(f"loops fired:           {len(jumps):>12}")
    print(f"max pose_jump (m):     {max(jumps):>12.3f}")
    print(f"mean pose_jump (m):    {sum(jumps) / len(jumps):>12.3f}")
    print(f"mean ICP score:        {sum(scores) / len(scores):>12.4f}")
else:
    print("loops fired:                       0")
print("=" * 60)
