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

"""AgiBot X2 policy constants shared by blueprints and control tasks.

``X2_JOINTS`` is the Dimos hardware/actuator order used by the MuJoCo
whole-body adapter.  The trained mjlab policy observes joints in MuJoCo qpos
order instead, where the arm joints come before the head joints; use
``X2_POLICY_JOINTS`` for ONNX observation/default/action vectors.
"""

X2_JOINTS: list[str] = [
    "x2/left_hip_pitch",
    "x2/left_hip_roll",
    "x2/left_hip_yaw",
    "x2/left_knee",
    "x2/left_ankle_pitch",
    "x2/left_ankle_roll",
    "x2/right_hip_pitch",
    "x2/right_hip_roll",
    "x2/right_hip_yaw",
    "x2/right_knee",
    "x2/right_ankle_pitch",
    "x2/right_ankle_roll",
    "x2/waist_yaw",
    "x2/waist_pitch",
    "x2/waist_roll",
    "x2/head_yaw",
    "x2/head_pitch",
    "x2/left_shoulder_pitch",
    "x2/left_shoulder_roll",
    "x2/left_shoulder_yaw",
    "x2/left_elbow",
    "x2/left_wrist_yaw",
    "x2/left_wrist_pitch",
    "x2/left_wrist_roll",
    "x2/right_shoulder_pitch",
    "x2/right_shoulder_roll",
    "x2/right_shoulder_yaw",
    "x2/right_elbow",
    "x2/right_wrist_yaw",
    "x2/right_wrist_pitch",
    "x2/right_wrist_roll",
]

X2_POLICY_JOINTS: list[str] = [
    "x2/left_hip_pitch",
    "x2/left_hip_roll",
    "x2/left_hip_yaw",
    "x2/left_knee",
    "x2/left_ankle_pitch",
    "x2/left_ankle_roll",
    "x2/right_hip_pitch",
    "x2/right_hip_roll",
    "x2/right_hip_yaw",
    "x2/right_knee",
    "x2/right_ankle_pitch",
    "x2/right_ankle_roll",
    "x2/waist_yaw",
    "x2/waist_pitch",
    "x2/waist_roll",
    "x2/left_shoulder_pitch",
    "x2/left_shoulder_roll",
    "x2/left_shoulder_yaw",
    "x2/left_elbow",
    "x2/left_wrist_yaw",
    "x2/left_wrist_pitch",
    "x2/left_wrist_roll",
    "x2/right_shoulder_pitch",
    "x2/right_shoulder_roll",
    "x2/right_shoulder_yaw",
    "x2/right_elbow",
    "x2/right_wrist_yaw",
    "x2/right_wrist_pitch",
    "x2/right_wrist_roll",
    "x2/head_yaw",
    "x2/head_pitch",
]

X2_DEFAULT_POSITIONS: list[float] = [
    -0.2,
    0.0,
    0.0,
    0.4,
    -0.2,
    0.0,
    -0.2,
    0.0,
    0.0,
    0.4,
    -0.2,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.2,
    0.0,
    -0.5,
    0.0,
    0.0,
    0.0,
    0.0,
    -0.2,
    0.0,
    -0.5,
    0.0,
    0.0,
    0.0,
]

X2_LEG_JOINTS: list[str] = X2_JOINTS[:12]
X2_UPPER_BODY_JOINTS: list[str] = X2_JOINTS[12:]
X2_UPPER_BODY_DEFAULT_POSITIONS: list[float] = X2_DEFAULT_POSITIONS[12:]
_X2_DEFAULT_BY_JOINT = dict(zip(X2_JOINTS, X2_DEFAULT_POSITIONS, strict=True))
X2_POLICY_DEFAULT_POSITIONS: list[float] = [
    _X2_DEFAULT_BY_JOINT[joint] for joint in X2_POLICY_JOINTS
]

X2_ACTION_SCALE: list[float] = [
    # Legs are policy-controlled.
    0.5,
    0.35,
    0.5,
    0.35,
    0.4,
    0.4,
    0.5,
    0.35,
    0.5,
    0.35,
    0.4,
    0.4,
    # Waist, head, and arms are decoupled: policy outputs are ignored and PD
    # targets come from held pose / teleop commands.
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
]
_X2_ACTION_SCALE_BY_JOINT = dict(zip(X2_JOINTS, X2_ACTION_SCALE, strict=True))
X2_POLICY_ACTION_SCALE: list[float] = [
    _X2_ACTION_SCALE_BY_JOINT[joint] for joint in X2_POLICY_JOINTS
]

X2_KP: list[float] = [
    40.0,
    40.0,
    30.0,
    80.0,
    40.0,
    20.0,
    40.0,
    40.0,
    30.0,
    80.0,
    40.0,
    20.0,
    120.0,
    120.0,
    120.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
    20.0,
]

X2_KD: list[float] = [
    4.0,
    4.0,
    3.0,
    8.0,
    4.0,
    2.0,
    4.0,
    4.0,
    3.0,
    8.0,
    4.0,
    2.0,
    12.0,
    12.0,
    12.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
    2.0,
]

__all__ = [
    "X2_ACTION_SCALE",
    "X2_DEFAULT_POSITIONS",
    "X2_JOINTS",
    "X2_KD",
    "X2_KP",
    "X2_LEG_JOINTS",
    "X2_POLICY_ACTION_SCALE",
    "X2_POLICY_DEFAULT_POSITIONS",
    "X2_POLICY_JOINTS",
    "X2_UPPER_BODY_DEFAULT_POSITIONS",
    "X2_UPPER_BODY_JOINTS",
]
