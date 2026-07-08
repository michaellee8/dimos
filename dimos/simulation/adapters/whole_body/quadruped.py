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

"""MuJoCo simulation ``WholeBodyAdapter`` for 12-DOF quadrupeds.

Pairs with ``MujocoSimModule`` via SHM keyed on the robot MJCF path, like
``SimMujocoG1WholeBodyAdapter``. Differences from the G1 adapter:

- 12 motors instead of 29.
- Commands are forwarded as raw position targets (``CMD_MODE_POSITION``)
  instead of the PD+tau bridge: quadruped RL policies here are trained
  against MuJoCo native ``<position>`` actuators whose kp/kd/forcerange
  live in the robot MJCF, so the sim must let those actuators close the
  loop. The kp/kd on incoming ``MotorCommand``s are ignored (they exist
  for hardware parity and must match the MJCF gains).
- Exposes the sim-only observations locomotion policies need:
  ``read_base_lin_vel()`` (body-frame, ground truth) and
  ``read_height_scan()`` (terrain grid from the module's height scanner).
"""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from dimos.hardware.whole_body.spec import (
    POS_STOP,
    IMUState,
    MotorCommand,
    MotorState,
)
from dimos.simulation.engines.mujoco_shm import (
    ManipShmReader,
    shm_key_from_path,
)
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

_NUM_MOTORS = 12

_READY_WAIT_TIMEOUT_S = 180.0
_READY_WAIT_POLL_S = 0.1
_ATTACH_RETRY_TIMEOUT_S = 30.0
_ATTACH_RETRY_POLL_S = 0.2


class SimMujocoQuadrupedAdapter:
    """Quadruped ``WholeBodyAdapter`` that proxies to a ``MujocoSimModule``.

    ``address`` (the robot MJCF path) is the discovery key - both sides
    derive the same SHM names from it via ``shm_key_from_path``.
    """

    def __init__(
        self,
        address: str | Path | None = None,
        **_: Any,
    ) -> None:
        if address is None:
            raise ValueError(
                "SimMujocoQuadrupedAdapter: address (MJCF XML path) is required - "
                "set HardwareComponent.address to the same MJCF path the "
                "MujocoSimModule loads."
            )
        self._address = address
        self._shm_key = shm_key_from_path(address)
        self._shm: ManipShmReader | None = None
        self._connected = False

    # Lifecycle

    def connect(self) -> bool:
        deadline = time.monotonic() + _ATTACH_RETRY_TIMEOUT_S
        while True:
            try:
                self._shm = ManipShmReader(self._shm_key)
                break
            except FileNotFoundError:
                if time.monotonic() > deadline:
                    logger.error(
                        "SimMujocoQuadrupedAdapter: SHM buffers not found",
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
                    "SimMujocoQuadrupedAdapter: sim module not ready",
                    timeout_s=_READY_WAIT_TIMEOUT_S,
                )
                self._shm.cleanup()
                self._shm = None
                return False
            time.sleep(_READY_WAIT_POLL_S)

        self._connected = True
        logger.info(
            "SimMujocoQuadrupedAdapter connected",
            num_motors=_NUM_MOTORS,
            shm_key=self._shm_key,
        )
        return True

    def disconnect(self) -> None:
        if self._shm is not None:
            self._shm.cleanup()
        self._shm = None
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected and self._shm is not None

    # IO (WholeBodyAdapter protocol)

    def read_motor_states(self) -> list[MotorState]:
        if not self.has_motor_states():
            return [MotorState()] * _NUM_MOTORS
        assert self._shm is not None
        positions = self._shm.read_positions(_NUM_MOTORS)
        velocities = self._shm.read_velocities(_NUM_MOTORS)
        efforts = self._shm.read_efforts(_NUM_MOTORS)
        return [
            MotorState(q=positions[i], dq=velocities[i], tau=efforts[i]) for i in range(_NUM_MOTORS)
        ]

    def has_motor_states(self) -> bool:
        # Sim ground truth is available the moment SHM attaches.
        return self._connected and self._shm is not None

    def read_imu(self) -> IMUState:
        if not self.has_motor_states():
            return IMUState()
        assert self._shm is not None
        quat, gyro, accel = self._shm.read_imu()
        return IMUState(
            quaternion=quat,
            gyroscope=gyro,
            accelerometer=accel,
        )

    def write_motor_commands(self, commands: list[MotorCommand]) -> bool:
        if not self.is_connected():
            return False
        assert self._shm is not None
        if len(commands) != _NUM_MOTORS:
            logger.error(
                f"SimMujocoQuadrupedAdapter: expected {_NUM_MOTORS} commands, got {len(commands)}"
            )
            return False
        # Position targets only - the MJCF's <position> actuators apply
        # kp/kd/forcerange exactly as the policy was trained against.
        q = [cmd.q if cmd.q != POS_STOP else 0.0 for cmd in commands]
        self._shm.write_position_command(q)
        return True

    # Sim-only observation extras (consumed by locomotion policy tasks).

    def read_base_lin_vel(self) -> tuple[float, float, float]:
        """Body-frame base linear velocity (velocimeter ground truth)."""
        if not self.has_motor_states():
            return (0.0, 0.0, 0.0)
        assert self._shm is not None
        return self._shm.read_base_lin_vel()

    def read_height_scan(self, n_rays: int) -> list[float]:
        """Terrain height-scan grid written by the sim module."""
        if not self.has_motor_states():
            return []
        assert self._shm is not None
        return self._shm.read_height_scan(n_rays)
