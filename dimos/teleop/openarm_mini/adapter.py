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

"""OpenArm Mini teleop adapter."""

from __future__ import annotations

import math

from dimos.teleop.openarm_mini.calibration import (
    FEETECH_POSITION_SPAN,
    OPENARM_MINI_ARM_JOINT_NAMES,
    OpenArmMiniCalibration,
    OpenArmMiniMotorCalibration,
    load_calibration,
)
from dimos.teleop.openarm_mini.config import OpenArmMiniTeleopConfig, validate_side
from dimos.teleop.openarm_mini.feetech import FeetechLeaderReader
from dimos.teleop.openarm_mini.mapping import combine_side_commands, map_side_readings
from dimos.teleop.runtime.types import TeleopCommand


class OpenArmMiniTeleopAdapter:
    """TeleopAdapter implementation for selected OpenArm Mini leader sides."""

    def __init__(self, config: OpenArmMiniTeleopConfig | None = None) -> None:
        self.config = config if config is not None else OpenArmMiniTeleopConfig()
        self._buses: dict[str, _ScservoSideBus] = {}
        self._previous_positions_by_side: dict[str, dict[str, float]] = {}
        self._connected = False

    def connect(self) -> None:
        """Load calibration and connect configured OpenArm Mini leader sides."""
        if self._connected:
            return
        buses: dict[str, _ScservoSideBus] = {}
        try:
            for side in self.config.sides():
                calibration = load_calibration(self.config.calibration_path(side), side)
                bus = _ScservoSideBus(
                    side, self.config.port(side), calibration, self.config.baudrate
                )
                bus.connect()
                buses[side] = bus
        except Exception:
            for bus in buses.values():
                bus.disconnect()
            raise
        self._buses = buses
        self._connected = True

    def disconnect(self) -> None:
        """Disconnect any connected Feetech buses."""
        for bus in self._buses.values():
            bus.disconnect()
        self._buses = {}
        self._connected = False
        self._previous_positions_by_side = {}

    def get_current_command(self) -> TeleopCommand | None:
        """Return the current JointState command envelope when readings are valid."""
        if not self._connected or not self.config.authority_active:
            return None

        side_commands = []
        next_previous_positions_by_side: dict[str, dict[str, float]] = {}
        try:
            for side in self.config.sides():
                bus = self._buses[side]
                side_command = map_side_readings(
                    side,
                    bus.read_positions(),
                    target_joint_names=self.config.target_joint_names(side),
                    previous_positions_by_joint=self._previous_positions_by_side.get(side),
                    max_joint_jump_radians=self.config.max_joint_jump_radians,
                )
                side_commands.append(side_command)
                next_previous_positions_by_side[side] = side_command.positions_by_joint
        except (KeyError, ValueError):
            return None

        self._previous_positions_by_side = next_previous_positions_by_side
        return TeleopCommand(payload=combine_side_commands(side_commands))


class _ScservoSideBus:
    """Small Feetech SDK wrapper for OpenArm Mini leader position reads."""

    def __init__(
        self,
        side: str,
        port: str,
        calibration: OpenArmMiniCalibration,
        baudrate: int,
    ) -> None:
        validate_side(side)
        self._side = side
        self._calibration = calibration
        self._reader = FeetechLeaderReader(
            port,
            baudrate,
            label=f"OpenArm Mini {side} Feetech",
        )

    def connect(self) -> None:
        self._reader.connect()

    def disconnect(self) -> None:
        self._reader.disconnect()

    def read_positions(self) -> dict[str, float]:
        motor_ids_by_name = {
            joint_name: self._calibration.motors[joint_name].id
            for joint_name in OPENARM_MINI_ARM_JOINT_NAMES
        }
        raw_positions = self._reader.read_raw_positions(motor_ids_by_name)
        positions: dict[str, float] = {}
        for joint_name in OPENARM_MINI_ARM_JOINT_NAMES:
            motor_calibration = self._calibration.motors[joint_name]
            raw_position = raw_positions[joint_name]
            positions[joint_name] = _calibrated_motor_radians(raw_position, motor_calibration)
        return positions


def _calibrated_motor_radians(raw_position: int, calibration: OpenArmMiniMotorCalibration) -> float:
    centered = raw_position - calibration.homing_offset
    radians = centered * math.tau / FEETECH_POSITION_SPAN
    if calibration.flip:
        radians = -radians
    return radians


def _normalize_motor_position(raw_position: int, calibration: OpenArmMiniMotorCalibration) -> float:
    """Backward-compatible helper for tests; returns calibrated radians."""
    return _calibrated_motor_radians(raw_position, calibration)
