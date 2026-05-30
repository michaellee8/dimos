# Go2 MCAP → dataset ingest

Turn a Go2 onboard MCAP recording into a memory2 SQLite dataset (`.db`) that the
`dimos map` CLI reads. Lidar scans are deskewed into the **world frame** (Go2
convention); two trajectories are emitted for comparison.

## Build

```sh
uv run python -m dimos.robot.unitree.go2.mcap.ingest \
    data/go2_china_office_indoor.mcap --out data/go2_china_office_indoor.db --seconds 60
```
Drop `--seconds` for the full recording. `mcap` must be installed (`uv pip install mcap`).

## Streams

| stream | type | content |
|---|---|---|
| `color_image` | Image | RGB, posed at `camera_optical` in world |
| `odom` | PoseStamped | Go2 leg-inertial odometry |
| `odom_bestz` | PoseStamped | leg xy/yaw + pitch-reconstructed z |
| `lidar` | PointCloud2 | per-scan world cloud (deskewed by `odom`) |
| `lidar_bestz` | PointCloud2 | per-scan world cloud (deskewed by `odom_bestz`) |
| `lidar_1s` / `lidar_bestz_1s` | PointCloud2 | 1 s accumulation per trajectory |

## Validate

```sh
dimos map summary data/go2_china_office_indoor.db
dimos map global  data/go2_china_office_indoor.db --lidar lidar       --voxel 0.1
dimos map global  data/go2_china_office_indoor.db --lidar lidar_bestz --voxel 0.1   # z-corrected
dimos map replay  data/go2_china_office_indoor.db --duration 60
```

Extrinsic (`extrinsics.py`): the L1 is mounted nearly upside-down; `EXT_R` is the
official `pitch=2.88` flip + `rotate_yaw_bias` (~-123°), ground-leveled. `bestz_traj.txt`
is the bundled reconstructed trajectory (column 6 = z).
