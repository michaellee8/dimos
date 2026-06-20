## 1. Target-set evaluation model and module boundary

- [x] 1.1 Define a target-set evaluation result shape with whole-set status, message, group IDs, global target joints, optional group diagnostics, and pose outputs for pose-targetable groups.
- [x] 1.2 Add ManipulationModule whole-set pose evaluation for `Mapping[PlanningGroupID, PoseStamped]` plus auxiliary group IDs, returning global selected joint targets.
- [x] 1.3 Add ManipulationModule whole-set joint evaluation for `Mapping[PlanningGroupID, JointState]`, including exact target validation and FK pose outputs for pose-targetable groups.
- [x] 1.4 Update the in-process Viser adapter to expose whole-set evaluation, target-set planning, whole-plan preview, and whole-plan execution helpers.
- [x] 1.5 Preserve existing one-robot behavior as the one-planning-group target-set case.

## 2. Pink multi-target IK

- [x] 2.1 Extend Pink IK pose-target solving to accept multiple pose-targeted planning groups in one request.
- [x] 2.2 Implement same-robot multi-frame Pink solving with multiple frame tasks in one Pink configuration.
- [x] 2.3 Implement cross-robot grouping for Pink IK by solving per robot model and combining results into one global selected joint target.
- [x] 2.4 Ensure auxiliary planning groups participate in the selected joints and seed/target result without receiving direct frame tasks.
- [x] 2.5 Keep collision semantics outside IK; surface kinematic success separately from collision/path-planning success.
- [x] 2.6 Add Pink IK tests for single-target regression, same-robot multi-frame targets, cross-robot targets, auxiliary groups, and global joint-name output.

## 3. Viser target-set UI and scene

- [x] 3.1 Replace robot-centric panel state with Planning Target Set state: selected group IDs, pose targets, global target joints, last valid target joints, whole-set status, diagnostics, plan status, and start snapshots.
- [x] 3.2 Add a planning-group checklist and a select-all-manipulators action.
- [x] 3.3 Make target controls planning-group-keyed; show gizmos only for selected pose-targetable groups and hide gizmos for unselected or auxiliary-only groups.
- [x] 3.4 Render one grouped Target Set joint panel with sections per selected planning group and one whole-set status/action row.
- [x] 3.5 Make pose gizmo edits trigger latest-request-wins whole-set IK evaluation, updating target joints on success and keeping last valid target joints on failure.
- [x] 3.6 Make joint edits trigger whole-set joint evaluation and update visible pose gizmos through FK outputs.
- [x] 3.7 Make Plan/Preview/Execute/Clear actions operate on the whole target set, with no normal per-robot or per-group action controls.
- [x] 3.8 Keep Viser robot placement URDF-authored; do not apply `base_pose` during scene registration.

## 4. Documentation

- [x] 4.1 Update manipulation/Viser user documentation with the Planning Target Set workflow and xArm launch examples.
- [x] 4.2 Document auxiliary groups as selected target-set members without assigned gizmos.
- [x] 4.3 Document that Viser uses URDF-authored placement and does not implicitly apply `base_pose`.
- [x] 4.4 Update contributor/coding-agent docs only if they currently describe robot-centric Viser planning or per-robot preview/execute state.

## 5. Verification

- [x] 5.1 Run `openspec validate add-viser-planning-target-set`.
- [x] 5.2 Run focused Pink IK tests, including new multi-target cases.
- [x] 5.3 Run focused Viser tests for target-set state, group-keyed gizmos, whole-set status, plan freshness, and whole-plan preview/execute actions.
- [x] 5.4 Run manipulation unit tests covering module whole-set evaluation and planning through joint targets.
- [ ] 5.5 Run xArm single-robot Viser manual QA with `xarm7-planner-coordinator` to verify the one-group workflow still works.
- [ ] 5.6 Run dual xArm mock Viser manual QA to verify selecting both manipulators, moving both gizmos, planning, previewing, and clearing the whole target set.
- [x] 5.7 Run docs validation commands for changed docs, including `doclinks` when available and `md-babel-py run <changed-doc>` for executable snippets.
- [x] 5.8 Run ruff/focused lint checks for touched manipulation and visualization files.
