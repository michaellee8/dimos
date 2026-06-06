## ADDED Requirements

### Requirement: Readable Damiao metadata documentation

DimOS SHALL provide readable developer documentation for Damiao adapter metadata helpers so future maintainers can understand motor order, identifiers, limits, gains, and validation behavior.

#### Scenario: Reading motor metadata helpers
- **GIVEN** a developer opens the Damiao metadata helper module
- **WHEN** they inspect the motor metadata type and receive-ID behavior
- **THEN** the documentation SHALL explain the meaning of joint order, motor type, send ID, receive ID, and default receive-ID derivation
- **AND** it MUST make clear that the metadata is used before hardware commands are sent.

#### Scenario: Reading arm metadata helpers
- **GIVEN** a developer opens the Damiao arm metadata type
- **WHEN** they inspect arm limits, gains, gravity model fields, bus fields, or validation helpers
- **THEN** the documentation SHALL explain that these values describe explicit adapter-owned hardware metadata
- **AND** it SHALL distinguish metadata coercion and validation from runtime hardware communication.

### Requirement: Damiao metadata validation readability

DimOS SHALL keep Damiao metadata validation behavior understandable without requiring readers to infer intent from tests alone.

#### Scenario: Understanding validation failures
- **GIVEN** an adapter provides duplicate IDs or mismatched vector lengths
- **WHEN** validation rejects the metadata
- **THEN** the helper documentation SHALL make the validation intent clear to developers
- **AND** validation errors MUST remain focused on preventing malformed metadata from reaching hardware command paths.
