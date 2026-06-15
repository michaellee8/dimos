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


from dimos.core.coordination.blueprints import autoconnect
from dimos.hardware.sensors.lidar.livox.module import Mid360
from dimos.hardware.sensors.lidar.pointlio.module import PointLio
from dimos.mapping.voxels import VoxelGridMapper
from dimos.visualization.vis_module import vis_module

voxel_size = 0.05

# Mid360 owns the Livox SDK and publishes imu + lidar; PointLio consumes those
# (auto-wired by stream name/type) and publishes odometry.
mid360_pointlio = autoconnect(
    Mid360.blueprint(),
    PointLio.blueprint(),
    vis_module("rerun"),
).global_config(n_workers=3, robot_model="mid360_pointlio")

mid360_pointlio_voxels = autoconnect(
    Mid360.blueprint(),
    PointLio.blueprint(),
    VoxelGridMapper.blueprint(voxel_size=voxel_size, carve_columns=False),
    vis_module(
        "rerun",
        rerun_config={
            "visual_override": {
                "world/lidar": None,
            },
        },
    ),
).global_config(n_workers=4, robot_model="mid360_pointlio_voxels")
