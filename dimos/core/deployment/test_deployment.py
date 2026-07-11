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
from pathlib import Path
import shutil
import subprocess

import pytest

from dimos.core.coordination.blueprints import Blueprint, autoconnect
from dimos.core.coordination.external_worker import ExternalWorkerClient
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.coordination.worker_manager_external import WorkerManagerExternal
from dimos.core.core import rpc
from dimos.core.deployment.models import (
    DeploymentSpec,
    ExternalModule,
    JsonValue,
    ModuleDeployment,
    PrepareResult,
)
from dimos.core.deployment.planner import (
    launch_command_for_package,
    plan_deployment,
)
from dimos.core.deployment.ref import resolve_deployment_ref
from dimos.core.deployment.target_session import LocalTargetSession
from dimos.core.global_config import global_config
from dimos.core.module import Module
from dimos.core.rpc_client import RPCClient


class NormalTestModule(Module):
    pass


class ExternalTestDeclaration(ExternalModule):
    implementation = "x:Y"

    @rpc
    def ping(self) -> str: ...


deployment_spec_for_test = DeploymentSpec(ExternalTestDeclaration.blueprint())


def _patch_declaration_file(
    monkeypatch: pytest.MonkeyPatch, declaration: type[ExternalModule], package: Path
) -> None:
    declaration_file = package / "declaration.py"
    declaration_file.write_text("# declaration anchor\n")
    monkeypatch.setattr(
        "dimos.core.deployment.planner.inspect.getfile",
        lambda cls: str(declaration_file) if cls is declaration else str(declaration_file),
    )


def _python_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    declaration: type[ExternalModule] = ExternalTestDeclaration,
    *,
    with_pixi: bool = False,
) -> Path:
    package = tmp_path / "pkg"
    python_dir = package / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    (python_dir / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    if with_pixi:
        (python_dir / "pixi.toml").write_text("[project]\nname='x'\nchannels=[]\nplatforms=[]\n")
    _patch_declaration_file(monkeypatch, declaration, package)
    return package


def test_resolve_example_deployment_ref() -> None:
    spec = resolve_deployment_ref("dimos.core.deployment.test_deployment:deployment_spec_for_test")
    assert isinstance(spec, DeploymentSpec)


def test_invalid_deployment_ref_rejected() -> None:
    with pytest.raises(ValueError, match="module-level DeploymentSpec"):
        resolve_deployment_ref("dimos.core.deployment.test_deployment:NormalTestModule")


def test_mixed_planning_does_not_mutate_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _python_package(monkeypatch, tmp_path)
    before = sorted(package.rglob("*"))
    spec = DeploymentSpec(
        autoconnect(NormalTestModule.blueprint(), ExternalTestDeclaration.blueprint()),
    )
    plan = plan_deployment(spec)
    after = sorted(package.rglob("*"))
    assert plan.python_modules == (NormalTestModule,)
    assert [env.module_class for env in plan.external_modules] == [ExternalTestDeclaration]
    assert plan.external_modules[0].policy == ModuleDeployment()
    assert before == after
    assert not hasattr(ExternalTestDeclaration, "__external_metadata__")


def test_plain_blueprint_with_external_module_fails() -> None:
    with pytest.raises(ValueError, match="External modules require"):
        ModuleCoordinator.build(ExternalTestDeclaration.blueprint())


def test_duplicate_external_declaration_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _python_package(monkeypatch, tmp_path)
    atom = ExternalTestDeclaration.blueprint().blueprints[0]
    spec = DeploymentSpec(Blueprint(blueprints=(atom, atom)))
    with pytest.raises(ValueError, match="Duplicate external declaration"):
        plan_deployment(spec)


def test_convention_discovery_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    _patch_declaration_file(monkeypatch, ExternalTestDeclaration, package)
    with pytest.raises(FileNotFoundError, match="No supported implementation convention"):
        plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint()))

    (package / "rust").mkdir()
    (package / "rust" / "Cargo.toml").write_text("[package]\nname='x'\n")
    with pytest.raises(NotImplementedError, match="not implemented"):
        plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint()))

    (package / "python").mkdir()
    (package / "python" / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    with pytest.raises(ValueError, match="Multiple implementation conventions"):
        plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint()))


def test_missing_python_implementation_ref_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class MissingImplementationDeclaration(ExternalModule):
        pass

    _python_package(monkeypatch, tmp_path, MissingImplementationDeclaration)
    with pytest.raises(ValueError, match="must declare implementation"):
        plan_deployment(DeploymentSpec(MissingImplementationDeclaration.blueprint()))


def test_prepare_command_selection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sync_commands: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...], *, cwd: Path, check: bool, text: bool
    ) -> subprocess.CompletedProcess[str]:
        assert check is True
        assert text is True
        sync_commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    _python_package(monkeypatch, tmp_path)
    monkeypatch.setattr("dimos.core.deployment.target_session.subprocess.run", fake_run)
    module = plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint())).external_modules[
        0
    ]
    session = LocalTargetSession()
    assert session.prepare_package(module).command_prefix == ("uv", "run", "python")
    assert sync_commands[-1] == ("uv", "sync")

    _python_package(monkeypatch, tmp_path, with_pixi=True)
    module = plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint())).external_modules[
        0
    ]
    assert session.prepare_package(module).command_prefix == ("pixi", "run", "uv", "run", "python")
    assert sync_commands[-1] == ("pixi", "run", "uv", "sync")
    assert launch_command_for_package(module) == ("pixi", "run", "uv", "run", "python")


def test_external_proxy_declared_rpc_and_undeclared_attr() -> None:
    proxy = RPCClient.remote(ExternalTestDeclaration)
    try:
        assert callable(proxy.ping)
        with pytest.raises(AttributeError, match="non-@rpc attribute access"):
            attr_name = "not_declared"
            getattr(proxy, attr_name)
    finally:
        proxy.stop_rpc_client()


def test_worker_manager_external_delegates_launch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeClient(ExternalWorkerClient):
        def __init__(self) -> None:
            self.launched: list[str] = []

        def launch_runtime(
            self,
            envelope: object,
            command_prefix: tuple[str, ...],
            environment: dict[str, str],
        ) -> None:
            self.launched.append(command_prefix[0])

        def status(self) -> dict[str, JsonValue]:
            module_ids: list[JsonValue] = [item for item in self.launched]
            return {"module_ids": module_ids}

        def stop_runtime(self, module_id: str) -> None:
            return None

        def shutdown(self) -> None:
            return None

    _python_package(monkeypatch, tmp_path)
    plan = plan_deployment(DeploymentSpec(ExternalTestDeclaration.blueprint()))
    module = plan.external_modules[0]
    manager = WorkerManagerExternal(global_config)
    manager.configure_plan(plan)
    manager._client = FakeClient()  # direct injection keeps this unit test in-process
    monkeypatch.setattr(
        manager._session,
        "prepare_package",
        lambda prepared_module: PrepareResult(
            module=prepared_module, command_prefix=("uv", "run", "python")
        ),
    )
    proxies = manager.deploy_parallel(
        [(ExternalTestDeclaration, global_config, dict(module.kwargs))], {}
    )
    try:
        assert len(proxies) == 1
        assert manager.health_check()
    finally:
        for proxy in proxies:
            proxy.stop_rpc_client()
        manager.stop()


def test_mixed_normal_and_external_example_e2e() -> None:
    if shutil.which("uv") is None:
        pytest.skip("uv is required for packaged external module smoke test")
    if shutil.which("pixi") is None:
        pytest.skip("pixi is required for the packaged external module example")
    import examples.external_python_module.deployment as deployment_module

    example_root = Path(__file__).parents[3] / "examples" / "external_python_module"
    coordinator = ModuleCoordinator.build_deployment(deployment_module.deployment_spec)
    try:
        external = coordinator.get_instance(deployment_module.ExampleExternalDeclaration)
        client = coordinator.get_instance(deployment_module.ExampleClient)
        assert external.greet("qa") == "hi, qa from external runtime"
        assert external.greet_with_helper("qa") == "hi, qa from external runtime; helper saw qa"
        assert (
            client.call_external_dependency("qa")
            == "external-only humanize formatted 1,234,567 for qa"
        )
        assert (
            client.roundtrip_stream("stream-qa")
            == "external-only humanize formatted 1,234,567 for stream-qa"
        )
    finally:
        coordinator.stop()
        shutil.rmtree(example_root / "python" / ".venv", ignore_errors=True)
        shutil.rmtree(example_root / "python" / ".pixi", ignore_errors=True)
        for generated in (
            example_root / "python" / "uv.lock",
            example_root / "python" / "pixi.lock",
        ):
            generated.unlink(missing_ok=True)
        for pycache in example_root.rglob("__pycache__"):
            shutil.rmtree(pycache, ignore_errors=True)
