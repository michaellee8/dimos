# DimOS Runtime Deployment Language

This context defines the language for discussing how DimOS modules retain stable identity while their implementations run in different environments or on different machines.

## Language

**In-Environment Python Module**:
A normal Python `Module` whose implementation is instantiated inside a local `PythonWorker` and shares that worker's Python environment.
_Avoid_: ExternalModule, remote normal Python module

**PythonWorker Preservation Boundary**:
The rule that deployment work does not replace the existing local `PythonWorker` path. In-environment Python modules continue using its lightweight object and RPC protocol.
_Avoid_: Universal external worker path, PythonWorker replacement

**ExternalModule**:
A declarative `Module` subclass whose implementation runs outside `PythonWorker`. It declares the DimOS-facing streams, config, RPC surface, and an implementation reference, but contains no build, process, watchdog, or transport behavior.
_Avoid_: NativeModule compatibility wrapper, process supervisor

**External Implementation Reference**:
The `ExternalModule` declaration that identifies what Runtime Host runs. A string identifies a packaged Python class; a `pathlib.Path` identifies a native executable relative to its convention-discovered implementation directory.
_Avoid_: Deployment-level implementation override, implementation kind flag

**NativeModule Compatibility Path**:
The existing `NativeModule` design in which a Python wrapper runs in `PythonWorker` and directly builds, launches, logs, and supervises a native subprocess. It remains available during migration to `ExternalModule`.
_Avoid_: Final external-module architecture, flag-day migration

**Convention Preset**:
A built-in recognizer that converts a standard implementation layout into prepare and launch behavior. V1 conventions include `python/pyproject.toml`, `rust/Cargo.toml`, and `cpp/CMakeLists.txt`.
_Avoid_: Hand-written prepare commands for every module, required manifest for standard layouts

**Deployment Spec**:
A deployment-owned description that references a Blueprint, defines named execution targets, and assigns Module classes to target names. It does not redefine module implementation details or Blueprint wiring.
_Avoid_: Module package declaration, Blueprint replacement

**Execution Target**:
A named machine or execution substrate on which modules may be prepared and run. In v1, each target name identifies one distinct machine.
_Avoid_: Module implementation, Deployment Assignment

**Deployment Assignment**:
A class-keyed mapping from a Module to an execution-target string name. Unassigned modules use the implicit local target.
_Avoid_: Target definition, implementation override

**Implicit Local Target**:
The execution target that exists in every Deployment Spec without explicit declaration. Modules absent from Deployment Assignments run locally.
_Avoid_: Required local target declaration, implicit remote placement

**Deployment Plan**:
An immutable, validated resolution of Deployment Spec, Blueprint modules, implementation conventions, prepare steps, concrete target definitions, target assignments, and worker routes.
_Avoid_: Behavioral reconciler, mutable deployment state

**Deployment Prepare Phase**:
The phase that realizes implementation requirements before launch, including locked Python environment setup, native builds, cross-compilation, and artifact sync.
_Avoid_: Module start, implicit build during run

**Idempotent Prepare**:
The rule that prepare executes required package-manager, build, and sync steps and relies on their caches or up-to-date checks rather than maintaining a separate DimOS freshness database.
_Avoid_: DimOS freshness cache, manual stale-state tracking

**Worker Manager**:
A coordinator-side backend scheduler that owns worker collections, placement, parallel deployment, rollback, health aggregation, and shutdown. DimOS uses one manager instance per deployment backend per coordinator.
_Avoid_: Worker process, per-machine manager

**WorkerManagerPython**:
The manager for in-environment Python modules. It owns and schedules the local `PythonWorker` pool.
_Avoid_: External-module manager, target worker

**WorkerManagerExternal**:
The manager for `ExternalModule` deployments. It owns target assignments and one `ExternalWorker` per execution machine, coordinates prepare and deployment, and aggregates rollback and health.
_Avoid_: Per-machine manager, separate deployment reconciler

**PythonWorker**:
A coordinator-side handle to one Python worker process that hosts one or more in-environment Python module instances.
_Avoid_: ExternalWorker, WorkerManagerPython

**ExternalWorker**:
A coordinator-side handle to one target-side external worker process on one execution machine. The handle sends requests over one control connection; the target-side entrypoint executes prepare steps and owns Runtime Host handles for ExternalModules assigned to that machine.
_Avoid_: One worker per module, WorkerManagerExternal, persistent target agent

**Runtime Host**:
The external equivalent of a module instance inside `PythonWorker`. It hosts exactly one ExternalModule implementation, receives a Module Launch Envelope, initializes control and stream bindings, and reports ready or failure.
_Avoid_: Worker manager, multi-module worker

**Ready Acknowledgement**:
The explicit Runtime Host signal sent after the launch envelope is parsed, the implementation is initialized, control is active, and stream bindings are ready.
_Avoid_: Treating process creation as successful module startup

**Module Launch Envelope**:
The unified serialized handoff to Runtime Host containing module identity, implementation launch metadata, module config, stream topics, transport descriptors, and control details. It extends the current `NativeModule.stdin_config` shape.
_Avoid_: Separate user-facing config and connection payloads

**Deployment Control Plane**:
The command and lifecycle path between ModuleCoordinator, WorkerManagerExternal, ExternalWorker, and Runtime Host. Prepare terminates at the target-side ExternalWorker entrypoint; deployed module lifecycle, status, logs, health, and method calls continue to Runtime Host.
_Avoid_: Stream data transport

**Deployment Data Plane**:
The transport path used by module streams, such as Zenoh, DDS, ROS, LCM, or SHM where applicable.
_Avoid_: Worker control protocol, lifecycle channel

**Fail-Fast Startup Rollback**:
The rule that startup stops already-started workers and Runtime Hosts if any module fails before the deployment reaches ready state.
_Avoid_: Partial startup, orphaned Runtime Host

**ExternalWorker Lease**:
A coordinator heartbeat or lease that causes an ExternalWorker to stop its Runtime Hosts if the coordinator disappears.
_Avoid_: Orphaned target processes, required persistent agent
