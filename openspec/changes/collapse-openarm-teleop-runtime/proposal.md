## Why

The generic `TeleopModule` base models only pull-based polling, while the existing phone, Quest, hosted Quest, and keyboard teleop implementations own event or frontend loops with different lifecycle and thread-affinity requirements. Keeping that polling policy under a generic name encourages unsafe inheritance and adds an abstraction around the sole compatible user, OpenArm Mini.

## What Changes

- Move polling, lifecycle, and publishing flow directly into `OpenArmMiniTeleopModule`.
- Simplify OpenArm Mini command production to return and publish `JointState` directly without a generic `TeleopCommand` envelope.
- Remove the generic teleop runtime base, command envelope, and their dedicated tests.
- Preserve a synchronous OpenArm Mini tick hook for deterministic unit testing.
- Make OpenArm Mini polling lifecycle explicit, including configuration validation, start/stop safety, worker cleanup, and read-error handling.
- Keep phone, Quest, hosted Quest, and keyboard teleop modules independent because they own their frontend or transport loops.
- Defer shared worker/rate/freshness helpers until multiple modules demonstrate the same runtime shape.
- **BREAKING**: Internal imports of `dimos.teleop.runtime.TeleopModule`, `TeleopModuleConfig`, and `TeleopCommand` are removed.

## Capabilities

### New Capabilities

- `openarm-mini-polling-teleop`: Pull-based OpenArm Mini leader polling, lifecycle, command publication, and failure behavior owned by the concrete module.

### Modified Capabilities

None.

## Impact

- Affects `dimos/teleop/openarm_mini/teleop_module.py` and its tests.
- Removes `dimos/teleop/runtime/teleop_module.py`, `dimos/teleop/runtime/types.py`, and corresponding runtime tests/imports.
- Does not change phone, Quest, hosted Quest, or keyboard teleop runtime behavior.
- Does not add dependencies or change external robot command message types.
