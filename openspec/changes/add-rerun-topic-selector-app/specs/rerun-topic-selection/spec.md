## ADDED Requirements

### Requirement: Current-session staged topic selection
The system SHALL let users stage renderable LCM topic choices and explicitly apply them before those topics are logged to Rerun during a selector-enabled visualization session.

#### Scenario: User stages and applies a renderable topic
- **GIVEN** selector-enabled visualization is running and a renderable LCM topic is visible in the catalog
- **WHEN** the user stages the topic and applies the selection
- **THEN** subsequent messages for that topic are logged to Rerun
- **AND** the embedded Rerun viewer can display the selected topic data.

#### Scenario: Staged topic does not log before apply
- **GIVEN** selector-enabled visualization is running and a renderable LCM topic is visible in the catalog
- **WHEN** the user stages the topic but does not apply the selection
- **THEN** subsequent messages for that topic are not logged merely because the staged state changed
- **AND** the UI indicates that the staged selection differs from the applied/logging selection.

#### Scenario: User clears and applies selected topics
- **GIVEN** a renderable LCM topic is selected and being logged to Rerun
- **WHEN** the user clears or removes the topic from the staged selection and applies that change
- **THEN** subsequent messages for that topic are not converted or logged by the selector-managed path
- **AND** other selected topics continue to be logged.

### Requirement: Selected-only logging before expensive conversion
The system SHALL avoid converting or logging unselected topics in managed-selection mode.

#### Scenario: High-bandwidth topic remains unselected
- **GIVEN** selector-enabled visualization is running and a high-bandwidth renderable LCM topic is flowing
- **WHEN** the topic is not in the applied selection
- **THEN** the topic is not converted to Rerun data by the selector-managed path
- **AND** the topic is not logged to Rerun merely because it is renderable.

#### Scenario: Unsupported topic cannot be selected for rendering
- **GIVEN** an observed LCM topic is marked unsupported or unknown in the catalog
- **WHEN** the user reviews available topics
- **THEN** the UI does not present it as a renderable topic selection
- **AND** the UI gives a short reason such as unknown message type or no Rerun converter.

### Requirement: Compatibility with existing visualization behavior
The system SHALL preserve existing automatic Rerun visualization behavior unless selector-enabled visualization is explicitly enabled.

#### Scenario: Existing blueprint uses standard visualization
- **GIVEN** a DimOS blueprint uses the existing visualization path without enabling the selector
- **WHEN** the blueprint runs
- **THEN** existing automatic Rerun logging behavior remains available
- **AND** topics are not silently hidden by selector state.

#### Scenario: Selector mode is opt-in
- **GIVEN** a user wants selected-only topic logging
- **WHEN** the user enables the selector visualization path through the provided opt-in surface
- **THEN** managed-selection behavior applies to that visualization session
- **AND** the behavior is limited to visualization and does not change robot control skills, MCP tools, or hardware command semantics.

### Requirement: Embedded Rerun viewer feedback
The system SHALL present topic selection and Rerun viewer availability in one web workflow.

#### Scenario: Rerun viewer is available
- **GIVEN** selector-enabled visualization is running and the Rerun web viewer endpoint is reachable
- **WHEN** the user opens the selector web app
- **THEN** the page shows the LCM topic catalog and an embedded Rerun viewer area
- **AND** applied renderable topics are reflected in the viewer as data is logged
- **AND** the page shows which topics are currently applied/logging.

#### Scenario: Rerun viewer is unavailable
- **GIVEN** selector-enabled visualization is running but the Rerun web viewer endpoint is unavailable
- **WHEN** the user opens the selector web app
- **THEN** the page still shows the LCM topic catalog when topic data is available
- **AND** the page shows an actionable connection hint for the Rerun viewer instead of failing silently.
