# XArm Voxel Planning Viser Demo

`xarm-voxel-planning-viser-demo` is an opt-in xArm7 MuJoCo demo for manually validating voxel-backed RoboPlan collision checking with Viser visualization.

Run it with MuJoCo simulation:

```bash
dimos --simulation run xarm-voxel-planning-viser-demo
```

The stack contains `MujocoSimModule`, `PointCloudSelfFilter`, `TfPoseSource`, `RayTracingVoxelMap`, `ManipulationModule`, and the xArm coordinator. It does not include the GPD/VGN grasp demo controllers, pick/place skills, or an agent loop.

Planning map stream chain:

```text
MujocoSimModule.pointcloud
  -> PointCloudSelfFilter.filtered_pointcloud
  -> RayTracingVoxelMap.global_map
  -> ManipulationModule.planning_voxel_map
```

Viser renders the planning voxel map at `/planning/voxel_map` as round, height-colored points from the latest map synchronized into the planning world before planning.

Key configuration values:

- `world_backend="roboplan"`
- `planner_name="roboplan"`
- `kinematics={"backend": "roboplan"}`
- mapper voxel resolution: `0.02` m
- planning collision voxel resolution: `0.04` m
- voxel persistence tuning: `min_health=0`, `max_health=4`
- ray clearing tuning: `shadow_depth=0.08`, `grace_depth=0.08`
- strict world frame: mapper and planning input use `world`

Known v1 limitations:

- self-filtering uses configured primitives only;
- no Scene Registry integration;
- no required workspace crop;
- voxel resolution is configured out-of-band/static;
- target-object voxels are not semantically excluded.
