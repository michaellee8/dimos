# DimOS Manipulation Planning Context

This context defines domain language for DimOS manipulation planning. It captures stable planning concepts, not implementation decisions.

## Language

**Planning group**:
A named subset of a robot model's joints and frames that can be selected as a planning unit.
_Avoid_: move group, joint group

**Composite planning group**:
A planning group that represents coordinated motion across multiple selected planning groups.
_Avoid_: group combination, combined groups, multi-group plan

**Composite RoboPlan model**:
A RoboPlan-facing robot model that represents multiple registered robot models as one planning scene.
_Avoid_: combined URDF, merged robot scene

**Planning world**:
The authoritative belief state for manipulation planning, including robot state and scene state used by planners.
_Avoid_: planner context, backend instance
