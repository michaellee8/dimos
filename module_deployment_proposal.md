# Proposal: Module Deployment for DimOS

Status: draft for review.

This proposal defines one deployment model for normal Python modules, packaged Python modules, native modules, and remote execution. The coordinator retains a stable module contract while deployment decides where to prepare and run an implementation.

## 1. Problem / Why now

DimOS needs an explicit deployment layer when a module has dependencies unavailable in the coordinator environment, needs a native build, or must run on another machine. That layer must prepare sources and artifacts, launch implementations, and preserve Blueprint-facing module identity, streams, configuration, and control.

The same model must support dependency-isolated Python, native executables, cross-compilation, and remote targets without replacing the efficient existing path for ordinary local Python modules.

## 2. Current state

| Path | Current ownership | Limitation addressed by this proposal |
| --- | --- | --- |
| Normal Python | `WorkerManagerPython` -> `PythonWorker` -> Python module instance | Requires dependencies in the DimOS worker environment. |
| Native wrapper | `PythonWorker` -> `NativeModule` wrapper -> native subprocess | Wrapper combines Blueprint integration, build/process supervision, and native handoff. |
| Local packaged Python | `WorkerManagerExternal` -> `ExternalWorker` -> prepared Python entrypoint | Validates dependency isolation locally; native and remote paths remain later work. |

Normal local Python remains the default and receives the full DimOS object and RPC surface. Native launch payloads that serialize topics and configuration provide useful precedent for the unified launch envelope described in Appendix A. The proposal makes the coordinator-visible contract independent of the process that implements it.

## 3. User-facing API and workflow

This section describes the intended public CLI. A temporary current launcher is an implementation detail and belongs in implementation documentation, not this API.

### Ordinary deployment path

`ExternalModule` is a lightweight, coordinator-importable `Module` contract whose implementation runs externally. Packaged Python declares an import reference; native modules declare an executable path relative to the discovered implementation directory.

```python skip
class HeavyDetector(ExternalModule):
    implementation = "heavy_detector.module:HeavyDetectorImpl"
    config: HeavyDetectorConfig
    image: In[Image]
    detections: Out[Detections]
```

```python skip
from pathlib import Path


class MLSPlanner(ExternalModule):
    implementation = Path("target/release/mls_planner")
    config: MLSPlannerConfig
    global_map: In[PointCloud2]
    path: Out[Path]
```

`DeploymentSpec` ties a Blueprint to named execution targets and class-keyed `ModuleDeployment` policy:

```python skip
go2_deployment = DeploymentSpec(
    blueprint=go2_stack,
    targets={
        "robot": SshTarget(host="go2", deployment_root="~/dimos-deployments/go2"),
        "gpu": SshTarget(host="gpu-box", deployment_root="~/dimos-deployments/go2"),
    },
    modules={
        MLSPlanner: ModuleDeployment(execution_target="robot", build_target="local"),
        HeavyDetector: ModuleDeployment(execution_target="gpu"),
    },
)
```

The Blueprint remains responsible for active modules, stream wiring, module references, and configuration. A module omitted from `modules` runs on `local`; an omitted build target resolves to its execution target. `local` is a `GlobalConfig`-derived target and cannot be redefined. A class-keyed policy applies to every active instance; resolved plans use unique instance IDs.

Ordinary deployments use conventions for preparation and runtime environments. Exceptional deployments can supply advanced `Preparation` and serializable `RuntimeEnvironmentSpec` overrides; their complete model and matching rules are in Appendix A.

### Commands

```bash
dimos deploy plan <deployment>
dimos deploy prepare <deployment>
dimos run <deployment>
```

`dimos deploy plan` resolves declarations, targets, conventions, and expected artifacts without mutating targets. It reports build and execution targets, selected behavior, source/artifact paths, transport assumptions, and validation errors.

```text
Module         Build   Execute  Worker route
Agent          local   local    WorkerManagerPython -> PythonWorker
MLSPlanner     local   robot    WorkerManagerExternal -> ExternalWorker -> native process
HeavyDetector  gpu     gpu      WorkerManagerExternal -> ExternalWorker -> Python entrypoint
```

`dimos deploy prepare` stages source and artifacts, builds or cross-compiles as needed, and may materialize reusable package environments on execution targets. It does **not** start an `ExternalWorker`, module runtime handle, or implementation process. It persists a content-addressed prepared-plan manifest binding declarations, source digests, target identities, policies, and staged paths.

`dimos run <deployment>` verifies that prepared manifest, bootstraps the required workers, and launches runtime handles. A changed declaration or source requires preparation again. `dimos run <blueprint>` retains today's local-default behavior and cannot contain `ExternalModule` declarations.

### Process topology

```text
normal Module -> WorkerManagerPython -> PythonWorker
ExternalModule -> WorkerManagerExternal -> ExternalWorker -> runtime
```

The external runtime is a thin Python entrypoint for packaged Python or a direct native subprocess for native code. Local external deployment uses this same route; SSH changes target access and control tunneling, not the route itself.

## 4. Package layout convention

The `ExternalModule` class file anchors discovery. Its sibling package must contain exactly one known implementation convention:

```text
detector/
  detector_module.py
  python/
    pyproject.toml
    uv.lock
    src/...
```

```text
mls_planner/
  mls_planner_external.py
  rust/
    Cargo.toml
    src/...
```

V1 recognizes `python/pyproject.toml`, `rust/Cargo.toml`, and `cpp/CMakeLists.txt`. Planning fails when zero or multiple known conventions match. The selected directory determines whether `implementation` is a Python class import reference or an executable path. Detailed matching, presets, overrides, and the existing native precedent are in Appendix A.

## 5. Worker / runtime architecture

DimOS unifies the coordinator-facing manager boundary, not worker implementations. `WorkerManagerPython` remains a local Python object host; `WorkerManagerExternal` is a target-machine deployment backend. The shared boundary covers deployment, rollback, status, logs, and module handles without requiring a common process protocol.

Normal Python stays on `WorkerManagerPython` and is not remotely deployable in v1. Packaged Python and native implementations are `ExternalModule`s and always follow the external route, including when local. This prevents local execution from hiding isolation or import assumptions that fail after remote placement.

`WorkerManagerExternal` owns target definitions, resolved module policy, target sessions, external-worker clients, rollback, health aggregation, and shutdown. It coordinates preparation through local or SSH `TargetSession`s, then requests launch from target-side `ExternalWorker`s.

An `ExternalWorker` is one target-side process per machine per deployment run. It uses the prepared runtime environment, receives serialized launch envelopes, starts and supervises implementation handles, forwards control by module ID, and stops handles on rollback or shutdown. It does not build source or transfer artifacts. A packaged-Python handle is a thin entrypoint process; a native handle is worker state around a direct subprocess. Existing `NativeModule` remains unchanged until migration.

## 6. Control plane vs data plane

The control plane carries worker bootstrap, launch, stop, health, logs, status, and supported method calls:

```text
ModuleCoordinator <-> WorkerManagerExternal <-> ExternalWorker <-> runtime handle
```

SSH may tunnel control RPC, but it never carries module stream data. Lease and reconnect semantics are defined in Appendix A.

The data plane carries streams such as images, point clouds, poses, paths, commands, and maps through DimOS transports including Zenoh, DDS, ROS, LCM, and machine-local SHM. Plans report cross-target transport assumptions; strict compatibility validation is deferred.

## 7. Phased roadmap

1. **Now — local packaged Python:** validate `ExternalModule`, convention discovery, prepared environments, local `ExternalWorker`, and the thin Python entrypoint.
2. **Later — local native:** add convention-driven native preparation and direct native subprocess launch.
3. **Later — native migration:** move existing `NativeModule` users incrementally after the external native path proves stable.
4. **Later — SSH packaged Python:** add remote source staging, control environment bootstrap, worker control, and packaged-Python launch.
5. **Later — SSH native:** add remote native artifact movement, remote builds, and cross-compile transfer.

## 8. Deferred decisions

1. When should DimOS add an optional `dimos.module.toml` or another manifest?
2. When should deployment definitions gain YAML/TOML representation after the Python-first API?
3. How should target profiles and local overlays layer secrets and personal machine details?
4. Should `dimos deploy <deployment>` become shorthand for prepare plus run?
5. When should strict data-plane compatibility checks become mandatory?

## Appendix A. Complete Design Model (non-normative)

### Complete type model

```python skip
from pathlib import Path


# Blueprint-facing contract whose implementation runs through the external deployment path.
class ExternalModule(Module):
    implementation: ClassVar[str | Path]
```

```python skip
# User-authored deployment intent tying one Blueprint to targets and per-module policy.
@dataclass(frozen=True)
class DeploymentSpec:
    blueprint: Blueprint
    targets: Mapping[str, ExecutionTarget]
    modules: Mapping[type[ModuleBase], ModuleDeployment]
```

```python skip
# Per-module policy describing where to build, where to run, and which overrides to use.
@dataclass(frozen=True)
class ModuleDeployment:
    execution_target: str = "local"
    build_target: str | None = None
    preparation: Preparation | None = None
    runtime_environment: RuntimeEnvironmentSpec | None = None
```

```python skip
# Serializable reference to target-side runtime-environment setup logic and config.
@dataclass(frozen=True)
class RuntimeEnvironmentSpec:
    implementation: str
    config: JsonObject = field(default_factory=dict)
```

```python skip
# Named remote machine where DimOS can prepare artifacts and run an ExternalWorker.
@dataclass(frozen=True)
class SshTarget(ExecutionTarget):
    host: str
    deployment_root: PurePosixPath
    expected_platform: Platform | None = None
```

```python skip
# Build/sync step that stages source or artifacts before any ExternalWorker starts.
class Preparation(ABC):
    async def prepare(self, context: PreparationContext) -> None: ...
    async def cleanup(self, context: PreparationContext) -> None: ...
```

```python skip
# Target-side setup step that materializes a reusable environment and returns a
# serializable launch description for the later ExternalWorker launch.
class RuntimeEnvironment(ABC):
    async def setup(self, context: RuntimeEnvironmentContext) -> RuntimeLaunch: ...
    async def teardown(self, context: RuntimeEnvironmentContext) -> None: ...
```

Invariants: the public spec contains user intent; the immutable internal `DeploymentPlan` contains resolved actions; target aliases resolving to the same machine are rejected; custom runtime-environment implementations are top-level, dependency-light import references with JSON-compatible config.

### Planning, prepare, and launch state model

| State | Permitted work | Must not exist yet |
| --- | --- | --- |
| Planned | Resolve declarations, targets, conventions, manifests, and platform checks. | Target mutation, workers, handles. |
| Prepared | Stage content-addressed source/artifacts; build; transfer; materialize reusable package environments; persist manifest. | `ExternalWorker`, runtime handles, implementation processes. |
| Running | Bootstrap one worker per execution machine; launch handles; await ready acknowledgements. | — |
| Stopped/failed | Stop handles and workers; retain immutable caches as policy permits. | Active handles. |

Preparation may use both build and execution sessions, for example to cross-compile locally then copy an artifact to a robot. Build tools provide idempotence through their caches or up-to-date checks. Planning validates native output destinations; it need not require a preparation output to already exist.

### Resolved plan and module launch envelope schemas

```text
DeploymentPlan
  run_id, declaration_digest, source_digests
  targets: machine identity, deployment root, platform
  modules: instance_id, contract, build target, execution target,
           convention/overrides, staged artifacts, worker route
```

```python skip
@dataclass(frozen=True)
class ModuleLaunchEnvelope:
    module_id: str
    runtime: RuntimeLaunch
    config: ModuleConfigPayload
    topics: Mapping[str, TopicBinding]
    control: ControlEndpoint
```

```json
{
  "module_id": "mls_planner-1",
  "runtime": {"executable": "target/release/mls_planner"},
  "topics": {"global_map": {"channel": "/global_map", "type": "sensor_msgs.PointCloud2", "transport": "zenoh"}},
  "config": {"world_frame": "map", "voxel_size": 0.1},
  "control": {"endpoint": "..."}
}
```

The thin Python entrypoint reads the envelope before importing the implementation and verifies it subclasses the declared contract. For native execution, the worker maps the envelope to argv, environment, stdin JSON, and control metadata. This generalizes the current native `stdin_config` payload.

### Convention matching and advanced overrides

| Matched implementation folder | Default behavior |
| --- | --- |
| `python/pyproject.toml` | Source preparation + uv environment; `uv.lock`, when present, pins resolution |
| `python/pyproject.toml` + `pixi.toml` | Source preparation + Pixi-backed environment; `pixi.lock`, when present, pins resolution |
| `rust/Cargo.toml` | Cargo preparation + native environment |
| `cpp/CMakeLists.txt` | CMake preparation + native environment |

Discovery starts at the contract class, walks to its nearest package root, and requires exactly one supported implementation folder. A bare `python/pyproject.toml` is valid; `pixi.toml` selects Pixi when present in that folder, while lock files pin their respective tool's resolution without defining the convention. Explicit preparation and runtime-environment overrides may select and validate one implementation folder, but never replace package-root discovery.

Existing native packages already use the relevant sibling pattern:

```text
mls_planner/
  mls_planner_native.py        # existing NativeModule compatibility path
  mls_planner_external.py      # proposed ExternalModule declaration
  rust/Cargo.toml
```

The existing wrapper's `cwd`, executable, build command, environment, and stdin-config recipe remain migration input rather than a second source of truth. No v1 project-root override is exposed.

### Lifecycle, leases, and shared environments

| Event | Required result |
| --- | --- |
| Startup failure before ready | Stop already-started workers and handles; mark deployment failed. |
| Handle death after startup | Mark deployment unhealthy; no automatic restart in v1. |
| `dimos stop` | Stop the coordinator, workers, and all handles. |
| `dimos restart` | Re-run the original command; prepare only if that command included it. |
| Coordinator lease expiry | Worker invalidates resume token and stops its handles. |

`dimos status` reports coordinator, managers, workers, and handles; `dimos log` aggregates their logs. A reconnect before lease expiry replaces the control connection epoch, preventing two coordinators from controlling one worker.

Within one run, modules share an environment only when source digest, execution-machine identity, and resolved runtime-environment fingerprint match. The run ID scopes it; target-side locks serialize setup; teardown waits for all dependent handles to stop. Cross-run reuse is limited to immutable source, artifact, and package-manager caches. Safety-sensitive provisioning must be bounded or self-expiring because a lease cannot reverse arbitrary system changes.
