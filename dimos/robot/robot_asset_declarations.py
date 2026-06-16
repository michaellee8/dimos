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

"""Robot asset declarations resolved by :mod:`dimos.robot.asset_manager`."""

from __future__ import annotations

from dimos.robot.asset_manager import RobotAssetDeclaration

XARM_ROS2_REPO = "https://github.com/xArm-Developer/xarm_ros2"
PIPER_DESCRIPTION_REPO = "https://github.com/agilexrobotics/agx_arm_urdf"
A750_DESCRIPTION_REPO = "https://github.com/adob/a750_description"


ROBOT_ASSETS: dict[str, RobotAssetDeclaration] = {
    "xarm6": RobotAssetDeclaration(
        model="xarm6",
        repo_url=XARM_ROS2_REPO,
        ref="humble",
        artifacts={
            "urdf": "xarm_description/urdf/xarm_device.urdf.xacro",
            "mesh_dir": "xarm_description/meshes",
        },
        package_roots={"xarm_description": "xarm_description"},
        xacro_args={"dof": "6", "limited": "true"},
        source_name="xarm_ros2",
    ),
    "xarm7": RobotAssetDeclaration(
        model="xarm7",
        repo_url=XARM_ROS2_REPO,
        ref="humble",
        artifacts={
            "urdf": "xarm_description/urdf/xarm_device.urdf.xacro",
            "mesh_dir": "xarm_description/meshes",
        },
        package_roots={"xarm_description": "xarm_description"},
        xacro_args={"dof": "7", "limited": "true"},
        source_name="xarm_ros2",
    ),
    "piper": RobotAssetDeclaration(
        model="piper",
        repo_url=PIPER_DESCRIPTION_REPO,
        ref="main",
        artifacts={
            "urdf": "piper/urdf/piper_with_gripper_description.xacro",
            "urdf_ik": "piper/urdf/piper_description.urdf",
            "mesh_dir": "piper/meshes",
        },
        # Upstream URDFs reference package://agx_arm_description/agx_arm_urdf/...
        # and expect the checkout directory to be named agx_arm_urdf inside the
        # package root. GitAssetCache preserves that checkout directory name.
        package_roots={"agx_arm_description": ".."},
        source_name="agx_arm_urdf",
        license="MIT",
    ),
    "a750": RobotAssetDeclaration(
        model="a750",
        repo_url=A750_DESCRIPTION_REPO,
        ref="master",
        artifacts={
            "urdf": "urdf/a750_rev1.urdf",
            "mesh_dir": "meshes/a750_rev1",
        },
        package_roots={"a750_description": "."},
        source_name="a750_description",
        license="MIT",
    ),
}
