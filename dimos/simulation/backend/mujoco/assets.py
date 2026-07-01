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

"""Bundled MuJoCo asset resolution (scene meshes, menagerie robots).

Split out of the legacy ``model.py`` so live code (the engine, the sim
module, robot blueprints) can load assets without importing the legacy
subprocess stack and its ONNX controllers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from etils import epath

from dimos.utils.data import get_data


def _get_data_dir() -> epath.Path:
    return epath.Path(str(get_data("mujoco_sim")))


def _update_assets(assets: dict[str, bytes], path: epath.Path | Path, glob: str = "*") -> None:
    """Populate MuJoCo's asset dict without importing mujoco_playground runtime code."""
    for asset_path in Path(str(path)).glob(glob):
        if asset_path.is_file():
            assets[asset_path.name] = asset_path.read_bytes()


def _menagerie_path() -> Path:
    spec = importlib.util.find_spec("mujoco_playground")
    if spec is None or not spec.submodule_search_locations:
        raise ImportError("mujoco_playground is required for bundled MuJoCo menagerie assets")
    root = Path(next(iter(spec.submodule_search_locations)))
    menagerie = root / "external_deps" / "mujoco_menagerie"
    if not menagerie.exists():
        raise FileNotFoundError(f"MuJoCo menagerie assets not found: {menagerie}")
    return menagerie


def get_assets() -> dict[str, bytes]:
    data_dir = _get_data_dir()
    assets: dict[str, bytes] = {}
    menagerie_path = _menagerie_path()

    # Assets used from https://sketchfab.com/3d-models/mersus-office-8714be387bcd406898b2615f7dae3a47
    # Created by Ryan Cassidy and Coleman Costello
    _update_assets(assets, data_dir, "*.xml")
    _update_assets(assets, data_dir, "*.obj")  # top-level scene meshes (e.g. dimos_office.obj)
    _update_assets(assets, data_dir / "scene_office1/textures", "*.png")
    _update_assets(assets, data_dir / "scene_office1/office_split", "*.obj")
    _update_assets(assets, menagerie_path / "unitree_go1" / "assets")
    _update_assets(assets, menagerie_path / "unitree_g1" / "assets")

    # From: https://sketchfab.com/3d-models/jeong-seun-34-42956ca979404a038b8e0d3e496160fd
    person_dir = epath.Path(str(get_data("person")))
    _update_assets(assets, person_dir, "*.obj")
    _update_assets(assets, person_dir, "*.png")

    return assets
