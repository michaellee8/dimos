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

"""ACT inference blueprints.

`ChunkPolicyModule` publishes `joint_command` directly so a coordinator's
servo / position task can consume it without an `ActionReplayer` task in
the tick loop. Two variants are provided:

* ``learning_infer_chunkpolicy_only`` — policy + camera only. Compose at
  the call site with your own coordinator::

      autoconnect(learning_infer_chunkpolicy_only, my_servo_coordinator)

* ``learning_infer_xarm7`` — sample fully wired blueprint: policy +
  camera + XArm7 ControlCoordinator running a servo task. The
  coordinator publishes ``joint_state`` and consumes ``joint_command``
  on the same LCM topics the policy uses, so ``autoconnect`` closes the
  loop with no extra glue. Use as a template for other arms.
"""

from __future__ import annotations

from dimos.control.coordinator import ControlCoordinator
from dimos.core.coordination.blueprints import autoconnect
from dimos.core.global_config import global_config
from dimos.core.transport import LCMTransport
from dimos.hardware.sensors.camera.realsense.camera import RealSenseCamera
from dimos.learning.inference.chunk_policy_module import ChunkPolicyModule
from dimos.learning.policy.base import ActionChunk
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.JointState import JointState
from dimos.robot.catalog.ufactory import xarm7 as _catalog_xarm7

# Stable topics so external tools (lcmspy, dimos topic echo) work without rebuild.
_T_COLOR_IMAGE   = "/camera/color_image"
_T_JOINT_STATE   = "/coordinator/joint_state"
_T_ACTION_CHUNK  = "/learning/action_chunk"
_T_JOINT_COMMAND = "/teleop/joint_command"  # matches coordinator_servo_* default

_INFER_TRANSPORTS = {
    ("color_image",   Image):       LCMTransport(_T_COLOR_IMAGE,   Image),
    ("joint_state",   JointState):  LCMTransport(_T_JOINT_STATE,   JointState),
    ("action_chunk",  ActionChunk): LCMTransport(_T_ACTION_CHUNK,  ActionChunk),
    ("joint_command", JointState):  LCMTransport(_T_JOINT_COMMAND, JointState),
}


learning_infer_chunkpolicy_only = autoconnect(
    RealSenseCamera.blueprint(enable_pointcloud=False),
    ChunkPolicyModule.blueprint(
        policy_path="data/runs/act_pickplace_001",
        inference_rate_hz=30.0,
    ),
).transports(_INFER_TRANSPORTS)


# Sample end-to-end inference blueprint: policy → coordinator → hardware.
# Mirror the arm config used in collection (xarm7 + gripper) so trained
# joint_names line up with what the servo task claims.
_xarm7_infer_cfg = _catalog_xarm7(
    name="arm",
    adapter_type="xarm",
    address=global_config.xarm7_ip,
    add_gripper=True,
)

learning_infer_xarm7 = autoconnect(
    RealSenseCamera.blueprint(enable_pointcloud=False),
    ChunkPolicyModule.blueprint(
        policy_path="data/runs/act_pickplace_001",
        inference_rate_hz=30.0,
        publish_joint_command=True,
    ),
    ControlCoordinator.blueprint(
        hardware=[_xarm7_infer_cfg.to_hardware_component()],
        tasks=[
            _xarm7_infer_cfg.to_task_config(task_type="servo", task_name="servo_arm"),
        ],
    ),
).transports(_INFER_TRANSPORTS)


__all__ = [
    "learning_infer_chunkpolicy_only",
    "learning_infer_xarm7",
]
