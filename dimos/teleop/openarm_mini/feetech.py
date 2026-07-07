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

"""Shared Feetech SDK helpers for OpenArm Mini leader tools and adapters."""

from __future__ import annotations

from collections.abc import Mapping
import importlib
from typing import Any

from dimos.teleop.openarm_mini.config import missing_dependency_error


def _load_scservo_sdk() -> Any:
    """Load the optional, untyped Feetech SDK at the hardware boundary."""
    try:
        return importlib.import_module("scservo_sdk")
    except ImportError as exc:
        raise missing_dependency_error() from exc


def _read_motor_position(packet_handler: Any, motor_id: int) -> int:
    result = packet_handler.ReadPos(motor_id)
    if isinstance(result, tuple):
        position = result[0]
    else:
        position = result
    return int(position)


class FeetechLeaderReader:
    """Concrete reader for raw Feetech positions on one OpenArm Mini leader bus."""

    def __init__(self, port: str, baudrate: int, *, label: str = "Feetech") -> None:
        self._port = port
        self._baudrate = baudrate
        self._label = label
        self._port_handler: Any | None = None
        self._packet_handler: Any | None = None

    def connect(self) -> None:
        sdk = _load_scservo_sdk()
        port_handler = sdk.PortHandler(self._port)
        packet_handler = sdk.sms_sts(port_handler)
        if not port_handler.openPort():
            raise RuntimeError(f"failed to open {self._label} port {self._port}")
        if not port_handler.setBaudRate(self._baudrate):
            port_handler.closePort()
            raise RuntimeError(f"failed to set {self._label} baudrate {self._baudrate}")
        self._port_handler = port_handler
        self._packet_handler = packet_handler

    def disconnect(self) -> None:
        if self._port_handler is None:
            return
        close_port = getattr(self._port_handler, "closePort", None)
        if callable(close_port):
            close_port()
        self._port_handler = None
        self._packet_handler = None

    def read_raw_positions(self, motor_ids_by_name: Mapping[str, int]) -> dict[str, int]:
        if self._packet_handler is None:
            raise RuntimeError(f"{self._label} reader is not connected")
        return {
            joint_name: _read_motor_position(self._packet_handler, motor_id)
            for joint_name, motor_id in motor_ids_by_name.items()
        }
