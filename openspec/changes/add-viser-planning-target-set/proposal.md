## Why

The current Viser manipulation panel is robot-centric: it selects one robot, edits one target, and plans through robot-scoped compatibility APIs. That is not sufficient for dual-arm and multi-group manipulation, where the user intent is a single coordinated target over a planning group selection such as `left_arm/manipulator` plus `right_arm/manipulator`.

DimOS now has first-class planning groups and generated plans over global joint names. Viser should expose that model naturally: users select a set of planning groups, edit pose gizmos or joint targets as one target set, and plan/preview/execute one whole generated plan. This also creates a clear path for natural pose-based bimanual planning through multi-target Pink IK.

## What Changes

- Add a Viser **Planning Target Set** workflow built on planning group selection rather than selected robot.
- Show planning-group-keyed target gizmos for selected pose-targetable groups.
- Treat auxiliary planning groups as members of the same target set without direct gizmo targets.
- Normalize pose-authored targets through whole-set IK into global joint targets, then plan through joint-target planning.
- Add whole-set evaluation semantics for IK, FK/target pose updates, feasibility, plan freshness, preview, and execute.
- Extend Pink IK to support multi-target pose evaluation through one unified API:
  - same-robot targets use one Pink solve with multiple frame tasks;
  - cross-robot targets are grouped by robot and combined into one global selected joint target.
- Keep collision validation and collision-free path planning in WorldSpec/planner responsibilities, not in IK semantics.
- Keep Viser robot placement URDF-authored for this change; do not infer or apply `base_pose` in Viser.

## Affected DimOS Surfaces

- Modules/streams:
  - `ManipulationModule` target evaluation helpers and Viser-facing adapter surface.
  - Manipulation planning group registry and group-target evaluation paths.
  - Pink IK pose-target solving behavior.
  - Viser visualization panel, scene target controls, and runtime state.
- Blueprints/CLI:
  - No new CLI command is expected.
  - Existing xArm planner/coordinator blueprints should be usable with Viser for single-arm and dual-arm mock validation.
- Skills/MCP:
  - No direct MCP skill behavior change is expected.
- Hardware/simulation/replay:
  - Dual-arm mock xArm planning should support group-target-set preview and planning in Viser.
  - Hardware execution remains gated by existing execution controls and coordinator behavior.
- Docs/generated registries:
  - Update manipulation/Viser usage docs if present.
  - Update OpenSpec/docs language to reflect Planning Target Set and multi-target Pink IK.

## Capabilities

### New Capabilities

- `viser-planning-target-set`: Viser UI behavior for selecting planning groups, authoring whole-set targets, evaluating target sets, and planning/previewing/executing generated plans.

### Modified Capabilities

- `manipulation-planning-groups`: Planning group workflows gain whole-set target authoring/evaluation semantics and multi-target Pink IK support.

## Impact

Users get a natural dual-arm Viser workflow: select both arm planning groups, manipulate group-keyed target gizmos, watch the whole target set solve to joint targets, then plan/preview/execute one generated plan. Developers get a cleaner module/UI boundary where Viser owns editing state and `ManipulationModule` owns target-set semantics.

Compatibility risks are mostly UI/API surface changes around the in-process Viser adapter and target evaluation helpers. Existing single-robot Viser workflows should remain usable as the one-group case of the target-set workflow. Testing should cover single-arm regression, dual xArm mock target-set selection, group-keyed gizmo visibility, whole-set IK failure/freshness behavior, Pink multi-target IK, and plan/preview/execute whole-set scope.
