## MODIFIED Requirements

### Requirement: OpenArm adapter compatibility

DimOS SHALL preserve the existing OpenArm adapter selection and observable behavior while keeping the binding-backed OpenArm RS path separate.

#### Scenario: Selecting the OpenArm adapter
- **GIVEN** an existing hardware configuration selects the OpenArm adapter
- **WHEN** DimOS initializes the manipulator hardware
- **THEN** DimOS SHALL continue to create an OpenArm-specific adapter through the existing `openarm` adapter selection surface
- **AND** the adapter SHALL preserve OpenArm-specific side, joint, motor, limit, gain, gravity-model, and in-tree CAN-driver behavior.

#### Scenario: Existing OpenArm blueprints
- **GIVEN** an existing OpenArm blueprint selects the current OpenArm adapter path
- **WHEN** this cleanup is present
- **THEN** the blueprint SHALL continue selecting the `openarm` adapter unless it is explicitly changed
- **AND** existing stable OpenArm runnable blueprint names SHALL remain stable unless a generated-registry update intentionally changes only binding-backed OpenArm RS names.

#### Scenario: OpenArm source-level stability
- **GIVEN** the original OpenArm adapter is the stable hardware path
- **WHEN** the binding-backed OpenArm RS path is renamed or refactored
- **THEN** DimOS SHALL NOT require the original OpenArm adapter to inherit binding-backed or shared Damiao runtime behavior
- **AND** any source-level OpenArm adapter changes MUST be limited to preserving existing behavior or undoing unintended refactor drift.

### Requirement: OpenArm hardware safety preservation

OpenArm adapter behavior SHALL remain at least as safe as the pre-cleanup behavior for enablement, command writes, gravity compensation, and shutdown.

#### Scenario: Stopping or disconnecting OpenArm hardware
- **GIVEN** OpenArm motors are enabled through DimOS
- **WHEN** the adapter is stopped or disconnected
- **THEN** DimOS SHALL attempt to disable or stop commanding the motors through the adapter
- **AND** the cleanup SHALL NOT introduce a continued background command loop after disconnect.

#### Scenario: OpenArm gravity compensation
- **GIVEN** OpenArm gravity compensation is enabled
- **WHEN** DimOS computes and sends supported OpenArm commands
- **THEN** gravity feed-forward SHALL use the OpenArm-specific model and current measured joint state
- **AND** invalid or stale state SHALL prevent unsafe gravity-compensation commands from being sent.
