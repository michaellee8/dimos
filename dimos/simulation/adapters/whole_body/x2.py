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

"""MuJoCo simulation ``WholeBodyAdapter`` for AgiBot X2."""

from __future__ import annotations

import math
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any

from dimos.hardware.whole_body.spec import (
    POS_STOP,
    IMUState,
    MotorCommand,
    MotorState,
)
from dimos.simulation.backend.mujoco.shm import (
    ManipShmReader,
    shm_key_from_path,
)
from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from dimos.hardware.whole_body.registry import WholeBodyAdapterRegistry

logger = setup_logger()

_NUM_MOTORS = 31

_READY_WAIT_TIMEOUT_S = 60.0
_READY_WAIT_POLL_S = 0.1
_ATTACH_RETRY_TIMEOUT_S = 30.0
_ATTACH_RETRY_POLL_S = 0.2


class SimMujocoX2WholeBodyAdapter:
    """X2 ``WholeBodyAdapter`` that proxies to ``MujocoSimModule`` via SHM."""

    def __init__(
        self,
        address: str | Path | None = None,
        domain_id: int = 0,
        **_: Any,
    ) -> None:
        if address is None:
            raise ValueError(
                "SimMujocoX2WholeBodyAdapter: address (MJCF XML path) is required. "
                "Set HardwareComponent.address to the same MJCF path the MujocoSimModule loads."
            )
        self._address = address
        self._shm_key = shm_key_from_path(address)
        self._shm: ManipShmReader | None = None
        self._connected = False

    def connect(self) -> bool:
        deadline = time.monotonic() + _ATTACH_RETRY_TIMEOUT_S
        while True:
            try:
                self._shm = ManipShmReader(self._shm_key)
                break
            except FileNotFoundError:
                if time.monotonic() > deadline:
                    logger.error(
                        "SimMujocoX2WholeBodyAdapter: SHM buffers not found",
                        address=self._address,
                        shm_key=self._shm_key,
                        timeout_s=_ATTACH_RETRY_TIMEOUT_S,
                    )
                    return False
                time.sleep(_ATTACH_RETRY_POLL_S)

        deadline = time.monotonic() + _READY_WAIT_TIMEOUT_S
        while not self._shm.is_ready():
            if time.monotonic() > deadline:
                logger.error(
                    "SimMujocoX2WholeBodyAdapter: sim module not ready",
                    timeout_s=_READY_WAIT_TIMEOUT_S,
                )
                self._shm.cleanup()
                self._shm = None
                return False
            time.sleep(_READY_WAIT_POLL_S)

        self._connected = True
        logger.info(
            "SimMujocoX2WholeBodyAdapter connected",
            num_motors=_NUM_MOTORS,
            shm_key=self._shm_key,
        )
        return True

    def disconnect(self) -> None:
        if self._shm is not None:
            try:
                self._shm.cleanup()
            except Exception as e:
                logger.warning(f"SHM cleanup raised: {e}")
        self._shm = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._shm is not None

    def read_motor_states(self) -> list[MotorState]:
        if not self._connected or self._shm is None:
            return [MotorState()] * _NUM_MOTORS
        positions = self._shm.read_positions(_NUM_MOTORS)
        velocities = self._shm.read_velocities(_NUM_MOTORS)
        efforts = self._shm.read_efforts(_NUM_MOTORS)
        return [
            MotorState(q=positions[i], dq=velocities[i], tau=efforts[i]) for i in range(_NUM_MOTORS)
        ]

    def has_motor_states(self) -> bool:
        return self._connected and self._shm is not None

    def read_imu(self) -> IMUState:
        if not self._connected or self._shm is None:
            return IMUState()
        quat, gyro, accel = self._shm.read_imu()
        linvel = self._shm.read_linear_velocity()

        w, x, y, z = quat
        sinr = 2.0 * (w * x + y * z)
        cosr = 1.0 - 2.0 * (x * x + y * y)
        roll = math.atan2(sinr, cosr)
        sinp = 2.0 * (w * y - z * x)
        pitch = math.copysign(math.pi / 2.0, sinp) if abs(sinp) >= 1.0 else math.asin(sinp)
        siny = 2.0 * (w * z + x * y)
        cosy = 1.0 - 2.0 * (y * y + z * z)
        yaw = math.atan2(siny, cosy)
        return IMUState(
            quaternion=quat,
            gyroscope=gyro,
            accelerometer=accel,
            linear_velocity=linvel,
            rpy=(roll, pitch, yaw),
        )

    def write_motor_commands(self, commands: list[MotorCommand]) -> bool:
        if not self._connected or self._shm is None:
            return False
        if len(commands) != _NUM_MOTORS:
            logger.error(
                f"SimMujocoX2WholeBodyAdapter: expected {_NUM_MOTORS} commands, got {len(commands)}"
            )
            return False

        q = [cmd.q if cmd.q != POS_STOP else 0.0 for cmd in commands]
        kp = [cmd.kp for cmd in commands]
        kd = [cmd.kd for cmd in commands]
        tau = [cmd.tau for cmd in commands]
        self._shm.write_pd_tau_command(q, kp, kd, tau)
        return True


def register(registry: WholeBodyAdapterRegistry) -> None:
    """Register with the whole-body adapter registry."""
    registry.register("sim_mujoco_x2", SimMujocoX2WholeBodyAdapter)


__all__ = ["SimMujocoX2WholeBodyAdapter"]
