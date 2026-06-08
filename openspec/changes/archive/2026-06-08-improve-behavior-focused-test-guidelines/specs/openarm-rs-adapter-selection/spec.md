## MODIFIED Requirements

### Requirement: Explicit OpenArm RS adapter selection

DimOS SHALL provide an explicit Rust-backed OpenArm adapter selection surface named `openarm_rs` for users who choose the binding-backed OpenArm path. Unit tests for the OpenArm RS adapter SHALL avoid fake `can_motor_control` hardware behavior and cover only constructor-time public metadata and validation behavior.

#### Scenario: Selecting the Rust-backed OpenArm path
- **GIVEN** a hardware configuration selects the binding-backed OpenArm adapter
- **WHEN** DimOS initializes manipulator hardware through the adapter registry
- **THEN** the configuration SHALL select the adapter using the `openarm_rs` key
- **AND** the selected adapter SHALL represent OpenArm hardware rather than a generic Damiao arm.

#### Scenario: Binding unavailable for OpenArm RS
- **GIVEN** the `can_motor_control` binding is not importable in the runtime environment
- **WHEN** a user selects the `openarm_rs` adapter
- **THEN** DimOS SHALL fail with a clear selected-adapter missing-binding error
- **AND** DimOS MUST continue discovering unrelated manipulator adapters that do not require that binding
- **AND** listing manipulator adapters MUST NOT import the OpenArm RS implementation only to discover its adapter key.

### Requirement: OpenArm RS safety staging

DimOS SHALL document and preserve staged validation expectations for the OpenArm RS adapter path. Unit tests for this path SHALL NOT simulate backend control-library effects with fake hardware classes.

#### Scenario: Validating before real hardware operation
- **GIVEN** a user wants to run OpenArm hardware through the `openarm_rs` path
- **WHEN** they follow DimOS bring-up guidance
- **THEN** the guidance SHALL start with binding availability and mock or virtual CAN validation
- **AND** it SHALL treat real hardware gravity compensation and trajectory execution as later staged QA steps.

#### Scenario: OpenArm RS tests remain behavior-focused
- **GIVEN** a test covers OpenArm RS adapter behavior
- **WHEN** it verifies behavior without the real control binding
- **THEN** it SHALL limit coverage to constructor-time metadata, limits, registration, and validation errors
- **AND** it SHALL avoid fake `can_motor_control` robots, buses, arms, state reads, and command effects.
