## Why

DimOS manipulation planning is currently robot-centric: planner and kinematics interfaces select a `robot_id`, while `RobotModelConfig` carries a single `joint_names`, `base_link`, and `end_effector_link` shape. That works for a single serial arm, but it hides the actual planning unit and makes torso+arm, dual-arm, and coordinated multi-group planning awkward or ambiguous.

Planning groups should be first-class. Robot identity should describe the hardware/model instance, while planning group selection should describe which kinematic chains participate in IK and motion planning. This change also makes joint naming unambiguous above the model parsing layer by using stable resolved joint names.

## What Changes

- Add first-class planning group definitions sourced primarily from SRDF `<group>` entries.
- Add conservative fallback generation of one `manipulator` planning group for unambiguous single-chain robots without SRDF.
- **BREAKING**: Planning and IK APIs move from robot-ID selection to explicit planning group selection.
- **BREAKING**: Joint states and generated paths above model parsing use resolved joint names of the form `{robot_name}/{local_joint_name}`.
- Add pose planning over pose-targeted planning groups plus request-scoped auxiliary planning groups that contribute free DOFs.
- Add coordinated multi-group planning semantics: one selected joint set, one synchronized path, and no overlapping selected joints.
- Replace robot-scoped end-effector FK/Jacobian queries with group-scoped queries.
- Introduce a minimal generated plan artifact that stores selected group IDs and a combined resolved-joint path, projecting lazily for preview and execution.
- Remove planning configuration concepts that duplicate robot model structure, including robot-level planning `base_link`, `end_effector_link`, and `base_pose` fields in the new design.

## Affected DimOS Surfaces

- Modules/streams:
  - Manipulation planning module plan/preview/execute flow.
  - Planning `WorldSpec`, `KinematicsSpec`, and `PlannerSpec` interfaces.
  - Drake planning world implementation and world monitor/preview integration.
  - Robot model/config parsing and model-to-planning config conversion.
- Blueprints/CLI:
  - Existing manipulation blueprints should continue for single serial arms through fallback group generation.
  - Ambiguous, branching, or multi-arm robots require SRDF rather than silent compatibility behavior.
- Skills/MCP:
  - Manipulation skills that call pose or joint planning must select planning groups explicitly or use wrapper defaults supplied by the skill layer.
- Hardware/simulation/replay:
  - Execution still sends projected trajectories to existing trajectory controller tasks.
  - Multi-task execution dispatches per-task trajectories; trajectory controllers own runtime concurrency.
  - No new hardware-safety behavior or atomic multi-task batch dispatch is introduced.
- Docs/generated registries:
  - User/developer docs for manipulation planning APIs, SRDF support, fallback generation, and joint naming need updates.
  - No generated blueprint registry changes are expected unless robot config/blueprint names change during implementation.

## Capabilities

### New Capabilities

- `manipulation-planning-groups`: Planning group discovery, selection, coordinated planning, IK target semantics, generated plans, and preview/execution projection.

### Modified Capabilities

- None. No existing OpenSpec capability specs are present in this repository checkout.

## Impact

This is a public manipulation planning API redesign. Existing code that plans by robot name or assumes bare local joint names will need migration to explicit planning group IDs and resolved joint names. Existing single-arm robots without SRDF should keep working through generated `{robot_name}/manipulator` groups if their configured controllable joints form one unambiguous serial chain.

The implementation needs tests for SRDF parsing, fallback generation, group resolution, resolved joint naming, IK with auxiliary groups, exact joint-target validation, multi-group planning result shape, and lazy preview/execution projection. Documentation should emphasize the distinction between robot identity, planning group identity, local model joint names, resolved joint names, and coordinator joint names.
