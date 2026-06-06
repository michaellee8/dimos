## ADDED Requirements

### Requirement: Reusable Damiao arm behavior

DimOS SHALL provide a reusable Damiao arm adapter behavior that can be shared by OpenArm and future Damiao-based manipulator adapters without requiring users to define a broad dynamic hardware configuration schema.

#### Scenario: Adding a Damiao-based arm implementation
- **GIVEN** a developer needs to add a new arm composed of Damiao motors
- **WHEN** the arm behavior fits the shared Damiao lifecycle, state-read, and MIT command model
- **THEN** the developer SHALL be able to define an arm-specific implementation by providing typed arm metadata and subclass-specific behavior
- **AND** they SHALL NOT need to duplicate the shared Damiao lifecycle and command plumbing.

#### Scenario: Preserving coordinator behavior
- **GIVEN** a Damiao-based adapter uses the shared behavior
- **WHEN** ControlCoordinator reads state or writes supported joint commands through the manipulator adapter surface
- **THEN** DimOS SHALL preserve the existing manipulator state and command semantics
- **AND** no new stream contract SHALL be required for the refactor.

### Requirement: Explicit arm-specific metadata

DimOS SHALL keep arm-specific Damiao metadata explicit and typed rather than relying on implicit OpenArm defaults inside generic Damiao behavior.

#### Scenario: Constructing a non-OpenArm Damiao adapter
- **GIVEN** a Damiao-based adapter does not represent OpenArm
- **WHEN** it is implemented using the shared Damiao behavior
- **THEN** it SHALL provide its own motor layout, gains, joint order, model/gravity metadata, and hardware assumptions
- **AND** DimOS SHALL NOT silently use OpenArm's motor table or OpenArm-specific defaults for that adapter.

#### Scenario: Validating shared command shape
- **GIVEN** a Damiao adapter accepts a supported position, effort, or MIT-style command
- **WHEN** the command is forwarded to hardware or a mock transport
- **THEN** the command SHALL be ordered according to the adapter's explicit arm metadata
- **AND** command length mismatches SHALL be rejected or surfaced as adapter errors rather than sent to hardware.

### Requirement: Optional binding behavior remains selected-adapter scoped

DimOS SHALL keep optional Damiao binding availability failures scoped to adapters that actually select the binding-backed path.

#### Scenario: Binding unavailable while discovering adapters
- **GIVEN** an optional Damiao binding is not importable in the runtime environment
- **WHEN** DimOS discovers manipulator adapters
- **THEN** adapter discovery SHALL continue for adapters that do not require that binding at discovery time
- **AND** missing-binding errors SHALL be raised only when selecting or connecting an adapter that requires the binding.
