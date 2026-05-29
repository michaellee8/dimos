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

"""Unitree Go2 FOPDT characterization — one-terminal HW flow.

Bundles GO2Connection + ControlCoordinator + (publish-only-when-active)
pygame keyboard teleop with the :class:`Characterizer` module so the
operator runs a single command:

    dimos run unitree-go2-characterization

instead of the two-terminal flow (``dimos run
unitree-go2-webrtc-keyboard-teleop`` + ``python -m
dimos.utils.benchmarking.characterization``). All operator input goes
through the pygame window:

  * **WASD/QE** — reposition the robot between steps (existing teleop).
  * **ENTER** — advance to the next SI step.
  * **K** — skip the current amplitude.
  * **Backspace** — quit (no artifact written).

Why the gate stream: ``dimos run`` deploys modules into forkserver
worker subprocesses that don't share the parent CLI's TTY, so
``input()`` inside the Characterizer would EOF immediately. Routing the
operator's ENTER/K/Backspace through KeyboardTeleop's pygame event loop
(which already owns its own X11 window for movement keys) and an
``Out[str]`` -> ``In[str]`` stream avoids stdin entirely.

For ``--mode self-test`` (pure in-process math) keep using the CLI
entrypoint. For end-to-end sim characterization, bring up
``coordinator-sim-fopdt`` in one terminal and run the CLI with
``--mode hw`` in another.
"""

from __future__ import annotations

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.transport import LCMTransport
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.sensor_msgs.JointState import JointState
from dimos.msgs.std_msgs.Int8 import Int8
from dimos.robot.unitree.go2.blueprints.basic.unitree_go2_coordinator import (
    unitree_go2_coordinator,
    unitree_go2_coordinator_rage,
)
from dimos.robot.unitree.keyboard_teleop import KeyboardTeleop
from dimos.utils.benchmarking.characterization import Characterizer
from dimos.utils.benchmarking.characterization_recorder import CharacterizationRecorder


def _make(coord, gait_mode: str, max_dist: float | None = None, step_s: float | None = None):
    """Compose the characterization blueprint.

    ``max_dist`` and ``step_s`` are per-step safety caps (the step ends
    on whichever comes first). For the default Go2 gait the profile
    defaults (6 m / 8 s) are sane. For rage we cut max_dist hard — the
    same commanded amplitude produces roughly 2x the output velocity,
    so the robot covers the default 6 m well before the FOPDT step
    finishes. 3 m keeps the high-amplitude steps inside a reasonable
    test arena while still allowing 1.5 s ~= 3.75*tau at 2 m/s output --
    enough to capture the rise to steady-state.
    """
    char_kwargs = {
        "robot": "go2",
        "mode": "hw",
        "gate_source": "stream",
        "gait_mode": gait_mode,
    }
    if max_dist is not None:
        char_kwargs["max_dist"] = max_dist
    if step_s is not None:
        char_kwargs["step_s"] = step_s
    return autoconnect(
        coord,
        KeyboardTeleop.blueprint(publish_only_when_active=True),
        Characterizer.blueprint(**char_kwargs),
        CharacterizationRecorder.blueprint(robot_id="go2", tag=f"recording_{gait_mode}"),
    ).transports(
        {
            ("gate", Int8): LCMTransport("/characterizer/gate", Int8),
            ("cmd_vel", Twist): LCMTransport("/cmd_vel", Twist),
            ("joint_state", JointState): LCMTransport("/coordinator/joint_state", JointState),
            ("odom", PoseStamped): LCMTransport("/go2/odom", PoseStamped),
        }
    )


unitree_go2_characterization = _make(unitree_go2_coordinator, gait_mode="default")
# Rage variant: same composition but the Go2 firmware is put into
# FsmRageMode on startup (faster / harder gait). Use it when you want
# to characterize the plant in rage mode for tuning the precision
# follower against that envelope. ``gait_mode="rage"`` is stamped into
# the artifact's provenance so the resulting JSON is clearly tagged
# (DERIVE uses it for the caveat string).
#
# Distance caps are tightened (3 m, 4 s) because rage roughly doubles
# the output velocity per commanded amp — the default 6 m / 8 s would
# run the robot off the floor at amp=2.0. Override per run with:
#   dimos run unitree-go2-characterization-rage \
#       -o characterizer.max_dist=2.0 -o characterizer.step_s=3.0
unitree_go2_characterization_rage = _make(
    unitree_go2_coordinator_rage,
    gait_mode="rage",
    max_dist=3.0,
    step_s=4.0,
)

__all__ = [
    "unitree_go2_characterization",
    "unitree_go2_characterization_rage",
]
