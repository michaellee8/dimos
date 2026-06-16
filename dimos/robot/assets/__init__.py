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

"""Git-backed robot asset resolution and universal asset processing."""

from dimos.robot.assets.git_cache import (
    DEFAULT_GIT_ASSET_CACHE_ROOT,
    DEFAULT_ROBOT_ASSET_CACHE_ROOT,
    GitAssetCache,
    GitAssetCacheError,
    GitAssetCacheWarning,
    GitAssetCheckout,
)
from dimos.robot.assets.manager import (
    ArtifactRole,
    RobotAssetDeclaration,
    RobotAssetError,
    RobotAssetManager,
    RobotAssetPackagePath,
    RobotAssetPath,
    default_robot_asset_manager,
    robot_asset_package_paths,
    robot_asset_xacro_args,
    set_default_robot_asset_manager,
)
from dimos.robot.assets.processing import (
    DERIVED_ASSET_CACHE_ROOT,
    PackageUriMode,
    render_urdf,
    resolve_package_uris,
)

__all__ = [
    "DEFAULT_GIT_ASSET_CACHE_ROOT",
    "DEFAULT_ROBOT_ASSET_CACHE_ROOT",
    "DERIVED_ASSET_CACHE_ROOT",
    "ArtifactRole",
    "GitAssetCache",
    "GitAssetCacheError",
    "GitAssetCacheWarning",
    "GitAssetCheckout",
    "PackageUriMode",
    "RobotAssetDeclaration",
    "RobotAssetError",
    "RobotAssetManager",
    "RobotAssetPackagePath",
    "RobotAssetPath",
    "default_robot_asset_manager",
    "render_urdf",
    "resolve_package_uris",
    "robot_asset_package_paths",
    "robot_asset_xacro_args",
    "set_default_robot_asset_manager",
]
