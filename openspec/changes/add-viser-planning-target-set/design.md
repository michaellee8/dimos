## Context

DimOS manipulation now treats planning groups as first-class planning units and stores successful results as `GeneratedPlan` artifacts over global joint names. Viser currently lags behind that model: the panel selects one robot, maintains one target, and delegates through robot-scoped convenience calls. That works for the single-arm case, but it does not express a coordinated dual-arm intent where `left_arm/manipulator` and `right_arm/manipulator` should be solved, checked, planned, previewed, and executed as one whole target set.

The current Viser implementation already has useful pieces: in-process adapter calls, target transform controls, joint sliders, preview animation, and `VisualizationSpec` integration through `WorldMonitor`. This change should preserve those pieces while changing their semantic unit from selected robot to planning target set.

Root `CONTEXT.md` defines the canonical language: Planning Group, Planning Group Selection, Auxiliary Planning Group, Planning Target Set, Generated Plan, Global Joint Name, and Robot Placement. This design follows those terms. For Viser placement, this change deliberately relies on URDF/xacro-authored placement and does not apply `RobotModelConfig.base_pose` inside Viser.

## Goals / Non-Goals

**Goals:**

- Make the Viser panel group-centric instead of robot-centric.
- Let users establish a Planning Target Set by selecting one or more planning groups.
- Show target gizmos keyed by Planning Group ID for selected pose-targetable groups.
- Treat auxiliary planning groups as normal target-set members without assigned gizmos.
- Make joint panels, IK, feasibility, planning, preview, execute, and freshness whole-set scoped.
- Normalize pose-authored targets into global joint targets via realtime whole-set IK.
- Add multi-target Pink IK behavior for same-robot multiple frame targets and cross-robot grouped solves.
- Keep planning, preview, and execution based on the whole `GeneratedPlan` for the target set.
- Preserve the single-robot workflow as the one-group target-set case.

**Non-Goals:**

- Do not add a new CLI command.
- Do not make Viser apply `base_pose` or infer backend weld behavior.
- Do not make IK collision-aware; collision validation and path collision avoidance remain WorldSpec/planner responsibilities.
- Do not add atomic multi-controller execution semantics beyond existing generated-plan projection/dispatch.
- Do not expose normal per-group or per-robot Plan/Preview/Execute controls in the target-set workflow.
- Do not require named left/right/dual-arm presets; a checklist plus “select all manipulators” is enough for the first UI.

## DimOS Architecture

### Viser panel and scene

The Viser panel should maintain a Planning Target Set state rather than a single selected robot state. The target set includes selected group IDs, target authoring state, last valid global target joints, whole-set status, diagnostics, plan freshness, and plan status.

Current robot visuals and preview ghosts remain robot-keyed because rendering a plan projects to whole robot models. Target transform controls become planning-group-keyed because pose targets belong to planning groups. A pose-targetable selected group gets a gizmo such as `/targets/left_arm/manipulator`; an auxiliary selected group participates without a gizmo.

The panel should display one unified Target Set joint panel, visually grouped by planning group. Per-group sections are views into one target set, not independent state machines. The action row operates on the whole set.

### ManipulationModule and adapter boundary

Viser should not implement IK or target-set feasibility semantics directly. The in-process adapter should expose whole-set operations backed by `ManipulationModule`, such as:

- evaluate pose targets for a planning target set;
- evaluate joint targets for a planning target set;
- plan the current target set through joint-target planning;
- preview and execute the current whole generated plan.

Evaluation results should use global joint names as the semantic output. Viser may display local labels inside group sections, but the returned target joint state must be unambiguous and directly usable by planning APIs.

Pose-authored targets should normalize to joint targets before planning. The panel should call pose target set evaluation during gizmo edits, update the last valid target joints, then call joint target planning when the user plans. Joint edits should call joint target set evaluation, update pose gizmos through FK where available, and update whole-set feasibility.

### Pink IK

Pink IK should expose one multi-target pose solve behavior while grouping internally by robot model:

- Same-robot multiple pose targets: solve one Pink configuration with multiple frame tasks.
- Cross-robot pose targets: solve one Pink problem per robot model and combine the results into one global selected joint target.

Auxiliary groups participate in the selected joints and seed/target vector but do not receive direct frame tasks. They are still solved, checked, planned, previewed, and executed with the whole target set.

IK should use the last valid target joints as the seed after target-set initialization. When a group is selected, its target initializes from current state. On IK failure, keep the last valid target joints, mark the whole target set invalid/stale, and disable planning.

### Planning and execution

Planning remains joint-target based after target-set evaluation. The whole target set lowers to `plan_to_joint_targets(...)` keyed by planning group. Preview and execute operate on the full generated plan without normal robot filtering in the panel.

Plan freshness is whole-set scoped. When planning succeeds, store a current-joint snapshot for all selected groups. Execution is enabled only if current selected-group joints still match that snapshot within tolerance.

### Blueprints and streams

No stream contract changes are expected. Existing xArm planner/coordinator blueprints remain the manual QA target. Viser should work with `xarm7-planner-coordinator` and dual xArm mock planner/coordinator through visualization config overrides.

### Skills/MCP and generated registries

No skill/MCP tool contract changes are expected. No blueprint registry regeneration is expected unless implementation changes blueprint definitions.

## Decisions

1. **Use Planning Target Set as the UI semantic unit.**
   - Rationale: Once groups are selected, independent per-group UI state causes discrepancies between IK, feasibility, planning, and execution.
   - Alternative rejected: separate group cards with independent status/actions.

2. **Keep Viser placement URDF-authored.**
   - Rationale: xArm xacro already encodes attachment placement. Applying `base_pose` in Viser risks double placement and duplicates Drake weld heuristics.
   - Alternative rejected: backend placement inference in Viser.

3. **Key target gizmos by Planning Group ID.**
   - Rationale: pose targets belong to planning groups, not robots. This avoids a future mismatch for robots with multiple pose-targetable groups.
   - Alternative rejected: robot-keyed target controls.

4. **Plan through joint targets after evaluation.**
   - Rationale: The panel can use pose gizmos naturally while the planner receives one uniform global joint target set.
   - Alternative rejected: separate UI modes for pose planning and joint planning.

5. **Group Pink multi-target solving by robot internally.**
   - Rationale: Same-robot multi-frame targets need one Pink configuration. Cross-robot targets can be solved per model and combined without building a combined Pinocchio model.
   - Alternative deferred: building one combined Pink model across robots.

6. **Whole-set status is canonical.**
   - Rationale: The Plan button must not be enabled because individual group sections look valid while the combined target set is invalid.
   - Alternative rejected: per-group canonical statuses.

## Safety / Simulation / Replay

Execution remains gated by existing Viser configuration (`allow_plan_execute`) and manipulation module state. The panel should not execute unless the whole plan is fresh and current selected-group joints match the planning start snapshot.

Collision checking remains outside IK and in WorldSpec/planner behavior. IK may return kinematically valid targets that planning later rejects due to collision or unavailable path. The UI must surface this as whole-set planning failure, not per-group success.

Manual QA should use mock xArm blueprints first, especially `xarm7-planner-coordinator` and the dual xArm planner/coordinator, before any hardware test. Hardware tests must keep execution explicitly opt-in.

Replay behavior is not expected to change except that Viser target-set state should consume the same current joint states as the existing panel.

## Risks / Trade-offs

- **Realtime IK cost:** Whole-set IK on every gizmo drag can be expensive. Use latest-request-wins and debounce behavior in the existing evaluation worker pattern.
- **State complexity:** The panel state becomes richer. Mitigate by making Planning Target Set the only authoritative UI state and treating per-group displays as projections.
- **Pink multi-frame correctness:** Same-robot multi-frame IK needs careful frame-task construction and result filtering. Add focused tests before relying on the UI.
- **Cross-robot IK limitation:** Cross-robot grouping combines independent kinematic solves. Inter-robot collision is handled by planning, not IK, so some targets may solve IK but fail planning.
- **Docs drift:** `add-planning-groups` artifacts still contain older terms such as ResolvedPlanningGroup. This change should use current glossary language and avoid reviving stale terms.

## Migration / Rollout

1. Add target-set evaluation structures and module/adapter methods while preserving single-group behavior.
2. Update Pink IK multi-target behavior with focused tests.
3. Rework Viser panel state and scene target controls to use planning group IDs.
4. Keep existing single-arm Viser interactions working as one selected group.
5. Add dual xArm mock tests and manual QA.
6. Update user-facing documentation for the target-set workflow.

Rollback can keep the current single-robot panel path if target-set UI is implemented behind a small internal adapter seam, but the final intended state should be group-centric only.

## Open Questions

- Exact Python location/name for the target-set evaluation result type.
- Whether target-set evaluation should be public RPC or only in-process adapter/module API initially.
- How much debouncing is needed for realtime whole-set IK with real robots and larger target sets.
