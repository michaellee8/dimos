# Planning Groups Design

## 1. Summary

This change makes **Planning Group** a first-class manipulation planning concept in DimOS.

Today, manipulation planning is centered on robot identity: planner and IK interfaces select a `WorldRobotID`, while `RobotModelConfig` carries one `joint_names`, one `base_link`, and one `end_effector_link`. That shape works for a single serial arm, but it conflates robot/model identity with the kinematic subset being planned.

The new design separates those concerns:

- Robot identity describes the hardware/model instance.
- Planning group identity describes the selectable kinematic planning unit.
- SRDF `<group>` declarations are the primary source of planning groups.
- Existing single-chain robots without SRDF can continue through conservative fallback generation of `{robot_name}/manipulator`.
- Planning and IK APIs select planning groups, not robot IDs.
- Pose planning supports request-scoped auxiliary groups, such as torso/waist joints that contribute free DOFs without direct pose constraints.
- Generated plans store only selected group IDs and one synchronized resolved-joint path.
- Preview and execution project from that generated plan lazily.

The design also standardizes public joint naming above model parsing: all public joint states and paths use resolved joint names of the form `{robot_name}/{local_joint_name}`.

## 2. Motivation

Current manipulation planning treats a robot instance as the planning unit. `PlannerSpec.plan_joint_path(...)`, `KinematicsSpec.solve(...)`, and several `WorldSpec` methods all center on `WorldRobotID`. `ManipulationModule` also stores planned paths and trajectories by `RobotName`.

That makes several important cases awkward:

- Arm-only planning versus torso+arm planning.
- Coordinated dual-arm planning.
- Future multi-robot coordinated planning.
- Robots with multiple selectable serial chains.
- Explicit distinction between controllable joints and planning groups.

The current `RobotModelConfig` fields also hide planning-group semantics. A single `end_effector_link` and `base_link` imply one planning chain per robot config. A single `joint_names` list currently acts like a hidden planning group, while also serving as the controllable/coordinator joint set.

Finally, local URDF joint names are ambiguous once multiple robots or arms with repeated names participate in one plan. Public state/path APIs need stable resolved names so a path can represent coordinated multi-group or multi-robot motion without relying on external robot scoping.

## 3. Goals and Non-Goals

### Goals

- Make planning groups first-class planning units.
- Use SRDF `<group>` declarations as the primary source of planning group definitions.
- Provide conservative fallback generation for current single-chain arms without SRDF.
- Require explicit planning group selection for planning and IK.
- Support coordinated planning over one or more selected planning groups.
- Support pose planning with request-scoped auxiliary groups that contribute free DOFs.
- Expose stable resolved joint names above model/SRDF parsing.
- Add group-aware IK and planner interfaces.
- Replace robot-scoped end-effector FK/Jacobian queries with group-scoped APIs.
- Store minimal generated plan artifacts and project lazily for preview/execution.
- Keep existing trajectory controllers unaware of planning groups.

### Non-Goals

- Full MoveIt SRDF support.
- First-class composite or nested planning groups.
- Mixed pose+joint target planning in one request.
- Atomic multi-task trajectory batch dispatch.
- Rollback-on-rejection for multi-task trajectory dispatch.
- Planning config placement transforms such as `base_pose`.
- Silent compatibility mode that treats old `joint_names` as an implicit planning group without validation.
- Making controllers, coordinator tasks, or hardware drivers planning-group-aware.

## 4. Domain Model

Root `CONTEXT.md` contains the canonical glossary for this change. The core design shape is:

```text
PlanningGroupDefinition
  model-level declaration from SRDF or fallback generation
        ↓ bind to concrete robot/world
ResolvedPlanningGroup
  runtime/world-bound group with resolved joints and link frames
        ↓ selected by request
PlanningGroupSelection
  one or more non-overlapping resolved groups
        ↓ IK/planner solve
GeneratedPlan
  selected group IDs + synchronized resolved-joint path
```

Important terms:

- **Planning Group**: named selectable serial kinematic chain of robot joints used as the manipulation planning unit.
- **Planning Group Definition**: model-level declaration before binding to a concrete robot/world.
- **Resolved Planning Group**: runtime/world-bound group with concrete robot identity, namespace, resolved joints, and frame data.
- **Planning Group Selection**: one or more planning groups chosen for a planning request.
- **Auxiliary Planning Group**: group selected in a specific pose-planning request without receiving a direct pose constraint in that request.
- **Planning Group ID**: public identifier, always `{robot_name}/{group_name}`.
- **Planning Group Descriptor**: immutable query snapshot describing an available planning group; not a live handle.
- **Local Model Joint Name**: name inside URDF/SRDF, such as `joint1`.
- **Resolved Joint Name**: public world-level name, always `{robot_name}/{local_joint_name}`.

Identifier layering:

```text
robot_name          Stable robot/model instance name.
WorldRobotID        Internal runtime world handle only.
PlanningGroupID     {robot_name}/{group_name}
Local joint name    joint1
Resolved joint name {robot_name}/{local_joint_name}
Coordinator name    Hardware/control boundary name; default identity with resolved name.
```

`WorldRobotID` must not appear in public state, path, generated plan, or planning group selection APIs.

## 5. Planning Group Sources

Planning group definitions are discovered in this precedence order:

1. Explicit `srdf_path` on robot/model config.
2. Conservative SRDF auto-discovery with visible warning.
3. Fallback single-chain generation.
4. Error if no supported SRDF groups exist and fallback cannot infer exactly one unambiguous serial chain.

Supported SRDF forms for this change:

```xml
<group name="arm">
  <chain base_link="base_link" tip_link="tool0"/>
</group>
```

```xml
<group name="arm">
  <joint name="joint1"/>
  <joint name="joint2"/>
  <joint name="joint3"/>
</group>
```

Unsupported forms are skipped with warnings:

- `<link>` groups.
- Nested `<group>` references.
- Mixed link/joint/chain forms.
- Branching, disconnected, unordered, or otherwise non-serial groups.
- SRDF `<end_effector>` metadata.

If a caller later selects a skipped group, resolution fails as unknown or unsupported.

## 6. Fallback Group Generation

When no SRDF is available, DimOS may generate exactly one planning group:

```text
group name: manipulator
group ID:   {robot_name}/manipulator
```

Fallback rules:

- Use `RobotModelConfig.joint_names` as the candidate controllable set.
- Validate that candidate joints form one unambiguous serial chain in the parsed model.
- Allow prismatic joints inside the serial chain.
- Exclude only terminal/tip prismatic joints when they are likely finger/gripper joints.
- Set fallback pose target tip to the last controlled chain link.
- Error for ambiguous, branching, disconnected, or multi-chain models; such robots require SRDF.

This preserves current single serial arm behavior without pretending every robot's `joint_names` list is a valid planning group.

## 7. End-Effector Semantics

A planning group is defined by chain/joints, not by SRDF `<end_effector>` metadata. This change ignores SRDF `<end_effector>` entirely.

Rules:

- Chain-defined group: pose target frame is the chain `tip_link`.
- Explicit joint-list group: may have a pose target frame only if validation proves it is one serial chain with a unique tip.
- Group with no valid tip: may participate in joint planning or as an auxiliary group, but cannot be directly pose-targeted.

Pose-targeted APIs validate only targeted groups. Auxiliary groups do not need to be pose-ineligible; auxiliary status is request-scoped. A group may have a tip and still be auxiliary in a particular request.

## 8. Public Planning APIs

Representative API shape for pose targets:

```python
plan_to_poses(
    pose_targets: Mapping[PlanningGroupID | PlanningGroupDescriptor, PoseStamped],
    *,
    auxiliary_groups: Sequence[PlanningGroupID | PlanningGroupDescriptor] = (),
) -> GeneratedPlan
```

Meaning:

- `pose_targets` are selected groups with end-effector pose constraints in this request.
- `auxiliary_groups` are selected groups with no pose constraint in this request.
- Effective selection is `pose_targets.keys() ∪ auxiliary_groups`.
- Auxiliary groups are free DOFs for IK and planning.
- Mixed pose+joint targets are not supported in this change.

Example:

```python
plan_to_poses(
    pose_targets={"robot/arm": target_pose},
    auxiliary_groups=["robot/torso"],
)
```

This plans one coordinated problem over arm and torso joints. The arm tip must reach `target_pose`; torso joints are free to move as needed.

Representative API shape for joint targets:

```python
plan_to_joint_targets(
    joint_targets: Mapping[PlanningGroupID | PlanningGroupDescriptor, JointState],
) -> GeneratedPlan
```

Rules:

- Joint targets are keyed by planning group at the API boundary.
- Each group's joint target keys must exactly match that group's selected resolved joints.
- Internally the request lowers to one ordered combined resolved-joint start/goal problem.

Planning APIs may accept either a Planning Group ID string or a Planning Group Descriptor. Descriptors are ergonomic immutable snapshots. APIs normalize descriptors by extracting their ID and re-resolving current runtime group data.

## 9. Spec Interface Changes

This section refers to DimOS Python `Spec` Protocols, not OpenSpec behavior specs.

### WorldSpec

`WorldSpec` owns planning group listing and resolution:

```python
list_planning_groups() -> Sequence[PlanningGroupDescriptor]
resolve_planning_groups(group_ids: Sequence[PlanningGroupID]) -> Sequence[ResolvedPlanningGroup]
```

Resolution responsibilities:

- Validate IDs are known.
- Bind model-level definitions to concrete robot/world data.
- Convert local model joint names to resolved joint names.
- Detect overlapping resolved joints across selected groups and fail.
- Return enough resolved data for IK/planner/backend internals to map back to local names and model instances.

Group-scoped query APIs replace robot-scoped end-effector APIs:

```python
get_group_pose(ctx, group_id) -> PoseStamped
get_group_jacobian(ctx, group_id) -> ...
```

These are valid only for groups with a pose target frame. `get_link_pose(ctx, robot_id, link_name)` remains as a lower-level query.

### KinematicsSpec

IK must solve over the full effective planning group selection:

```python
solve_pose_targets(
    world: WorldSpec,
    pose_targets: Mapping[PlanningGroupID | PlanningGroupDescriptor, PoseStamped],
    *,
    auxiliary_groups: Sequence[PlanningGroupID | PlanningGroupDescriptor] = (),
    seed: JointState | None = None,
    tolerances: PoseTolerance | None = None,
    check_collision: bool = True,
    max_attempts: int = 1,
) -> IKResult
```

IK constraints apply only to `pose_targets`. Auxiliary group joints are decision variables with no direct pose constraints. `IKResult.solution` contains exactly the selected resolved joints, not full robot/world state.

### PlannerSpec

Planner APIs operate over selected groups / resolved selected joints rather than a single `robot_id`.

For joint planning:

- Start and goal `JointState` keys must exactly equal selected resolved joints.
- Missing keys, extra keys, or partial goals fail early.

For pose planning:

- IK returns a selected-joint goal.
- The planner solves one combined joint-space problem from selected-joint start to selected-joint goal.

Backends may return or raise `UNSUPPORTED` for backend limitations, including cross-robot coordinated planning. The public interface permits multi-robot selections.

## 10. State, Naming, and Exactness Rules

Above the model/SRDF parsing layer, all joint states use resolved joint names:

```text
{robot_name}/{local_joint_name}
```

Examples:

```text
left/joint1
right/joint1
a750/joint3
```

Local names remain inside URDF/SRDF parsing and backend internals. Backends may strip the robot namespace and use `(local_joint_name, model_instance)` internally.

Exactness rules:

- Joint-space start keys must exactly equal selected resolved joints.
- Joint-space goal keys must exactly equal selected resolved joints.
- No missing selected joints.
- No extra joints.
- No partial targets.
- `IKResult.solution.keys()` equals selected resolved joints.
- `PlanningResult.path[i].keys()` equals selected resolved joints for every waypoint.

These rules prevent silently planning for the wrong group or ignoring caller-supplied joints.

## 11. Generated Plan Model

`GeneratedPlan` is the canonical planning artifact:

```python
GeneratedPlan:
    group_ids: tuple[PlanningGroupID, ...]
    path: list[JointState]
    status: PlanningStatus
    planning_time: float | None
    path_length: float | None
    iterations: int | None
    message: str
```

`GeneratedPlan.path[i]` contains exactly the selected resolved joints for every waypoint.

The plan does not store:

- Per-robot paths.
- Per-task trajectories.
- Preview samples.
- Live world/planner handles.
- Controller-specific execution plans.

`ManipulationModule` may keep `_last_plan: GeneratedPlan | None` as convenience state, but the returned plan object is canonical.

## 12. Preview and Execution Projection

Preview and execution project lazily from `GeneratedPlan`.

### Preview

`preview_plan(plan)`:

- Uses the selected resolved-joint path.
- Projects into visualization/world monitor data as needed.
- Does not require execution-specific trajectory precomputation.

### Execution

`execute_plan(plan)`:

1. Group resolved joint names by robot namespace/coordinator task.
2. Project the combined path into one `JointTrajectory` per affected trajectory task.
3. Order trajectory positions according to the task's configured joint order.
4. Convert resolved joint names to coordinator joint names if a boundary mapping exists.
5. Invoke each trajectory task.

The current coordinator/JTC architecture already treats task invocation as asynchronous dispatch. JTCs run concurrently in the coordinator tick loop. This change does not add atomic batch dispatch, rollback-on-rejection, or a new execution batch abstraction.

Planning groups do not enter the controller layer. Controllers consume joint-name-keyed trajectories.

## 13. Migration Plan

Configuration changes:

- Add `srdf_path` to `RobotConfig`.
- Add `srdf_path` to `RobotModelConfig`.
- Store parsed planning group definitions on `RobotModelConfig`.
- Keep `RobotConfig.joint_names` and `RobotModelConfig.joint_names`, but define them as the controllable/coordinator joint set, not a planning group.

Fields removed or deprecated under the new design:

- `RobotConfig.base_link`
- `RobotConfig.base_pose`
- `RobotModelConfig.base_link`
- `RobotModelConfig.base_pose`
- `RobotModelConfig.end_effector_link`

Implementation rollout:

1. Add planning group data model and SRDF/fallback extraction.
2. Add deterministic local/resolved joint-name helpers.
3. Update `WorldSpec` and Drake world to list and resolve planning groups.
4. Add group-scoped pose/Jacobian APIs.
5. Update `KinematicsSpec` and IK implementation to solve selected pose targets plus auxiliary free groups.
6. Update `PlannerSpec` and planner implementation to operate over selected resolved joints.
7. Replace `ManipulationModule` robot-keyed planned path/trajectory caches with `GeneratedPlan` and optional `_last_plan`.
8. Update preview and execution projection.
9. Update manipulation skills/wrappers and documentation.
10. Update existing robot configs; rely on fallback for current single serial arms unless SRDF is added.

Generated registry updates are not expected unless implementation changes blueprint names or adds/removes blueprint module-level variables. If that happens, run:

```bash
pytest dimos/robot/test_all_blueprints_generation.py
```

## 14. Validation and Errors

Validation should fail clearly for:

- Unknown planning group ID.
- Unsupported selected SRDF group form.
- Fallback cannot infer one serial chain.
- Selected planning groups overlap in resolved joints.
- Pose-targeted group has no valid tip/pose target frame.
- Joint target keys do not exactly match selected group joints.
- Start/goal joint states contain missing or extra selected joints.
- Backend does not support the requested coordinated planning problem.
- Cross-robot coordinated planning requested on a backend that cannot support it.

Warnings should be emitted for:

- SRDF auto-discovery.
- Unsupported SRDF groups skipped during parsing.

Manual QA should cover:

- Single-arm no-SRDF fallback planning.
- SRDF chain group planning.
- SRDF joint-list group planning.
- Arm+torso pose planning where torso is auxiliary/free.
- Multi-group result shape and no-overlap validation.
- Multi-task execution projection with distinct joint namespaces.

## 15. Alternatives Considered

- **Composite groups as first-class objects**: rejected. Selecting multiple groups per request is enough and avoids duplicate group modeling.
- **Bare group names**: rejected. Planning Group IDs are always namespaced as `{robot_name}/{group_name}`.
- **Robot-scoped planning API**: rejected. Robot identity and planning group selection are separate concerns.
- **Full SRDF support**: deferred. This change supports only serial chain and ordered joint-list groups.
- **Parsing SRDF `<end_effector>`**: rejected for this change. Group pose target frame comes from chain/joint validation, not end-effector metadata.
- **Implicit default planning group**: rejected. Planning group selection is required.
- **Treating old `joint_names` as a compatibility planning group**: rejected unless it validates through conservative fallback.
- **`include_groups` with implicit semantics**: rejected in favor of request-scoped `auxiliary_groups`.
- **Enforcing auxiliary groups to be joint-only/no-EEF**: rejected. Auxiliary status belongs to the request, not the group definition.
- **Mixed pose+joint constraints now**: deferred.
- **Precomputed execution plans**: rejected. Generated plans stay minimal; downstream projections happen lazily.
- **Atomic multi-task trajectory dispatch**: deferred. Existing task invocation is acceptable for now.

## 16. Rollout / Implementation Phases

Suggested implementation phases:

1. **Data model and parsing**
   - Add planning group definition/descriptor/resolved-group types.
   - Add SRDF path fields.
   - Implement supported SRDF group parsing.
   - Implement fallback generation.

2. **World resolution**
   - Add `WorldSpec.list_planning_groups()` and `resolve_planning_groups(...)`.
   - Update Drake world to bind group definitions to model instances and resolved names.
   - Add overlap validation.

3. **Group-scoped kinematics queries**
   - Add `get_group_pose(...)` and `get_group_jacobian(...)`.
   - Remove/deprecate robot-scoped end-effector queries.

4. **IK and planner interfaces**
   - Update IK to accept pose targets plus auxiliary groups.
   - Update planner to operate over selected resolved joints.
   - Enforce exact start/goal key rules.

5. **Generated plan flow**
   - Add `GeneratedPlan`.
   - Replace robot-keyed planned path/trajectory caches.
   - Store only optional `_last_plan` convenience state.

6. **Preview and execution projection**
   - Project generated plans to visualization as needed.
   - Project generated plans to per-task `JointTrajectory` at execution time.

7. **Robot config migration and docs**
   - Update existing robot configs.
   - Add docs for SRDF support, fallback generation, APIs, and naming rules.
   - Update manipulation skills/wrappers.

## 17. Safety / Simulation / Replay

This is primarily a planning API and modeling change. It should not change low-level trajectory controller semantics.

Hardware-facing assumptions:

- Execution still sends `JointTrajectory` messages to existing coordinator trajectory tasks.
- Affected trajectory tasks control disjoint resolved/coordinator joint sets.
- Multi-task dispatch is fast and non-blocking.
- Trajectory tasks execute concurrently in the coordinator tick loop.
- No new hardware-safety behavior, rollback, or atomic all-or-nothing dispatch is introduced.

Simulation and replay should mirror hardware behavior because group resolution and generated plan projection happen above hardware drivers. Existing single-arm simulation/replay stacks should continue through fallback if they form one unambiguous serial chain.

## 18. Risks / Trade-offs

- **API breakage:** Existing callers plan by robot name or robot ID. Mitigation: provide migration docs and temporary wrapper conveniences where appropriate.
- **Partial SRDF support confusion:** Users may expect full MoveIt SRDF semantics. Mitigation: warn on skipped groups and document supported forms clearly.
- **Fallback misclassification:** Terminal prismatic stripping may accidentally exclude a real controllable prismatic axis. Mitigation: fallback only applies to unambiguous single chains; SRDF is required for precise modeling.
- **Joint naming migration cost:** Resolved names require updates across planner results, state monitors, and execution projection. Mitigation: deterministic helper conversion and strict layering.
- **Backend capability mismatch:** Some planners may not support multi-robot coordinated planning. Mitigation: allow `UNSUPPORTED` while preserving interface semantics.
- **Dispatch skew for multiple trajectory tasks:** Sequential task invocation can create tiny start-time differences. Mitigation: accepted for now; future coordinator batch dispatch can address this if needed.

## 19. Open Questions

- Exact error/status enum names for unsupported groups, no target frame, overlapping groups, and backend-unsupported problems.
- Exact temporary compatibility wrappers, if any, for existing manipulation skill APIs.
- Whether to write a short ADR for removing planning config placement fields in favor of URDF/model placement.
- Whether future coordinator-level `execute_batch(...)` is needed for tighter multi-task synchronization.

## Appendix: Design Q&A Summary

- **Term:** Use Planning Group; avoid Move Group/movegroup.
- **Ownership:** Define groups at model/config level; resolve to runtime/world-bound groups.
- **Composites:** Do not create composite groups now; select multiple groups per request.
- **Multi-group meaning:** One coordinated joint-space problem and one synchronized result.
- **End effectors:** Groups are defined by chain/joints, not SRDF `<end_effector>` metadata.
- **Group declaration:** Support chain or ordered joint list; validate as serial chain.
- **Default selection:** Planning group selection is required; no implicit default selection.
- **IDs:** Planning Group ID is always `{robot_name}/{group_name}`.
- **Descriptors:** Query APIs return immutable snapshots, not live handles.
- **Selectors:** APIs may accept group ID strings or descriptors; no dedicated selector type.
- **Joint goals:** Joint target APIs are keyed by planning group at API boundary, then lowered to one ordered resolved-joint problem.
- **Resolution:** `WorldSpec` owns group listing/resolution; planner delegates resolution to world.
- **Joint state exactness:** Joint-space start/goal keys must exactly equal selected resolved joints.
- **Source of truth:** SRDF first, conservative fallback only when no SRDF is present.
- **Fallback name:** Generated group is `manipulator`.
- **Fallback source:** Use `RobotModelConfig.joint_names` as candidate controllable joints.
- **Prismatic joints:** Middle prismatic joints are allowed; terminal/tip prismatic finger joints may be excluded.
- **SRDF scope:** Parse `<group>` only; ignore `<end_effector>`.
- **Unsupported SRDF:** Skip unsupported group forms with warnings.
- **SRDF discovery:** Explicit path, then warning auto-discovery, then fallback, then error.
- **Config fields:** Add `srdf_path`; remove planning-level `base_link`, `end_effector_link`, and `base_pose` in the new design.
- **Robot placement:** Placement belongs in URDF/model, not separate planning config transforms.
- **FK/Jacobian:** Replace robot-scoped end-effector APIs with group-scoped APIs.
- **Cross-robot planning:** Interface allows it; backends may report unsupported.
- **Overlaps:** Selected groups must never overlap in resolved joints.
- **Result shape:** `PlanningResult.path` remains combined and synchronized.
- **Stored plan:** Store selected group IDs and path only; project lazily for preview/execution.
- **Resolved naming:** Above parsing, use `{robot_name}/{local_joint_name}` everywhere.
- **Coordinator mapping:** Coordinator names are a control-boundary concern; default identity with resolved names.
- **Auxiliary groups:** Auxiliary means selected without pose constraint in this request only.
- **Auxiliary DOFs:** Auxiliary groups are free DOFs for pose planning.
- **Mixed targets:** No mixed pose+joint target API in this change.
- **IK:** IK solves over pose-targeted groups plus auxiliary groups.
- **IK result:** `IKResult.solution` contains exactly selected resolved joints.
- **Planning result:** `PlanningResult.path` contains exactly selected resolved joints.
- **Execution:** Split path by trajectory task and send to existing JTCs; no new batch/rollback semantics.
- **Generated plan:** Returned plan object is canonical; module last-plan storage is convenience.
