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

"""RSL-RL whole-body-control task for the AgiBot X2 humanoid."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]

from dimos.control.task import (
    BaseControlTask,
    ControlMode,
    CoordinatorState,
    JointCommandOutput,
    ResourceClaim,
)
from dimos.protocol.service.spec import BaseConfig
from dimos.robot.agibot.x2_ultra.policy_constants import (
    X2_DEFAULT_POSITIONS,
    X2_JOINTS,
    X2_LEG_JOINTS,
    X2_POLICY_ACTION_SCALE,
    X2_POLICY_DEFAULT_POSITIONS,
    X2_POLICY_JOINTS,
)
from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from dimos.hardware.whole_body.spec import WholeBodyAdapter
    from dimos.msgs.geometry_msgs.Twist import Twist

logger = setup_logger()

_NUM_ACTIONS = 31
_NUM_POLICY_JOINTS = 12
_OBS_DIM = 105
_DEFAULT_DECIMATION = 5


@dataclass
class X2RslRlWBCTaskConfig:
    """Configuration for the X2 RSL-RL WBC task."""

    policy_onnx: str | Path
    joint_names: list[str]
    all_joint_names: list[str]
    default_positions: list[float] = field(
        default_factory=lambda: list(X2_POLICY_DEFAULT_POSITIONS)
    )
    action_scale: list[float] = field(default_factory=lambda: list(X2_POLICY_ACTION_SCALE))
    priority: int = 50
    decimation: int = _DEFAULT_DECIMATION
    timeout: float = 1.0
    auto_arm: bool = False
    auto_dry_run: bool = False


class X2RslRlWBCTask(BaseControlTask):
    """Runs the X2 velocity policy inside the coordinator tick loop.

    Observation layout matches the MJLab/RSL-RL export:
    ``[base_lin_vel, base_ang_vel, projected_gravity, q-default, dq,
    last_action, cmd]`` → 105 floats.  The policy outputs 31 joint-position
    actions, but the deployed decoupled controller owns only the 12 leg
    joints.  Waist, arms, and head are held/commanded by a separate servo
    task; their policy output dimensions are retained only for observation
    history compatibility.  ``all_joint_names`` must be in policy order, not
    the X2 adapter's actuator order.
    """

    def __init__(
        self,
        name: str,
        config: X2RslRlWBCTaskConfig,
        adapter: WholeBodyAdapter,
    ) -> None:
        if len(config.joint_names) != _NUM_POLICY_JOINTS:
            raise ValueError(
                f"X2RslRlWBCTask '{name}' requires {_NUM_POLICY_JOINTS} policy joints, "
                f"got {len(config.joint_names)}"
            )
        if len(config.all_joint_names) != _NUM_ACTIONS:
            raise ValueError(
                f"X2RslRlWBCTask '{name}' requires {_NUM_ACTIONS} all_joint_names, "
                f"got {len(config.all_joint_names)}"
            )
        if list(config.joint_names) != list(config.all_joint_names[:_NUM_POLICY_JOINTS]):
            raise ValueError(
                f"X2RslRlWBCTask '{name}' joint_names must match the first "
                f"{_NUM_POLICY_JOINTS} entries of all_joint_names. The X2 policy "
                "action order is legs first, then decoupled waist, arms, and head."
            )
        if len(config.default_positions) != _NUM_ACTIONS:
            raise ValueError(
                f"X2RslRlWBCTask '{name}' requires {_NUM_ACTIONS} defaults, "
                f"got {len(config.default_positions)}"
            )
        if len(config.action_scale) != _NUM_ACTIONS:
            raise ValueError(
                f"X2RslRlWBCTask '{name}' requires {_NUM_ACTIONS} action scales, "
                f"got {len(config.action_scale)}"
            )
        if config.decimation < 1:
            raise ValueError(f"X2RslRlWBCTask '{name}' requires decimation >= 1")

        policy_path = Path(config.policy_onnx).expanduser()
        if not policy_path.exists():
            raise FileNotFoundError(f"X2 policy ONNX not found: {policy_path}")

        self._name = name
        self._config = config
        self._adapter = adapter
        self._joint_names_list = list(config.joint_names)
        self._joint_names_set = frozenset(config.joint_names)
        self._all_joint_names = list(config.all_joint_names)
        self._default = np.asarray(config.default_positions, dtype=np.float32)
        self._action_scale = np.asarray(config.action_scale, dtype=np.float32)

        providers = ort.get_available_providers()
        self._session = ort.InferenceSession(str(policy_path), providers=providers)
        self._validate_policy_metadata()
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name
        input_shape = self._session.get_inputs()[0].shape
        output_shape = self._session.get_outputs()[0].shape
        logger.info(
            "X2RslRlWBCTask loaded policy",
            name=name,
            policy=str(policy_path),
            input_name=self._input_name,
            input_shape=input_shape,
            output_name=self._output_name,
            output_shape=output_shape,
            providers=providers,
        )

        self._last_action = np.zeros(_NUM_ACTIONS, dtype=np.float32)
        self._last_targets: list[float] | None = None
        self._cached_q = self._default.copy()
        self._cached_dq = np.zeros(_NUM_ACTIONS, dtype=np.float32)
        self._state_seen = False
        self._tick_count = 0

        self._active = False
        self._armed = False
        self._dry_run = bool(config.auto_dry_run)

        self._cmd_lock = threading.Lock()
        self._cmd = np.zeros(3, dtype=np.float32)
        self._last_cmd_time: float = 0.0
        self._last_dry_run_log_t: float = 0.0

    @property
    def name(self) -> str:
        return self._name

    def claim(self) -> ResourceClaim:
        return ResourceClaim(
            joints=self._joint_names_set,
            priority=self._config.priority,
            mode=ControlMode.SERVO_POSITION,
        )

    def is_active(self) -> bool:
        return self._active

    def compute(self, state: CoordinatorState) -> JointCommandOutput | None:
        if not self._active:
            return None
        fresh = self._refresh_state_caches(state)
        if not self._state_seen and not fresh:
            return None

        current_policy_q = self._cached_q[:_NUM_POLICY_JOINTS].copy()

        if not self._armed:
            self._last_targets = current_policy_q.tolist()
            return JointCommandOutput(
                joint_names=self._joint_names_list,
                positions=self._last_targets,
                mode=ControlMode.SERVO_POSITION,
            )

        self._tick_count += 1
        if self._tick_count % self._config.decimation != 0:
            if self._dry_run or self._last_targets is None:
                return None
            return JointCommandOutput(
                joint_names=self._joint_names_list,
                positions=self._last_targets,
                mode=ControlMode.SERVO_POSITION,
            )

        imu = next(iter(state.imu.values())) if state.imu else self._adapter.read_imu()
        base_lin_vel = np.asarray(imu.linear_velocity, dtype=np.float32)
        base_ang_vel = np.asarray(imu.gyroscope, dtype=np.float32)
        gravity = self._projected_gravity(imu.quaternion)

        with self._cmd_lock:
            if (
                self._config.timeout > 0.0
                and self._last_cmd_time > 0.0
                and (state.t_now - self._last_cmd_time) > self._config.timeout
            ):
                cmd = np.zeros(3, dtype=np.float32)
            else:
                cmd = self._cmd.copy()

        obs = self._build_obs(
            base_lin_vel, base_ang_vel, gravity, self._cached_q, self._cached_dq, cmd
        )
        raw = self._session.run([self._output_name], {self._input_name: obs.reshape(1, -1)})[0]
        action = raw[0, :_NUM_ACTIONS].astype(np.float32)
        self._last_action[:] = action

        target_q = action * self._action_scale + self._default
        target_policy_q = target_q[:_NUM_POLICY_JOINTS]
        self._last_targets = target_policy_q.tolist()

        if self._dry_run:
            if (state.t_now - self._last_dry_run_log_t) >= 1.0:
                max_delta = float(np.max(np.abs(target_policy_q - current_policy_q)))
                logger.info(
                    f"X2RslRlWBCTask '{self._name}' DRY-RUN (|delta q|max={max_delta:.3f} rad)"
                )
                self._last_dry_run_log_t = state.t_now
            return None

        return JointCommandOutput(
            joint_names=self._joint_names_list,
            positions=self._last_targets,
            mode=ControlMode.SERVO_POSITION,
        )

    def on_preempted(self, by_task: str, joints: frozenset[str]) -> None:
        if joints & self._joint_names_set:
            logger.warning(f"X2RslRlWBCTask '{self._name}' preempted by {by_task} on {joints}")

    def set_velocity_command(self, vx: float, vy: float, yaw_rate: float, t_now: float) -> None:
        """Set the commanded ``(vx, vy, yaw_rate)`` for the policy."""
        with self._cmd_lock:
            self._cmd[:] = [vx, vy, yaw_rate]
            self._last_cmd_time = t_now

    def on_twist(self, msg: Twist, t_now: float) -> bool:
        """Accept a Twist command from the coordinator's ``twist_command`` input."""
        self.set_velocity_command(
            float(msg.linear.x),
            float(msg.linear.y),
            float(msg.angular.z),
            t_now,
        )
        return True

    def start(self) -> None:
        self._active = True
        self._armed = bool(self._config.auto_arm)
        self._dry_run = bool(self._config.auto_dry_run)
        self._last_targets = None
        self._last_action[:] = 0.0
        self._tick_count = 0
        with self._cmd_lock:
            self._cmd[:] = 0.0
            self._last_cmd_time = 0.0
        logger.info(
            f"X2RslRlWBCTask '{self._name}' started "
            f"({'armed' if self._armed else 'unarmed'}"
            + (", dry-run" if self._dry_run else "")
            + ")"
        )

    def stop(self) -> None:
        self._active = False
        self._armed = False
        self._last_targets = None
        logger.info(f"X2RslRlWBCTask '{self._name}' stopped")

    def arm(self) -> bool:
        """Arm policy output."""
        if not self._active:
            logger.warning(f"X2RslRlWBCTask '{self._name}' arm() called before start()")
            return False
        if self._armed:
            return False
        self._armed = True
        self._last_action[:] = 0.0
        logger.info(f"X2RslRlWBCTask '{self._name}' armed")
        return True

    def disarm(self) -> bool:
        """Disarm policy output and hold current pose."""
        if not self._armed:
            return False
        self._armed = False
        self._last_action[:] = 0.0
        logger.info(f"X2RslRlWBCTask '{self._name}' disarmed")
        return True

    def set_dry_run(self, enabled: bool) -> None:
        """Enable or disable dry-run mode."""
        self._dry_run = bool(enabled)
        self._last_dry_run_log_t = 0.0
        logger.info(f"X2RslRlWBCTask '{self._name}' dry_run = {self._dry_run}")

    def _refresh_state_caches(self, state: CoordinatorState) -> bool:
        all_present = True
        for i, jname in enumerate(self._all_joint_names):
            pos = state.joints.get_position(jname)
            vel = state.joints.get_velocity(jname)
            if pos is None or vel is None:
                all_present = False
            else:
                self._cached_q[i] = pos
                self._cached_dq[i] = vel
        if all_present:
            self._state_seen = True
        return all_present

    def _build_obs(
        self,
        base_lin_vel: np.ndarray,
        base_ang_vel: np.ndarray,
        gravity: np.ndarray,
        q: np.ndarray,
        dq: np.ndarray,
        cmd: np.ndarray,
    ) -> np.ndarray:
        obs = np.zeros(_OBS_DIM, dtype=np.float32)
        obs[0:3] = base_lin_vel
        obs[3:6] = base_ang_vel
        obs[6:9] = gravity
        obs[9:40] = q - self._default
        obs[40:71] = dq
        obs[71:102] = self._last_action
        obs[102:105] = cmd
        return obs

    def _validate_policy_metadata(self) -> None:
        get_modelmeta = getattr(self._session, "get_modelmeta", None)
        if get_modelmeta is None:
            return
        meta = getattr(get_modelmeta(), "custom_metadata_map", {}) or {}
        joint_names_raw = meta.get("joint_names")
        if joint_names_raw:
            expected = ",".join(
                _to_policy_export_joint_name(name) for name in self._all_joint_names
            )
            if joint_names_raw != expected:
                raise ValueError(
                    "X2 policy ONNX joint_names metadata does not match configured "
                    "all_joint_names order. The ONNX policy expects "
                    f"{joint_names_raw!r}, configured {expected!r}."
                )
        _validate_metadata_vector(
            meta.get("default_joint_pos"),
            self._default,
            "default_joint_pos",
        )
        _validate_metadata_vector(
            meta.get("action_scale"),
            self._action_scale,
            "action_scale",
        )

    @staticmethod
    def _projected_gravity(quaternion: tuple[float, ...]) -> np.ndarray:
        w, x, y, z = quaternion
        gx = 2.0 * (-x * z + w * y)
        gy = 2.0 * (-y * z - w * x)
        gz = -(w * w - x * x - y * y + z * z)
        return np.array([gx, gy, gz], dtype=np.float32)


class X2RslRlWBCTaskParams(BaseConfig):
    policy_onnx: str | Path
    hardware_id: str
    all_joint_names: list[str]
    auto_arm: bool = False
    auto_dry_run: bool = False
    decimation: int | None = None


def _to_policy_export_joint_name(joint_name: str) -> str:
    short = joint_name.split("/", 1)[-1]
    return f"{short}_joint"


def _validate_metadata_vector(
    raw: str | None,
    expected: np.ndarray,
    field_name: str,
) -> None:
    if not raw:
        return
    actual = np.asarray([float(value) for value in raw.split(",")], dtype=np.float32)
    if actual.shape != expected.shape or not np.allclose(actual, expected, atol=1e-4):
        raise ValueError(
            f"X2 policy ONNX {field_name} metadata does not match configured {field_name}"
        )


def create_task(cfg: Any, hardware: Any) -> X2RslRlWBCTask:
    from dimos.control.hardware_interface import ConnectedWholeBody

    params = X2RslRlWBCTaskParams.model_validate(cfg.params)
    hw = hardware.get(params.hardware_id) if hardware else None
    if hw is None:
        raise ValueError(
            f"X2RslRlWBCTask {cfg.name!r} references unknown hardware "
            f"{params.hardware_id!r}. Declare the hardware before the task."
        )
    if not isinstance(hw, ConnectedWholeBody):
        raise TypeError(
            f"X2RslRlWBCTask {cfg.name!r} requires WHOLE_BODY hardware "
            f"for {params.hardware_id!r}, got {type(hw).__name__}."
        )

    kwargs: dict[str, Any] = dict(
        policy_onnx=params.policy_onnx,
        joint_names=cfg.joint_names,
        all_joint_names=params.all_joint_names,
        priority=cfg.priority,
        auto_arm=params.auto_arm,
        auto_dry_run=params.auto_dry_run,
    )
    if params.decimation is not None:
        kwargs["decimation"] = params.decimation
    return X2RslRlWBCTask(
        cfg.name,
        X2RslRlWBCTaskConfig(**kwargs),
        adapter=hw.adapter,
    )


__all__ = [
    "X2_DEFAULT_POSITIONS",
    "X2_JOINTS",
    "X2_LEG_JOINTS",
    "X2_POLICY_ACTION_SCALE",
    "X2_POLICY_DEFAULT_POSITIONS",
    "X2_POLICY_JOINTS",
    "X2RslRlWBCTask",
    "X2RslRlWBCTaskConfig",
    "create_task",
]
