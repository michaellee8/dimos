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

"""Cartesian Quest teleop for a small joint chain (e.g. the Go2 FR leg).

Uses the shared [PinocchioIK] solver to translate controller pose deltas
into joint targets. Pattern mirrors [TeleopIKTask] - snapshot EE pose on
first command after engage, apply incoming deltas relative to it, solve IK
warm-started from current joint state.

Use case: Go2 tripod blueprint. Operator holds right A; subsequent right-
controller motion drives the held-up FR paw in body frame.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pinocchio
from pydantic import Field

from dimos.control.task import (
    BaseControlTask,
    ControlMode,
    CoordinatorState,
    JointCommandOutput,
    ResourceClaim,
)
from dimos.manipulation.planning.kinematics.pinocchio_ik import (
    PinocchioIK,
    check_joint_delta,
    pose_to_se3,
)
from dimos.protocol.service.spec import BaseConfig
from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped

logger = setup_logger()


@dataclass
class QuestJointTaskConfig:
    """Per-instance config built from TaskConfig.params."""

    joint_names: list[str]
    model_path: str
    ee_joint_id: int
    priority: int = 20
    command_timeout: float = 0.3
    max_joint_delta_deg: float = 30.0


class QuestJointTask(BaseControlTask):
    """Quest controller delta -> IK -> joint targets for a short kinematic chain.

    Engagement is upstream (Quest base module only publishes
    right_controller_output while A is held). On the first command after
    engage, snapshot the current EE pose from FK on the *real* joint state;
    subsequent commands apply the controller delta relative to that.
    """

    def __init__(self, name: str, config: QuestJointTaskConfig) -> None:
        if not config.joint_names:
            raise ValueError(f"QuestJointTask {name!r} requires joint_names")
        if not config.model_path:
            raise ValueError(f"QuestJointTask {name!r} requires model_path")

        self._name = name
        self._config = config
        self._joint_names = frozenset(config.joint_names)
        self._joint_names_list = list(config.joint_names)
        self._n = len(config.joint_names)

        self._ik = PinocchioIK.from_model_path(config.model_path, config.ee_joint_id)
        if self._ik.nq != self._n:
            logger.warning(
                f"QuestJointTask {name}: URDF nq ({self._ik.nq}) != "
                f"joint_names count ({self._n})"
            )

        self._lock = threading.Lock()
        self._target_delta: PoseStamped | None = None
        self._last_command_t: float = -1.0
        self._initial_ee_pose: pinocchio.SE3 | None = None

        logger.info(
            f"QuestJointTask {name} initialized "
            f"(model={config.model_path}, ee_joint_id={config.ee_joint_id}, "
            f"joints={config.joint_names})"
        )

    @property
    def name(self) -> str:
        return self._name

    def claim(self) -> ResourceClaim:
        return ResourceClaim(
            joints=self._joint_names,
            priority=self._config.priority,
            mode=ControlMode.SERVO_POSITION,
        )

    def is_active(self) -> bool:
        with self._lock:
            return self._last_command_t > 0.0

    def compute(self, state: CoordinatorState) -> JointCommandOutput | None:
        with self._lock:
            if self._last_command_t < 0.0 or self._target_delta is None:
                return None
            if state.t_now - self._last_command_t > self._config.command_timeout:
                # Operator released A (or stream dropped) - go inactive and
                # forget the snapshot so the next engage re-anchors cleanly.
                self._last_command_t = -1.0
                self._initial_ee_pose = None
                self._target_delta = None
                return None
            delta_msg = self._target_delta

        # Pull current joint state in URDF order. For the FR leg this is
        # [FR_hip_joint, FR_thigh_joint, FR_calf_joint].
        q_current = self._get_current_joints(state)
        if q_current is None:
            return None

        # Snapshot initial EE pose on first command after engage.
        with self._lock:
            need_snapshot = self._initial_ee_pose is None
        if need_snapshot:
            initial_pose = self._ik.forward_kinematics(q_current)
            with self._lock:
                self._initial_ee_pose = initial_pose

        # target = initial + controller_delta (translation only; we ignore
        # controller orientation for the leg since 3 DOF can't reach
        # arbitrary 6-DOF poses anyway).
        delta_se3 = pose_to_se3(delta_msg)
        with self._lock:
            if self._initial_ee_pose is None:
                return None
            target_pose = pinocchio.SE3(
                self._initial_ee_pose.rotation,  # keep orientation fixed
                self._initial_ee_pose.translation + delta_se3.translation,
            )

        q_solution, converged, err = self._ik.solve(target_pose, q_current)
        if not converged:
            logger.debug(
                f"QuestJointTask {self._name}: IK partial (err={err:.4f}), "
                f"applying anyway"
            )

        if not check_joint_delta(q_solution, q_current, self._config.max_joint_delta_deg):
            logger.warning(
                f"QuestJointTask {self._name}: joint delta > "
                f"{self._config.max_joint_delta_deg} deg, holding"
            )
            return None

        return JointCommandOutput(
            joint_names=self._joint_names_list,
            positions=[float(x) for x in q_solution],
            mode=ControlMode.SERVO_POSITION,
        )

    def on_cartesian_command(self, msg: PoseStamped, t_now: float) -> None:
        """Coordinator delivers pose here when `msg.frame_id == self.name`."""
        with self._lock:
            self._target_delta = msg
            self._last_command_t = t_now

    # --- Internals -----------------------------------------------------------

    def _get_current_joints(self, state: CoordinatorState) -> np.ndarray | None:
        """Read joint positions in the order URDF expects."""
        q = np.empty(self._n, dtype=np.float64)
        for i, jname in enumerate(self._joint_names_list):
            pos = state.joints.get_position(jname)
            if pos is None:
                return None
            q[i] = pos
        return q


class QuestJointTaskParams(BaseConfig):
    """TaskConfig.params schema."""

    model_path: str = Field(..., description="Path to URDF (or MJCF) for IK")
    ee_joint_id: int = Field(..., description="Pinocchio joint id of the EE")
    command_timeout: float = 0.3
    max_joint_delta_deg: float = 30.0


def create_task(cfg: Any, hardware: Any) -> QuestJointTask:
    params = QuestJointTaskParams.model_validate(cfg.params)
    return QuestJointTask(
        cfg.name,
        QuestJointTaskConfig(
            joint_names=cfg.joint_names,
            model_path=params.model_path,
            ee_joint_id=params.ee_joint_id,
            priority=cfg.priority,
            command_timeout=params.command_timeout,
            max_joint_delta_deg=params.max_joint_delta_deg,
        ),
    )


__all__ = ["QuestJointTask", "QuestJointTaskConfig", "create_task"]
