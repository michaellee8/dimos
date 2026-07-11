## ADDED Requirements

### Requirement: Deployment references resolve local deployment specs

DimOS SHALL provide a temporary deployment launcher that accepts a Python import reference to a module-level deployment spec variable and resolves it without invoking arbitrary factories or callables.

#### Scenario: Resolve a valid deployment reference
- **GIVEN** a deployment reference in the form `module.path:variable_name`
- **AND** the referenced variable is a deployment spec instance
- **WHEN** a developer runs the temporary launcher in plan mode with that reference
- **THEN** DimOS SHALL resolve the referenced deployment spec
- **AND** it SHALL report the planned modules and deployment targets without preparing packages, starting external workers, or launching module processes.

#### Scenario: Reject an invalid deployment reference
- **GIVEN** a deployment reference that does not resolve to a deployment spec instance
- **WHEN** a developer runs the temporary launcher with that reference
- **THEN** DimOS MUST fail before preparing or launching modules
- **AND** the error MUST explain that the reference must point to a module-level deployment spec variable.

### Requirement: Plan prepare and run phases are explicit

DimOS SHALL expose explicit internal plan, prepare, and run phases for local packaged-Python external module deployment.

#### Scenario: Plan does not mutate local package state
- **GIVEN** a valid deployment spec containing a local packaged-Python external module
- **WHEN** a developer runs the temporary launcher in plan mode
- **THEN** DimOS SHALL validate and report the deployment plan
- **AND** it MUST NOT stage packages, create environments, start external workers, or launch module processes.

#### Scenario: Prepare stages without launching workers
- **GIVEN** a valid deployment spec containing a local packaged-Python external module
- **WHEN** a developer runs the temporary launcher in prepare mode
- **THEN** DimOS SHALL perform required local package preparation through a target session
- **AND** it MUST NOT start an external worker
- **AND** it MUST NOT launch the external module runtime process.

#### Scenario: Run performs temporary convenience deployment
- **GIVEN** a valid deployment spec containing normal Python modules and local packaged-Python external modules
- **WHEN** a developer runs the temporary launcher in run mode
- **THEN** DimOS SHALL plan, prepare idempotently, bootstrap external workers, launch runtime handles, wait for readiness, and run the deployment through the coordinator
- **AND** normal Python modules and external modules SHALL be available through their declared runtime surfaces.

### Requirement: Deployment specs carry module deployment policy

DimOS SHALL use deployment specs with `modules: dict[type[ModuleBase], ModuleDeployment]` policy and resolved plans to carry external module deployment context instead of mutating external declaration classes with class-level deployment metadata.

#### Scenario: External module in plain blueprint fails clearly
- **GIVEN** a plain blueprint contains an active external module declaration
- **WHEN** the blueprint is built without a deployment spec
- **THEN** DimOS MUST fail before deployment
- **AND** the error MUST explain that external modules require a deployment spec.

#### Scenario: Deployment spec defaults external modules to local policy
- **GIVEN** a deployment spec contains an external module declaration in its blueprint
- **AND** the deployment spec omits an explicit policy for that external module class
- **WHEN** DimOS plans the deployment
- **THEN** DimOS SHALL assign the external module the default local module deployment policy
- **AND** it SHALL route that module through the external worker path.

#### Scenario: Normal modules remain on Python worker path
- **GIVEN** a deployment spec contains a normal Python module without explicit deployment policy
- **WHEN** DimOS plans and runs the deployment
- **THEN** DimOS SHALL route the normal Python module through the existing Python worker path.

### Requirement: External module package discovery uses conventions

DimOS SHALL discover local packaged-Python external module implementations by convention from the external declaration class file and SHALL NOT require deployment policy to repeat package implementation identity.

#### Scenario: Python implementation convention is accepted
- **GIVEN** an external declaration class with a string implementation reference
- **AND** exactly one sibling implementation directory contains `python/pyproject.toml`
- **WHEN** DimOS plans the deployment
- **THEN** DimOS SHALL classify the module as a local packaged-Python external module
- **AND** it SHALL use the declaration implementation reference as the packaged Python runtime class reference.

#### Scenario: Pixi metadata selects Pixi-backed uv command path
- **GIVEN** a local packaged-Python external module with `python/pyproject.toml`
- **AND** `python/pixi.toml` exists
- **WHEN** DimOS prepares and launches the module
- **THEN** DimOS SHALL use the Pixi plus uv command path
- **AND** the module runtime SHALL start from the packaged Python project.

#### Scenario: Missing implementation convention fails clearly
- **GIVEN** an external declaration class has no supported sibling implementation directory
- **WHEN** DimOS plans the deployment
- **THEN** DimOS MUST fail before preparing or launching the module
- **AND** the error MUST identify that no supported implementation convention was found.

#### Scenario: Multiple implementation conventions fail clearly
- **GIVEN** an external declaration class has more than one known sibling implementation convention, including `python/`, `rust/`, or `cpp/`
- **WHEN** DimOS plans the deployment
- **THEN** DimOS MUST fail before preparing or launching the module
- **AND** the error MUST identify that multiple implementation conventions are ambiguous.

#### Scenario: Future native conventions are rejected as not implemented
- **GIVEN** an external declaration class resolves to a sibling `rust/Cargo.toml` or `cpp/CMakeLists.txt` implementation directory
- **WHEN** DimOS plans the deployment for this change
- **THEN** DimOS MUST fail before preparing or launching the module
- **AND** the error MUST state that native external module execution is not implemented in this PR.

### Requirement: Coordinator routes mixed module deployments

DimOS SHALL route normal Python modules and local packaged-Python external modules through their appropriate worker managers within the real coordinator deployment flow.

#### Scenario: Mixed deployment uses both worker paths
- **GIVEN** a deployment spec whose blueprint contains a normal Python module and a local packaged-Python external module
- **WHEN** DimOS runs the deployment
- **THEN** the normal Python module SHALL be deployed through the existing Python worker path
- **AND** the local packaged-Python external module SHALL be deployed through the external worker path
- **AND** coordinator-managed stream wiring, module refs, lifecycle calls, and declared RPC access SHALL operate across the mixed deployment.

#### Scenario: Existing normal Python deployment remains compatible
- **GIVEN** an existing blueprint that contains only normal Python modules
- **WHEN** the blueprint is deployed through the existing DimOS run path
- **THEN** DimOS MUST preserve the existing Python worker deployment behavior
- **AND** the new external deployment path MUST NOT be required for that blueprint.

### Requirement: External worker owns external runtime handles

DimOS SHALL launch local packaged-Python runtime processes through a target-side external worker process rather than directly from the coordinator-side external worker manager.

#### Scenario: Prepare does not start external worker
- **GIVEN** a valid deployment spec containing a local packaged-Python external module
- **WHEN** DimOS prepares the deployment
- **THEN** DimOS SHALL use a target session for preparation commands
- **AND** it MUST NOT start the external worker process.

#### Scenario: Run bootstraps local external worker
- **GIVEN** a prepared local packaged-Python external module
- **WHEN** DimOS runs the deployment
- **THEN** `WorkerManagerExternal` SHALL bootstrap a local external worker through the target session
- **AND** it SHALL control that worker through an external worker client.

#### Scenario: External worker launches runtime handle
- **GIVEN** a local external worker is running
- **WHEN** `WorkerManagerExternal` requests launch for a local packaged-Python external module
- **THEN** the external worker SHALL spawn and supervise the packaged-Python runtime entrypoint
- **AND** `WorkerManagerExternal` MUST NOT directly spawn the runtime entrypoint process.

#### Scenario: External worker control payloads are serialized data
- **GIVEN** `WorkerManagerExternal` sends a control request to an external worker
- **WHEN** the request crosses the external worker client boundary
- **THEN** the request payload SHALL contain JSON-compatible data
- **AND** it MUST NOT contain live Python classes, live module instances, callables, or pickled refs.

### Requirement: Module launch envelopes are serialized data

DimOS SHALL hand off local packaged-Python runtime launch information with serialized module launch envelopes rather than pickled live Python class objects.

#### Scenario: Runtime launch envelope contains import references and data
- **GIVEN** a planned local packaged-Python external module
- **WHEN** DimOS creates the module launch envelope
- **THEN** the envelope SHALL include module identity, declaration import reference, implementation import reference, prepared package paths, config payload, stream bindings where available, and readiness settings
- **AND** it MUST NOT include live Python class objects, live module instances, callables, or pickled refs.

#### Scenario: Runtime entrypoint validates implementation subclass
- **GIVEN** the external worker launches a packaged-Python runtime entrypoint with a module launch envelope
- **WHEN** the runtime entrypoint imports the declaration and implementation classes
- **THEN** it MUST verify that the implementation is a subclass of the declaration
- **AND** it MUST fail before serving RPC if the implementation does not satisfy the declaration.

### Requirement: External modules preserve declared Module semantics

DimOS SHALL support local packaged-Python external modules for declared lifecycle, streams, config metadata, RPC methods, skills, and module refs.

#### Scenario: Declared RPC call reaches external runtime
- **GIVEN** a local packaged-Python external module declaration with a declared RPC method
- **AND** the external runtime implementation serves that method
- **WHEN** coordinator-side code calls the declared RPC on the external module proxy
- **THEN** DimOS SHALL deliver the call to the external runtime through the configured RPC transport
- **AND** the caller SHALL receive the runtime method result.

#### Scenario: Undeclared Python object access is rejected
- **GIVEN** a local packaged-Python external module proxy
- **WHEN** coordinator-side code attempts to access an attribute that is not part of the declared external module surface
- **THEN** DimOS MUST reject the access
- **AND** it MUST NOT require live Python object passthrough from the external runtime process.

#### Scenario: Declared module refs are rebindable
- **GIVEN** a local packaged-Python external module declares a module ref to another module's declared surface
- **WHEN** the coordinator wires module refs during deployment
- **THEN** DimOS SHALL provide a declared proxy suitable for supported RPC calls
- **AND** it MUST NOT rely on pickled live module instances across the external boundary.

### Requirement: Duplicate external declaration instances are rejected in v1

DimOS SHALL reject duplicate active instances of the same external declaration class until external runtime identity is instance-scoped.

#### Scenario: Duplicate external declaration class is active
- **GIVEN** a deployment spec whose blueprint activates two external module instances with the same declaration class
- **WHEN** DimOS plans the deployment
- **THEN** DimOS MUST fail before preparing or launching modules
- **AND** the error MUST explain that duplicate external declaration instances are not supported yet.

### Requirement: External runtime readiness is based on RPC responsiveness

DimOS SHALL treat a launched local packaged-Python external module as ready only after its required side-effect-free lifecycle or readiness RPC endpoint responds within a bounded timeout.

#### Scenario: Runtime becomes ready
- **GIVEN** an external worker has launched a local packaged-Python external module runtime handle
- **WHEN** the module runtime starts its RPC server and responds to the required readiness RPC
- **THEN** DimOS SHALL mark the module ready for coordinator lifecycle and wiring operations.

#### Scenario: Runtime startup times out
- **GIVEN** an external worker has launched a local packaged-Python external module runtime handle
- **WHEN** the required readiness RPC endpoint does not respond before the readiness timeout
- **THEN** DimOS MUST fail the deployment
- **AND** it SHALL provide enough error context, including captured runtime output where available, for the developer to identify startup or packaging failures.

### Requirement: Example package demonstrates supported external module behavior

DimOS SHALL include a local example package under `examples/external_python_module/` that demonstrates the supported local packaged-Python external module workflow and declared module surface.

#### Scenario: Example package imports without PYTHONPATH
- **GIVEN** the repository root is the current working directory
- **WHEN** a developer references `examples.external_python_module.deployment:deployment_spec`
- **THEN** DimOS SHALL resolve the example deployment spec without requiring a `PYTHONPATH` override.

#### Scenario: Example package plans prepares and runs
- **GIVEN** the repository's local external packaged-Python example package
- **WHEN** a developer runs the temporary launcher in plan, prepare, and run modes against the example deployment reference
- **THEN** DimOS SHALL exercise the same deployment spec resolution, local package preparation, external worker launch, runtime handle launch, readiness, and coordinator routing behavior used by non-example packaged-Python modules
- **AND** the example MUST NOT require robot hardware, remote SSH, native build tools, or non-local services.

#### Scenario: Example package demonstrates declared RPC behavior
- **GIVEN** the repository's local external packaged-Python example package includes a declared RPC method
- **WHEN** the example is run through the coordinator deployment path and the declared RPC is called
- **THEN** the call SHALL reach the external runtime module through the configured RPC transport
- **AND** the example SHALL return a visible result that confirms the runtime implementation handled the call.

#### Scenario: Example package documents the supported surface
- **GIVEN** a developer reads the example package files or README
- **WHEN** they inspect how the example is structured
- **THEN** the example SHALL show the coordinator-visible declaration, packaged runtime implementation, deployment spec reference, supported package layout, external worker topology, and launcher commands
- **AND** it SHALL demonstrate declared RPC behavior
- **AND** it SHALL identify where other declared surfaces such as streams, lifecycle behavior, config metadata, skills, and module refs are supported by tests or documentation.
