## 1. Deployment contracts and planning

- [x] 1.1 Replace the current `DeploymentSpec.external` shortcut with proposal-shaped `modules: dict[type[ModuleBase], ModuleDeployment]` policy while preserving normal Python module defaults.
- [x] 1.2 Add or update `ModuleDeployment` model fields for local v1 policy: execution target, build target placeholder, preparation placeholder, and runtime-environment placeholder.
- [x] 1.3 Move implementation identity onto `ExternalModule.implementation` and remove class-level deployment metadata mutation from deployment spec initialization.
- [x] 1.4 Implement immutable resolved plan data that carries route, package discovery result, target, runtime identity, module IDs, and launch intent without mutating declaration classes.
- [x] 1.5 Make plain `ModuleCoordinator.build(blueprint)` fail clearly when the active blueprint graph contains an `ExternalModule` declaration.
- [x] 1.6 Make `ModuleCoordinator.build_deployment(DeploymentSpec(...))` route external modules using resolved plan data, including default local policy when an external module is omitted from `DeploymentSpec.modules`.
- [x] 1.7 Reject duplicate active instances of the same external declaration class during planning with an explicit unsupported-in-v1 error.
- [x] 1.8 Add or update tests for invalid deployment references, plain blueprint rejection, default external local policy, normal module defaults, no class mutation, mixed planning, and duplicate external declaration rejection.

## 2. Convention discovery and example import shape

- [x] 2.1 Implement convention discovery from the external declaration class file to exactly one supported sibling implementation directory.
- [x] 2.2 Support `python/pyproject.toml` as the local packaged-Python convention and optional `python/pixi.toml` as the Pixi-backed uv selection.
- [x] 2.3 Detect `rust/Cargo.toml` and `cpp/CMakeLists.txt` as known future conventions and fail with a native-not-implemented error in this PR.
- [x] 2.4 Fail clearly when zero or multiple implementation conventions are found.
- [x] 2.5 Fail clearly when a Python implementation convention is found but the declaration has no string `implementation` reference.
- [x] 2.6 Rename the example from `examples/external-python-module/` to `examples/external_python_module/` and update imports, docs, tests, and launcher commands so repo-root usage requires no `PYTHONPATH` override.
- [x] 2.7 Add or update tests for uv-only discovery, Pixi discovery, missing convention, multiple convention ambiguity, native convention rejection, missing implementation reference, and example import resolution.

## 3. Target session and preparation phase

- [x] 3.1 Add a minimal local `TargetSession` abstraction for v1 target-side command execution and worker bootstrap shape.
- [x] 3.2 Move package preparation command execution behind the local target session.
- [x] 3.3 Ensure `plan` performs no filesystem mutation and starts no workers or runtimes.
- [x] 3.4 Ensure `prepare` runs required package preparation through the target session and does not start `ExternalWorker` or runtime handles.
- [x] 3.5 Preserve uv-only preparation with `uv sync` and Pixi-backed preparation with `pixi run uv sync`.
- [x] 3.6 Add or update tests proving prepare uses the target session, prepare does not start workers, missing files/tools fail before runtime launch, and launcher `prepare` remains idempotent enough for local v1.

## 4. External worker process and client

- [x] 4.1 Add a target-side `ExternalWorker` process for local v1, started with DimOS forkserver multiprocessing practice rather than direct runtime subprocess launch from `WorkerManagerExternal`.
- [x] 4.2 Add an `ExternalWorkerClient` request/response control handle with JSON-serializable request payload shapes.
- [x] 4.3 Implement minimum v1 worker requests: `launch_runtime`, `stop_runtime`, `status` or `health`, and `shutdown`.
- [x] 4.4 Move packaged-Python runtime subprocess spawning, readiness wait ownership, process stop, and startup output capture into `ExternalWorker`.
- [x] 4.5 Keep `WorkerManagerExternal` responsible for target sessions, external worker clients, launch requests, returned coordinator-side declared RPC proxies, health aggregation, rollback, and shutdown.
- [x] 4.6 Integrate external worker lifecycle logs with existing DimOS logging and propagate `DIMOS_RUN_LOG_DIR` to worker/runtime processes.
- [x] 4.7 Add or update tests proving `WorkerManagerExternal` bootstraps an external worker, does not directly spawn runtime entrypoints, delegates launch/stop to the worker, captures startup failure output, and shuts down cleanly.

## 5. Serialized module launch envelope and runtime entrypoint

- [x] 5.1 Replace pickled live-class launch envelopes with serialized `ModuleLaunchEnvelope` data.
- [x] 5.2 Include at least module ID, module/rpc name, declaration import reference, implementation import reference, package/runtime paths, config payload, stream bindings where available, and readiness settings.
- [x] 5.3 Update the packaged-Python runtime entrypoint to read the serialized envelope, import declaration and implementation classes, verify `issubclass(implementation, declaration)`, instantiate the runtime module, and serve declared RPC handlers.
- [x] 5.4 Ensure runtime launch command selection remains `uv run python ...` for uv-only and `pixi run uv run python ...` for Pixi-backed projects.
- [x] 5.5 Ensure no live Python class objects, live module instances, callables, or pickled refs cross the external boundary.
- [x] 5.6 Add or update tests for envelope serialization, subclass validation failure, readiness success, readiness timeout failure with output context, and declared RPC success.

## 6. Coordinator integration and declared surface behavior

- [x] 6.1 Preserve existing normal Python blueprint deployment behavior for blueprints that do not use deployment specs or external modules.
- [x] 6.2 Wire mixed deployments so normal Python modules use `WorkerManagerPython` and external declarations use `WorkerManagerExternal -> ExternalWorker` under the same `ModuleCoordinator` lifecycle.
- [x] 6.3 Preserve coordinator-managed stream setup, declared module refs, lifecycle calls, and declared RPC access across the mixed deployment.
- [x] 6.4 Ensure external proxies expose declared RPC methods through the existing RPC backend and reject undeclared Python object access.
- [x] 6.5 Add or update end-to-end local tests containing at least one normal Python module and one local packaged-Python external module.
- [x] 6.6 Add regression tests proving existing normal Python module deployment still works without requiring the external path.

## 7. Temporary launcher and example package

- [x] 7.1 Update the temporary launcher `plan`, `prepare`, and `run` commands for the new resolved plan, target session, and external worker topology.
- [x] 7.2 Ensure `plan` prints or returns the deployment plan without staging, preparing, bootstrapping workers, or launching runtime processes.
- [x] 7.3 Ensure `prepare` stages/checks local packaged-Python projects without launching external workers or runtime processes.
- [x] 7.4 Ensure `run` performs plan, idempotent prepare, external worker bootstrap, runtime launch, readiness, coordinator wiring, and lifecycle for the end-to-end proof.
- [x] 7.5 Update the example package to show the declaration/runtime split, `ExternalModule.implementation`, local `python/` package layout, deployment spec module-level variable, external worker topology, and temporary launcher usage.
- [x] 7.6 Ensure the example package demonstrates declared RPC behavior with a visible result returned from the external runtime implementation.
- [x] 7.7 Ensure the example package demonstrates declared RPC behavior and points to focused tests/docs for other declared surfaces such as streams, lifecycle, config metadata, skills, and module refs.
- [x] 7.8 Add automated coverage or a smoke test that runs the example package through the same plan, prepare, run, readiness, external worker, and declared RPC path expected of user packages.

## 8. Documentation

- [x] 8.1 Update `docs/usage/modules.md` or a nearby user-facing guide with the external packaged-Python module concept and supported declared surface area.
- [x] 8.2 Update the focused authoring guide for local packaged-Python external modules, including declaration/runtime split, `implementation`, convention discovery, supported project layouts, `DeploymentSpec.modules`, and temporary launcher usage.
- [x] 8.3 Link to `examples/external_python_module/` as the canonical runnable reference for declared RPCs and other supported external module behavior.
- [x] 8.4 Update contributor docs for target-session preparation, external worker topology, temporary launcher behavior, testing expectations, example-package manual QA, startup timeout debugging, and log locations.
- [x] 8.5 Update coding-agent docs or `AGENTS.md` only if new reusable conventions are introduced during implementation.

## 9. Verification

- [x] 9.1 Run `openspec validate external-python-module-deployment --type change --strict --no-interactive`.
- [x] 9.2 Run focused pytest targets for deployment planning, convention discovery, target-session prepare, external worker launch, serialized envelopes, external proxy behavior, coordinator routing, readiness timeout, and the end-to-end local packaged module.
- [x] 9.3 Run existing focused tests for normal Python module deployment and coordinator lifecycle behavior.
- [x] 9.4 Run `uv run mypy dimos/` or a narrower agreed type-check target if full mypy is too slow for the implementation iteration.
- [x] 9.5 Run docs link/snippet validation for changed documentation if the repo docs tooling is available.
- [x] 9.6 Manually QA the temporary launcher through `plan`, `prepare`, and `run` against `examples/external_python_module/` from the repository root without `PYTHONPATH`.
- [x] 9.7 Manually call the example package's declared RPC and confirm the visible result is produced by the external runtime implementation.
- [x] 9.8 If implementation adds or renames registered blueprints, run `pytest dimos/robot/test_all_blueprints_generation.py`; otherwise confirm no generated blueprint registry update is needed.
