## ADDED Requirements

### Requirement: Planning target set selection

Viser SHALL let users establish a planning target set by selecting one or more manipulation planning groups.

#### Scenario: select multiple manipulator groups
- **GIVEN** a Viser manipulation scene contains `left_arm/manipulator` and `right_arm/manipulator`
- **WHEN** the user selects both planning groups
- **THEN** Viser treats them as one planning target set
- **AND** subsequent IK, feasibility, planning, preview, execute, and stale-state checks are scoped to the whole target set

#### Scenario: select all manipulators convenience action
- **GIVEN** a Viser manipulation scene contains multiple manipulator planning groups
- **WHEN** the user chooses the select-all-manipulators action
- **THEN** all manipulator planning groups become members of the current planning target set
- **AND** the user can still adjust the selection explicitly

### Requirement: Group-keyed target controls

Viser SHALL key pose target controls by Planning Group ID for selected pose-targetable planning groups.

#### Scenario: selected pose-targetable group shows gizmo
- **GIVEN** a selected planning group has a pose target frame
- **WHEN** Viser renders the planning target set
- **THEN** Viser shows a target gizmo associated with that Planning Group ID
- **AND** moving the gizmo edits that group's pose target within the whole target set

#### Scenario: unselected group hides gizmo
- **GIVEN** a planning group is not part of the planning target set
- **WHEN** Viser renders target controls
- **THEN** Viser does not show a target gizmo for that group
- **AND** that group does not contribute target joints to the planning target set

#### Scenario: auxiliary group has no assigned gizmo
- **GIVEN** a planning group is selected as an auxiliary member of the planning target set
- **WHEN** Viser renders target controls
- **THEN** Viser does not assign a direct pose gizmo to that auxiliary group
- **AND** the auxiliary group still participates in whole-set IK, feasibility, planning, preview, and execute behavior

### Requirement: Target initialization from current state

Viser SHALL initialize newly selected planning groups from current robot state.

#### Scenario: selecting a group is motion-neutral
- **GIVEN** a planning group is not selected
- **WHEN** the user adds the group to the planning target set
- **THEN** Viser initializes that group's target joints from current joints
- **AND** if the group is pose-targetable, its target gizmo starts at the current group pose
- **AND** adding the group alone does not create a motion target away from current state

### Requirement: Whole-set target authoring

Viser SHALL treat pose gizmos and joint controls as views over one planning target set.

#### Scenario: pose edit updates target joints
- **GIVEN** a planning target set has one or more selected pose-targetable groups
- **WHEN** the user moves any selected group's target gizmo
- **THEN** Viser requests whole-set IK evaluation for all active pose targets
- **AND** Viser updates the target-set joint controls from the returned global target joints when evaluation succeeds

#### Scenario: joint edit updates pose targets
- **GIVEN** a planning target set has target joints and pose-targetable groups
- **WHEN** the user edits target joints
- **THEN** Viser requests whole-set joint target evaluation
- **AND** Viser updates visible pose gizmos from the evaluated group poses when available

### Requirement: Whole-set status and failures

Viser SHALL expose one canonical whole-set status for target validity and plan readiness.

#### Scenario: IK failure keeps last valid target
- **GIVEN** a planning target set has a last valid solved target joint state
- **WHEN** realtime IK evaluation fails for a subsequent gizmo edit
- **THEN** Viser keeps the last valid target joints
- **AND** marks the planning target set invalid or stale
- **AND** disables planning until a whole-set evaluation succeeds again

#### Scenario: per-group diagnostics are explanatory
- **GIVEN** a planning target set evaluation returns diagnostics for individual groups
- **WHEN** Viser displays target-set status
- **THEN** the whole-set status controls whether planning is enabled
- **AND** per-group diagnostics are displayed only as explanatory details

### Requirement: Whole-set planning actions

Viser SHALL plan, preview, execute, clear, and report freshness for the whole planning target set.

#### Scenario: plan target set through joint targets
- **GIVEN** a planning target set has valid global target joints
- **WHEN** the user requests planning
- **THEN** Viser requests joint-target planning for the selected planning groups
- **AND** the request represents the whole target set rather than an individual robot or group

#### Scenario: preview and execute full generated plan
- **GIVEN** planning succeeds for a planning target set
- **WHEN** the user previews or executes from Viser
- **THEN** Viser acts on the full generated plan for the target set
- **AND** the normal UI does not expose per-robot or per-group preview/execute actions

#### Scenario: execute requires whole-set freshness
- **GIVEN** a generated plan was created for a planning target set
- **WHEN** current joints for any selected planning group drift from the plan start snapshot beyond tolerance
- **THEN** Viser marks the plan stale for the whole target set
- **AND** disables execute for the whole plan

### Requirement: URDF-authored visual placement

Viser SHALL rely on authored URDF/xacro placement for robot visuals in this workflow.

#### Scenario: dual xArm visual placement is not double-applied
- **GIVEN** dual xArm robot models encode placement in their authored URDF/xacro output
- **WHEN** Viser registers the robots for visualization
- **THEN** Viser renders the prepared URDFs as authored
- **AND** Viser does not apply `base_pose` as an additional implicit visual transform
