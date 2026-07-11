## Context

DimOS currently deploys normal Python modules through `ModuleCoordinator` and `WorkerManagerPython`. The coordinator deploys module classes into forkserver worker processes, creates coordinator-side proxies, wires streams/module refs, and calls lifecycle RPCs. Runtime declared RPC calls already use the selected LCM/Zenoh RPC backend: the proxy calls `<ModuleName>/<method>`, and the module instance serves its declared RPC handlers in the worker process.

The broader module-deployment proposal needs a local packaged-Python proof that validates the intended structure. The first runnable proof must therefore preserve the manager/worker split used for future remote and native deployment, even though the only implemented execution target in this PR is local packaged Python.

Relevant current surfaces include:

- `dimos/core/coordination/module_coordinator.py` for deployment, stream wiring, lifecycle, and module refs.
- `dimos/core/coordination/worker_manager_python.py` and `python_worker.py` for current normal Python worker behavior.
- `dimos/core/rpc_client.py` and `dimos/protocol/rpc/` for declared RPC proxy behavior.
- `dimos/core/module.py` for runtime `Module` lifecycle, stream declarations, declared RPCs, skills, and module refs.
- `dimos/core/coordination/blueprints.py` for blueprint shape discovery and wiring.

## Goals / Non-Goals

**Goals:**

- Provide coordinator-visible external module declarations that describe module shape without importing packaged runtime dependencies.
- Allow a deployment spec to combine normal Python modules and local packaged-Python external modules.
- Route normal Python modules to `WorkerManagerPython` and packaged-Python external modules to `WorkerManagerExternal -> ExternalWorker -> thin Python entrypoint` through the real `ModuleCoordinator` deployment flow.
- Introduce a minimal local `TargetSession` so `prepare` can execute target-side commands without starting workers.
- Implement internal `plan`, `prepare`, and `run` phases for local packaged-Python deployment.
- Provide a temporary launcher for `plan`, `prepare`, and `run` using a Python import reference to a module-level deployment spec variable.
- Provide an example package under `examples/external_python_module/` that demonstrates the external packaged-Python module pattern end-to-end, including declared RPC behavior and repository-root importability without `PYTHONPATH`.
- Launch packaged-Python modules from `python/pyproject.toml` projects with `uv`, and from `python/pyproject.toml` plus `python/pixi.toml` projects with `pixi run uv run`.
- Preserve normal declared RPC semantics by using existing LCM/Zenoh RPC transport directly between coordinator proxy and external runtime module.
- Use current RPC responsiveness as the initial readiness check.
- Use JSON-serializable worker-control requests and module launch envelopes. No live class objects or live module objects may cross the external boundary.

**Non-Goals:**

- No public `dimos deploy` CLI, deployment registry, prepared-plan registry, manifest registry, or `dimos run <deployment>` integration.
- No remote SSH target support.
- No native Rust/C++ prepare/build/run support.
- No migration of existing `NativeModule` wrappers.
- No Poetry, Hatch, Conda-without-Pixi, Nix, Docker, or generic environment plugin support.
- No strict lockfile enforcement for `uv.lock` or `pixi.lock`.
- No arbitrary Python object passthrough, raw `getattr`, live object identity, pickle-based refs, or PythonWorker Actor behavior across the external boundary.
- No duplicate active instances of the same external declaration class in one deployment graph.
- No separate persistent target agent or reconnection lease protocol in the first PR.

## DimOS Architecture

The external path should preserve the current separation between deployment control-plane management and runtime data/RPC transports.

```text
DeploymentSpec reference
        │
        ▼
temporary launcher ── plan / prepare / run ──▶ ModuleCoordinator
                                                   │
                             ┌─────────────────────┴─────────────────────┐
                             ▼                                           ▼
                    WorkerManagerPython                         WorkerManagerExternal
                    normal Python modules                       external declarations
                             │                                           │
                             ▼                                           ▼
                    PythonWorker process                         TargetSession
                    real Module instance                         prepare commands
                                                                         │
                                                                         ▼
                                                                ExternalWorker process
                                                                packaged runtime handles
                                                                         │
                                                                         ▼
                                                                thin Python entrypoint
                                                                real Module instance
```

The local v1 execution target is the coordinator machine, but it must still use the target-session and external-worker boundaries. Direct `WorkerManagerExternal -> subprocess.Popen(runtime entrypoint)` is not acceptable for this PR because it proves only dependency isolation, not the intended deployment structure.

### External declarations and runtime implementation

The coordinator imports only the lightweight external declaration. The declaration is a public developer contract and includes the module-owned implementation identity:

```python
class ExampleExternalDeclaration(ExternalModule):
    implementation = "example_external.runtime:ExampleExternalRuntime"

    requests: In[str]
    replies: Out[str]
```

The packaged runtime imports the real implementation from the prepared Python environment. The implementation subclasses the declaration and the runtime `Module` so it can reuse existing `Module.__init__()`, stream setup, lifecycle methods, `serve_module_rpc(...)`, `@rpc`, and `@skill` behavior.

```text
Coordinator-visible declaration:
  shape only: streams, config metadata, declared RPCs, declared skills, declared refs, implementation ref

External packaged implementation:
  declaration + real Module runtime
  starts the normal RPC backend and serves declared RPC handlers
```

### Deployment specs and routing

`DeploymentSpec` should contain the blueprint/module graph plus class-keyed deployment policy:

```python
DeploymentSpec(
    blueprint=example_blueprint,
    modules={
        ExampleExternalDeclaration: ModuleDeployment(),
    },
)
```

The first implementation should support the proposal-shaped `modules: dict[type[ModuleBase], ModuleDeployment]` API. For external modules inside a `DeploymentSpec`, omitted module policy defaults to local `ModuleDeployment()`. For normal Python modules, omitted policy keeps the existing Python worker route. For a plain blueprint without `DeploymentSpec`, any active `ExternalModule` declaration must fail clearly because there is no deployment context.

Planning must not mutate declaration classes with deployment metadata. The resolved plan carries the route, package discovery result, target, runtime identity, and launch intent.

The combined PR should prove mixed routing through the actual `ModuleCoordinator` path. A standalone demo that manually constructs launch envelopes or directly drives `WorkerManagerExternal` is not sufficient.

### Plan, prepare, run

Internal phases should exist now even though the temporary launcher is the only user-facing entrypoint:

- `plan`: resolve the import reference, validate declarations, discover package conventions, classify routes, reject duplicates, and print/return the plan without mutating the filesystem.
- `prepare`: use `TargetSession` to perform local package preparation/staging for external modules without launching `ExternalWorker` or module runtimes.
- `run`: temporary convenience mode that performs plan, idempotent prepare, external-worker bootstrap, runtime launch, readiness wait, coordinator wiring, and lifecycle until a prepared-plan registry exists.

The launcher reference syntax should match existing DimOS registry conventions for blueprint objects: `module.path:variable_name`. The resolved object must be a `DeploymentSpec` instance, not a class, subclass, factory, or arbitrary callable.

### Package discovery convention

The `ExternalModule` class file anchors package discovery. `ModuleDeployment` configures where that class builds and executes; it does not repeat implementation details.

V1 discovery rule:

1. Start at the `ExternalModule` declaration class file.
2. Walk to the package root that contains the declaration module.
3. Look for exactly one known sibling implementation convention.
4. Support `python/pyproject.toml` now, with optional `python/pixi.toml` selecting Pixi-backed uv launch.
5. Detect `rust/Cargo.toml` and `cpp/CMakeLists.txt` as known future conventions but fail with a not-implemented error in this change.
6. Fail during planning if zero or multiple known implementation conventions match.
7. Fail during planning if a Python implementation directory exists but the declaration lacks a string implementation reference.

The example package should be renamed to `examples/external_python_module/` so commands work from the repository root without `PYTHONPATH`, for example:

```bash
uv run python -m dimos.core.deployment.launcher plan examples.external_python_module.deployment:deployment_spec
```

### Packaged-Python preparation and launch

External packaged Python projects use sibling implementation conventions:

- `python/pyproject.toml` is required for uv-only packaged Python.
- `python/pyproject.toml` and `python/pixi.toml` are required for Pixi + uv packaged Python.

Command selection:

- Prepare uv-only: `uv sync` in the `python/` directory.
- Launch uv-only: `uv run python -m dimos.core.deployment.runtime ...` in the `python/` directory.
- Prepare Pixi + uv: `pixi run uv sync` in the `python/` directory.
- Launch Pixi + uv: `pixi run uv run python -m dimos.core.deployment.runtime ...` in the `python/` directory.

The first PR should keep validation shallow: check for required files, select commands, execute preparation, and fail clearly when required tools or files are missing. It should not require lockfiles or perform deep reproducibility validation.

### WorkerManagerExternal, TargetSession, and ExternalWorker

`WorkerManagerExternal` parallels `WorkerManagerPython` at the coordinator-facing manager boundary. It owns resolved external module routes, target-session handles, `ExternalWorkerClient` handles, rollback, health aggregation, and shutdown. It coordinates pre-worker `prepare` through target sessions and then requests runtime launch through external-worker clients.

`TargetSession` provides coordinator-side access to one target. V1 only needs `LocalTargetSession`, but the API should preserve the remote shape: run commands, ensure directories, copy or stage files if needed, and bootstrap an external worker during run. Prepare uses target sessions and must not start `ExternalWorker`.

`ExternalWorkerClient` is the coordinator-side control handle. Local v1 should follow existing DimOS worker practice by starting the target-side `ExternalWorker` with `multiprocessing.get_context("forkserver")` and an explicit request/response pipe. The request payloads should remain JSON-serializable in shape even if the local transport is a Python pipe.

`ExternalWorker` is the target-side process for one machine and deployment run. It uses the prepared runtime environment, starts packaged-Python runtime handles with `subprocess`, captures startup stdout/stderr tails for failures, waits for readiness, stops handles during rollback/shutdown, and logs lifecycle events through existing DimOS logging configuration. It must not import user implementation code itself; the thin Python entrypoint imports the implementation inside the prepared runtime environment.

Minimum worker-control requests for v1:

- `launch_runtime`: launch one runtime handle from a serialized module launch envelope and wait for readiness.
- `stop_runtime`: stop one runtime handle.
- `status` or `health`: report worker and handle state.
- `shutdown`: stop all handles and exit the worker.

### ModuleLaunchEnvelope

The per-module runtime handle receives one serialized envelope. V1 should not pickle live Python class objects, live modules, or callables. The envelope should be JSON-serializable in meaning and can be passed through a temporary file or another simple local mechanism.

Minimum fields:

- `module_id`: stable resolved module instance ID for this deployment run.
- `module_name` / `rpc_name`: the declaration-visible runtime identity used for lifecycle/readiness RPCs.
- `declaration_ref`: import reference for the coordinator-visible declaration class.
- `implementation_ref`: import reference from `ExternalModule.implementation` for packaged Python.
- `package_root` / `runtime_workdir`: prepared package paths needed by the runtime command.
- `config`: JSON-compatible module config payload, empty if not needed in v1.
- `streams`: resolved stream/topic/transport/type bindings where available.
- `readiness`: method name and timeout settings for side-effect-free responsiveness check.

The runtime entrypoint imports `declaration_ref` and `implementation_ref`, verifies `issubclass(implementation, declaration)`, instantiates the implementation, starts the normal module RPC server, and responds to readiness.

### RPC, lifecycle, skills, and module refs

External RPC should follow the current DimOS declared RPC pattern:

```text
Coordinator proxy -> existing LCM/Zenoh RPC backend -> real Module runtime process
```

`ExternalWorker` must not become a per-call RPC forwarder. It owns process/session lifecycle: runtime launch, readiness wait, stop/restart where supported, teardown, logs, and status. Declared RPC calls go through the same backend as normal Python module RPC calls.

Coordinator-side external proxies should behave like `RPCClient.remote(...)`: declared `@rpc` methods are callable; arbitrary non-declared attributes are not available. V1 should reject duplicate active instances of the same external declaration class because current RPC identity is class-name based and not instance-scoped.

Module refs should be declared and rebindable by contract, not by live object assignment. For this PR, refs should support declared RPC proxy behavior across the coordinator/runtime boundary. Full Python object ref semantics are explicitly out of scope.

### Logging and failure context

External workers and runtime handles should integrate with existing DimOS logging from v1. The local external worker should inherit/pass `DIMOS_RUN_LOG_DIR`, use the repository's logger setup for lifecycle events, and include captured runtime stdout/stderr tails in startup/readiness failures. Console suppression should follow the existing worker pattern: suppress console output when requested without dropping file logs.

### DimOS Spec Protocols and adapter protocols

This change should not introduce Protocols just to satisfy type checking. If an existing DimOS Spec Protocol is needed for a module ref contract, use the real project type directly. Any new adapter interfaces should represent real deployment/runtime boundaries, not analyzer-only abstractions.

### CLI entrypoints and generated registries

The temporary launcher is an integration harness, not a committed public CLI contract equivalent to `dimos run`. It should not require changes to `dimos/robot/all_blueprints.py`. If implementation later adds or renames registered blueprints, regenerate with `pytest dimos/robot/test_all_blueprints_generation.py`, but that is not expected for this scoped change.

## Decisions

1. **The PR proves structure, not only isolation.** Local packaged Python must use `WorkerManagerExternal -> ExternalWorker -> thin Python entrypoint`.

2. **Plain blueprints cannot contain external declarations.** Any graph containing `ExternalModule` requires `DeploymentSpec` so planning can carry deployment context.

3. **Deployment policy uses `modules`, not class mutation.** `DeploymentSpec.modules` contains class-keyed `ModuleDeployment` policy. Omitted external policy defaults to local inside a deployment spec. Declaration classes must not be mutated with deployment metadata.

4. **Implementation identity belongs to `ExternalModule`.** `ExternalModule.implementation` selects the module-owned runtime implementation. `ModuleDeployment` selects execution/build/preparation policy.

5. **Convention discovery is v1's package model.** Discovery starts from the declaration class file and selects exactly one sibling implementation directory.

6. **Prepare does not start workers.** Prepare uses target sessions only. Run bootstraps `ExternalWorker` and launches runtime handles.

7. **Temporary run is convenience.** Until prepared-plan persistence exists, the launcher `run` command may perform plan and idempotent prepare before launch.

8. **Local ExternalWorker follows DimOS worker practice.** V1 uses forkserver multiprocessing and request/response control. The protocol shape remains remote-safe and JSON-serializable.

9. **No pickled live launch envelopes.** Runtime handoff uses a serialized `ModuleLaunchEnvelope` with import references and data, not Python class objects.

10. **Declared RPC parity, not Python object parity.** External modules support normal Module semantics for declared surface area. They do not emulate PythonWorker raw object behavior.

11. **Readiness uses RPC responsiveness.** The external worker launches the process and waits until a side-effect-free lifecycle/readiness RPC endpoint responds. A separate health protocol can come later.

## Safety / Simulation / Replay

This change should be validated with local test modules and should not require robot hardware. It does not change robot motion commands, hardware safety policy, simulation behavior, or replay data handling.

Manual QA should avoid robot-facing blueprints unless the packaged module under test is explicitly non-actuating or simulated. If an external module exposes skills later, those skills must follow the existing DimOS `@skill` safety expectations and system prompt guidance.

## Risks / Trade-offs

- **RPC name collisions:** Current RPC naming is class-name based. V1 rejects duplicate active external declaration class instances and documents instance-scoped names as future work.
- **Coordinator/runtime shape drift:** Declaration and implementation can diverge. Mitigation: validate `issubclass(runtime, declaration)` and declared surface shape at launch or readiness time where practical.
- **Packaging environment variability:** uv and Pixi availability can differ by developer machine. Mitigation: fail early with clear missing-tool/missing-file errors and keep checks shallow.
- **Lifecycle timing:** RPC readiness as health can race with process startup. Mitigation: use bounded retry with a clear timeout and process output context on failure.
- **Boundary confusion:** Developers may expect arbitrary Python object access because normal Python workers support it in some cases. Mitigation: docs and errors should state that only declared external surface area is supported.
- **Temporary run semantics:** `run` performing prepare is convenient but differs from the future prepared-plan model. Mitigation: document this as temporary and keep prepare side effects separated from worker/runtime launch.

## Migration / Rollout

Existing normal Python module deployment must remain compatible. External deployment should be opt-in through `DeploymentSpec` and external declarations.

Rollout steps:

1. Update deployment declaration/planning types to use `ModuleDeployment`, convention discovery, serialized launch envelopes, and immutable resolved plan data.
2. Add local target-session preparation and local external-worker process/client control.
3. Move packaged-Python runtime launch ownership from `WorkerManagerExternal` into `ExternalWorker`.
4. Integrate routing into `ModuleCoordinator` without changing default normal blueprint execution, and fail clearly for plain blueprints with external declarations.
5. Rename/update the example package to `examples/external_python_module/` and exercise it through `plan`, `prepare`, and `run` without `PYTHONPATH`.
6. Add focused docs for external packaged-Python module authors and coding agents.
7. Verify normal module tests still pass and add structural external deployment tests.

Rollback is straightforward while this remains behind the new deployment spec path: remove or stop using the temporary launcher and external deployment spec while normal `dimos run` remains unchanged.

## Open Questions

- What is the exact future persisted prepared-plan manifest schema? Not required for this PR.
- What is the future instance-scoped RPC naming scheme for duplicate external declaration instances? V1 rejects duplicates.
- How should remote worker leases and reconnection tokens behave? Not required for this local-only PR.
