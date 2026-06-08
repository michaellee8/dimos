## ADDED Requirements

### Requirement: Behavior-focused unit test guidance

DimOS SHALL provide coding-agent testing guidance that tells agents to write unit tests around observable behavior rather than incidental object shape.

#### Scenario: Agent prepares to write a unit test
- **GIVEN** a coding agent is writing or reviewing a unit test
- **WHEN** it consults the DimOS coding-agent testing guidance
- **THEN** the guidance SHALL instruct it to structure the test as setup, execute functionality, and check the desired result
- **AND** the guidance SHALL discourage tests that only construct an object and assert many minor properties.

#### Scenario: Agent reviews an over-assertive test
- **GIVEN** a proposed test asserts private fields, full metadata snapshots, or every backend command detail
- **WHEN** the agent applies the testing guidance
- **THEN** it SHALL either replace those assertions with a public behavior check or justify the smallest safety-critical assertion needed
- **AND** it SHALL prefer a test name that states the desired behavior being protected.

### Requirement: Test-quality review checklist

DimOS SHALL provide a concise checklist for coding agents to evaluate whether a unit test is behavior-focused.

#### Scenario: Agent self-reviews a new test
- **GIVEN** a coding agent has written a new unit test
- **WHEN** it applies the checklist
- **THEN** the checklist SHALL ask what behavior would break if the test failed
- **AND** it SHALL ask whether the test executed functionality rather than only constructing an object
- **AND** it SHALL ask whether the assertions target public outcomes instead of private implementation details.
