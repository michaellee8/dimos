## ADDED Requirements

### Requirement: OpenArm adapter compatibility

DimOS SHALL preserve the existing OpenArm adapter selection and observable behavior while refactoring shared Damiao behavior underneath it.

#### Scenario: Selecting the OpenArm adapter
- **GIVEN** an existing hardware configuration selects the OpenArm adapter
- **WHEN** DimOS initializes the manipulator hardware
- **THEN** DimOS SHALL continue to create an OpenArm-specific adapter through the existing adapter selection surface
- **AND** the adapter SHALL preserve OpenArm-specific side, joint, motor, limit, gain, and gravity-model behavior.

#### Scenario: Existing OpenArm blueprints
- **GIVEN** an existing OpenArm blueprint selects the current OpenArm adapter path
- **WHEN** this refactor is present
- **THEN** the blueprint SHALL continue selecting the OpenArm adapter unless it is explicitly changed
- **AND** existing runnable blueprint names SHALL remain stable unless a generated-registry update intentionally changes them.

### Requirement: OpenArm hardware safety preservation

OpenArm adapter behavior SHALL remain at least as safe as the pre-refactor behavior for enablement, command writes, gravity compensation, and shutdown.

#### Scenario: Stopping or disconnecting OpenArm hardware
- **GIVEN** OpenArm motors are enabled through DimOS
- **WHEN** the adapter is stopped or disconnected
- **THEN** DimOS SHALL attempt to disable or stop commanding the motors through the adapter
- **AND** the refactor SHALL NOT introduce a continued background command loop after disconnect.

#### Scenario: OpenArm gravity compensation
- **GIVEN** OpenArm gravity compensation is enabled
- **WHEN** DimOS computes and sends supported OpenArm commands
- **THEN** gravity feed-forward SHALL use the OpenArm-specific model and current measured joint state
- **AND** invalid or stale state SHALL prevent unsafe gravity-compensation commands from being sent.

### Requirement: Staged OpenArm validation

DimOS SHALL support staged validation of refactored OpenArm adapter behavior before real full-arm use.

#### Scenario: Mock or virtual validation
- **GIVEN** the refactored OpenArm or Damiao adapter path is available
- **WHEN** a developer validates the change without real hardware
- **THEN** DimOS SHALL support mock or virtual transport tests for lifecycle, state reads, supported commands, and shutdown
- **AND** real hardware validation SHALL be treated as a later staged QA step.
