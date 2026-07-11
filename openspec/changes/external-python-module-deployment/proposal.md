## Why

DimOS modules currently assume that Python implementations can be imported and run inside the coordinator-managed Python worker pool. That blocks modules whose runtime dependencies should remain outside the main DimOS environment, and it leaves the broader module-deployment proposal without a runnable proof of its intended manager/worker structure.

This change introduces the first real external deployment path: local packaged-Python modules that keep a coordinator-visible `ExternalModule` contract while their implementation runs outside the coordinator Python environment. The PR's acceptance bar is structural, not only dependency isolation: packaged Python must use the same `WorkerManagerExternal -> ExternalWorker -> runtime handle` topology intended for later native and remote deployment work.

## What Changes

- Add a coordinator-visible `ExternalModule` declaration model for module shape: streams, config metadata, declared RPCs, declared skills, declared module refs, and a module-owned implementation reference.
- Add `DeploymentSpec` planning for blueprints that can contain both normal Python modules and local packaged-Python external modules.
- Replace class-level external metadata mutation with resolved deployment planning. A plain blueprint that contains an `ExternalModule` must fail clearly; a `DeploymentSpec` supplies the deployment context.
- Route normal Python modules through the existing `WorkerManagerPython` path and local packaged-Python external modules through `WorkerManagerExternal`, a target session, an `ExternalWorker` process, and a thin packaged-Python runtime entrypoint.
- Add explicit internal `plan`, `prepare`, and `run` phases. `prepare` uses target-session commands and must not start an `ExternalWorker` or module runtime. The temporary `run` command remains a convenience `plan + prepare + launch` path until prepared-plan persistence exists.
- Add a temporary integration launcher for resolving deployment references and exercising `plan`, `prepare`, and `run` without introducing a public DimOS CLI registry yet.
- Add an example package under `examples/external_python_module/` that is importable from the repository root without `PYTHONPATH` and demonstrates the external packaged-Python pattern end-to-end.
- Discover packaged-Python implementation layout by convention from the `ExternalModule` declaration class file. V1 supports exactly one sibling `python/pyproject.toml` implementation directory, optionally with `python/pixi.toml`.
- Replace pickled live-class launch envelopes with JSON-serializable module launch envelopes that carry module identity, import references, prepared package paths, stream bindings, config payloads, and readiness settings.
- Preserve declared RPC behavior by using the existing LCM/Zenoh RPC transport directly between the coordinator-side proxy and the real module runtime process. `ExternalWorker` is not a per-call RPC forwarder.
- Do not support arbitrary Python object passthrough, live instance identity, pickle-based refs, duplicate external declaration instances, remote SSH execution, native module execution, prepared-plan registries, public deploy CLI integration, or generic environment plugins in this change.

## Affected DimOS Surfaces

- Modules/streams: `ExternalModule` declarations, module implementation references, module deployment metadata, stream shape discovery, lifecycle RPC calls, declared skills/RPCs, and declared module refs.
- Coordination: `ModuleCoordinator` routing, a shared coordinator-facing worker-manager surface, `WorkerManagerExternal`, local target-session preparation, `ExternalWorkerClient`, and target-side `ExternalWorker` lifecycle.
- Deployment internals: plan/prepare/run models, convention discovery, serialized `ModuleLaunchEnvelope`, readiness waits, runtime handle IDs, duplicate-instance rejection, and local packaged-Python command selection.
- Blueprints/CLI: Deployment through `ModuleCoordinator.build_deployment(...)`; a temporary deployment launcher for import references such as `examples.external_python_module.deployment:deployment_spec`. No public `dimos deploy`, prepared-plan registry, or `dimos run <deployment>` CLI yet.
- Skills/MCP: Declared `@skill` metadata for external modules should remain discoverable through the declared module shape and runtime `Module` implementation.
- Hardware/simulation/replay: No direct hardware, simulation, or replay behavior change. The first proof should be safe for local test modules only.
- Docs/generated registries: New developer documentation and an `examples/` package for external packaged-Python module declarations, runtime implementation, declared RPCs, and the temporary launcher. No generated blueprint registry change is required for this first PR.

## Capabilities

### New Capabilities

- `external-module-deployment`: Defines how DimOS plans, prepares, launches, wires, and controls local packaged-Python external modules through the coordinator while preserving the proposed external worker topology.

### Modified Capabilities

None.

## Impact

Developers will be able to prove a packaged Python module can run outside the main DimOS Python environment while still participating in normal coordinator-managed lifecycle, stream wiring, and declared RPC calls. The included example package should become the concrete manual QA surface and reference implementation for module authors. The compatibility risk is mostly around preserving existing normal Python module deployment behavior while adding a second manager path and rejecting unsupported plain-blueprint `ExternalModule` usage. Dependency scope is intentionally narrow: `uv` is required for packaged Python projects and Pixi is supported only when `python/pixi.toml` exists. Test coverage should include planning validation, convention discovery, local prepare/run behavior, coordinator routing, target-session behavior, external worker lifecycle, JSON-serializable launch envelopes, duplicate-instance rejection, readiness timeout behavior, declared RPC calls over the existing RPC backend, and the example package path.
