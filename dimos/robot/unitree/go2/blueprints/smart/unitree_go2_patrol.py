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

"""Two-point patrol blueprint (simple-nav base).

Click two points in the dimos-viewer; the robot patrols A <-> B until you touch
teleop (WASD), which halts it. Click two new points to re-arm.

This composes the same simple-nav stack as `unitree_go2`, but inserts a
`PatrolController` on the click line. The planner's and MovementManager's
`clicked_point` inputs are remapped to `patrol_goal`, so the controller — not
the raw viewer click — decides the planner's goal.

For the Mid-360 demo, apply the SAME two changes to
`unitree_go2_mid360_nav.py` on the NUC:
  1. add `PatrolController.blueprint()` to the autoconnect, and
  2. `.remappings(...)` the planner + MovementManager `clicked_point` -> `patrol_goal`.
"""

from dimos.core.coordination.blueprints import autoconnect
from dimos.mapping.costmapper import CostMapper
from dimos.mapping.voxels import VoxelGridMapper
from dimos.navigation.movement_manager.movement_manager import MovementManager
from dimos.navigation.patrol_controller import PatrolController
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.unitree.go2.blueprints.basic.unitree_go2_basic import unitree_go2_basic

unitree_go2_patrol = autoconnect(
    unitree_go2_basic,
    VoxelGridMapper.blueprint(emit_every=5),
    CostMapper.blueprint(),
    ReplanningAStarPlanner.blueprint().remappings(
        [(ReplanningAStarPlanner, "clicked_point", "patrol_goal")]
    ),
    MovementManager.blueprint().remappings(
        [(MovementManager, "clicked_point", "patrol_goal")]
    ),
    PatrolController.blueprint(),
).global_config(n_workers=10, robot_model="unitree_go2")
