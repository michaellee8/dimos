## 1. Planning group data model and parsing

- [x] 1.1 Add planning group model types for definitions, descriptors, resolved groups, and generated plans.
- [x] 1.2 Add `srdf_path` to robot/model configuration and carry it through model-to-planning config conversion.
- [x] 1.3 Implement SRDF parsing for supported `<group><chain .../></group>` declarations.
- [x] 1.4 Implement SRDF parsing for ordered `<group><joint .../>...</group>` declarations that validate as one serial chain.
- [x] 1.5 Emit warnings and skip unsupported SRDF groups, including link groups, nested group references, mixed forms, and non-serial groups.
- [x] 1.6 Ignore SRDF `<end_effector>` metadata for planning group extraction.
- [x] 1.7 Implement conservative SRDF auto-discovery with visible warning after explicit `srdf_path` lookup fails or is absent.
- [x] 1.8 Implement fallback generation of `{robot_name}/manipulator` from `RobotModelConfig.joint_names` when no SRDF is available.
- [x] 1.9 Validate fallback as exactly one unambiguous serial chain, allowing middle prismatic joints and excluding only terminal/tip prismatic finger joints.
- [x] 1.10 Add unit tests for SRDF chain groups, joint-list groups, skipped unsupported groups, and fallback success/failure cases.

## 2. Naming and group resolution

- [x] 2.1 Add deterministic helpers for local model joint names to resolved joint names: `{robot_name}/{local_joint_name}`.
- [x] 2.2 Add inverse validation/stripping helper for backend internals that need local joint names.
- [x] 2.3 Update public joint-state/path surfaces above model parsing to use resolved joint names.
- [x] 2.4 Add `WorldSpec.list_planning_groups()` and return immutable planning group descriptor snapshots.
- [x] 2.5 Add `WorldSpec.resolve_planning_groups(...)` and bind definitions to concrete robot/world data.
- [x] 2.6 Validate unknown group IDs during resolution.
- [x] 2.7 Validate selected groups never overlap in resolved joints.
- [x] 2.8 Update Drake world internals to map resolved joint names to local joint names and model instances.
- [x] 2.9 Add focused tests for descriptors, stable IDs, resolved names, duplicate local joint disambiguation, unknown groups, and overlap rejection.

## 3. Group-scoped world and kinematics APIs

- [x] 3.1 Add group-scoped pose query API for planning groups with valid pose target frames.
- [x] 3.2 Add group-scoped Jacobian query API for planning groups with valid pose target frames.
- [x] 3.3 Preserve lower-level link pose querying for explicit robot/link lookups.
- [x] 3.4 Remove or deprecate robot-scoped end-effector FK/Jacobian APIs.
- [x] 3.5 Update `KinematicsSpec` to solve pose targets keyed by planning group plus request-scoped auxiliary groups.
- [x] 3.6 Ensure IK solves over the full effective selection and treats auxiliary group joints as free variables.
- [x] 3.7 Ensure `IKResult.solution` contains exactly selected resolved joints and excludes unrelated joints.
- [x] 3.8 Add tests for pose-targeted groups, auxiliary groups, no-target-frame rejection, and selected-joint-only IK results.

## 4. Planner APIs and generated plan flow

- [x] 4.1 Update planner APIs to accept planning group selection / resolved selected joints instead of a single `robot_id` planning target.
- [x] 4.2 Enforce exact start and goal `JointState` keys for joint-space planning: no missing, extra, or partial joints.
- [x] 4.3 Implement pose planning lowering from pose targets plus auxiliary groups to IK goal and combined joint-space planning.
- [x] 4.4 Allow backends to report `UNSUPPORTED` for coordinated planning problems they cannot solve.
- [x] 4.5 Add `GeneratedPlan` as the canonical returned planning artifact with selected group IDs and combined resolved-joint path.
- [x] 4.6 Ensure every `GeneratedPlan.path` waypoint contains exactly selected resolved joints.
- [x] 4.7 Replace robot-keyed planned path and planned trajectory caches in `ManipulationModule` with optional `_last_plan` convenience state.
- [x] 4.8 Add tests for joint target exactness, pose planning result shape, multi-group synchronized paths, backend unsupported reporting, and generated plan reuse.

## 5. Preview and execution projection

- [x] 5.1 Update preview APIs to accept an explicit `GeneratedPlan` and optionally fall back to `_last_plan` convenience state.
- [x] 5.2 Project generated plan paths lazily into visualization/world monitor calls.
- [x] 5.3 Update execution APIs to accept an explicit `GeneratedPlan` and optionally fall back to `_last_plan` convenience state.
- [x] 5.4 Project generated plan paths lazily into one `JointTrajectory` per affected coordinator trajectory task.
- [x] 5.5 Order projected trajectory positions according to each task's configured joint order.
- [x] 5.6 Convert resolved joint names to coordinator joint names at the execution boundary when a mapping exists.
- [x] 5.7 Keep trajectory controllers and coordinator tasks planning-group agnostic.
- [x] 5.8 Add tests for single-task execution projection, multi-task execution projection, task joint ordering, and preview projection.

## 6. Robot config migration and API cleanup

- [x] 6.1 Reframe planning-level `RobotConfig.base_link` and `RobotConfig.base_pose` usage as active compatibility behavior.
- [x] 6.2 Reframe planning-level `RobotModelConfig.base_link`, `RobotModelConfig.base_pose`, and `RobotModelConfig.end_effector_link` usage as active compatibility behavior.
- [x] 6.3 Keep and document `RobotConfig.joint_names` and `RobotModelConfig.joint_names` as controllable/coordinator joint sets, not planning groups.
- [x] 6.4 Update existing robot catalog/config entries to use SRDF where needed or rely on fallback for unambiguous single-chain arms.
- [x] 6.5 Update manipulation skills/wrappers to select planning groups explicitly or provide clear wrapper-level defaults.
- [x] 6.6 Run `pytest dimos/robot/test_all_blueprints_generation.py` if implementation changes blueprint names or generated registry inputs.

## 7. Documentation

- [x] 7.1 Update user-facing manipulation planning docs with planning group concepts, IDs, resolved joint names, and API examples.
- [x] 7.2 Document supported and unsupported SRDF forms plus skipped-group warning behavior.
- [x] 7.3 Document fallback generation rules and failure behavior for ambiguous robots.
- [x] 7.4 Document pose targets, auxiliary groups, joint targets, generated plans, preview, and execution flow.
- [x] 7.5 Update contributor docs or add a development note covering group resolution ownership, local/resolved naming, and controller boundaries.
- [x] 7.6 Update coding-agent docs or `AGENTS.md` only if implementation introduces recurring guidance beyond the existing design docs.

## 8. Verification

- [x] 8.1 Run `openspec validate add-planning-groups`.
- [x] 8.2 Run focused tests for robot config/model parsing changes.
- [x] 8.3 Run focused tests for planning group SRDF/fallback parsing.
- [x] 8.4 Run focused tests for `WorldSpec`/Drake world group resolution and group-scoped queries.
- [x] 8.5 Run focused tests for IK and planner selected-joint semantics.
- [x] 8.6 Run focused tests for `ManipulationModule` generated plan, preview, and execution projection.
- [x] 8.7 Run broader manipulation/planning pytest targets touched by the implementation.
- [x] 8.8 Run type checks for changed planning/manipulation modules if feasible: `uv run mypy dimos/` or a narrower supported target. Attempted narrow mypy; unavailable in this environment (`mypy` executable missing).
- [x] 8.9 Run docs validation commands for changed docs, including `uv run doclinks` if available.
- [x] 8.10 Run markdown snippet validation with `uv run md-babel-py run <changed-doc>` for docs containing executable Python examples, if available.
- [x] 8.11 Manually QA a single-arm no-SRDF fallback planning flow in replay or simulation. Covered by `dimos/e2e_tests/test_manipulation_planning_groups.py::test_single_arm_plans_and_executes_through_control_coordinator` using `openarm-mock-planner-coordinator` under `self_hosted_large`.
- [ ] 8.12 Manually QA an SRDF-backed chain group flow if a test fixture or robot config is available.
- [ ] 8.13 Manually QA arm-plus-auxiliary-group pose planning in simulation/replay if a suitable model is available.
- [x] 8.14 Manually QA a dual-arm planning flow by launching a dual-arm planning example, preferably OpenArm if available or another suitable dual-arm robot stack, then using the manipulation client to initiate one coordinated plan that selects both arms' planning groups and verifies the generated plan contains both arms' resolved joint names. Covered by `dimos/e2e_tests/test_manipulation_planning_groups.py::test_dual_arm_plans_and_dispatches_both_arms_through_control_coordinator` using `openarm-mock-planner-coordinator` under `self_hosted_large`.
