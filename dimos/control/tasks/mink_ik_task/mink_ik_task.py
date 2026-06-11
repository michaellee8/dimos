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

"""QP differential-IK control task built on mink (MuJoCo-native).

One task drives all configured end-effectors (e.g. both G1 arms) in a
single QP per tick: joint/velocity limits and self-collision avoidance
enter as hard constraints, a posture cost resolves the redundancy, and
non-claimed DOF (legs, waist, floating base) are frozen so the solver
cannot "use" phantom body motion to reach a target. This replaces the
damped-least-squares ``cartesian_ik`` task wherever constraint handling
matters; the global planner remains responsible for routing around
clutter — this task is local.

Targets arrive via ``on_cartesian_command``; ``PoseStamped.frame_id``
selects the end-effector. Poses are interpreted in the robot's **base
frame** (the model is solved with its floating base pinned at the
origin — for the G1, that is the pelvis frame). An end-effector with no
target yet holds its current pose. Once tracking, a stale target means
*hold the last solution* (``timeout=0``, the default) — the task never
decays toward defaults; that's the lower-priority servo holder's job if
this task is stopped.

Requires the ``[ik]`` extra (mink + a QP solver).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Any

import numpy as np

from dimos.control.task import (
    BaseControlTask,
    ControlMode,
    CoordinatorState,
    JointCommandOutput,
    ResourceClaim,
)
from dimos.protocol.service.spec import BaseConfig
from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from dimos.msgs.geometry_msgs.Pose import Pose
    from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped

logger = setup_logger()

_WARN_PERIOD_S = 1.0
_DEFAULT_VELOCITY_LIMIT = 3.14  # rad/s per claimed joint


def _default_model_joint(coordinator_name: str) -> str:
    """``g1/left_shoulder_pitch`` → ``left_shoulder_pitch_joint``."""
    short = coordinator_name.rsplit("/", 1)[-1]
    return f"{short}_joint"


@dataclass
class MinkIKTaskConfig:
    """Configuration for the mink QP differential-IK task.

    Attributes:
        joint_names: Coordinator joints this task claims and commands.
        model_path: Full-robot MJCF for the solver (same file the sim uses).
        ee_frames: Command ``frame_id`` → model body name, one entry per
            end-effector (e.g. ``{"left_ee": "left_wrist_yaw_link", ...}``).
        joint_name_map: Coordinator → model joint name for every joint that
            should be mirrored into the solver (claimed + synced). Defaults
            to the ``hw/x`` → ``x_joint`` convention.
        synced_joints: Extra coordinator joints (not claimed) mirrored into
            the model each solve so collision avoidance sees the true
            posture — e.g. legs + waist owned by the WBC.
        model_meshdir: Mesh directory override for MJCFs without one.
        collision_body_pairs: Body-name pairs (model namespace) passed to
            mink's CollisionAvoidanceLimit; each side is a list of bodies
            whose geoms are checked against the other side's.
        priority: Arbitration priority (above servo holders, below WBC).
        timeout: Seconds without any fresh target before going inactive.
            0 (default) = never; hold the last solution indefinitely.
        decimation: Solve the QP every N ticks; re-emit the last command on
            off ticks.
        max_joint_delta: Per-tick command change clamp (rad) — safety rail.
        velocity_limits: Model joint name → rad/s; defaults to
            3.14 rad/s for every claimed joint.
    """

    joint_names: list[str]
    model_path: str | Path
    ee_frames: dict[str, str]
    joint_name_map: dict[str, str] = field(default_factory=dict)
    synced_joints: list[str] = field(default_factory=list)
    model_meshdir: str | Path | None = None
    collision_body_pairs: list[tuple[list[str], list[str]]] = field(default_factory=list)
    priority: int = 20
    timeout: float = 0.0
    decimation: int = 1
    max_joint_delta: float = 0.26  # ~15° per tick
    velocity_limits: dict[str, float] = field(default_factory=dict)
    position_cost: float = 1.0
    orientation_cost: float = 1.0
    # Nullspace regularizer. Keep well below the frame costs: the QP's
    # equilibrium offset from the target scales ~linearly with this ratio.
    posture_cost: float = 1e-2
    lm_damping: float = 1.0
    solver: str = "daqp"
    solver_damping: float = 1e-3
    min_collision_distance: float = 0.005


class MinkIKTask(BaseControlTask):
    """Dual-arm-capable cartesian servo task: one mink QP per tick."""

    def __init__(self, name: str, config: MinkIKTaskConfig) -> None:
        if not config.joint_names:
            raise ValueError(f"MinkIKTask '{name}' requires at least one joint")
        if not config.ee_frames:
            raise ValueError(f"MinkIKTask '{name}' requires at least one entry in ee_frames")

        import mink
        import mujoco

        self._mink = mink
        self._mujoco = mujoco
        self._name = name
        self._config = config
        self._claimed = list(config.joint_names)
        self._claimed_set = frozenset(self._claimed)

        model_path = Path(config.model_path).resolve()
        spec = mujoco.MjSpec.from_file(str(model_path))
        meshdir = (
            Path(config.model_meshdir)
            if config.model_meshdir
            else model_path.parent / (spec.meshdir or "")
        )
        spec.meshdir = str(meshdir.resolve())
        self._model = spec.compile()

        name_map = dict(config.joint_name_map)
        synced = list(dict.fromkeys([*self._claimed, *config.synced_joints]))
        for coord in synced:
            name_map.setdefault(coord, _default_model_joint(coord))

        # coordinator joint → model qpos address (claimed + synced)
        self._sync_qpos_adr: dict[str, int] = {}
        claimed_dof_set: set[int] = set()
        for coord in synced:
            model_name = name_map[coord]
            jid = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_JOINT, model_name)
            if jid < 0:
                raise ValueError(f"MinkIKTask {name}: joint '{model_name}' not in model")
            self._sync_qpos_adr[coord] = int(self._model.jnt_qposadr[jid])
            if coord in self._claimed_set:
                claimed_dof_set.add(int(self._model.jnt_dofadr[jid]))
        self._claimed_qpos_adr = np.array(
            [self._sync_qpos_adr[c] for c in self._claimed], dtype=int
        )

        for frame_id, body in config.ee_frames.items():
            if mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_BODY, body) < 0:
                raise ValueError(f"MinkIKTask {name}: ee body '{body}' ({frame_id}) not in model")

        # Base template: floating base (if any) pinned at the origin so
        # targets are expressed in the robot's base frame.
        self._q_template = self._model.qpos0.copy()
        for jid in range(self._model.njnt):
            if self._model.jnt_type[jid] == mujoco.mjtJoint.mjJNT_FREE:
                adr = self._model.jnt_qposadr[jid]
                self._q_template[adr : adr + 3] = 0.0
                self._q_template[adr + 3 : adr + 7] = (1.0, 0.0, 0.0, 0.0)

        self._configuration = mink.Configuration(self._model)
        self._configuration.update(self._q_template.copy())

        self._frame_tasks: dict[str, Any] = {
            frame_id: mink.FrameTask(
                frame_name=body,
                frame_type="body",
                position_cost=config.position_cost,
                orientation_cost=config.orientation_cost,
                lm_damping=config.lm_damping,
            )
            for frame_id, body in config.ee_frames.items()
        }
        posture = mink.PostureTask(self._model, cost=config.posture_cost)
        posture.set_target_from_configuration(self._configuration)
        self._tasks: list[Any] = [*self._frame_tasks.values(), posture]

        frozen_dofs = [d for d in range(self._model.nv) if d not in claimed_dof_set]
        if frozen_dofs:
            self._tasks.append(mink.DofFreezingTask(self._model, frozen_dofs))

        velocity_limits = dict(config.velocity_limits) or {
            name_map[c]: _DEFAULT_VELOCITY_LIMIT for c in self._claimed
        }
        self._limits: list[Any] = [
            mink.ConfigurationLimit(self._model),
            mink.VelocityLimit(self._model, velocity_limits),
        ]
        geom_pairs = self._resolve_collision_pairs(config.collision_body_pairs)
        if geom_pairs:
            self._limits.append(
                mink.CollisionAvoidanceLimit(
                    self._model,
                    geom_pairs,
                    minimum_distance_from_collisions=config.min_collision_distance,
                )
            )

        self._lock = threading.Lock()
        self._targets: dict[str, tuple[Pose | PoseStamped, float]] = {}
        self._hold_targets: dict[str, Any] = {}  # frame_id → SE3, anchored once
        self._active = False
        self._cached_positions: dict[str, float] = {}
        self._state_seen = False
        self._last_command: JointCommandOutput | None = None
        self._tick_count = 0
        self._last_warn_t = -np.inf

        logger.info(
            f"MinkIKTask {name}: model={model_path.name}, ee_frames={config.ee_frames}, "
            f"{len(self._claimed)} claimed joints, {len(frozen_dofs)} frozen DOF, "
            f"{len(geom_pairs)} collision geom pairs"
        )

    def _resolve_collision_pairs(
        self, body_pairs: list[tuple[list[str], list[str]]]
    ) -> list[tuple[list[int], list[int]]]:
        pairs = []
        for side_a, side_b in body_pairs:
            geoms_a = self._body_list_geoms(side_a)
            geoms_b = self._body_list_geoms(side_b)
            if geoms_a and geoms_b:
                pairs.append((geoms_a, geoms_b))
            else:
                logger.warning(
                    f"MinkIKTask {self._name}: collision pair {side_a} ↔ {side_b} "
                    f"has no collision geoms; skipping"
                )
        return pairs

    def _body_list_geoms(self, bodies: list[str]) -> list[int]:
        geoms: list[int] = []
        for body in bodies:
            bid = self._mujoco.mj_name2id(self._model, self._mujoco.mjtObj.mjOBJ_BODY, body)
            if bid < 0:
                logger.warning(f"MinkIKTask {self._name}: collision body '{body}' not in model")
                continue
            geoms.extend(
                g
                for g in self._mink.get_body_geom_ids(self._model, bid)
                if self._model.geom_contype[g] or self._model.geom_conaffinity[g]
            )
        return geoms

    # ------------------------------------------------------------------
    # ControlTask protocol

    @property
    def name(self) -> str:
        return self._name

    def claim(self) -> ResourceClaim:
        return ResourceClaim(
            joints=self._claimed_set,
            priority=self._config.priority,
            mode=ControlMode.SERVO_POSITION,
        )

    def is_active(self) -> bool:
        with self._lock:
            return self._active and bool(self._targets)

    def compute(self, state: CoordinatorState) -> JointCommandOutput | None:
        with self._lock:
            if not self._active or not self._targets:
                return None
            if self._config.timeout > 0:
                newest = max(t for _, t in self._targets.values())
                if state.t_now - newest > self._config.timeout:
                    logger.warning(f"MinkIKTask {self._name} timed out; deactivating")
                    self._active = False
                    return None
            targets = dict(self._targets)
            last_command = self._last_command

        self._tick_count += 1
        if self._config.decimation > 1 and (self._tick_count - 1) % self._config.decimation:
            return last_command

        q = self._build_q(state)
        if q is None:
            return None
        q_measured = q[self._claimed_qpos_adr].copy()
        self._configuration.update(q)

        for frame_id, frame_task in self._frame_tasks.items():
            target = targets.get(frame_id)
            if target is not None:
                self._hold_targets.pop(frame_id, None)
                frame_task.set_target(self._pose_to_se3(target[0]))
            else:
                # No target for this EE: hold the pose it had when holding
                # began. Anchoring once (not every tick) is what makes it a
                # hold — re-anchoring at the current pose would let the arm
                # drift freely with every disturbance.
                hold = self._hold_targets.get(frame_id)
                if hold is None:
                    hold = self._configuration.get_transform_frame_to_world(
                        self._config.ee_frames[frame_id], "body"
                    )
                    self._hold_targets[frame_id] = hold
                frame_task.set_target(hold)

        dt = state.dt * self._config.decimation
        if dt <= 0.0:
            dt = 0.02
        dt = float(np.clip(dt, 1e-3, 0.05))

        try:
            velocity = self._mink.solve_ik(
                self._configuration,
                self._tasks,
                dt,
                self._config.solver,
                damping=self._config.solver_damping,
                limits=self._limits,
            )
        except Exception as exc:
            if state.t_now - self._last_warn_t > _WARN_PERIOD_S:
                self._last_warn_t = state.t_now
                logger.warning(f"MinkIKTask {self._name}: QP solve failed ({exc}); holding")
            return last_command

        self._configuration.integrate_inplace(velocity, dt)
        q_solution = self._configuration.q[self._claimed_qpos_adr]

        delta = np.clip(
            q_solution - q_measured, -self._config.max_joint_delta, self._config.max_joint_delta
        )
        command = JointCommandOutput(
            joint_names=self._claimed,
            positions=(q_measured + delta).tolist(),
            mode=ControlMode.SERVO_POSITION,
        )
        with self._lock:
            self._last_command = command
        return command

    def _build_q(self, state: CoordinatorState) -> np.ndarray | None:
        """Full model qpos from measured joints (base pinned at origin).

        Missing joints fall back to the last seen value — never a default —
        and the task stays silent until one complete snapshot has arrived.
        """
        q = self._q_template.copy()
        missing = False
        for coord, adr in self._sync_qpos_adr.items():
            pos = state.joints.get_position(coord)
            if pos is None:
                pos = self._cached_positions.get(coord)
                if pos is None:
                    missing = True
                    continue
            else:
                self._cached_positions[coord] = pos
            q[adr] = pos
        if missing and not self._state_seen:
            return None
        self._state_seen = True
        return q

    def _pose_to_se3(self, pose: Pose | PoseStamped) -> Any:
        position = np.asarray([pose.position.x, pose.position.y, pose.position.z], dtype=np.float64)
        o = pose.orientation
        wxyz = np.asarray([o.w, o.x, o.y, o.z], dtype=np.float64)
        return self._mink.SE3.from_rotation_and_translation(self._mink.SO3(wxyz), position)

    def on_cartesian_command(self, pose: Pose | PoseStamped, t_now: float) -> bool:
        """Accept a base-frame EE target; ``frame_id`` selects the end-effector."""
        frame_id = getattr(pose, "frame_id", "") or ""
        if frame_id not in self._config.ee_frames:
            if len(self._config.ee_frames) == 1 and not frame_id:
                frame_id = next(iter(self._config.ee_frames))
            else:
                logger.warning(
                    f"MinkIKTask {self._name}: unknown ee frame_id '{frame_id}' "
                    f"(known: {list(self._config.ee_frames)})"
                )
                return False
        with self._lock:
            self._targets[frame_id] = (pose, t_now)
            self._active = True
        return True

    def on_preempted(self, by_task: str, joints: frozenset[str]) -> None:
        if joints & self._claimed_set:
            logger.warning(f"MinkIKTask {self._name} preempted by {by_task} on {sorted(joints)}")

    def start(self) -> None:
        with self._lock:
            self._active = True
        logger.info(f"MinkIKTask {self._name} started")

    def stop(self) -> None:
        with self._lock:
            self._active = False
        logger.info(f"MinkIKTask {self._name} stopped")

    def clear(self) -> None:
        with self._lock:
            self._targets.clear()
            self._hold_targets.clear()
            self._active = False
            self._last_command = None
        logger.info(f"MinkIKTask {self._name} cleared")


__all__ = ["MinkIKTask", "MinkIKTaskConfig"]


class MinkIKTaskParams(BaseConfig):
    model_path: str | Path
    ee_frames: dict[str, str]
    model_meshdir: str | Path | None = None
    joint_name_map: dict[str, str] = {}
    synced_joints: list[str] = []
    collision_body_pairs: list[tuple[list[str], list[str]]] = []
    timeout: float = 0.0
    decimation: int = 1
    max_joint_delta: float = 0.26
    solver: str = "daqp"


def create_task(cfg: Any, hardware: Any) -> MinkIKTask:
    del hardware
    params = MinkIKTaskParams.model_validate(cfg.params)
    return MinkIKTask(
        cfg.name,
        MinkIKTaskConfig(
            joint_names=cfg.joint_names,
            model_path=params.model_path,
            ee_frames=params.ee_frames,
            model_meshdir=params.model_meshdir,
            joint_name_map=params.joint_name_map,
            synced_joints=params.synced_joints,
            collision_body_pairs=params.collision_body_pairs,
            priority=cfg.priority,
            timeout=params.timeout,
            decimation=params.decimation,
            max_joint_delta=params.max_joint_delta,
            solver=params.solver,
        ),
    )
