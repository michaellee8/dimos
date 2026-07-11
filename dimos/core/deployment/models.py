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

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, NewType, TypeAlias, cast

from dimos.core.coordination.blueprints import Blueprint
from dimos.core.core import rpc
from dimos.core.module import Deployment, ModuleBase
from dimos.core.stream import In, Out, Transport

RuntimeSessionId = NewType("RuntimeSessionId", str)
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class ExternalModule(ModuleBase):
    """Coordinator-visible declaration for a packaged external Module.

    Subclasses declare streams, config type, @rpc/@skill methods, module refs,
    and a module-owned implementation reference. The coordinator imports this
    declaration only; the packaged runtime class subclasses it plus the real
    Module implementation surface.
    """

    deployment: ClassVar[Deployment] = "external-python"
    implementation: ClassVar[str | Path | None] = None

    @rpc
    def dimos_ready(self) -> str:
        """Side-effect-free readiness endpoint for external process startup."""
        return "ready"

    @rpc
    def set_transport(self, stream_name: str, transport: Transport[object]) -> bool:
        """Attach a coordinator-selected transport to a declared stream.

        External runtime classes commonly inherit the declaration before
        `Module`. Providing the real implementation here prevents the
        declaration method from shadowing `Module.set_transport`.
        """
        stream = getattr(self, stream_name, None)
        if not stream:
            raise ValueError(f"{stream_name} not found in {self.__class__.__name__}")

        if not isinstance(stream, Out) and not isinstance(stream, In):
            raise TypeError(f"Output {stream_name} is not a valid stream")

        stream._transport = transport
        return True


@dataclass(frozen=True)
class ModuleDeployment:
    execution_target: str = "local"
    build_target: str | None = None
    preparation: str | None = None
    runtime_environment: str | None = None
    readiness_timeout_s: float = 10.0


@dataclass(frozen=True)
class LocalPythonPackage:
    package_root: Path
    declaration: type[ExternalModule]
    declaration_ref: str
    implementation_ref: str
    uses_pixi: bool
    readiness_timeout_s: float = 10.0

    @property
    def python_dir(self) -> Path:
        return self.package_root / "python"


@dataclass(frozen=True)
class ModuleLaunchEnvelope:
    module_id: str
    module_name: str
    rpc_name: str
    declaration_ref: str
    implementation_ref: str
    package_root: str
    runtime_workdir: str
    config: JsonObject = field(default_factory=dict)
    streams: JsonObject = field(default_factory=dict)
    readiness_method: str = "dimos_ready"
    readiness_timeout_s: float = 10.0

    def to_json(self) -> JsonObject:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "rpc_name": self.rpc_name,
            "declaration_ref": self.declaration_ref,
            "implementation_ref": self.implementation_ref,
            "package_root": self.package_root,
            "runtime_workdir": self.runtime_workdir,
            "config": self.config,
            "streams": self.streams,
            "readiness_method": self.readiness_method,
            "readiness_timeout_s": self.readiness_timeout_s,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, JsonValue]) -> ModuleLaunchEnvelope:
        config = data.get("config", {})
        streams = data.get("streams", {})
        if not isinstance(config, dict):
            raise TypeError("ModuleLaunchEnvelope config must be a JSON object")
        if not isinstance(streams, dict):
            raise TypeError("ModuleLaunchEnvelope streams must be a JSON object")
        return cls(
            module_id=_required_str(data, "module_id"),
            module_name=_required_str(data, "module_name"),
            rpc_name=_required_str(data, "rpc_name"),
            declaration_ref=_required_str(data, "declaration_ref"),
            implementation_ref=_required_str(data, "implementation_ref"),
            package_root=_required_str(data, "package_root"),
            runtime_workdir=_required_str(data, "runtime_workdir"),
            config=config,
            streams=streams,
            readiness_method=_required_str(data, "readiness_method"),
            readiness_timeout_s=_required_float(data, "readiness_timeout_s"),
        )


@dataclass(frozen=True)
class ExternalModulePlan:
    module_class: type[ExternalModule]
    module_id: str
    module_name: str
    rpc_name: str
    package: LocalPythonPackage
    policy: ModuleDeployment
    kwargs: dict[str, object] = field(default_factory=dict)

    def launch_envelope(self) -> ModuleLaunchEnvelope:
        return ModuleLaunchEnvelope(
            module_id=self.module_id,
            module_name=self.module_name,
            rpc_name=self.rpc_name,
            declaration_ref=self.package.declaration_ref,
            implementation_ref=self.package.implementation_ref,
            package_root=str(self.package.package_root),
            runtime_workdir=str(self.package.python_dir),
            config=_json_object_from_kwargs(self.kwargs),
            readiness_timeout_s=self.package.readiness_timeout_s,
        )


@dataclass(frozen=True)
class DeploymentPlan:
    python_modules: tuple[type[ModuleBase], ...]
    external_modules: tuple[ExternalModulePlan, ...]

    @property
    def external_by_class(self) -> dict[type[ExternalModule], ExternalModulePlan]:
        return {module.module_class: module for module in self.external_modules}


@dataclass(frozen=True)
class PrepareResult:
    module: ExternalModulePlan
    command_prefix: tuple[str, ...]


@dataclass(frozen=True)
class DeploymentSpec:
    blueprint: Blueprint
    modules: dict[type[ModuleBase], ModuleDeployment] = field(default_factory=dict)


def _required_str(data: Mapping[str, JsonValue], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"ModuleLaunchEnvelope {key} must be a string")
    return value


def _required_float(data: Mapping[str, JsonValue], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, int | float):
        raise TypeError(f"ModuleLaunchEnvelope {key} must be a number")
    return float(value)


def _json_object_from_kwargs(kwargs: Mapping[str, object]) -> JsonObject:
    result: JsonObject = {}
    for key, value in kwargs.items():
        try:
            result[key] = _coerce_json_value(value)
        except TypeError as exc:
            raise TypeError(
                f"ModuleLaunchEnvelope config value for {key!r} is not JSON-compatible"
            ) from exc
    return result


def _coerce_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return cast("JsonValue", value)
    if isinstance(value, list):
        result: list[JsonValue] = []
        for item in value:
            result.append(_coerce_json_value(item))
        return result
    if isinstance(value, dict):
        result_dict: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result_dict[key] = _coerce_json_value(item)
        return result_dict
    raise TypeError(f"{type(value).__name__} is not JSON-compatible")
