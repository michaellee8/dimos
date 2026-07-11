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

"""Hosted teleop blueprints (WebRTC transport)."""

from pathlib import Path

from dimos.constants import STATE_DIR
from dimos.core.coordination.blueprints import autoconnect
from dimos.core.global_config import global_config
from dimos.core.transport import (
    CloudflareTransport,
    CloudflareVideoTransport,
    LCMTransport,
    LiveKitTransport,
    LiveKitVideoTransport,
)
from dimos.hardware.sensors.camera.realsense.camera import RealSenseCamera
from dimos.mapping.costmapper import CostMapper
from dimos.mapping.voxels import VoxelGridMapper
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.geometry_msgs.TwistStamped import TwistStamped
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.msgs.std_msgs.Bool import Bool
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.manipulators.xarm.blueprints.teleop import (
    coordinator_teleop_xarm6,
    coordinator_teleop_xarm7,
)
from dimos.robot.manipulators.xarm.config import XARM6_SIM_PATH, XARM7_SIM_PATH
from dimos.robot.unitree.go2.blueprints.basic.unitree_go2_basic import unitree_go2_basic
from dimos.robot.unitree.go2.connection import GO2Connection
from dimos.simulation.engines.mujoco_sim_module import MujocoSimModule
from dimos.teleop.quest.quest_types import Buttons
from dimos.teleop.quest_hosted.arm_hosted_connection import ArmHostedConnection
from dimos.teleop.quest_hosted.go2_hosted_connection import Go2HostedConnection
from dimos.teleop.quest_hosted.hosted_extensions import HostedTwistTeleopModule

# Hosted teleop via the legacy module wrapper (the transport swap is preferred).
teleop_hosted_go2 = autoconnect(
    HostedTwistTeleopModule.blueprint(),
    unitree_go2_basic,
).global_config(n_workers=8, viewer="none")


HOSTED_RECORDINGS_DIR = STATE_DIR / "hosted_teleop" / "recordings"


class HostedTeleopRecorderConfig(TeleopRecorderConfig):
    # Same generic recorder, just defaulting recordings into the hosted dir.
    db_path: str | Path = HOSTED_RECORDINGS_DIR / "recording_hosted.db"


class HostedTeleopRecorder(TeleopRecorder):
    """Generic ``TeleopRecorder`` defaulting to the hosted recordings dir.

    Ports + per-run timestamping are inherited; this only changes the default
    output path. Compose at the CLI::

        dimos run teleop-hosted-xarm7 hosted-teleop-recorder
        dimos run teleop-hosted-go2   hosted-teleop-recorder
    """

    config: HostedTeleopRecorderConfig


# ─── XArm hosted manipulation (coordinator-driven, WebXR operator) ──────────
#
# ArmHostedConnection bridges operator VR poses/buttons (over cmd_unreliable) to
# the ControlCoordinator's TeleopIKTask (over LCM), and mux'es the arm cameras
# into one CF video track. All broker-bound streams live on ArmHostedConnection
# so they share the one BrokerProvider session. Run any of these with
# `-o transports.broker.api_key=dtk_live_...`; pass `--simulation` for MuJoCo.


# Distinct classes so two RealSense units coexist in one blueprint: module
# identity is the class throughout the stack (blueprint dedup, coordinator
# registries, remap keys, RPC topics, config namespace). Configure serials with
# -o frontcamera.serial_number=... -o wristcamera.serial_number=...
class FrontCamera(RealSenseCamera):
    pass


class WristCamera(RealSenseCamera):
    pass


# Two-camera XArm hosted teleop: front/overview = cam1, wrist = cam2,
# operator-selectable via camera_select, mux'd into one video track. One
# blueprint per arm; pass --simulation for MuJoCo, omit it for real hardware.
#
# Real: two RealSense units (-o frontcamera.serial_number=... -o
#   wristcamera.serial_number=...).
# --simulation: MuJoCo renders both cams from the arm's scene (env_camera →
#   cam1, wrist_camera → cam2). The coordinator already brings a bare
#   MujocoSimModule; we override it (same class = same module) with one that
#   also renders the overview cam. 848×480 matches RealSense and stays wide
#   enough for the latency stamp (needs ≥768px).
#
# The .transports() dict binds every broker-bound stream to CloudflareTransport
# so they share the one BrokerProvider session. LCM topics that feed the
# coordinator (cartesian_command, ee_twist, gripper) MUST carry the leading
# slash to match its default "/"-prefixed inputs — without it the arm engages
# but never moves.

if global_config.simulation:
    _xarm6_cameras = (
        MujocoSimModule.blueprint(
            address=str(XARM6_SIM_PATH),
            headless=False,
            dof=6,
            camera_name="wrist_camera",
            camera2_name="env_camera",
            width=848,
            height=480,
        ),
    )
    _xarm6_remaps = [
        (MujocoSimModule, "color_image2", "cam1_in"),  # env overview → cam1
        (MujocoSimModule, "color_image", "cam2_in"),  # wrist → cam2
    ]
else:
    _xarm6_cameras = (
        FrontCamera.blueprint(camera_name="front", enable_depth=False, enable_pointcloud=False),
        WristCamera.blueprint(camera_name="wrist", enable_depth=False, enable_pointcloud=False),
    )
    _xarm6_remaps = [
        (FrontCamera, "color_image", "cam1_in"),
        (WristCamera, "color_image", "cam2_in"),
    ]

teleop_hosted_xarm6 = (
    autoconnect(
        ArmHostedConnection.blueprint(task_names={"right": "teleop_xarm"}),
        coordinator_teleop_xarm6,
        *_xarm6_cameras,
    )
    .remappings(_xarm6_remaps)
    .transports(
        {
            ("cmd_raw", bytes): CloudflareTransport.spec("cmd_unreliable"),
            ("state_json", bytes): CloudflareTransport.spec("state_reliable"),
            ("telemetry_out", bytes): CloudflareTransport.spec("state_reliable_back"),
            ("mux_image", Image): CloudflareVideoTransport.spec(),
            ("right_controller_output", PoseStamped): LCMTransport.spec(
                "/coordinator_cartesian_command", PoseStamped
            ),
            ("teleop_buttons", Buttons): LCMTransport.spec("teleop_buttons", Buttons),
            ("coordinator_ee_twist_command", TwistStamped): LCMTransport.spec(
                "/coordinator_ee_twist_command", TwistStamped
            ),
            ("gripper_command", Bool): LCMTransport.spec("/gripper_command", Bool),
            # Cameras → station over LCM (cameras run in other workers).
            ("cam1_in", Image): LCMTransport.spec("cam1_in", Image),
            ("cam2_in", Image): LCMTransport.spec("cam2_in", Image),
        }
    )
    .global_config(viewer="none")
)


if global_config.simulation:
    _xarm7_cameras = (
        MujocoSimModule.blueprint(
            address=str(XARM7_SIM_PATH),
            headless=False,
            dof=7,
            camera_name="wrist_camera",
            camera2_name="env_camera",
            width=848,
            height=480,
        ),
    )
    _xarm7_remaps = [
        (MujocoSimModule, "color_image2", "cam1_in"),  # env overview → cam1
        (MujocoSimModule, "color_image", "cam2_in"),  # wrist → cam2
    ]
else:
    _xarm7_cameras = (
        FrontCamera.blueprint(camera_name="front", enable_depth=False, enable_pointcloud=False),
        WristCamera.blueprint(camera_name="wrist", enable_depth=False, enable_pointcloud=False),
    )
    _xarm7_remaps = [
        (FrontCamera, "color_image", "cam1_in"),
        (WristCamera, "color_image", "cam2_in"),
    ]

teleop_hosted_xarm7 = (
    autoconnect(
        ArmHostedConnection.blueprint(task_names={"right": "teleop_xarm"}),
        coordinator_teleop_xarm7,
        *_xarm7_cameras,
    )
    .remappings(_xarm7_remaps)
    .transports(
        {
            ("cmd_raw", bytes): CloudflareTransport.spec("cmd_unreliable"),
            ("state_json", bytes): CloudflareTransport.spec("state_reliable"),
            ("telemetry_out", bytes): CloudflareTransport.spec("state_reliable_back"),
            ("mux_image", Image): CloudflareVideoTransport.spec(),
            ("right_controller_output", PoseStamped): LCMTransport.spec(
                "/coordinator_cartesian_command", PoseStamped
            ),
            ("teleop_buttons", Buttons): LCMTransport.spec("teleop_buttons", Buttons),
            ("coordinator_ee_twist_command", TwistStamped): LCMTransport.spec(
                "/coordinator_ee_twist_command", TwistStamped
            ),
            ("gripper_command", Bool): LCMTransport.spec("/gripper_command", Bool),
            # Cameras → station over LCM (cameras run in other workers).
            ("cam1_in", Image): LCMTransport.spec("cam1_in", Image),
            ("cam2_in", Image): LCMTransport.spec("cam2_in", Image),
        }
    )
    .global_config(viewer="none")
)


__all__ = [
    "teleop_hosted_go2",
    "teleop_hosted_go2_livekit",
    "teleop_hosted_go2_multicam",
    "teleop_hosted_go2_transport",
    "teleop_hosted_xarm6",
    "teleop_hosted_xarm7",
]
