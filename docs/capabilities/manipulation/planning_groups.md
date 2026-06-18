# Manipulation Planning Groups

Planning groups are named, selectable kinematic chains used by manipulation
planning. They separate the hardware robot identity from the part of the robot
being planned.

## Concepts

| Concept | Meaning |
|---------|---------|
| Planning group | A named serial chain of controllable robot joints. |
| Planning group ID | Stable API ID in the form `{robot_name}/{group_name}`. |
| Resolved joint name | World-level joint name in the form `{robot_name}/{local_joint_name}`. |
| Generated plan | Minimal planning artifact containing selected group IDs and one synchronized resolved-joint path. |
| Auxiliary group | A group selected for a pose request without receiving its own pose target. |

Local URDF/SRDF joint names stay inside model parsing and backend internals.
Public planning states and generated plan paths use resolved joint names so two
robots can safely have the same local joint names.

## Planning group sources

DimOS discovers planning groups in this order:

1. Explicit `srdf_path` on `RobotConfig` / `RobotModelConfig`.
2. Conservative SRDF auto-discovery near the model path, with a visible warning.
3. Fallback generation of one `{robot_name}/manipulator` group if the configured
   controllable joints form exactly one unambiguous serial chain.
4. Error if no SRDF exists and fallback cannot infer a single chain.

Supported SRDF group forms:

```xml
<group name="arm">
  <chain base_link="base_link" tip_link="tool0" />
</group>
```

```xml
<group name="arm">
  <joint name="joint1" />
  <joint name="joint2" />
  <joint name="joint3" />
</group>
```

Unsupported SRDF forms are skipped with warnings: link groups, nested group
references, mixed group declarations, branching/non-serial groups, and SRDF
`<end_effector>` metadata. A chain group's `tip_link` is the pose target frame.
An ordered joint-list group may be pose-targeted only when DimOS can validate a
unique serial target frame.

## Fallback behavior

When no SRDF is available, fallback uses `RobotModelConfig.joint_names` as the
candidate controllable set. This field is the robot's controllable/coordinator
joint set, not an implicit planning group.

Fallback succeeds only when those joints form one unambiguous serial chain. It
allows prismatic joints in the middle of the chain and strips only terminal/tip
prismatic joints, which usually represent gripper fingers. The generated group
name is always `manipulator`.

## Planning APIs

Planning APIs select groups explicitly. Descriptors returned by
`WorldSpec.list_planning_groups()` can be passed where a group ID is accepted;
the API normalizes them back to IDs and re-resolves current world state.

```python skip
# Joint-space planning for one group.
manip.plan_to_joint_targets({
    "left_arm/manipulator": JointState(
        name=["left_arm/joint1", "left_arm/joint2"],
        position=[0.2, -0.1],
    )
})

# Pose planning for an arm while a torso/waist group participates as free DOFs.
manip.plan_to_poses(
    {"robot/arm": target_pose},
    auxiliary_groups=["robot/torso"],
)

plan = manip._last_plan
manip.preview_plan(plan)
manip.execute_plan(plan)
```

For joint-space planning, start and goal joint keys must exactly match the
selected resolved joints: no missing, extra, or partial joints.

## Generated plans and execution

A `GeneratedPlan` stores:

- selected planning group IDs;
- a single synchronized path of `JointState` waypoints keyed by resolved joint
  names;
- status, timing, path length, iteration count, and message metadata.

Preview and execution project this path lazily. Preview sends projected joint
paths to the world monitor. Execution splits the path by affected coordinator
trajectory task, orders each trajectory by that task's configured joint order,
maps resolved/local names to coordinator names at the boundary, and invokes each
trajectory controller. Controllers remain planning-group agnostic.

Multi-task dispatch is not atomic in this change: if one trajectory task accepts
and a later task rejects, DimOS reports the rejection but does not roll back the
accepted task.

## Compatibility planning config fields

`RobotConfig.base_link`, `RobotConfig.base_pose`,
`RobotModelConfig.base_link`, `RobotModelConfig.base_pose`, and
`RobotModelConfig.end_effector_link` remain as compatibility fields for the
current Drake weld/placement behavior and robot-scoped compatibility helpers.
New planning logic should use model/SRDF structure and planning group base/tip
links instead.

Robot placement should be encoded in URDF/xacro/MJCF. `joint_names` remains
supported and should describe the controllable/coordinator joint set.
