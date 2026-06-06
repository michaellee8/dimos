## ADDED Requirements

### Requirement: Explicit OpenArm RS adapter selection

DimOS SHALL provide an explicit Rust-backed OpenArm adapter selection surface named `openarm_rs` for users who choose the binding-backed OpenArm path.

#### Scenario: Selecting the Rust-backed OpenArm path
- **GIVEN** a hardware configuration selects the binding-backed OpenArm adapter
- **WHEN** DimOS initializes manipulator hardware through the adapter registry
- **THEN** the configuration SHALL select the adapter using the `openarm_rs` key
- **AND** the selected adapter SHALL represent OpenArm hardware rather than a generic Damiao arm.

#### Scenario: Binding unavailable for OpenArm RS
- **GIVEN** the `can_motor_control` binding is not importable in the runtime environment
- **WHEN** a user selects the `openarm_rs` adapter
- **THEN** DimOS SHALL fail with a clear selected-adapter missing-binding error
- **AND** DimOS MUST continue discovering unrelated manipulator adapters that do not require that binding.

### Requirement: OpenArm RS blueprint naming

DimOS SHALL expose binding-backed OpenArm runnable blueprints with names that identify the OpenArm RS path.

#### Scenario: Listing binding-backed OpenArm blueprints
- **GIVEN** binding-backed OpenArm blueprints are exported
- **WHEN** a user lists or runs OpenArm blueprints through the DimOS CLI
- **THEN** runnable names SHALL use `openarm-rs` wording instead of `dm-motor-openarm` wording
- **AND** documentation SHALL describe those blueprints as opt-in alternatives to the stable `openarm` path.

### Requirement: OpenArm RS safety staging

DimOS SHALL document and preserve staged validation expectations for the OpenArm RS adapter path.

#### Scenario: Validating before real hardware operation
- **GIVEN** a user wants to run OpenArm hardware through the `openarm_rs` path
- **WHEN** they follow DimOS bring-up guidance
- **THEN** the guidance SHALL start with binding availability and mock or virtual CAN validation
- **AND** it SHALL treat real hardware gravity compensation and trajectory execution as later staged QA steps.
