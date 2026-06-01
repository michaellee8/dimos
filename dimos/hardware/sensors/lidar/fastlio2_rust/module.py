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

"""Python NativeModule wrapper for the native Rust FAST-LIO2 pipeline.

Unlike the C++ ``FastLio2`` module, this one does not talk to the LiDAR
hardware directly.  It consumes ``lidar`` (PointCloud2) and ``imu`` (Imu)
streams over LCM — wire it to the Livox ``Mid360`` module via autoconnect —
runs the FAST-LIO2 LiDAR-inertial pipeline, and publishes ``odometry`` plus
the registered world-frame scan.

Usage::

    from dimos.hardware.sensors.lidar.fastlio2_rust.module import FastLio2Rust
    from dimos.hardware.sensors.lidar.livox.module import Mid360
    from dimos.core.coordination.blueprints import autoconnect

    from dimos.core.coordination.module_coordinator import ModuleCoordinator
    ModuleCoordinator.build(autoconnect(
        Mid360.blueprint(host_ip="192.168.1.5"),
        FastLio2Rust.blueprint(),
    )).loop()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dimos.core.native_module import NativeModule, NativeModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.sensor_msgs.Imu import Imu
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.navigation.nav_stack.frames import FRAME_BODY, FRAME_ODOM
from dimos.spec import perception


class FastLio2RustConfig(NativeModuleConfig):
    cwd: str | None = "rust"
    executable: str = "result/bin/fastlio2_rust_native"
    build_command: str | None = "nix build .#fastlio2_rust_native"
    stdin_config: bool = True

    # Output message frames.
    frame_id: str = FRAME_ODOM
    child_frame_id: str = FRAME_BODY

    # FAST-LIO2 pipeline parameters (mirror the Rust serde defaults).
    lidar_filter_num: int = 3
    lidar_min_range: float = 0.5
    lidar_max_range: float = 20.0
    scan_resolution: float = 0.15
    map_resolution: float = 0.3
    cube_len: float = 300.0
    det_range: float = 60.0
    move_thresh: float = 1.5
    # Process/measurement noise (accel, gyro, accel-bias, gyro-bias).
    na: float = 0.01
    ng: float = 0.01
    nba: float = 0.0001
    nbg: float = 0.0001
    imu_init_num: int = 20
    near_search_num: int = 5
    ieskf_max_iter: int = 5
    gravity_align: bool = True
    # IMU-to-LiDAR extrinsics; estimate online or hold fixed.
    esti_il: bool = False
    r_il: list[float] = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    t_il: list[float] = [0.0, 0.0, 0.0]
    lidar_cov_inv: float = 1000.0

    def to_config_dict(self) -> dict[str, Any]:
        # frame_id lives on the base NativeModuleConfig, so the default
        # to_config_dict() drops it; the Rust pipeline still needs it.
        config = super().to_config_dict()
        config["frame_id"] = self.frame_id
        return config


class FastLio2Rust(NativeModule, perception.Odometry):
    """Native Rust FAST-LIO2 LiDAR-inertial odometry.

    Ports:
        lidar (In[PointCloud2]): Livox point cloud frames.
        imu (In[Imu]): IMU samples (m/s^2 linear accel, rad/s angular vel).
        odometry (Out[Odometry]): Estimated body pose + twist in ``frame_id``.
        world_cloud (Out[PointCloud2]): Registered (world-frame) scan.
    """

    config: FastLio2RustConfig

    lidar: In[PointCloud2]
    imu: In[Imu]
    odometry: Out[Odometry]
    world_cloud: Out[PointCloud2]


# Verify protocol port compliance (mypy will flag missing ports)
if TYPE_CHECKING:
    FastLio2Rust()
