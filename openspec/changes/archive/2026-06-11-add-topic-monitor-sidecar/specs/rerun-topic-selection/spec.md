## MODIFIED Requirements

### Requirement: Compatibility with existing visualization behavior
The system SHALL preserve existing automatic Rerun visualization behavior for normal blueprints and SHALL make attach-style topic monitoring available through `dimos topic monitor` rather than requiring ordinary blueprints to embed selector-specific visualization wiring.

#### Scenario: Existing blueprint uses standard visualization
- **GIVEN** a DimOS blueprint uses the standard visualization path
- **WHEN** the blueprint runs
- **THEN** existing automatic Rerun logging behavior remains available
- **AND** topics are not silently hidden by topic monitor selection state.

#### Scenario: User wants selected-only topic visualization after startup
- **GIVEN** a DimOS run is already active and publishing LCM topics
- **WHEN** the user runs `dimos topic monitor`
- **THEN** selected-only topic logging applies to the monitor's independent sidecar viewer
- **AND** the original robot or simulation stack is not modified.

#### Scenario: Dedicated selector demo is used
- **GIVEN** a user wants a self-contained selector smoke test or demonstration
- **WHEN** the user runs the dedicated selector demo blueprint
- **THEN** the demo remains available as a hardware-free way to exercise topic cataloging, staging, applying, clearing, and embedded Rerun viewing
- **AND** ordinary production blueprints are not required to use selector-specific visualization wiring.
