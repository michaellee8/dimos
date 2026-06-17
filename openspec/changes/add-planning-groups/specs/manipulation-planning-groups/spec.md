## ADDED Requirements

### Requirement: Planning group discovery

DimOS SHALL expose manipulation planning groups discovered from supported SRDF group declarations or from conservative fallback generation when no SRDF is available.

#### Scenario: supported SRDF chain group is discovered
- **GIVEN** a robot model configuration references an SRDF containing a `<group>` with one `<chain base_link="..." tip_link="..."/>`
- **WHEN** planning groups are listed for that robot
- **THEN** the chain group is available as a planning group
- **AND** its public Planning Group ID is `{robot_name}/{group_name}`

#### Scenario: supported SRDF joint-list group is discovered
- **GIVEN** a robot model configuration references an SRDF containing a `<group>` with an ordered list of `<joint name="..."/>` entries
- **AND** those joints validate as one serial chain
- **WHEN** planning groups are listed for that robot
- **THEN** the joint-list group is available as a planning group

#### Scenario: unsupported SRDF groups are skipped
- **GIVEN** an SRDF contains unsupported group forms such as link groups, nested group references, mixed forms, or non-serial groups
- **WHEN** planning groups are discovered
- **THEN** unsupported groups are skipped with warnings
- **AND** supported groups from the same SRDF remain available

#### Scenario: fallback group is generated for unambiguous single-chain robot
- **GIVEN** a robot has no SRDF
- **AND** its configured controllable joints form exactly one unambiguous serial chain
- **WHEN** planning groups are listed for that robot
- **THEN** DimOS exposes one generated planning group named `manipulator`
- **AND** the group ID is `{robot_name}/manipulator`

#### Scenario: ambiguous fallback fails
- **GIVEN** a robot has no SRDF
- **AND** its configured controllable joints are branching, disconnected, ambiguous, or otherwise not one serial chain
- **WHEN** planning groups are discovered
- **THEN** DimOS fails with an error requiring SRDF rather than silently creating an implicit group

### Requirement: Planning group descriptors

DimOS SHALL provide read-only planning group descriptors that identify available groups without acting as live runtime handles.

#### Scenario: descriptor includes stable identity
- **GIVEN** a planning group exists for a robot
- **WHEN** a caller lists planning groups
- **THEN** the returned descriptor includes the Planning Group ID
- **AND** the Planning Group ID is stable and namespaced as `{robot_name}/{group_name}`

#### Scenario: descriptor can be used as selector
- **GIVEN** a caller receives a planning group descriptor from a query API
- **WHEN** the caller passes that descriptor to a planning API
- **THEN** DimOS selects the group by descriptor ID
- **AND** DimOS re-resolves current runtime group data instead of trusting stale descriptor fields

### Requirement: Resolved joint naming

DimOS SHALL expose resolved joint names above the model parsing layer using `{robot_name}/{local_joint_name}`.

#### Scenario: generated path uses resolved names
- **GIVEN** a robot named `left` has a local model joint named `joint1`
- **WHEN** DimOS returns a planning result path that includes that joint
- **THEN** the path uses `left/joint1` as the joint name
- **AND** the bare local name `joint1` is not exposed in the public path

#### Scenario: duplicate local names remain unambiguous
- **GIVEN** two robots both contain a local model joint named `joint1`
- **WHEN** a coordinated plan includes both joints
- **THEN** the plan distinguishes them with resolved names such as `left/joint1` and `right/joint1`

### Requirement: Planning group selection validation

DimOS SHALL validate that selected planning groups are known and do not overlap in resolved joints.

#### Scenario: non-overlapping groups are accepted
- **GIVEN** a planning request selects two known planning groups with disjoint resolved joints
- **WHEN** DimOS resolves the planning group selection
- **THEN** the selection is accepted
- **AND** the effective selected joint set is the union of both groups' resolved joints

#### Scenario: overlapping groups are rejected
- **GIVEN** a planning request selects two planning groups that share at least one resolved joint
- **WHEN** DimOS resolves the planning group selection
- **THEN** the request fails before planning begins
- **AND** the error identifies overlapping selected joints or groups

#### Scenario: unknown group is rejected
- **GIVEN** a planning request references a Planning Group ID that is not available
- **WHEN** DimOS resolves the planning group selection
- **THEN** the request fails with an unknown planning group error

### Requirement: Pose planning with auxiliary groups

DimOS SHALL support pose planning with pose-targeted groups and request-scoped auxiliary groups that contribute free degrees of freedom.

#### Scenario: auxiliary torso helps arm pose planning
- **GIVEN** a pose planning request targets `robot/arm`
- **AND** the request includes `robot/torso` as an auxiliary group
- **WHEN** DimOS solves IK and planning for the request
- **THEN** the effective planning selection includes both arm and torso joints
- **AND** the arm pose target is enforced
- **AND** torso joints are free decision variables with no direct pose constraint in that request

#### Scenario: auxiliary status is request-scoped
- **GIVEN** a planning group has a valid pose target frame
- **WHEN** that group is listed in `auxiliary_groups` for a pose planning request
- **THEN** DimOS treats it as unconstrained by pose for that request
- **AND** the same group may be directly pose-targeted in a different request

#### Scenario: pose-targeted group without target frame is rejected
- **GIVEN** a planning group has no valid pose target frame
- **WHEN** a caller uses that group as a key in pose targets
- **THEN** DimOS rejects the request before planning begins

### Requirement: Joint target planning exactness

DimOS SHALL require joint target planning requests to provide exact selected resolved joint keys.

#### Scenario: exact joint target is accepted
- **GIVEN** a joint target request selects a planning group with resolved joints `robot/joint1` and `robot/joint2`
- **WHEN** the request provides target values for exactly `robot/joint1` and `robot/joint2`
- **THEN** DimOS accepts the target for planning

#### Scenario: missing joint target is rejected
- **GIVEN** a joint target request selects a planning group with resolved joints `robot/joint1` and `robot/joint2`
- **WHEN** the request provides a target for only `robot/joint1`
- **THEN** DimOS rejects the request as incomplete

#### Scenario: extra joint target is rejected
- **GIVEN** a joint target request selects a planning group with resolved joints `robot/joint1` and `robot/joint2`
- **WHEN** the request also includes `robot/joint3`
- **THEN** DimOS rejects the request because the target contains joints outside the selected planning groups

### Requirement: IK result shape

DimOS SHALL return IK solutions containing exactly the resolved joints selected by the effective planning group selection.

#### Scenario: IK result excludes unrelated joints
- **GIVEN** a pose request targets `robot/arm` and includes `robot/torso` as auxiliary
- **WHEN** IK succeeds
- **THEN** the IK solution contains arm and torso resolved joints
- **AND** it excludes unrelated gripper, base, or other-arm joints that were not selected

#### Scenario: IK solves over auxiliary joints
- **GIVEN** a pose request has auxiliary groups
- **WHEN** IK attempts to satisfy pose targets
- **THEN** auxiliary group joints are available as free variables during the solve

### Requirement: Generated plan artifact

DimOS SHALL return a generated plan as the canonical artifact for successful planning.

#### Scenario: generated plan contains selected groups and combined path
- **GIVEN** a planning request succeeds for one or more planning groups
- **WHEN** DimOS returns the generated plan
- **THEN** the plan includes the selected Planning Group IDs
- **AND** the plan includes one synchronized path of resolved-joint-keyed joint states

#### Scenario: generated plan path contains exactly selected joints
- **GIVEN** a generated plan was produced for a planning group selection
- **WHEN** a caller inspects any waypoint in the path
- **THEN** that waypoint contains exactly the selected resolved joints
- **AND** unrelated joints are excluded

#### Scenario: generated plan is reusable for downstream calls
- **GIVEN** a caller receives a generated plan
- **WHEN** the caller previews or executes the plan
- **THEN** DimOS uses the generated plan as the source artifact
- **AND** the caller does not need hidden robot-keyed planned path state

### Requirement: Preview and execution projection

DimOS SHALL project generated plans lazily for preview and execution without making controllers planning-group-aware.

#### Scenario: preview projects selected path
- **GIVEN** a generated plan contains a resolved-joint path
- **WHEN** a caller previews the plan
- **THEN** DimOS projects the path into visualization using the selected joints
- **AND** preview does not require a precomputed execution trajectory stored in the plan

#### Scenario: execution projects per trajectory task
- **GIVEN** a generated plan contains resolved joints for one or more coordinator trajectory tasks
- **WHEN** a caller executes the plan
- **THEN** DimOS projects the combined path into one trajectory per affected task
- **AND** each trajectory is ordered according to that task's configured joint order
- **AND** planning group concepts are not exposed to the trajectory controller

#### Scenario: multi-task execution is dispatched without batch atomicity
- **GIVEN** a generated plan affects multiple trajectory tasks with disjoint joints
- **WHEN** the plan is executed
- **THEN** DimOS dispatches projected trajectories to the affected tasks
- **AND** runtime concurrency is handled by the coordinator and trajectory tasks
- **AND** DimOS does not require an atomic batch dispatch for this change

### Requirement: Group-scoped kinematics queries

DimOS SHALL provide group-scoped pose and Jacobian queries for planning groups with valid pose target frames.

#### Scenario: group pose query succeeds for chain group
- **GIVEN** a planning group has a valid tip or pose target frame
- **WHEN** a caller requests the group's pose
- **THEN** DimOS returns the pose for that group target frame

#### Scenario: group pose query fails without target frame
- **GIVEN** a planning group has no valid pose target frame
- **WHEN** a caller requests the group's pose or Jacobian
- **THEN** DimOS fails with a clear error rather than guessing a frame

### Requirement: Backend unsupported reporting

DimOS SHALL allow planning backends to reject coordinated planning problems they cannot support.

#### Scenario: cross-robot planning unsupported by backend
- **GIVEN** a request selects planning groups across multiple robots
- **AND** the active backend cannot solve cross-robot coordinated planning
- **WHEN** planning is requested
- **THEN** DimOS reports the request as unsupported
- **AND** the failure occurs without sending commands to trajectory controllers
