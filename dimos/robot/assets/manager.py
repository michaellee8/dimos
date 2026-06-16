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

"""Robot model asset declarations and lazy path adapters."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dimos.robot.assets.git_cache import GitAssetCache


class RobotAssetError(RuntimeError):
    """Raised when a robot asset declaration cannot satisfy a request."""


class ArtifactRole(str, Enum):
    """Common robot asset artifact roles.

    Strings are canonical internally; this enum is a convenience for common roles.
    """

    URDF = "urdf"
    MJCF = "mjcf"
    SRDF = "srdf"
    MESH_DIR = "mesh_dir"


@dataclass(frozen=True)
class RobotAssetDeclaration:
    """Typed declaration for one robot model's assets."""

    model: str
    repo_url: str
    ref: str
    artifacts: Mapping[str, str]
    package_roots: Mapping[str, str] = field(default_factory=dict)
    xacro_args: Mapping[str, str] = field(default_factory=dict)
    source_name: str | None = None
    license: str | None = None


class RobotAssetManager:
    """Resolve robot model artifacts and package roots from declarations."""

    def __init__(
        self,
        declarations: Mapping[str, RobotAssetDeclaration] | None = None,
        git_cache: GitAssetCache | None = None,
    ) -> None:
        self._declarations = dict(declarations or {})
        self._git_cache = git_cache or GitAssetCache()

    def get_declaration(self, model: str) -> RobotAssetDeclaration:
        try:
            return self._declarations[model]
        except KeyError as exc:
            available = ", ".join(sorted(self._declarations)) or "none"
            raise RobotAssetError(
                f"Unknown robot asset model {model!r}. Available models: {available}."
            ) from exc

    def resolve_artifact(self, model: str, role: str | ArtifactRole) -> Path:
        declaration = self.get_declaration(model)
        role_key = _role_key(role)
        try:
            relative_path = declaration.artifacts[role_key]
        except KeyError as exc:
            available = ", ".join(sorted(declaration.artifacts)) or "none"
            raise RobotAssetError(
                f"Robot asset model {model!r} does not declare artifact role {role_key!r}. "
                f"Available roles: {available}."
            ) from exc

        path = self._checkout(declaration) / relative_path
        if not path.exists():
            raise RobotAssetError(
                f"Declared artifact {role_key!r} for robot asset model {model!r} does not exist: {path}"
            )
        return path

    def resolve_package_root(self, model: str, package_name: str) -> Path:
        declaration = self.get_declaration(model)
        try:
            relative_path = declaration.package_roots[package_name]
        except KeyError as exc:
            available = ", ".join(sorted(declaration.package_roots)) or "none"
            raise RobotAssetError(
                f"Robot asset model {model!r} does not declare ROS package root "
                f"{package_name!r}. Available package roots: {available}."
            ) from exc

        path = self._checkout(declaration) / relative_path
        if not path.exists():
            raise RobotAssetError(
                f"Declared package root {package_name!r} for robot asset model {model!r} "
                f"does not exist: {path}"
            )
        return path

    def package_roots(self, model: str) -> dict[str, Path]:
        declaration = self.get_declaration(model)
        return {
            package_name: RobotAssetPackagePath(model, package_name, manager=self)
            for package_name in declaration.package_roots
        }

    def xacro_args(self, model: str) -> dict[str, str]:
        return dict(self.get_declaration(model).xacro_args)

    def _checkout(self, declaration: RobotAssetDeclaration) -> Path:
        return self._git_cache.resolve(declaration.repo_url, declaration.ref).path


class RobotAssetPath(type(Path())):  # type: ignore[misc]
    """Lazy Path-like adapter for a declared robot model artifact."""

    def __new__(
        cls,
        model: str,
        role: str | ArtifactRole,
        *relative_parts: object,
        manager: RobotAssetManager | None = None,
    ) -> RobotAssetPath:
        instance: RobotAssetPath = super().__new__(cls, ".")
        object.__setattr__(instance, "_robot_asset_model", model)
        object.__setattr__(instance, "_robot_asset_role", _role_key(role))
        object.__setattr__(
            instance, "_robot_asset_relative_parts", tuple(str(p) for p in relative_parts)
        )
        object.__setattr__(
            instance, "_robot_asset_manager", manager or default_robot_asset_manager()
        )
        object.__setattr__(instance, "_robot_asset_resolved_cache", None)
        return instance

    def __init__(
        self,
        model: str,
        role: str | ArtifactRole,
        *relative_parts: object,
        manager: RobotAssetManager | None = None,
    ) -> None:
        del model, role, relative_parts, manager

    def _resolve(self) -> Path:
        cache: Path | None = object.__getattribute__(self, "_robot_asset_resolved_cache")
        if cache is None:
            manager: RobotAssetManager = object.__getattribute__(self, "_robot_asset_manager")
            model = object.__getattribute__(self, "_robot_asset_model")
            role = object.__getattribute__(self, "_robot_asset_role")
            relative_parts = object.__getattribute__(self, "_robot_asset_relative_parts")
            cache = manager.resolve_artifact(model, role).joinpath(*relative_parts)
            object.__setattr__(self, "_robot_asset_resolved_cache", cache)
        return cache

    def __getattribute__(self, name: str) -> object:
        try:
            object.__getattribute__(self, "_robot_asset_model")
        except AttributeError:
            return object.__getattribute__(self, name)

        if name.startswith("_robot_asset_") or name in {"_resolve"}:
            return object.__getattribute__(self, name)

        return getattr(object.__getattribute__(self, "_resolve")(), name)

    def __str__(self) -> str:
        return str(self._resolve())

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __truediv__(self, other: object) -> RobotAssetPath:
        model = object.__getattribute__(self, "_robot_asset_model")
        role = object.__getattribute__(self, "_robot_asset_role")
        relative_parts = object.__getattribute__(self, "_robot_asset_relative_parts")
        manager = object.__getattribute__(self, "_robot_asset_manager")
        return RobotAssetPath(model, role, *relative_parts, other, manager=manager)


class RobotAssetPackagePath(type(Path())):  # type: ignore[misc]
    """Lazy Path-like adapter for a declared ROS package root."""

    def __new__(
        cls,
        model: str,
        package_name: str,
        *relative_parts: object,
        manager: RobotAssetManager | None = None,
    ) -> RobotAssetPackagePath:
        instance: RobotAssetPackagePath = super().__new__(cls, ".")
        object.__setattr__(instance, "_robot_asset_model", model)
        object.__setattr__(instance, "_robot_asset_package_name", package_name)
        object.__setattr__(
            instance, "_robot_asset_relative_parts", tuple(str(p) for p in relative_parts)
        )
        object.__setattr__(
            instance, "_robot_asset_manager", manager or default_robot_asset_manager()
        )
        object.__setattr__(instance, "_robot_asset_resolved_cache", None)
        return instance

    def __init__(
        self,
        model: str,
        package_name: str,
        *relative_parts: object,
        manager: RobotAssetManager | None = None,
    ) -> None:
        del model, package_name, relative_parts, manager

    def _resolve(self) -> Path:
        cache: Path | None = object.__getattribute__(self, "_robot_asset_resolved_cache")
        if cache is None:
            manager: RobotAssetManager = object.__getattribute__(self, "_robot_asset_manager")
            model = object.__getattribute__(self, "_robot_asset_model")
            package_name = object.__getattribute__(self, "_robot_asset_package_name")
            relative_parts = object.__getattribute__(self, "_robot_asset_relative_parts")
            cache = manager.resolve_package_root(model, package_name).joinpath(*relative_parts)
            object.__setattr__(self, "_robot_asset_resolved_cache", cache)
        return cache

    def __getattribute__(self, name: str) -> object:
        try:
            object.__getattribute__(self, "_robot_asset_model")
        except AttributeError:
            return object.__getattribute__(self, name)

        if name.startswith("_robot_asset_") or name in {"_resolve"}:
            return object.__getattribute__(self, name)

        return getattr(object.__getattribute__(self, "_resolve")(), name)

    def __str__(self) -> str:
        return str(self._resolve())

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __truediv__(self, other: object) -> RobotAssetPackagePath:
        model = object.__getattribute__(self, "_robot_asset_model")
        package_name = object.__getattribute__(self, "_robot_asset_package_name")
        relative_parts = object.__getattribute__(self, "_robot_asset_relative_parts")
        manager = object.__getattribute__(self, "_robot_asset_manager")
        return RobotAssetPackagePath(model, package_name, *relative_parts, other, manager=manager)


_DEFAULT_MANAGER: RobotAssetManager | None = None


def default_robot_asset_manager() -> RobotAssetManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        from dimos.robot.assets.declarations import ROBOT_ASSETS

        _DEFAULT_MANAGER = RobotAssetManager(ROBOT_ASSETS)
    return _DEFAULT_MANAGER


def set_default_robot_asset_manager(manager: RobotAssetManager | None) -> None:
    """Override the process-default robot asset manager.

    Passing ``None`` clears the override and restores lazy construction from the
    DimOS declarations module on the next default lookup.
    """
    global _DEFAULT_MANAGER
    _DEFAULT_MANAGER = manager


def robot_asset_package_paths(model: str) -> dict[str, Path]:
    return default_robot_asset_manager().package_roots(model)


def robot_asset_xacro_args(model: str) -> dict[str, str]:
    return default_robot_asset_manager().xacro_args(model)


def _role_key(role: str | ArtifactRole) -> str:
    return role.value if isinstance(role, ArtifactRole) else str(role)
