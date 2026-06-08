## MODIFIED Requirements

### Requirement: Binding-backed adapter safety behavior

DimOS SHALL preserve the safety expectations already required for the binding-backed adapter while renaming and narrowing its surface. Tests for this behavior SHALL verify observable adapter outcomes and safety-relevant command effects rather than broad snapshots of private adapter construction state.

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
- **WHEN** DimOS discovers or lists manipulator adapters without selecting OpenArm RS
- **THEN** discovery SHALL continue for adapters that do not require the binding
- **AND** missing-binding errors SHALL occur only when selecting or connecting the OpenArm RS path
- **AND** registry listing MUST NOT import the OpenArm RS implementation only to discover its adapter key.

#### Scenario: Safety tests remain behavior-focused
- **GIVEN** a test protects binding-backed adapter safety behavior
- **WHEN** the test verifies command output or state behavior
- **THEN** it SHALL name the safety behavior being protected
- **AND** it SHALL avoid asserting unrelated private fields or full default tables that are not required to prove that behavior.
