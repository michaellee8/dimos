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

"""R1 Pro keyboard teleop — drives the chassis Twist via WASD.

Composes ``r1pro_coordinator`` (R1ProConnection + ControlCoordinator with the
chassis BASE + r1pro WHOLE_BODY hardware) with ``KeyboardTeleop`` (Twist out).
KeyboardTeleop's ``cmd_vel`` Out is auto-wired to the coordinator's
``twist_command`` In, which routes through the ``vel_chassis`` task into
the chassis ``transport_lcm`` adapter and out to the robot.

Keys (from KeyboardTeleop):
    W/S  ±linear.x          A/D  ±angular.z          Q/E  ±linear.y (strafe)
    Shift  2x boost         Ctrl 0.5x slow           Space  emergency stop

Arms / torso are NOT driven by this blueprint — use the manipulation
blueprint for those.

Usage:
    dimos run r1pro-keyboard-teleop
"""

from __future__ import annotations

from dimos.core.coordination.blueprints import autoconnect
from dimos.robot.galaxea.r1pro.blueprints.basic.r1pro_coordinator import r1pro_coordinator
from dimos.robot.unitree.keyboard_teleop import KeyboardTeleop

r1pro_keyboard_teleop = autoconnect(
    r1pro_coordinator,
    KeyboardTeleop.blueprint(),
)

__all__ = ["r1pro_keyboard_teleop"]
