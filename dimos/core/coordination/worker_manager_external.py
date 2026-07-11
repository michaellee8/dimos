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

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import Any

from dimos.core.coordination.external_worker import ExternalWorkerClient
from dimos.core.deployment.models import DeploymentPlan, ExternalModule, ExternalModulePlan
from dimos.core.deployment.target_session import LocalTargetSession
from dimos.core.global_config import GlobalConfig
from dimos.core.module import ModuleBase, ModuleSpec
from dimos.core.rpc_client import ModuleProxyProtocol, RPCClient


class WorkerManagerExternal:
    deployment_identifier = "external-python"

    def __init__(self, g: GlobalConfig) -> None:
        self.g = g
        self._session = LocalTargetSession()
        self._client: ExternalWorkerClient | None = None
        self._plan_by_class: dict[type[ExternalModule], ExternalModulePlan] = {}
        self._launched_module_ids: list[str] = []

    def configure_plan(self, plan: DeploymentPlan) -> None:
        self._plan_by_class = plan.external_by_class

    def start(self) -> None:
        return None

    def deploy(
        self, module_class: type[ModuleBase], global_config: GlobalConfig, kwargs: dict[str, Any]
    ) -> ModuleProxyProtocol:
        return self.deploy_parallel([(module_class, global_config, kwargs)], {})[0]

    def deploy_parallel(
        self, specs: Sequence[ModuleSpec], blueprint_args: Mapping[str, Mapping[str, Any]]
    ) -> list[ModuleProxyProtocol]:
        if not specs:
            return []
        client = self._ensure_worker_client()
        proxies: list[ModuleProxyProtocol] = []
        for module_class, _global_config, kwargs in specs:
            if not issubclass(module_class, ExternalModule):
                raise TypeError(f"{module_class.__name__} is not an ExternalModule declaration")
            module_plan = self._plan_by_class.get(module_class)
            if module_plan is None:
                raise ValueError(
                    f"External module {module_class.__name__} is missing resolved deployment plan"
                )
            effective_plan = _with_deploy_kwargs(
                module_plan, _merge_config_kwargs(module_plan.kwargs, kwargs)
            )
            prepared = self._session.prepare_package(effective_plan)
            client.launch_runtime(
                effective_plan.launch_envelope(),
                prepared.command_prefix,
                self._runtime_environment(effective_plan),
            )
            self._launched_module_ids.append(effective_plan.module_id)
            proxies.append(RPCClient.remote(module_class))  # type: ignore[arg-type]
        return proxies

    def prepare_plan(self, plan: DeploymentPlan) -> list[str]:
        prepared: list[str] = []
        for module in plan.external_modules:
            result = self._session.prepare_package(module)
            prepared.append(" ".join(result.command_prefix))
        return prepared

    def stop(self) -> None:
        if self._client is not None:
            for module_id in reversed(self._launched_module_ids):
                try:
                    self._client.stop_runtime(module_id)
                except (BrokenPipeError, EOFError, ConnectionResetError, RuntimeError):
                    pass
            try:
                self._client.shutdown()
            except (BrokenPipeError, EOFError, ConnectionResetError, RuntimeError):
                pass
            self._client = None
        self._launched_module_ids = []

    def health_check(self) -> bool:
        if self._client is None:
            return True
        status = self._client.status()
        module_ids = status.get("module_ids", [])
        return isinstance(module_ids, list)

    def suppress_console(self) -> None:
        return None

    def _ensure_worker_client(self) -> ExternalWorkerClient:
        if self._client is None:
            self._client = ExternalWorkerClient()
            self._client.start_process()
        return self._client

    def _runtime_environment(self, module: ExternalModulePlan) -> dict[str, str]:
        env = os.environ.copy()
        repo_root = Path(__file__).parents[3]
        pythonpath_entries = [str(repo_root), str(module.package.package_root)]
        existing = env.get("PYTHONPATH")
        if existing:
            pythonpath_entries.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
        return env


def prepare_deployment(plan: DeploymentPlan, g: GlobalConfig) -> list[str]:
    manager = WorkerManagerExternal(g)
    return manager.prepare_plan(plan)


def _with_deploy_kwargs(
    module_plan: ExternalModulePlan, kwargs: dict[str, object]
) -> ExternalModulePlan:
    return ExternalModulePlan(
        module_class=module_plan.module_class,
        module_id=module_plan.module_id,
        module_name=module_plan.module_name,
        rpc_name=module_plan.rpc_name,
        package=module_plan.package,
        policy=module_plan.policy,
        kwargs=kwargs,
    )


def _merge_config_kwargs(
    base: Mapping[str, object], overrides: Mapping[str, object]
) -> dict[str, object]:
    merged = dict(base)
    for key, override_value in overrides.items():
        base_value = merged.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = _merge_config_kwargs(base_value, override_value)
        else:
            merged[key] = override_value
    return merged
