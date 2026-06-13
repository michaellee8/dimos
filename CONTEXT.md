# DimOS Robotics Language

Shared vocabulary for DimOS robotics concepts. These terms define domain language, not implementation details.

## Language

**Planning Group**:
A named selectable serial kinematic chain of robot joints used as the unit of manipulation planning. A planning group is defined by its chain/joints, not by end-effector metadata.
_Avoid_: Move group, movegroup

**Planning Group Definition**:
The model-level declaration of a planning group before it is bound to a concrete robot in a planning world.
_Avoid_: Runtime group, robot ID

**End-Effector Association**:
Separate metadata used for pose-targeted operations. For a planning group defined by a chain, the end-effector link is the chain tip. For a planning group defined only by joints, there is no end-effector link.
_Avoid_: Planning group definition

**Resolved Planning Group**:
A planning group after model-level declarations have been bound to a concrete robot, namespace, and planning world.
_Avoid_: Planning group config, robot ID

**Planning Group Selection**:
The set of one or more planning groups chosen for a planning request.
_Avoid_: Composite group

**Auxiliary Planning Group**:
A planning group selected to participate in a specific planning request without receiving a direct end-effector pose constraint in that request. A planning group may be auxiliary in one request and directly targeted in another.
_Avoid_: Joint-only group, intrinsic auxiliary group

**Coordinated Planning Problem**:
A planning request over one or more selected planning groups that is solved as one combined joint-space problem with one synchronized result.
_Avoid_: Batch planning, independent planning

**Planning Group ID**:
An API-level identifier for a planning group, always namespaced as `{robot_name}/{group_name}`.
_Avoid_: Bare group name, robot ID

**Planning Group Descriptor**:
A read-only snapshot returned by query APIs that describes an available planning group and may be used ergonomically as a planning group selector.
_Avoid_: Live planning group handle, resolved planning group

**Joint State**:
A resolved-joint-name-keyed robot state that can represent any set of joints and is not inherently coupled to a robot, planning group, or planning group selection.
_Avoid_: Planning-group-scoped state

**Robot Model Joint Names**:
The objective set of controllable joints exposed by a robot coordinator for state and command. This usually aligns with the model's actuated joints, but is not itself a planning group.
_Avoid_: Implicit planning group

**Local Model Joint Name**:
A joint name as it appears inside a robot model or SRDF before the model is bound to a concrete robot in a planning world.
_Avoid_: Runtime joint name, coordinator joint name

**Resolved Joint Name**:
A world-level joint name exposed above the model parsing layer, always namespaced as `{robot_name}/{local_joint_name}` so it is stable and unique within a planning world.
_Avoid_: Bare joint name, local joint name

**Robot Placement**:
The placement of a robot model within the planning world. Robot placement belongs in the robot model description rather than in a separate planning configuration transform.
_Avoid_: Planning base pose, config placement transform
