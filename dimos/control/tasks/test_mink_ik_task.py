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

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("mink")
import mujoco

from dimos.control.task import CoordinatorState, JointStateSnapshot
from dimos.control.tasks.mink_ik_task.mink_ik_task import MinkIKTask, MinkIKTaskConfig
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped

_ARM_XML = """
<mujoco model="mini_arm">
  <compiler angle="radian"/>
  <worldbody>
    <body name="base">
      <body name="link1" pos="0 0 0.1">
        <joint name="j1" type="hinge" axis="0 0 1" range="-3.0 3.0"/>
        <geom name="l1_geom" type="capsule" fromto="0.05 0 0 0.2 0 0" size="0.03"/>
        <body name="link2" pos="0.2 0 0">
          <joint name="j2" type="hinge" axis="0 1 0" range="-2.5 2.5"/>
          <geom name="l2_geom" type="capsule" fromto="0 0 0 0.2 0 0" size="0.03"/>
          <body name="link3" pos="0.2 0 0">
            <joint name="j3" type="hinge" axis="0 1 0" range="-2.5 2.5"/>
            <geom name="l3_geom" type="capsule" fromto="0 0 0 0.15 0 0" size="0.025"/>
            <body name="ee_link" pos="0.15 0 0">
              <geom name="ee_geom" type="sphere" size="0.02"/>
            </body>
          </body>
        </body>
      </body>
    </body>
  </worldbody>
</mujoco>
"""

_JOINTS = ["mini/j1", "mini/j2", "mini/j3"]
_NAME_MAP = {"mini/j1": "j1", "mini/j2": "j2", "mini/j3": "j3"}


@pytest.fixture
def task(tmp_path: Path) -> MinkIKTask:
    model = tmp_path / "mini_arm.xml"
    model.write_text(_ARM_XML)
    return MinkIKTask(
        "mink_arms",
        MinkIKTaskConfig(
            joint_names=_JOINTS,
            model_path=model,
            ee_frames={"ee": "ee_link"},
            joint_name_map=_NAME_MAP,
        ),
    )


def _state(positions: list[float], t_now: float = 100.0, dt: float = 0.02) -> CoordinatorState:
    snap = JointStateSnapshot(
        joint_positions=dict(zip(_JOINTS, positions, strict=True)), timestamp=t_now
    )
    return CoordinatorState(joints=snap, t_now=t_now, dt=dt)


def _fk(positions: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """EE (position, quaternion xyzw) for a joint configuration."""
    model = mujoco.MjModel.from_xml_string(_ARM_XML)
    data = mujoco.MjData(model)
    data.qpos[:] = positions
    mujoco.mj_kinematics(model, data)
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "ee_link")
    w, x, y, z = data.xquat[bid]
    return data.xpos[bid].copy(), np.array([x, y, z, w])


def _target(position: list[float], frame_id: str = "ee") -> PoseStamped:
    return PoseStamped(frame_id=frame_id, position=position, orientation=[0.0, 0.0, 0.0, 1.0])


def test_inactive_until_first_target(task: MinkIKTask) -> None:
    task.start()
    assert not task.is_active()
    assert task.compute(_state([0.0, 0.0, 0.0])) is None

    assert task.on_cartesian_command(_target([0.3, 0.2, 0.2]), t_now=100.0)
    assert task.is_active()


def test_claim_shape(task: MinkIKTask) -> None:
    claim = task.claim()
    assert claim.joints == frozenset(_JOINTS)
    assert claim.priority == 20


def test_converges_to_reachable_target(task: MinkIKTask) -> None:
    task.start()
    goal_q = [0.5, -0.4, 0.6]
    goal_pos, goal_quat = _fk(goal_q)
    task.on_cartesian_command(
        PoseStamped(frame_id="ee", position=goal_pos.tolist(), orientation=goal_quat.tolist()),
        t_now=100.0,
    )

    q = [0.0, 0.0, 0.0]
    for i in range(300):
        out = task.compute(_state(q, t_now=100.0 + 0.02 * i))
        assert out is not None
        assert out.joint_names == _JOINTS
        q = list(out.positions)  # perfect tracking

    assert np.linalg.norm(_fk(q)[0] - goal_pos) < 1e-2


def test_per_tick_delta_is_clamped(tmp_path: Path) -> None:
    model = tmp_path / "mini_arm.xml"
    model.write_text(_ARM_XML)
    task = MinkIKTask(
        "mink_arms",
        MinkIKTaskConfig(
            joint_names=_JOINTS,
            model_path=model,
            ee_frames={"ee": "ee_link"},
            joint_name_map=_NAME_MAP,
            max_joint_delta=0.01,
        ),
    )
    task.start()
    task.on_cartesian_command(_target([0.0, 0.55, 0.1]), t_now=100.0)  # 90° away
    out = task.compute(_state([0.0, 0.0, 0.0]))
    assert out is not None
    assert np.all(np.abs(out.positions) <= 0.01 + 1e-12)


def test_holds_last_solution_when_target_stale(task: MinkIKTask) -> None:
    task.start()
    task.on_cartesian_command(_target([0.3, 0.2, 0.2]), t_now=100.0)
    first = task.compute(_state([0.0, 0.0, 0.0], t_now=100.0))
    assert first is not None
    # timeout=0: hours later, still active and still emitting.
    later = task.compute(_state(list(first.positions), t_now=3700.0))
    assert task.is_active()
    assert later is not None


def test_timeout_deactivates(tmp_path: Path) -> None:
    model = tmp_path / "mini_arm.xml"
    model.write_text(_ARM_XML)
    task = MinkIKTask(
        "mink_arms",
        MinkIKTaskConfig(
            joint_names=_JOINTS,
            model_path=model,
            ee_frames={"ee": "ee_link"},
            joint_name_map=_NAME_MAP,
            timeout=0.5,
        ),
    )
    task.start()
    task.on_cartesian_command(_target([0.3, 0.2, 0.2]), t_now=100.0)
    assert task.compute(_state([0.0, 0.0, 0.0], t_now=100.0)) is not None
    assert task.compute(_state([0.0, 0.0, 0.0], t_now=101.0)) is None
    assert not task.is_active()


def test_unknown_frame_id_rejected(tmp_path: Path) -> None:
    model = tmp_path / "mini_arm.xml"
    model.write_text(_ARM_XML)
    task = MinkIKTask(
        "mink_arms",
        MinkIKTaskConfig(
            joint_names=_JOINTS,
            model_path=model,
            ee_frames={"ee": "ee_link", "ee2": "link3"},
            joint_name_map=_NAME_MAP,
        ),
    )
    task.start()
    assert not task.on_cartesian_command(_target([0.3, 0.2, 0.2], frame_id="nope"), t_now=100.0)
    assert not task.is_active()


_G1_MJCF = Path(__file__).parents[3] / "data" / "mujoco_sim" / "g1_gear_wbc.xml"
_G1_MESHDIR = Path(__file__).parents[3] / "data" / "g1_urdf" / "meshes"


@pytest.mark.skipif(not _G1_MJCF.exists(), reason="G1 MJCF assets not present")
def test_g1_dual_arm_smoke() -> None:
    sides = ("left", "right")
    arm = ("shoulder_pitch", "shoulder_roll", "shoulder_yaw", "elbow",
           "wrist_roll", "wrist_pitch", "wrist_yaw")  # fmt: skip
    joints = [f"g1/{side}_{j}" for side in sides for j in arm]

    task = MinkIKTask(
        "mink_arms",
        MinkIKTaskConfig(
            joint_names=joints,
            model_path=_G1_MJCF,
            model_meshdir=_G1_MESHDIR,
            ee_frames={"left_ee": "left_wrist_yaw_link", "right_ee": "right_wrist_yaw_link"},
            collision_body_pairs=[
                (
                    [f"left_{j}_link" for j in ("elbow", "wrist_yaw")],
                    [f"right_{j}_link" for j in ("elbow", "wrist_yaw")],
                )
            ],
        ),
    )
    task.start()

    # Pelvis-frame target for the left hand, taken from FK at a known config.
    spec = mujoco.MjSpec.from_file(str(_G1_MJCF))
    spec.meshdir = str(_G1_MESHDIR)
    model = spec.compile()
    data = mujoco.MjData(model)
    free_adr = next(
        int(model.jnt_qposadr[j])
        for j in range(model.njnt)
        if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE
    )
    data.qpos[free_adr : free_adr + 7] = [0, 0, 0, 1, 0, 0, 0]
    goal_arm_q = [0.3, 0.4, 0.1, 0.8, 0.0, 0.3, 0.2]
    for j, value in zip(arm, goal_arm_q, strict=True):
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, f"left_{j}_joint")
        data.qpos[model.jnt_qposadr[jid]] = value
    mujoco.mj_kinematics(model, data)
    left_bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "left_wrist_yaw_link")
    goal_pos = data.xpos[left_bid].copy()
    w, x, y, z = data.xquat[left_bid]

    task.on_cartesian_command(
        PoseStamped(frame_id="left_ee", position=goal_pos.tolist(), orientation=[x, y, z, w]),
        t_now=100.0,
    )

    q = dict.fromkeys(joints, 0.0)
    for i in range(400):
        snap = JointStateSnapshot(joint_positions=dict(q), timestamp=100.0 + 0.02 * i)
        out = task.compute(CoordinatorState(joints=snap, t_now=100.0 + 0.02 * i, dt=0.02))
        assert out is not None
        q = dict(zip(out.joint_names, out.positions, strict=True))

    # Left hand converged in the pelvis frame; right arm (no target) held still.
    data.qpos[:] = model.qpos0
    data.qpos[free_adr : free_adr + 7] = [0, 0, 0, 1, 0, 0, 0]
    for name, value in q.items():
        jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name.split("/")[-1] + "_joint")
        data.qpos[model.jnt_qposadr[jid]] = value
    mujoco.mj_kinematics(model, data)
    assert np.linalg.norm(data.xpos[left_bid] - goal_pos) < 2e-2
    right_q = [q[f"g1/right_{j}"] for j in arm]
    assert np.allclose(right_q, 0.0, atol=5e-2), f"right arm drifted: {right_q}"


def test_missing_state_is_safe_until_first_snapshot(task: MinkIKTask) -> None:
    task.start()
    task.on_cartesian_command(_target([0.3, 0.2, 0.2]), t_now=100.0)
    empty = CoordinatorState(joints=JointStateSnapshot(), t_now=100.0, dt=0.02)
    assert task.compute(empty) is None  # never emit from a default pose

    assert task.compute(_state([0.1, 0.1, 0.1])) is not None
    # After one full snapshot, partial dropouts fall back to cached values.
    assert task.compute(empty) is not None
