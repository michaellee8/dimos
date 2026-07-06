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

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, cast

from dimos.core.coordination.python_worker import PythonWorker
from dimos.core.coordination.worker_launcher import CommandWorkerLauncher, WorkerLauncher
from dimos.core.global_config import GlobalConfig
from dimos.core.module import ModuleBase, ModuleSpec
from dimos.core.rpc_client import ModuleProxyProtocol, RPCClient
from dimos.core.runtime_environment import (
    PythonProjectRuntimeEnvironment,
    RuntimeEnvironmentRegistry,
    RuntimePlacement,
)
from dimos.utils.logging_config import setup_logger
from dimos.utils.safe_thread_map import safe_thread_map

if TYPE_CHECKING:
    from dimos.core.resource_monitor.monitor import StatsMonitor

logger = setup_logger()


class WorkerManagerPython:
    deployment_identifier: str = "python"

    def __init__(self, g: GlobalConfig, worker_launcher: WorkerLauncher | None = None) -> None:
        self._cfg = g
        self._n_workers = g.n_workers
        self._worker_launcher = worker_launcher
        self._workers: list[PythonWorker] = []
        self._runtime_environment_registry = RuntimeEnvironmentRegistry()
        self._runtime_workers: dict[str, list[PythonWorker]] = {}
        self._runtime_launchers: dict[str, WorkerLauncher] = {}
        self._runtime_placements_by_module: dict[type[ModuleBase], RuntimePlacement] = {}
        self._closed = False
        self._started = False
        self._stats_monitor: StatsMonitor | None = None

    def register_runtime_environments(self, registry: RuntimeEnvironmentRegistry) -> None:
        self._runtime_environment_registry = self._runtime_environment_registry.merge(registry)

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._add_workers_to_pool(self._workers, self._worker_launcher, self._n_workers)
        logger.info("Worker pool started.", n_workers=self._n_workers)

        if self._cfg.dtop:
            from dimos.core.resource_monitor.monitor import StatsMonitor

            self._stats_monitor = StatsMonitor(self)
            self._stats_monitor.start()

    def add_workers(self, n: int) -> None:
        """Spawn *n* additional worker processes into the pool."""
        if self._closed:
            raise RuntimeError("WorkerManager is closed")
        if not self._started:
            raise RuntimeError("WorkerManager not started; call start() first")
        self._add_workers_to_pool(self._workers, self._worker_launcher, n)
        self._n_workers += n
        logger.info("Added workers to pool.", added=n, total=self._n_workers)

    def deploy(
        self,
        module_class: type[ModuleBase],
        global_config: GlobalConfig,
        kwargs: dict[str, Any],
        runtime_placement: RuntimePlacement | None = None,
    ) -> ModuleProxyProtocol:
        if self._closed:
            raise RuntimeError("WorkerManager is closed")

        if not self._started:
            self.start()

        workers, launcher = self._pool_for(runtime_placement)
        self._ensure_capacity_for_dedicated(
            [(module_class, global_config, kwargs)],
            workers,
            launcher,
        )
        worker = self._select_worker(workers, launcher, dedicated=module_class.dedicated_worker)
        actor = worker.deploy_module(
            module_class,
            global_config,
            kwargs=kwargs,
            implementation_path=(runtime_placement.implementation if runtime_placement else None),
            runtime_name=(runtime_placement.runtime if runtime_placement else None),
        )
        if runtime_placement is not None:
            self._runtime_placements_by_module[module_class] = runtime_placement
        return cast("ModuleProxyProtocol", RPCClient(actor, module_class))

    def deploy_fresh(
        self,
        module_class: type[ModuleBase],
        global_config: GlobalConfig,
        kwargs: dict[str, Any],
        runtime_placement: RuntimePlacement | None = None,
    ) -> ModuleProxyProtocol:
        """Spawn a brand-new worker process and deploy *module_class* on it.

        Used by restart so the new module is imported by a Python process with
        a clean ``sys.modules`` — existing workers would reuse the old class
        object even after ``importlib.reload`` in the parent.
        """
        if self._closed:
            raise RuntimeError("WorkerManager is closed")
        if not self._started:
            self.start()

        if runtime_placement is None:
            runtime_placement = self._runtime_placements_by_module.get(module_class)
        workers, launcher = self._pool_for(runtime_placement)
        worker = PythonWorker(launcher)
        worker.start_process()
        workers.append(worker)
        if runtime_placement is None:
            self._n_workers += 1
        if module_class.dedicated_worker:
            worker.dedicated = True
        actor = worker.deploy_module(
            module_class,
            global_config,
            kwargs=kwargs,
            implementation_path=(runtime_placement.implementation if runtime_placement else None),
            runtime_name=(runtime_placement.runtime if runtime_placement else None),
        )
        if runtime_placement is not None:
            self._runtime_placements_by_module[module_class] = runtime_placement
        return cast("ModuleProxyProtocol", RPCClient(actor, module_class))

    def undeploy(
        self,
        proxy: ModuleProxyProtocol,
        module_class: type[ModuleBase] | None = None,
    ) -> None:
        """Undeploy a module and shut down its worker if it is now empty."""
        actor = getattr(proxy, "actor_instance", None)
        if actor is None:
            raise ValueError("Proxy has no actor_instance. Cannot undeploy.")

        module_id = actor._module_id
        target: PythonWorker | None = None
        for workers in self._all_worker_pools():
            for worker in workers:
                if module_id in worker._modules:
                    target = worker
                    break
            if target is not None:
                break
        if target is None:
            raise ValueError(f"No worker holds module_id={module_id}")

        target.undeploy_module(module_id)

        if not target._modules:
            target.shutdown()
            removed_from_default_pool = self._remove_worker_from_pool(target)
            if removed_from_default_pool:
                self._n_workers = max(0, self._n_workers - 1)
        if module_class is not None:
            self._runtime_placements_by_module.pop(module_class, None)

    def runtime_placement_for(self, module_class: type[ModuleBase]) -> RuntimePlacement | None:
        return self._runtime_placements_by_module.get(module_class)

    def deploy_parallel(
        self,
        specs: Iterable[ModuleSpec],
        blueprint_args: Mapping[str, Mapping[str, Any]],
        runtime_placements: Mapping[type[ModuleBase], RuntimePlacement] | None = None,
    ) -> list[ModuleProxyProtocol]:
        if self._closed:
            raise RuntimeError("WorkerManager is closed")

        specs = list(specs)
        runtime_placements = runtime_placements or {}
        if len(specs) == 0:
            return []

        if not self._started:
            self.start()

        created_runtime_pools: set[str] = set()

        workers_by_index: dict[int, PythonWorker] = {}
        assignments: list[tuple[PythonWorker, ModuleSpec]] = []

        def _deploy(item: tuple[PythonWorker, ModuleSpec]) -> ModuleProxyProtocol:
            worker, (module_class, global_config, kwargs) = item
            placement = runtime_placements.get(module_class)
            return cast(
                "ModuleProxyProtocol",
                RPCClient(
                    worker.deploy_module(
                        module_class,
                        global_config,
                        kwargs,
                        implementation_path=(placement.implementation if placement else None),
                        runtime_name=(placement.runtime if placement else None),
                    ),
                    module_class,
                ),
            )

        def _stop_created_runtime_pools() -> list[Exception]:
            cleanup_errors: list[Exception] = []
            for runtime_name in created_runtime_pools:
                try:
                    self._stop_runtime_pool(runtime_name)
                except Exception as e:
                    cleanup_errors.append(e)
            return cleanup_errors

        def _rollback(
            _outcomes: list[
                tuple[tuple[PythonWorker, ModuleSpec], ModuleProxyProtocol | Exception]
            ],
            successes: list[ModuleProxyProtocol],
            errors: list[Exception],
        ) -> list[ModuleProxyProtocol]:
            cleanup_errors: list[Exception] = []
            for proxy in successes:
                try:
                    self.undeploy(proxy)
                except Exception as e:
                    logger.error("Error rolling back deployed module", exc_info=True)
                    cleanup_errors.append(e)
            cleanup_errors.extend(_stop_created_runtime_pools())
            if cleanup_errors:
                raise ExceptionGroup(
                    "Python worker deployment failed and rollback cleanup also failed",
                    [*errors, *cleanup_errors],
                )
            raise ExceptionGroup("Python worker deployment failed", errors)

        try:
            # Pre-assign workers sequentially (so least-loaded accounting is
            # correct), then deploy concurrently via threads. The per-worker lock
            # serializes deploys that land on the same worker process.
            # Process dedicated specs first so they claim empty workers before
            # non-dedicated specs land on them; preserve input order in output.
            order = sorted(range(len(specs)), key=lambda i: not specs[i][0].dedicated_worker)
            for i in order:
                module_class, _, kwargs = specs[i]
                placement = runtime_placements.get(module_class)
                existing_runtime_names = set(self._runtime_workers)
                workers, launcher = self._pool_for(placement)
                if placement is not None and placement.runtime not in existing_runtime_names:
                    created_runtime_pools.add(placement.runtime)
                self._ensure_capacity_for_dedicated(
                    [specs[i]],
                    workers,
                    launcher,
                )
                worker = self._select_worker(
                    workers, launcher, dedicated=module_class.dedicated_worker
                )
                worker.reserve_slot()
                kwargs.update(blueprint_args.get(module_class.name, {}))
                workers_by_index[i] = worker

            assignments = [(workers_by_index[i], specs[i]) for i in range(len(specs))]
            deployed_modules = safe_thread_map(assignments, _deploy, on_errors=_rollback)
        except Exception as error:
            if not created_runtime_pools:
                raise
            cleanup_errors = _stop_created_runtime_pools()
            if cleanup_errors:
                raise ExceptionGroup(
                    "Python worker deployment failed and rollback cleanup also failed",
                    [error, *cleanup_errors],
                ) from error
            raise
        for (module_class, _, _), _proxy in zip(specs, deployed_modules, strict=True):
            placement = runtime_placements.get(module_class)
            if placement is not None:
                self._runtime_placements_by_module[module_class] = placement
        return deployed_modules

    def health_check(self) -> bool:
        workers = self.workers
        if len(workers) == 0:
            logger.error("health_check: no workers found")
            return False
        for w in workers:
            if w.pid is None:
                logger.error("health_check: worker died", worker_id=w.worker_id)
                return False
        return True

    def suppress_console(self) -> None:
        for worker in self.workers:
            worker.suppress_console()

    @property
    def workers(self) -> list[PythonWorker]:
        workers = list(self._workers)
        for runtime_workers in self._runtime_workers.values():
            workers.extend(runtime_workers)
        return workers

    def stop(self) -> None:
        if self._closed:
            return
        self._closed = True

        if self._stats_monitor is not None:
            self._stats_monitor.stop()
            self._stats_monitor = None

        logger.info("Shutting down all workers...")

        for worker in reversed(self.workers):
            try:
                worker.shutdown()
            except Exception as e:
                logger.error(f"Error shutting down worker: {e}", exc_info=True)

        self._workers.clear()
        self._runtime_workers.clear()
        self._runtime_launchers.clear()

        logger.info("All workers shut down")

    def _select_worker(
        self,
        workers: list[PythonWorker],
        launcher: WorkerLauncher | None,
        dedicated: bool = False,
    ) -> PythonWorker:
        """Pick a worker for a new module and mark it dedicated if needed."""
        if dedicated:
            for w in workers:
                if not w.dedicated and w.module_count == 0:
                    w.dedicated = True
                    return w
            self._add_workers_to_pool(workers, launcher, 1)
            w = workers[-1]
            w.dedicated = True
            return w

        candidates = [w for w in workers if not w.dedicated]
        if not candidates:
            self._add_workers_to_pool(workers, launcher, 1)
            return workers[-1]
        return min(candidates, key=lambda w: w.module_count)

    def _ensure_capacity_for_dedicated(
        self,
        specs: Iterable[ModuleSpec],
        workers: list[PythonWorker],
        launcher: WorkerLauncher | None,
    ) -> None:
        """Grow the pool so non-dedicated workers >= dedicated workers.

        If the total number of dedicated modules (already deployed + about to be)
        exceeds half the worker pool, scale up to `2 * total_dedicated` workers.
        """
        new_dedicated = sum(1 for spec in specs if spec[0].dedicated_worker)
        already_dedicated = sum(1 for w in workers if w.dedicated)
        total_dedicated = already_dedicated + new_dedicated
        if total_dedicated == 0:
            return
        total_workers = len(workers)
        if total_dedicated * 2 > total_workers:
            n_to_add = total_dedicated * 2 - total_workers
            logger.warning(
                "Auto-scaling worker pool for dedicated modules.",
                dedicated=total_dedicated,
                before=total_workers,
                added=n_to_add,
            )
            self._add_workers_to_pool(workers, launcher, n_to_add)

    def _pool_for(
        self,
        runtime_placement: RuntimePlacement | None,
    ) -> tuple[list[PythonWorker], WorkerLauncher | None]:
        if runtime_placement is None:
            return self._workers, self._worker_launcher
        runtime_name = runtime_placement.runtime
        if runtime_name not in self._runtime_workers:
            runtime = self._runtime_environment_registry.resolve(runtime_name)
            if not isinstance(runtime, PythonProjectRuntimeEnvironment):
                raise ValueError(
                    f"Runtime environment {runtime.name!r} must be a Python Runtime Project"
                )
            launcher = CommandWorkerLauncher(runtime.resolve_python_project())
            self._runtime_launchers[runtime_name] = launcher
            self._runtime_workers[runtime_name] = []
            if self._started:
                self._add_workers_to_pool(
                    self._runtime_workers[runtime_name],
                    launcher,
                    max(1, self._n_workers),
                )
        return self._runtime_workers[runtime_name], self._runtime_launchers[runtime_name]

    def _add_workers_to_pool(
        self,
        workers: list[PythonWorker],
        launcher: WorkerLauncher | None,
        n: int,
    ) -> None:
        for _ in range(n):
            worker = PythonWorker(launcher)
            worker.start_process()
            workers.append(worker)

    def _all_worker_pools(self) -> list[list[PythonWorker]]:
        return [self._workers, *self._runtime_workers.values()]

    def _remove_worker_from_pool(self, worker: PythonWorker) -> bool:
        for workers in self._all_worker_pools():
            if worker in workers:
                workers.remove(worker)
                return workers is self._workers
        return False

    def _stop_runtime_pool(self, runtime_name: str) -> None:
        workers = self._runtime_workers.pop(runtime_name, [])
        self._runtime_launchers.pop(runtime_name, None)
        for worker in reversed(workers):
            worker.shutdown()
