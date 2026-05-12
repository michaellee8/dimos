# PGO experiments

We will load lidar frames from a recording and experiment with how
pose-graph optimization (PGO) reassembles the map. To start, no PGO at
all — just feed lidar frames through `VoxelMapTransformer` to get a
single global pointcloud, using whatever pose each frame already
carries (raw odometry). This gives us the baseline drift to improve
against.

## Load the recording

```python session=pgo
from dimos.memory2.store.sqlite import SqliteStore
from dimos.utils.data import get_data

store = SqliteStore(path=get_data("go2_hongkong_office.db"))
lidar = store.streams.lidar
print(lidar.summary())
```

<!--Result:-->
```
Stream("lidar"): 4235 items, 2026-05-06 08:12:09 — 2026-05-06 08:21:27 (558.0s)
```

## Baseline global map (first 3 minutes, no PGO)

Slice to a 120 s window. We splice a small generator-based transform
between `slice_lidar` and `VoxelMapTransformer` to time the downstream
consumer per-frame — yielding hands control to the voxel transformer's
`add_frame` call; on resume we measure elapsed and append to a parallel
numerical side-stream (same `ts`, value = ms).

```python session=pgo
import time
from dimos.mapping.voxels import VoxelMapTransformer
from dimos.memory2.store.memory import MemoryStore
from dimos.memory2.transform import measure_gpu_mem, measure_time

t0 = lidar.first().ts
slice_lidar = lidar#.before(t0 + 500)

mem = MemoryStore()
frame_ms = mem.stream("frame_ms", float)

global_map = (
    slice_lidar
    .transform(measure_time(frame_ms))
    .transform(VoxelMapTransformer(device="CUDA:0", emit_every=0))
    .last().data
)

vals = [o.data for o in frame_ms]
print(f"frames={len(vals)}  total={sum(vals) / 1000:.1f}s  "
      f"mean={sum(vals) / len(vals):.1f}ms  max={max(vals):.1f}ms")

from dimos.memory2.vis.space.space import Space
Space().add(global_map).to_svg("assets/pgo_baseline_map.svg")
```

<!--Result:-->
```
12:23:38.944 [inf][dimos/mapping/voxels.py       ] VoxelGrid using device: CUDA:0
frames=4235  total=6.9s  mean=1.6ms  max=60.9ms
```

![output](assets/pgo_baseline_map.svg)

## PGO trajectory overlaid on voxels map

For realtime use, building an extra global map per pipeline is too
expensive. The interesting signal from PGO is its *corrected
trajectory* — overlay it on the voxels-only map (which is fast and
accurate locally) and you can see exactly where PGO undid drift.

`pgo_trajectories(stream)` returns two `Path` messages: ``drifted`` is
the raw odometry pose at each keyframe (the input to PGO), ``corrected``
is iSAM2's optimized pose after all loop closures have settled.

```python session=pgo
from dimos.memory2.vis.space.elements import Polyline
from dimos.mapping.pgo import pgo_trajectories

loop_score = mem.stream("loop_score", float)
pose_jump_m = mem.stream("pose_jump_m", float)

drifted_path, corrected_path, pgo_map = pgo_trajectories(
    slice_lidar,
    loop_score=loop_score,
    pose_jump=pose_jump_m,
    global_map_voxel_size=0.05,  # also rebuild global map from corrected keyframes
)
print(f"keyframes: {len(corrected_path.poses)}")
jumps = [o.data for o in pose_jump_m]
print(f"loops fired: {loop_score.count()}  "
      f"max pose_jump: {max(jumps, default=0):.3f} m")

# Pickle the corrected keyframe trajectory so future relocalization
# tests have a pose oracle. (Drifted poses are recoverable per-frame
# from each lidar obs.pose, so we don't need to save them.)
import pickle
from pathlib import Path
Path("assets/pgo_corrected_path.pkl").write_bytes(pickle.dumps(corrected_path))

(
    Space()
    .add(global_map)
    .add(Polyline(msg=drifted_path, color="#e74c3c", width=0.08))   # red
    .add(Polyline(msg=corrected_path, color="#2ecc71", width=0.08)) # green
    .to_svg("assets/pgo_trajectories.svg")
)

# PGO map (keyframe body clouds through corrected poses) + corrected path
(
    Space()
    .add(pgo_map)
    .add(Polyline(msg=corrected_path, color="#2ecc71", width=0.08))
    .to_svg("assets/pgo_map.svg")
)
```

<!--Result:-->
```
12:23:48.380 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0598 source=125 target=78
12:23:48.611 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0229 source=134 target=96
12:23:51.096 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0463 source=289 target=248
12:23:51.219 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0193 source=298 target=240
12:23:51.374 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0736 source=308 target=68
12:23:51.550 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0352 source=317 target=60
12:23:51.762 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0222 source=324 target=51
12:23:51.986 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0165 source=333 target=38
12:23:52.226 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0204 source=341 target=29
12:23:52.601 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0416 source=353 target=19
12:23:54.419 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0601 source=435 target=404
12:23:54.678 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0324 source=442 target=415
12:23:54.974 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0292 source=452 target=407
12:23:56.874 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.17 source=539 target=498
12:23:57.078 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0475 source=547 target=499
12:23:57.483 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0445 source=562 target=498
12:23:57.911 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0478 source=576 target=498
12:23:58.267 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.031 source=588 target=490
12:23:58.544 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0249 source=596 target=484
12:23:58.812 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0475 source=605 target=481
12:24:01.054 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0177 source=710 target=668
12:24:01.334 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0454 source=719 target=668
12:24:01.574 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0529 source=726 target=666
12:24:02.583 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0231 source=772 target=734
12:24:02.874 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0166 source=782 target=741
12:24:03.336 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0176 source=798 target=741
12:24:03.727 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0236 source=808 target=734
12:24:03.964 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0251 source=815 target=727
12:24:04.238 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0238 source=825 target=720
12:24:05.830 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0674 source=896 target=10
12:24:06.110 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0509 source=906 target=343
12:24:06.499 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0397 source=920 target=32
12:24:06.753 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0299 source=928 target=339
12:24:07.025 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0219 source=939 target=38
12:24:07.211 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.013 source=946 target=53
12:24:07.520 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0152 source=958 target=56
12:24:07.787 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0141 source=970 target=61
12:24:08.002 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0113 source=980 target=74
12:24:08.235 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0153 source=989 target=91
12:24:08.499 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0115 source=999 target=99
12:24:08.674 [inf][dimos/mapping/pgo.py          ] Loop closure detected score=0.0111 source=1006 target=105
keyframes: 1007
loops fired: 41  max pose_jump: 1.021 m
```


![output](assets/pgo_trajectories.svg)

![output](assets/pgo_map.svg)

## Two-pass voxel rebuild (PGO corrections + voxels.py)

Re-stream every lidar frame through `VoxelGrid`, but transform each
frame's world cloud by the rigid drift correction interpolated (SLERP
for rotation, linear for translation) between the surrounding keyframe
corrections at that frame's timestamp. Each frame is inserted exactly
once at its converged corrected pose — walls collapse to a single
layer, and `VoxelGrid.carve_columns` evicts stale voxels in revisited
columns.

Reuses the trajectories from the cell above (no second PGO run).

```python session=pgo
from dimos.mapping.pgo import apply_pgo_corrections

import pickle
from pathlib import Path

twopass_map = apply_pgo_corrections(
    slice_lidar,
    drifted_path=drifted_path,
    corrected_path=corrected_path,
    voxel_size=0.05,
)
Path("assets/pgo_twopass_map.pkl").write_bytes(pickle.dumps(twopass_map))

(
    Space()
    .add(twopass_map)
    .add(Polyline(msg=corrected_path, color="#2ecc71", width=0.08))
    .to_svg("assets/pgo_twopass_map.svg")
)
```

![output](assets/pgo_twopass_map.svg)

## Per-frame voxels ingest coste

```python session=pgo output=assets/pgo_frame_ms.svg
from dimos.memory2.transform import smooth
from dimos.memory2.vis.plot.plot import Plot

(
    Plot()
    .add(frame_ms.offset(10).transform(smooth(20)),
         label="voxels add_frame (ms)")
    .to_svg("{output}")
)
```

<!--Result:-->
![output](assets/pgo_frame_ms.svg)

## Loop closures: spatial correction & ICP fitness

Each loop closure event yields one sample on each side-stream:

- `pose_jump_m` — the worst per-keyframe translation correction PGO
  applied (i.e. how far the most-shifted past pose moved). A small
  number means the graph was already nearly-consistent; a big number
  means PGO undid significant accumulated drift.
- `loop_score` — ICP fitness of the matched submap pair (lower is
  better).

```python session=pgo output=assets/pgo_loop_events.svg
(
    Plot()
    .add(pose_jump_m, label="max pose shift (m)", gap_fill=30.0)
    .add(loop_score, label="ICP fitness", gap_fill=30.0)
    .to_svg("{output}")
)
```

<!--Result:-->
![output](assets/pgo_loop_events.svg)
