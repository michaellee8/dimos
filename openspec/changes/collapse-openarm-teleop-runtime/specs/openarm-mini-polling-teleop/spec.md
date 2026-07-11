## ADDED Requirements

### Requirement: Concrete polling ownership
The OpenArm Mini teleop module SHALL own the polling worker used to read configured leader devices and SHALL NOT depend on a generic teleop runtime superclass.

#### Scenario: Module starts polling
- **WHEN** the OpenArm Mini teleop module starts with valid leader configuration
- **THEN** it connects each enabled leader and starts exactly one polling worker

#### Scenario: Duplicate start is attempted
- **WHEN** start is requested while the polling worker is already active
- **THEN** the module does not create a second polling worker

### Requirement: Direct joint command publication
Each successful polling tick SHALL map current leader readings to a `JointState` and publish that command directly on the module's joint command output.

#### Scenario: Valid leader readings are available
- **WHEN** a polling tick reads and maps valid positions from all enabled leaders
- **THEN** the resulting `JointState` is published once

#### Scenario: Authority is inactive
- **WHEN** a polling tick runs while OpenArm Mini authority is inactive
- **THEN** no joint command is published

### Requirement: Failed readings do not publish commands
The OpenArm Mini teleop module SHALL suppress commands produced from invalid or failed leader reads and SHALL remain able to process a later polling tick.

#### Scenario: Leader read fails
- **WHEN** an enabled leader returns an invalid reading or raises an expected transport error
- **THEN** that polling tick publishes no joint command and a later tick can retry

### Requirement: Deterministic polling cleanup
Stopping the OpenArm Mini teleop module SHALL signal and join its polling worker, clear worker state, disconnect every connected leader, and stop module resources.

#### Scenario: Active module stops
- **WHEN** stop is requested while polling is active
- **THEN** polling terminates and all connected leaders are disconnected

### Requirement: Valid polling configuration
The OpenArm Mini teleop module SHALL reject a polling period that is not strictly positive.

#### Scenario: Non-positive polling period is configured
- **WHEN** module configuration specifies a zero or negative polling period
- **THEN** configuration or module construction fails with a validation error

### Requirement: Synchronous tick hook
The OpenArm Mini teleop module SHALL expose a synchronous tick operation that performs one read-map-publish opportunity without requiring the background polling worker.

#### Scenario: Unit test invokes one tick
- **WHEN** a caller invokes `tick()` with connected fake leader inputs
- **THEN** one polling iteration is performed deterministically
