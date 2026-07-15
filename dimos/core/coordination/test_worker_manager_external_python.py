from __future__ import annotations

from unittest.mock import Mock

from dimos.core.coordination import worker_manager_external_python as external_manager
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.external_python_module import ExternalPythonModule
from dimos.core.global_config import global_config


class _ExternalDeclaration(ExternalPythonModule):
    implementation = "test_runtime.module.Runtime"


def test_coordinator_registers_mixed_managers() -> None:
    coordinator = ModuleCoordinator(global_config)

    assert set(coordinator._managers) == {"python", "external-python"}
    assert coordinator._managers["external-python"].health_check()
    assert coordinator._managers["python"].health_check()


def test_coordinator_keeps_blueprint_override_kwargs_for_restart() -> None:
    coordinator = ModuleCoordinator(global_config)
    manager = Mock()
    manager.deploy_parallel.return_value = [Mock()]
    coordinator._managers = {"external-python": manager}

    coordinator.deploy_parallel(
        [(_ExternalDeclaration, global_config, {"declared": "value"})],
        {_ExternalDeclaration.name: {"override": "value"}},
    )

    assert coordinator._deployed_kwargs[_ExternalDeclaration] == {
        "declared": "value",
        "override": "value",
    }


def test_external_manager_dispatches_and_undeploys(monkeypatch) -> None:
    worker = Mock()
    worker.pid = 123
    proxy = Mock()
    monkeypatch.setattr(external_manager, "ExternalPythonWorker", Mock(return_value=worker))
    monkeypatch.setattr(external_manager.RPCClient, "remote", Mock(return_value=proxy))

    manager = external_manager.WorkerManagerExternalPython(global_config)
    deployed = manager.deploy(_ExternalDeclaration, global_config, {})

    assert deployed is proxy
    worker.start.assert_called_once()
    assert manager.health_check()
    manager.undeploy(proxy)
    worker.stop.assert_called_once()
    assert manager.health_check()


def test_external_manager_deploy_fresh_uses_a_new_worker(monkeypatch) -> None:
    workers = [Mock(pid=1), Mock(pid=2)]
    proxies = [Mock(), Mock()]
    monkeypatch.setattr(
        external_manager,
        "ExternalPythonWorker",
        Mock(side_effect=workers),
    )
    monkeypatch.setattr(external_manager.RPCClient, "remote", Mock(side_effect=proxies))

    manager = external_manager.WorkerManagerExternalPython(global_config)
    manager.deploy(_ExternalDeclaration, global_config, {})
    manager.deploy_fresh(_ExternalDeclaration, global_config, {})

    assert workers[0].start.call_count == 1
    assert workers[1].start.call_count == 1
    manager.stop()
    workers[0].stop.assert_called_once()
    workers[1].stop.assert_called_once()


def test_external_manager_reports_failed_worker_diagnostics(monkeypatch) -> None:
    worker = Mock(pid=None, declaration=_ExternalDeclaration)
    worker.diagnostics.return_value = "x" * 10000
    proxy = Mock()
    monkeypatch.setattr(external_manager, "ExternalPythonWorker", Mock(return_value=worker))
    monkeypatch.setattr(external_manager.RPCClient, "remote", Mock(return_value=proxy))

    manager = external_manager.WorkerManagerExternalPython(global_config)
    manager.deploy(_ExternalDeclaration, global_config, {})

    assert not manager.health_check()
    worker.diagnostics.assert_called_once()
