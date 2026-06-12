## ADDED Requirements

### Requirement: memory2 streams support generic payload strategies
memory2 SHALL allow a stream backend to delegate payload encoding, lazy loader attachment, and decode-error policy to an optional payload strategy without changing the logical stream payload type.

#### Scenario: Stream appends through a payload strategy
- **GIVEN** a memory2 stream is created with a payload strategy for its payload type
- **WHEN** the stream appends a value
- **THEN** the backend MUST preserve normal observation metadata insertion semantics
- **AND** the backend MUST delegate payload byte encoding to the configured payload strategy before writing the blob.

#### Scenario: Stream queries attach strategy loaders
- **GIVEN** a memory2 stream has stored blobs written by a payload strategy
- **WHEN** observations are queried or replayed
- **THEN** the backend MUST attach lazy data loaders through the payload strategy
- **AND** observation metadata must remain readable without materializing the payload.

### Requirement: Payload strategies remain storage-generic
memory2 SHALL keep payload strategy integration generic so the base store and backend abstractions do not depend on H.264-specific classes.

#### Scenario: Base store creates a strategy-backed backend
- **GIVEN** a stream configuration includes a payload strategy
- **WHEN** the generic store creates the backend
- **THEN** the store MUST pass the strategy through the generic backend construction path
- **AND** the store MUST avoid payload-specific imports, type checks, or backend subclasses for H.264.

#### Scenario: Storage backend binds optional local resources
- **GIVEN** a concrete store implementation reopens a stream with a serialized payload strategy
- **WHEN** the strategy needs store-local resources such as a SQLite connection for auxiliary metadata
- **THEN** the concrete store MAY bind those resources through a strategy hook
- **AND** the binding hook must remain generic so other strategies can use the same extension point.

### Requirement: Payload strategy configuration survives store reopen
memory2 SHALL persist payload strategy identity and configuration in stream registry metadata so reopened stores can reconstruct strategy-backed streams.

#### Scenario: Reopen a strategy-backed stream
- **GIVEN** a stream was created with a payload strategy
- **WHEN** a later process reopens the store
- **THEN** memory2 MUST deserialize the configured payload strategy
- **AND** the reopened stream must use that strategy for lazy payload access and replay behavior.

### Requirement: Replay honors strategy decode suppression
memory2 SHALL allow payload strategies to classify decode errors that replay should suppress while preserving normal failure behavior for unrelated errors.

#### Scenario: Strategy suppresses an undecodable payload
- **GIVEN** a replay iterator encounters a payload decode error
- **AND** the stream's payload strategy classifies that error as suppressible
- **WHEN** replay advances through the stream
- **THEN** memory2 MUST skip that undecodable observation
- **AND** replay MUST continue with later observations.

#### Scenario: Strategy does not suppress an error
- **GIVEN** a replay iterator encounters a payload decode error
- **AND** the stream's payload strategy does not classify that error as suppressible
- **WHEN** replay advances through the stream
- **THEN** memory2 MUST surface the error to the caller.
