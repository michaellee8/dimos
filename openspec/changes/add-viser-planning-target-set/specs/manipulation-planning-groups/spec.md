## ADDED Requirements

### Requirement: Whole-set pose target evaluation

DimOS SHALL evaluate pose targets for a planning target set and return a global selected joint target when evaluation succeeds.

#### Scenario: dual-arm pose targets evaluate to global joints
- **GIVEN** a planning target set includes `left_arm/manipulator` and `right_arm/manipulator`
- **AND** each selected group has an assigned pose target
- **WHEN** DimOS evaluates the pose target set
- **THEN** DimOS returns a target joint state using global joint names for both selected groups
- **AND** the result can be used as the goal for joint-target planning

#### Scenario: auxiliary group participates without pose target
- **GIVEN** a planning target set includes one pose-targeted group and one auxiliary group
- **WHEN** DimOS evaluates the pose target set
- **THEN** the auxiliary group's selected joints participate in the returned target joint state
- **AND** DimOS does not require a direct pose target for the auxiliary group

### Requirement: Multi-target Pink IK behavior

DimOS SHALL support multi-target pose evaluation with Pink IK for same-robot and cross-robot planning target sets.

#### Scenario: same robot multiple frame targets
- **GIVEN** one robot has multiple selected pose-targetable planning groups
- **WHEN** DimOS evaluates pose targets for those groups using Pink IK
- **THEN** DimOS solves the targets as one same-robot multi-frame IK problem
- **AND** returns one global selected joint target for the effective planning group selection

#### Scenario: cross robot pose targets
- **GIVEN** a planning target set contains pose targets for planning groups on different robots
- **WHEN** DimOS evaluates the target set using Pink IK
- **THEN** DimOS evaluates the targets per robot model as needed
- **AND** combines successful results into one global selected joint target for the whole target set

#### Scenario: IK does not own collision semantics
- **GIVEN** Pink IK returns a kinematically valid target joint state
- **WHEN** collision validation or path planning is required
- **THEN** DimOS performs collision checks through the planning world or planner responsibilities
- **AND** the IK result alone is not treated as proof that execution is collision-free

### Requirement: Whole-set joint target evaluation

DimOS SHALL evaluate joint targets for a planning target set as one whole selected target.

#### Scenario: joint target evaluation returns poses for selected groups
- **GIVEN** a planning target set has global target joints for selected planning groups
- **WHEN** DimOS evaluates the joint target set
- **THEN** DimOS returns whole-set validity
- **AND** returns target poses for pose-targetable selected groups when available

#### Scenario: invalid joint target blocks whole set
- **GIVEN** any selected planning group has missing, extra, or invalid target joints
- **WHEN** DimOS evaluates the joint target set
- **THEN** the whole target set is invalid
- **AND** planning is not enabled for the target set

### Requirement: Target-set seed continuity

DimOS SHALL use last valid target joints as the preferred seed for subsequent whole-set IK evaluation.

#### Scenario: current state initializes target set
- **GIVEN** a planning group is newly added to a target set
- **WHEN** DimOS initializes target-set evaluation state
- **THEN** DimOS uses current joints for that group as the initial target and seed

#### Scenario: subsequent IK uses last valid target
- **GIVEN** a planning target set has a last valid solved target joint state
- **WHEN** a subsequent pose edit triggers IK evaluation
- **THEN** DimOS uses the last valid target joints as the preferred seed
- **AND** planning still uses actual current state as the start when a plan is requested
