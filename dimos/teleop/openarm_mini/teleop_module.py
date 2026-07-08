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

"""OpenArm Mini teleop module using the shared teleop runtime."""

from __future__ import annotations

from pydantic import Field

from dimos.teleop.openarm_mini.adapter import OpenArmMiniTeleopAdapter
from dimos.teleop.openarm_mini.config import OpenArmMiniTeleopConfig
from dimos.teleop.runtime.teleop_module import TeleopModule, TeleopModuleConfig
from dimos.teleop.runtime.types import TeleopCommand


class OpenArmMiniTeleopModuleConfig(TeleopModuleConfig):
    """Config for OpenArm Mini leader teleoperation."""

    # Default to one side so running the concrete module directly only requires
    # one leader calibration/port override. Dual-arm blueprints opt into both.
    openarm_mini: OpenArmMiniTeleopConfig = Field(
        default_factory=lambda: OpenArmMiniTeleopConfig(enabled_sides=("left",))
    )


class OpenArmMiniTeleopModule(TeleopModule):
    """Teleop module for OpenArm Mini leader devices."""

    config: OpenArmMiniTeleopModuleConfig  # type: ignore[assignment]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._adapter = OpenArmMiniTeleopAdapter(self.openarm_mini_config.openarm_mini)

    @property
    def openarm_mini_config(self) -> OpenArmMiniTeleopModuleConfig:
        return self.config

    def connect_teleop(self) -> None:
        self._adapter.connect()

    def disconnect_teleop(self) -> None:
        self._adapter.disconnect()

    def get_current_command(self) -> TeleopCommand | None:
        return self._adapter.get_current_command()
