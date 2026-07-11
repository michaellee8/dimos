## 1. Concrete OpenArm Mini Polling Runtime

- [x] 1.1 Change `OpenArmMiniTeleopModuleConfig` to inherit from `ModuleConfig`, retain a strictly positive polling period, and remove generic stale/publish-rate settings.
- [x] 1.2 Change `OpenArmMiniTeleopModule` to inherit directly from `Module` and add its polling stop event, worker reference, and defensive start/stop RPC lifecycle.
- [x] 1.3 Replace `TeleopCommand` production and generic payload publication with `JointState | None` reads and direct `joint_command` publication from a synchronous `tick()`.
- [x] 1.4 Add the concrete fixed-period polling loop with expected read-failure recovery and visible handling for unexpected worker exceptions.

## 2. Tests and Runtime Removal

- [x] 2.1 Update OpenArm Mini teleop tests for direct joint commands, synchronous tick publication, invalid polling configuration, duplicate-start behavior, and deterministic worker/bus cleanup.
- [x] 2.2 Remove the generic teleop runtime base, command-envelope types, and dedicated runtime tests.
- [x] 2.3 Search code, blueprints, generated registry, and documentation for removed runtime imports or obsolete stale/publish-rate configuration and update all references.

## 3. Verification

- [x] 3.1 Run focused OpenArm Mini teleop and OpenArm blueprint tests with the default marker exclusions.
- [x] 3.2 Run Ruff and mypy on all changed production and test files.
- [x] 3.3 Run the blueprint generation validity check and verify the working diff contains only the intended runtime collapse plus pre-existing user changes.
