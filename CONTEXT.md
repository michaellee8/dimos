# DimOS Robotics Context

DimOS describes robots, actuators, control surfaces, and manipulation planning using precise robotics terminology. This glossary records stable domain language only, not implementation details.

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

**Coordinated simulation clock**:
A simulation benchmark clock policy where simulator time advances in lockstep with the DimOS control coordinator clock.
_Avoid_: autonomous simulator loop, write-triggered stepping, settle step

**Runtime sidecar**:
A separate process or environment that owns a benchmark simulator backend while DimOS owns orchestration, control integration, skills, and artifacts.
_Avoid_: plugin, embedded simulator

**Depth observation**:
A depth image interpreted with its camera calibration and the pose of its camera frame at the image timestamp.
_Avoid_: depth point cloud, raw 3D points

**SHM runtime data plane**:
A local shared-memory command/state channel between a ControlCoordinator-facing hardware adapter and a DimOS simulator client module, used when high-rate motor control must cross local process boundaries without RPC.
_Avoid_: remote sidecar protocol, public simulator API, benchmark control plane, module object sharing

**Motor state projection**:
The hardware-facing subset of simulator state that resembles what a raw robot driver exposes: actuator positions, velocities, efforts, commands, enable state, and errors.
_Avoid_: task observation, scene observation, evaluator state

**Whole-body motor surface**:
A hardware control surface that treats a robot as an ordered set of motors with per-motor state and commands, independent of whether the robot is a manipulator, mobile base, or humanoid.
_Avoid_: manipulator-only adapter, end-effector API, task action API

**Benchmark episode config**:
A backend-facing declaration of benchmark intent that names the task, robot, runtime constraints, and evaluation setup before any DimOS blueprint is launched.
_Avoid_: hardware config, simulator config, blueprint config

**Resolved runtime plan**:
The concrete DimOS launch material derived from a benchmark episode config, including hardware components, simulator connection config, observation streams, evaluator setup, and artifact routing.
_Avoid_: benchmark intent, user-authored task config

**Runtime prelaunch orchestration**:
The phase that starts and coordinates the simulator sidecar environment and the DimOS blueprint environment before a benchmark episode begins.
_Avoid_: config parsing, blueprint launch, single-process startup

**Remote runtime boundary**:
The network-facing protocol boundary between a DimOS simulator client and a benchmark backend process that may run in another environment or on another machine.
_Avoid_: shared memory boundary, hardware adapter boundary, in-process simulator object

**Runtime protocol schema**:
The shared, backend-neutral message contract used on the remote runtime boundary to describe episodes, robot motor surfaces, actions, observations, scores, and artifacts.
_Avoid_: backend SDK type, DimOS hardware adapter type, simulator object

**Runtime protocol package**:
A lightweight installable package in the monorepo that contains only remote runtime protocol schemas, codecs, and compatibility tests so sidecars can depend on it without installing DimOS.
_Avoid_: DimOS submodule, simulator backend package, hardware adapter package

**Damiao-based Robot**:
A robot whose joints are actuated by one or more Damiao motors, possibly spread across multiple CAN buses and physical limbs.
_Avoid_: Damiao arm when the robot may contain multiple motor groups

**Damiao Joint Group**:
An ordered set of Damiao-driven joints that forms a meaningful physical group such as an arm, torso, or other controllable body section.
_Avoid_: Arm when the group is not necessarily an arm

**Damiao Bus**:
A named communication channel used by a Damiao-based Robot to reach one or more Damiao motors.
_Avoid_: Treating a bus as owned by a single joint group when multiple groups may share a channel

**OpenArm**:
An OpenArm robot configuration built from Damiao motors, with OpenArm-specific joints, side naming, limits, and robot description.
_Avoid_: Damiao robot when referring to OpenArm-specific geometry or naming
