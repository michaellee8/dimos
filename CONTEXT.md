# DimOS Runtime Deployment Language

This context defines the language for discussing how DimOS modules keep a stable module identity while their implementations run in different environments and on different machines.

## Language

**Module Contract**:
A DimOS-facing module identity that declares the streams, RPCs, config shape, and lifecycle surface other modules depend on.
_Avoid_: Stub module, fake module

**In-Environment Python Module**:
A normal Python Module that runs inside the current DimOS Python worker environment and keeps today's local, in-process-package dependency assumptions.
_Avoid_: Packaged runtime module, remote module

**Packaged Runtime Module**:
A module implementation launched through an external prepared runtime, such as a native executable or a packaged Python runtime project, while DimOS keeps a stable wrapper or contract for graph integration. This can remain under the existing NativeModule naming for now because both cases spawn an external process.
_Avoid_: Normal Python module, abstract Blueprint

**Packaged Python Runtime Backend**:
A Packaged Runtime Module backend that launches a prepared Python runtime process through Deployment Worker plus Runtime Host for both local and remote assignments, not through the normal in-environment PythonWorker. The Deployment Worker should spawn and supervise this process without importing its implementation.
_Avoid_: Native binary backend, in-environment Python module, normal PythonWorker

**Packaged Python Entrypoint**:
A DimOS-provided entrypoint installed or importable inside a packaged Python runtime project. The Deployment Worker launches it, passes a Module Launch Envelope, and the entrypoint imports and runs the packaged Python implementation.
_Avoid_: Arbitrary Python script, Deployment Worker import

**Runtime Backend**:
The mechanism that runs a module implementation after deployment prepares its requirements. Normal PythonWorker runs only in-environment Python modules; packaged Python modules and native modules use separate packaged runtime backends.
_Avoid_: Deployment package, execution target

**Deployment Worker**:
A minimal worker process launched on an execution target, local or remote, that connects to the coordinator and spawns packaged module processes on that target without importing their implementations. V1 uses one Deployment Worker per target, with one Runtime Host per packaged/native module.
_Avoid_: Remote-only worker, module process, target profile

**Runtime Host**:
A target-local process that hosts exactly one module implementation in the v1 deployment model. It parses the Module Launch Envelope, brings up the module, and handles module-level operations such as lifecycle and method calls.
_Avoid_: Deployment Worker, multi-module worker pool

**Module-Kind Worker Routing**:
The rule that worker choice depends on the deployed module kind, not on a top-level local-vs-deployment mode. Normal Python modules use PythonWorker; packaged Python and native modules use Deployment Worker plus Runtime Host.
_Avoid_: Blueprint-mode worker split, deployment-mode-only worker split

**NativeModule Target Path**:
The target architecture where NativeModule implementations are spawned and supervised through Deployment Worker plus Runtime Host for both local and remote assignments, rather than being hosted as PythonWorker-managed wrapper modules.
_Avoid_: Permanent PythonWorker native wrapper

**Module Launch Envelope**:
The serialized handoff from DimOS to an external runtime process, carrying resolved module identity, config, stream topics, transport descriptors, implementation identity, and optional control-plane connection details.
_Avoid_: Module contract, runtime requirement

**Runtime Requirement**:
The stable environment or artifact declaration needed by a module implementation, such as a Python project, Pixi project, Nix flake, native project, binary target, or executable path.
_Avoid_: Machine assignment, deployment target

**Module Runtime Declaration**:
A module-owned declaration of the Runtime Requirement and launch recipe for that module implementation. It belongs with the module package, not in Blueprint wiring or Deployment Assignment.
_Avoid_: Blueprint runtime config, execution assignment

**Self-Contained Module Package**:
A deployable module unit that carries its Module Contract, implementation, runtime and build requirements, preparation recipes, and launch recipe.
_Avoid_: Execution target, machine profile

**Module Package Convention**:
A project layout convention for Self-Contained Module Packages that uses existing Python, native, Pixi, Nix, Cargo, and blueprint files before introducing a dedicated manifest.
_Avoid_: Required manifest, registry format

**Module Package Reference**:
The local coordinator-side reference to a Self-Contained Module Package, including enough information to find its source root, runtime declaration, launch recipe, and files or artifacts to sync.
_Avoid_: Execution target profile, deployment assignment

**Assignment-First Package Discovery**:
The default v1 rule that a Deployment Spec assigns Module Contracts to targets, and DimOS discovers the corresponding Self-Contained Module Package from each contract or wrapper anchor. Explicit package references are overrides for ambiguous layouts or alternate implementations.
_Avoid_: Required package map, package-first deployment spec

**Preparation Strategy**:
The deployment-owned choice of where and how to realize a Runtime Requirement, such as preparing on the execution machine, preparing on the coordinator host then syncing, or cross-compiling elsewhere then syncing artifacts.
_Avoid_: Runtime requirement, build requirement

**Execution Assignment**:
The deployment-owned choice of where the module process runs.
_Avoid_: Runtime requirement, environment declaration

**Execution Target Profile**:
The concrete description of a machine or execution substrate that a deployment can use to prepare, sync, launch, and connect module processes.
_Avoid_: Runtime requirement, module contract

**Deployment Assignment**:
The deployment-owned binding that chooses which Self-Contained Module Package runs on which Execution Target Profile.
_Avoid_: Runtime requirement, module package

**Partial Deployment Assignment**:
The rule that a Deployment Spec may assign only some modules to explicit targets; unassigned modules remain on the local-default path. Deployment plans should show both assigned and default-local modules.
_Avoid_: All-or-nothing deployment assignment, implicit remote placement

**Target Profile / Assignment Separation**:
The rule that target profiles describe available machines or substrates, while deployment assignments bind modules to those targets for a specific run.
_Avoid_: Deployment profile containing everything, machine profile with module placement

**Deployment Reconciler**:
The component that turns a Self-Contained Module Package, Execution Target Profile, and Deployment Assignment into concrete prepare, sync, launch, and connection actions.
_Avoid_: Module package, execution target

**Deployment Prepare Phase**:
The deployment phase that realizes runtime requirements before launch, such as installing Python environments, building native artifacts, cross-compiling, or syncing prepared outputs to execution targets.
_Avoid_: Run phase, module start

**Idempotent Prepare**:
The rule that deployment preparation should run required package-manager, build, and sync steps each time and rely on those tools' own caches or up-to-date checks rather than a separate DimOS deployment-state cache.
_Avoid_: DimOS freshness database, manual stale-state tracking

**Fail-Fast Startup Rollback**:
The rule that deployment run should stop already-started workers and runtime hosts if any module fails before the deployment reaches the running state.
_Avoid_: Partial startup, orphaned runtime host

**Deployment Run Lifecycle**:
The rule that deployment runs participate in the same DimOS lifecycle commands as local runs, including status, stop, restart, and logs, with the coordinator propagating lifecycle operations to deployment workers and runtime hosts.
_Avoid_: Separate deployment-only lifecycle CLI

**Deployment Worker Lease**:
A heartbeat or lease from the coordinator to a Deployment Worker that causes the worker to stop its Runtime Hosts if the coordinator disappears.
_Avoid_: Remote orphaned runtime host, indefinite detached worker

**Ephemeral Deployment Worker**:
The v1 rule that a Deployment Worker is started for a specific deployment run and exits when that run stops. A persistent target agent can implement the same control contract later.
_Avoid_: Required target daemon, persistent agent v1

**Deployment Control Plane**:
The command and lifecycle communication path between coordinator, Deployment Workers, and Runtime Hosts, used for spawn, stop, status, logs, health, and method calls.
_Avoid_: Stream data transport, sensor data plane

**Deployment Data Plane**:
The stream transport path used by module inputs and outputs, such as Zenoh, DDS, ROS, LCM, or SHM where applicable.
_Avoid_: Worker control protocol, lifecycle channel

**Deferred Data-Plane Guard**:
The v1 choice to report cross-target stream transport assumptions in deployment plans without enforcing full data-plane compatibility checks; stricter guards can be added later.
_Avoid_: v1 transport verifier, mandatory data-plane preflight

**Deployment Spec**:
A deployment-owned operational description of which module packages run on which execution targets, how their artifacts are prepared or synced, and what cross-machine connections they require. It does not define the abstract module graph or stream wiring.
_Avoid_: Blueprint, connection profile, module package

**Local-Default Deployment**:
The rule that a Blueprint runs with today's fully local worker spawning behavior unless a Deployment Spec explicitly assigns modules to non-local execution targets.
_Avoid_: Implicit remote deployment, auto-distributed run

**Explicit Remote Package Rule**:
The rule that a module assigned to a non-local execution target must be a Packaged Runtime Module, such as a native module or packaged Python runtime module. Normal in-environment Python modules are local-only.
_Avoid_: Remote normal Python module, implicit remote Python environment

## Open Language Questions

**Grounded Blueprint vs Deployment Spec Boundary**:
Should DimOS expose a named **Grounded Blueprint** object, or should **Deployment Spec** stay as the concrete operational layer beside an abstract Blueprint?
_Current leaning_: Deployment Spec should stay free of abstract Blueprint connection/profile concerns and describe deployment mechanics only.

**Module Package Convention Shape**:
What filesystem convention should DimOS use to discover Self-Contained Module Packages before a dedicated manifest exists?
_Current leaning_: convention-first discovery with explicit package overrides when a Module Contract has multiple implementations or an unusual layout. Existing native precedent includes a contract or wrapper module beside a runtime source directory, such as `mls_planner_native.py` plus `rust/Cargo.toml`. Packaged Python should mirror that shape with a contract or wrapper module beside a `runtime/` Python project.

**Module Package Anchor**:
The Module Contract or NativeModule wrapper file is the v1 anchor for discovering a Self-Contained Module Package. Discovery starts at that file and looks for sibling runtime roots such as `rust/`, `cpp/`, `runtime/`, `pixi.toml`, or `flake.nix`.
_Avoid_: Required package marker file, manifest-first discovery
