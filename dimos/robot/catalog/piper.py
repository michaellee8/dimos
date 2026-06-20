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

"""Agilex Piper robot configuration."""

from __future__ import annotations

from typing import Any

from dimos.robot.assets.source import RobotDescriptionSource
from dimos.robot.config import GripperConfig, RobotConfig
from dimos.utils.data import LfsPath

PIPER_DESCRIPTION_REPO = "https://github.com/agilexrobotics/agx_arm_urdf"
_PIPER_REPO = RobotDescriptionSource(url=PIPER_DESCRIPTION_REPO, ref="main")
_PIPER_PACKAGE_PATHS = {
    # Upstream URDFs reference package://agx_arm_description/agx_arm_urdf/...
    # and expect the checkout directory to be named agx_arm_urdf inside the
    # package root. GitAssetCache preserves that checkout directory name.
    "agx_arm_description": _PIPER_REPO.parent,
}

# Static no-gripper URDF for Pinocchio FK (xacro not supported by Pinocchio)
PIPER_FK_MODEL = _PIPER_REPO / "piper" / "urdf" / "piper_description.urdf"

# Simulation model path (MJCF)
PIPER_SIM_PATH = LfsPath("piper/scene.xml")

# Piper gripper collision exclusions (parallel jaw gripper)
# The gripper fingers (link7, link8) can touch each other and gripper_base
PIPER_GRIPPER_COLLISION_EXCLUSIONS: list[tuple[str, str]] = [
    ("gripper_base", "link7"),
    ("gripper_base", "link8"),
    ("link7", "link8"),
    ("link6", "gripper_base"),
]


def piper(
    name: str = "piper",
    *,
    adapter_type: str = "mock",
    address: str | None = None,
    y_offset: float = 0.0,
    **overrides: Any,
) -> RobotConfig:
    """Create a Piper robot configuration.

    Piper has 6 revolute joints (joint1-joint6) for the arm and 2 prismatic
    joints (joint7, joint8) for the parallel jaw gripper.

    Args:
        name: Robot identifier.
        adapter_type: Hardware adapter ("mock", "piper").
        address: CAN port (e.g., "can0").
        y_offset: Y-axis offset for base pose (multi-arm setups).
        **overrides: Override any RobotConfig field.
    """
    defaults: dict[str, Any] = {
        "name": name,
        "model_path": _PIPER_REPO / "piper" / "urdf" / "piper_with_gripper_description.xacro",
        "end_effector_link": "gripper_base",
        "adapter_type": adapter_type,
        "address": address,
        "joint_names": [f"joint{i}" for i in range(1, 7)],
        "base_link": "base_link",
        "home_joints": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "base_pose": [0, y_offset, 0, 0, 0, 0, 1],
        "package_paths": _PIPER_PACKAGE_PATHS,
        "xacro_args": {},
        "auto_convert_meshes": True,
        "collision_exclusion_pairs": PIPER_GRIPPER_COLLISION_EXCLUSIONS,
        "gripper": GripperConfig(
            type="piper",
            joints=["gripper"],
            collision_exclusions=PIPER_GRIPPER_COLLISION_EXCLUSIONS,
            open_position=0.08,
            close_position=0.0,
        ),
    }
    defaults.update(overrides)
    return RobotConfig(**defaults)


__all__ = ["PIPER_FK_MODEL", "PIPER_GRIPPER_COLLISION_EXCLUSIONS", "piper"]
