# Copyright 2026 Dimensional Inc.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from dimos.core.coordination.external_python_worker import ExternalPythonWorker
from dimos.core.coordination.worker_manager import WorkerManager
from dimos.core.global_config import GlobalConfig
from dimos.core.module import ModuleBase, ModuleSpec
from dimos.core.rpc_client import ModuleProxyProtocol, RPCClient
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


def _merge_config_kwargs(kwargs: dict[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(kwargs)
    merged.update(overrides)
    return merged


class WorkerManagerExternalPython(WorkerManager):
    deployment_identifier = "external-python"

    def __init__(self, g: GlobalConfig) -> None:
        super().__init__(g)
        self._workers: dict[ModuleProxyProtocol, ExternalPythonWorker] = {}
        self._module_kwargs: dict[ModuleProxyProtocol, dict[str, Any]] = {}
        self._closed = False

    def start(self) -> None:
        return

    def deploy(
        self,
        module_class: type[ModuleBase],
        global_config: GlobalConfig,
        kwargs: dict[str, Any],
    ) -> ModuleProxyProtocol:
        if self._closed:
            raise RuntimeError("WorkerManager is closed")
        runtime_kwargs = dict(kwargs)
        runtime_kwargs["g"] = global_config
        worker = ExternalPythonWorker(module_class, global_config, runtime_kwargs)
        worker.start()
        proxy = cast("ModuleProxyProtocol", RPCClient.remote(module_class))
        self._workers[proxy] = worker
        self._module_kwargs[proxy] = dict(kwargs)
        return proxy

    def deploy_parallel(
        self, specs: Sequence[ModuleSpec], blueprint_args: Mapping[str, Mapping[str, Any]]
    ) -> list[ModuleProxyProtocol]:
        return [
            self.deploy(
                module_class,
                global_config,
                _merge_config_kwargs(kwargs, blueprint_args.get(module_class.name, {})),
            )
            for module_class, global_config, kwargs in specs
        ]

    def deploy_fresh(
        self,
        module_class: type[ModuleBase],
        global_config: GlobalConfig,
        kwargs: dict[str, Any],
    ) -> ModuleProxyProtocol:
        return self.deploy(module_class, global_config, kwargs)

    def undeploy(self, proxy: ModuleProxyProtocol) -> None:
        worker = self._workers.pop(proxy, None)
        if worker is None:
            raise ValueError("Proxy is not managed by external Python workers")
        worker.stop()
        self._module_kwargs.pop(proxy, None)

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True
        for worker in self._workers.values():
            worker.stop()
        self._workers.clear()
        self._module_kwargs.clear()

    def health_check(self) -> bool:
        healthy = True
        for _proxy, worker in self._workers.items():
            if worker.pid is not None:
                continue
            module_name = worker.declaration.__name__
            try:
                diagnostics = worker.diagnostics()[:4096]
            except Exception as error:
                diagnostics = f"diagnostics unavailable: {error!r}"
            logger.error(
                "External Python worker failed health check",
                module=module_name,
                diagnostics=diagnostics,
            )
            healthy = False
        return healthy

    def suppress_console(self) -> None:
        return
