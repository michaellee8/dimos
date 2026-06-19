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

"""Direct optional imports for VAMP robot artifacts."""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from typing import cast

from dimos.manipulation.planning.vamp.errors import VampDependencyError
from dimos.manipulation.planning.world.config import (
    CustomVampArtifactConfig,
    OfficialVampArtifactConfig,
    VampArtifactConfig,
)

_VAMP_IMPORT_ERROR: ImportError | None

try:
    import vamp
    import vamp.baxter
    import vamp.fetch
    import vamp.panda
    import vamp.sphere
    import vamp.ur5
except ImportError as exc:
    _VAMP_IMPORT_ERROR = exc
else:
    _VAMP_IMPORT_ERROR = None


def require_vamp() -> None:
    """Raise with install guidance when the optional VAMP package is unavailable."""
    if _VAMP_IMPORT_ERROR is not None:
        raise VampDependencyError() from _VAMP_IMPORT_ERROR


def load_vamp_robot_module(artifact: VampArtifactConfig) -> vamp.RobotModule:
    """Load the configured VAMP robot module."""
    require_vamp()
    if isinstance(artifact, OfficialVampArtifactConfig):
        return _load_official_robot_module(artifact.robot)
    if isinstance(artifact, CustomVampArtifactConfig):
        return _load_custom_robot_module(artifact.path)
    raise TypeError(f"Unsupported VAMP artifact config: {type(artifact).__name__}")


def _load_official_robot_module(robot: str) -> vamp.RobotModule:
    match robot:
        case "baxter":
            return cast("vamp.RobotModule", vamp.baxter)
        case "fetch":
            return cast("vamp.RobotModule", vamp.fetch)
        case "panda":
            return cast("vamp.RobotModule", vamp.panda)
        case "sphere":
            return cast("vamp.RobotModule", vamp.sphere)
        case "ur5":
            return cast("vamp.RobotModule", vamp.ur5)
        case _:
            raise ValueError(f"Installed VAMP package does not expose robot artifact '{robot}'")


def _load_custom_robot_module(path: Path) -> vamp.RobotModule:
    artifact_path = path.expanduser().resolve()
    if not artifact_path.exists():
        raise FileNotFoundError(f"VAMP custom artifact path does not exist: {artifact_path}")

    if artifact_path.is_dir():
        parent = str(artifact_path.parent)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        return cast("vamp.RobotModule", importlib.import_module(artifact_path.name))

    module_name = artifact_path.stem
    spec = importlib.util.spec_from_file_location(module_name, artifact_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load VAMP custom artifact module: {artifact_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return cast("vamp.RobotModule", module)
