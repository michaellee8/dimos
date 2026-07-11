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
from __future__ import annotations

from pathlib import Path
import subprocess

from dimos.core.deployment.models import ExternalModulePlan, PrepareResult
from dimos.core.deployment.planner import launch_command_for_package, prepare_command_for_package


class LocalTargetSession:
    """Coordinator-side access to the local execution target for v1."""

    def run(self, command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=cwd, check=True, text=True)

    def prepare_package(self, module: ExternalModulePlan) -> PrepareResult:
        command = prepare_command_for_package(module)
        self.run(command, cwd=module.package.python_dir)
        return PrepareResult(module=module, command_prefix=launch_command_for_package(module))
