## MODIFIED Requirements

### Requirement: Binding-backed OpenArm adapter scope

DimOS SHALL narrow the current binding-backed DMMotor/OpenArm behavior into an explicit OpenArm RS adapter path rather than presenting it as a generic DMMotor arm adapter.

#### Scenario: Selecting the renamed binding-backed adapter
- **GIVEN** a hardware configuration needs the Rust-backed OpenArm binding path
- **WHEN** the configuration selects an adapter type
- **THEN** it SHALL use `openarm_rs` for the binding-backed OpenArm adapter
- **AND** it SHALL NOT rely on `dm_motor_arm` as the documented OpenArm binding-backed adapter key.

#### Scenario: Avoiding generic Damiao defaults
- **GIVEN** a non-OpenArm Damiao arm needs support in the future
- **WHEN** a developer evaluates the OpenArm RS adapter
- **THEN** DimOS SHALL make clear that OpenArm RS metadata and defaults are OpenArm-specific
- **AND** DimOS MUST require a separate explicit adapter or change before treating those defaults as generic Damiao behavior.

### Requirement: Binding-backed adapter safety behavior

DimOS SHALL preserve the safety expectations already required for the binding-backed adapter while renaming and narrowing its surface.

#### Scenario: Coherent state reads
- **GIVEN** the OpenArm RS adapter is connected through the binding-backed path
- **WHEN** DimOS reads positions, velocities, and efforts during one coordinator cycle
- **THEN** the adapter SHALL provide a coherent state snapshot rather than independently loading the CAN bus for each read
- **AND** stale or malformed state SHALL be surfaced before unsafe commands are sent.

#### Scenario: Gravity-compensation-only command
- **GIVEN** a user invokes a gravity-compensation-only validation path through the binding-backed adapter
- **WHEN** the adapter sends MIT commands for gravity compensation
- **THEN** the command SHALL use zero position stiffness so the arm remains manually movable
- **AND** the command SHALL use current measured state and configured OpenArm gravity metadata.

#### Scenario: Missing binding remains selected-adapter scoped
- **GIVEN** the optional binding is not installed
- **WHEN** DimOS discovers manipulator adapters without selecting OpenArm RS
- **THEN** discovery SHALL continue for adapters that do not require the binding
- **AND** missing-binding errors SHALL occur only when selecting or connecting the OpenArm RS path.
