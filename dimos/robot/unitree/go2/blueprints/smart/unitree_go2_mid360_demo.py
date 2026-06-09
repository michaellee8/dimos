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

"""Unitree Go2 click-to-navigate demo on an external Livox Mid-360 LiDAR.

This is the ``unitree-go2`` nav experience (camera + click-to-go + WASD), but
with the map built from the Mid-360 + FastLio2 SLAM front-end instead of the
Go2's built-in WebRTC LiDAR. It is assembled from parts already proven on this
branch:

- Front-end (sensor + SLAM): the FastLio2 config that runs cleanly in
  ``unitree-go2-record`` — including ``max_velocity_norm_ms=3.1``, the
  anti-divergence cap (~7 mph) that record uses to keep SLAM from blowing up
  while the dog is driven.
- Back-end (nav): the same RayTracingVoxelMap -> CostMapper ->
  ReplanningAStarPlanner -> MovementManager stack ``unitree-go2`` uses.
- Base (camera + viewer): ``unitree_go2_basic`` on this branch, which has
  ClockSync disabled (the camera-window fix — the WebRTC image stream has no
  timestamps, so clock-sync mis-correlated the feed).

Click-to-navigate flow::

    dimos-viewer click ─→ RerunWebSocketServer.clicked_point ─┐
    RayTracingVoxelMap.global_map ─→ CostMapper.global_costmap ┤
    FastLio2.odometry ─→ OdometryToPoseStamped.odom ───────────┴─→ ReplanningAStarPlanner
        ReplanningAStarPlanner.nav_cmd_vel ─→ MovementManager ─→ cmd_vel ─→ GO2Connection

Modelled on ``jerin/feat/mid360_map``'s ``unitree_go2_mid360_nav`` (the graph)
and ``unitree-go2-record`` (the validated sensor config).

Usage:
    dimos run unitree-go2-mid360-demo
    # override the LiDAR IP if it isn't the venue default:
    LIDAR_IP=192.168.1.155 dimos run unitree-go2-mid360-demo
"""

from __future__ import annotations

import os

# Debug: publishes ReplanningAStarPlanner's inflated navigation_costmap so the
# robot/goal connectivity is visible in rerun. Set before importing the planner.
os.environ.setdefault("DEBUG_NAVIGATION", "1")

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.core import rpc
from dimos.core.module import Module
from dimos.core.stream import In, Out
from dimos.hardware.sensors.lidar.fastlio2.module import FastLio2
from dimos.mapping.costmapper import CostMapper
from dimos.mapping.pointclouds.occupancy import GeneralOccupancyConfig
from dimos.mapping.ray_tracing.module import RayTracingVoxelMap
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.navigation.movement_manager.movement_manager import MovementManager
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.unitree.go2.blueprints.basic.unitree_go2_basic import unitree_go2_basic
from dimos.robot.unitree.go2.connection import GO2Connection

# Documented Mid-360 IP for the venue rig (NOT the .155 factory default).
# Overridable via LIDAR_IP, matching unitree-go2-record's convention.
_LIDAR_IP = os.getenv("LIDAR_IP", "192.168.1.157")

# Shared voxel size for FastLio2's internal filtering and the ray-traced map.
voxel_size = 0.05

# Anti-divergence velocity cap (m/s). FastLio2 defaults this to 0.0 (disabled);
# unitree-go2-record sets 3.1 (~7 mph) — enough headroom for the Go2 with some
# buffer, while keeping SLAM from catastrophically diverging when driven.
max_velocity_norm_ms = 3.1

# Mid-360 mounted on the Go2 head, ~0.45 m off the floor (matches the
# record-rig geometry, ~0.47 m). Orientation is left identity: the lidar's
# forward pitch is absorbed by FastLio2's IMU gravity alignment at startup, so
# for anchoring the world frame to ground (z=0) only the height matters.
mid360_mount = Pose(0.0, 0.0, 0.45, *Quaternion.from_euler(Vector3(0, 0, 0)))

# Anything below this height is treated as floor/self and ignored when building
# the costmap. The Mid-360 sits ~0.45 m up and the rest of the Go2 below it, so
# 0.5 m safely excludes the dog's own body. Tradeoff: low obstacles (e.g. chair
# legs that stop below 0.5 m) won't show up.
costmap_min_height = 0.5


class OdometryToPoseStamped(Module):
    """Repackages FastLio2's ``Odometry`` as a ``PoseStamped`` on ``odom``.

    ``ReplanningAStarPlanner`` expects the robot pose as ``PoseStamped`` on
    ``odom``; FastLio2 publishes it as ``Odometry``. Converting here keeps the
    planner's pose in the same SLAM frame as the ray-traced map it plans on
    (using ``GO2Connection.odom`` instead would drift relative to the map).
    """

    odometry: In[Odometry]
    odom: Out[PoseStamped]

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(self.odometry.subscribe(self._on_odometry))

    @rpc
    def stop(self) -> None:
        super().stop()

    def _on_odometry(self, msg: Odometry) -> None:
        self.odom.publish(
            PoseStamped(
                ts=msg.ts,
                frame_id=msg.frame_id,
                position=msg.position,
                orientation=msg.orientation,
            )
        )


unitree_go2_mid360_demo = (
    autoconnect(
        unitree_go2_basic,
        # map_freq=-1 disables FastLio2's own global map so only the
        # ray-tracer publishes `global_map` (avoids a topic conflict).
        FastLio2.blueprint(
            voxel_size=voxel_size,
            map_voxel_size=voxel_size,
            map_freq=-1,
            lidar_ip=_LIDAR_IP,
            mount=mid360_mount,
            max_velocity_norm_ms=max_velocity_norm_ms,
        ),
        RayTracingVoxelMap.blueprint(voxel_size=voxel_size, max_health=3, grace_depth=0.4),
        OdometryToPoseStamped.blueprint(),
        # general_occupancy ignores points below `min_height` — keeps the Go2's
        # own body out of the costmap so the robot isn't standing inside an
        # inflated obstacle.
        CostMapper.blueprint(
            algo="general",
            config=GeneralOccupancyConfig(min_height=costmap_min_height),
        ),
        ReplanningAStarPlanner.blueprint(),
        MovementManager.blueprint(),
        # FastLio2 owns the robot pose. Attach the Go2's `base_link` TF chain
        # under FastLio2's `body` (identity), so the rendered robot box and
        # camera frame line up with the planner's idea of where the robot is
        # — instead of drifting off into the Go2's independent webrtc odom.
        GO2Connection.blueprint(tf_base_link_parent="body"),
    )
    # FastLio2 owns the world-frame `lidar`; OdometryToPoseStamped owns the
    # world-frame `odom`. The Go2's built-in copies are moved aside so they
    # don't collide with the FastLio2-derived topics the nav stack plans on.
    .remappings([
        (GO2Connection, "lidar", "go2_lidar"),
        (GO2Connection, "odom", "go2_odom"),
    ])
    .global_config(n_workers=10, robot_model="unitree_go2")
)

__all__ = ["unitree_go2_mid360_demo"]
