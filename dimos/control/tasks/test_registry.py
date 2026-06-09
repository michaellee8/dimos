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

from dimos.control.tasks.registry import ControlTaskRegistry


def test_control_task_registry_discovers_manifest_task_types() -> None:
    registry = ControlTaskRegistry()

    assert registry.available() == [
        "cartesian_ik",
        "g1_groot_wbc",
        "servo",
        "teleop_ik",
        "trajectory",
        "velocity",
        "x2_rsl_rl_wbc",
    ]


def test_discovered_factory_paths_resolve_current_flat_modules() -> None:
    registry = ControlTaskRegistry()

    factory = registry._resolve_factory("servo")

    assert factory.__module__ == "dimos.control.tasks.servo_task"
    assert factory.__name__ == "create_task"
