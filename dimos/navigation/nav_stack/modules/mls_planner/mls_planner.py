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

"""Multi-Level Surface (MLS) path planner.

Extracts walkable surfaces from a voxelized global map, builds a sparse
waypoint graph over those surfaces, and plans paths via local A* plus
shortest-path search on the graph. Skeleton — algorithm is filled in
piecewise.
"""

from __future__ import annotations

from typing import Any

from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.nav_msgs.Path import Path
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class MLSPlannerConfig(ModuleConfig):
    world_frame: str = "map"


class MLSPlanner(Module):
    config: MLSPlannerConfig

    global_map: In[PointCloud2]
    start_pose: In[Odometry]
    goal_pose: In[Odometry]
    path: Out[Path]
    surface_map: Out[PointCloud2]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._latest_start: Odometry | None = None

    async def handle_global_map(self, _msg: PointCloud2) -> None:
        return

    async def handle_start_pose(self, msg: Odometry) -> None:
        self._latest_start = msg

    async def handle_goal_pose(self, msg: Odometry) -> None:
        if self._latest_start is None:
            logger.warning("MLSPlanner received goal before start; skipping")
            return
        logger.info(
            "MLSPlanner goal received (not yet implemented)",
            start=(self._latest_start.x, self._latest_start.y, self._latest_start.z),
            goal=(msg.x, msg.y, msg.z),
        )
