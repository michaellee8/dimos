#!/usr/bin/env python3
# Copyright 2025-2026 Dimensional Inc.
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

from datetime import datetime
import os
from pathlib import Path

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import global_config
from dimos.core.stream import In
from dimos.hardware.sensors.camera.realsense.camera import RealSenseCamera
from dimos.hardware.sensors.lidar.livox.module import Mid360
from dimos.hardware.sensors.lidar.pointlio.module import PointLio
from dimos.hardware.sensors.lidar.pointlio.recorder import PointlioRecorder
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.sensor_msgs.CameraInfo import CameraInfo
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.Imu import Imu
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.utils.logging_config import set_run_log_dir, setup_logger

logger = setup_logger()

_LIDAR_IP = os.getenv("LIDAR_IP", "192.168.1.107")


def _default_recording_dir() -> Path:
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d") + "_" + now.strftime("%I-%M%p").lower() + "-PST"
    return Path("recordings") / stamp


class RealsenseRecorder(PointlioRecorder):
    """Records Point-LIO odom + lidar plus the RealSense + raw Livox streams.

    Point-LIO stamps each ``pointlio_lidar`` frame with the latest odometry pose
    (inherited ``@pose_setter_for``), so the trajectory is baked into the cloud at
    record time. The camera and raw-livox streams are recorded as-is; the offline
    post-process aligns them.
    """

    pointlio_odometry: In[Odometry]
    pointlio_lidar: In[PointCloud2]
    color_image: In[Image]
    realsense_depth_image: In[Image]
    realsense_pointcloud: In[PointCloud2]
    realsense_camera_info: In[CameraInfo]
    realsense_depth_camera_info: In[CameraInfo]
    realsense_imu: In[Imu]
    livox_lidar: In[PointCloud2]
    livox_imu: In[Imu]


realsense_mid360_record = autoconnect(
    RealSenseCamera.blueprint().remappings(
        [
            (RealSenseCamera, "depth_image", "realsense_depth_image"),
            (RealSenseCamera, "pointcloud", "realsense_pointcloud"),
            (RealSenseCamera, "camera_info", "realsense_camera_info"),
            (RealSenseCamera, "depth_camera_info", "realsense_depth_camera_info"),
            (RealSenseCamera, "imu", "realsense_imu"),
        ]
    ),
    Mid360.blueprint(
        lidar_ip=_LIDAR_IP,
    ).remappings(
        [
            (Mid360, "lidar", "livox_lidar"),
            (Mid360, "imu", "livox_imu"),
        ]
    ),
    PointLio.blueprint(
        frame_id="world",
        lidar_ip=_LIDAR_IP,
    ).remappings(
        [
            (PointLio, "lidar", "pointlio_lidar"),
            (PointLio, "odometry", "pointlio_odometry"),
        ]
    ),
    RealsenseRecorder.blueprint(),
).global_config(n_workers=6)


if __name__ == "__main__":
    recording_dir = _default_recording_dir().resolve()
    recording_dir.mkdir(parents=True, exist_ok=True)
    set_run_log_dir(recording_dir)
    global_config.obstacle_avoidance = False
    coordinator = ModuleCoordinator.build(
        realsense_mid360_record,
        {RealsenseRecorder.name: {"db_path": str(recording_dir / "mem2.db")}},
    )
    coordinator.loop()
