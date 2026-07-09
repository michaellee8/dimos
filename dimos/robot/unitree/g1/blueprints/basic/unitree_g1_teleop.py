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

"""Unitree G1 GR00T WBC + Quest teleop.

The full ``unitree-g1-groot-wbc`` stack (locomotion policy, nav, viewer,
``--simulation mujoco`` / ``--scene-package`` support) plus the Quest WebXR
retargeting module. Put on the headset, open
``https://<host>:8443/teleop``, and:

    left stick        walk forward/back (+ yaw or strafe, see
                      ``right_stick_mode``)
    right stick       yaw (press = zero-Twist e-stop)
    both triggers     hold to track your hands with the robot's arms
                      (release: arms hold in place)

Wrist targets route to the ``dual_arm_ik`` coordinator task declared in
the groot blueprint (frame_id "dual_arm_ik/left|right"); locomotion goes
out as ``cmd_vel``. If a ``color_image`` producer exists in the
composition (real robot camera), frames are pushed into the headset.

Usage:
    dimos --simulation mujoco --scene-package office run unitree-g1-teleop
    dimos run unitree-g1-teleop                      # real hardware
"""

from __future__ import annotations

from dimos.core.coordination.blueprints import autoconnect
from dimos.robot.unitree.g1.blueprints.basic.unitree_g1_groot_wbc import unitree_g1_groot_wbc
from dimos.robot.unitree.g1.quest_teleop import G1QuestTeleopModule

unitree_g1_teleop = autoconnect(
    unitree_g1_groot_wbc,
    G1QuestTeleopModule.blueprint(),
).remappings(
    [
        (G1QuestTeleopModule, "left_controller_output", "coordinator_cartesian_command"),
        (G1QuestTeleopModule, "right_controller_output", "coordinator_cartesian_command"),
    ]
)
