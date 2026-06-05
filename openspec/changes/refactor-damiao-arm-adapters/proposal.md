## Why

The new `dm_motor_arm` path proves that DimOS can operate Damiao/DMMotor arms through the binding-backed adapter, but the current shape is awkward for future Damiao-based arms: shared Damiao behavior and OpenArm-specific assumptions are mixed together. The earlier idea of fully dynamic URDF-plus-sidecar configuration is more flexible than this project currently needs and would add a larger configuration surface than necessary.

This change should refactor the adapter structure around a small class hierarchy: keep `OpenArmAdapter` as the explicit OpenArm adapter, extract reusable Damiao/CAN/MIT behavior into a shared base, and let future Damiao arms opt in by subclassing with their own class-level arm specs.

## What Changes

- Add a reusable Damiao arm adapter base that owns generic binding/CAN lifecycle, state reads, MIT command writes, gravity compensation plumbing, and shared validation.
- Keep `OpenArmAdapter` and the `openarm` adapter registration as the stable OpenArm-specific surface.
- Move OpenArm-specific motor tables, URDF paths, gains, limits, side handling, and model metadata into the OpenArm subclass/spec rather than keeping them as generic `DMMotorArm` defaults.
- Preserve the opt-in `dm_motor_arm` adapter path where useful, but make its relationship to the shared Damiao base explicit.
- Avoid introducing a broad user-editable sidecar schema in this change; new Damiao arms can be added through typed subclasses and catalog/blueprint presets.
- No **BREAKING** public CLI or blueprint behavior is intended; existing OpenArm blueprints should keep selecting `openarm` unless explicitly migrated.

## Affected DimOS Surfaces

- Modules/streams: Manipulator adapter implementations behind the existing `ManipulatorAdapter` protocol; ControlCoordinator stream behavior should remain unchanged.
- Blueprints/CLI: Existing OpenArm blueprints and `dimos run` entries should remain stable; opt-in DMMotor/OpenArm blueprints may be adjusted only to use the refactored adapter classes.
- Skills/MCP: No direct skill or MCP changes planned.
- Hardware/simulation/replay: Real OpenArm/Damiao hardware lifecycle, mock/vcan validation, gravity compensation, enable/disable safety, and command semantics.
- Docs/generated registries: OpenArm/manipulation documentation may need updates to explain the adapter split; blueprint registry regeneration is needed only if runnable blueprint names change.

## Capabilities

### New Capabilities

- `damiao-arm-adapter-refactor`: Covers the reusable Damiao arm adapter structure, subclass-based arm specs, and preservation of OpenArm adapter behavior.
- `openarm-adapter-compatibility`: Covers compatibility expectations for existing OpenArm adapter registration, blueprints, hardware behavior, and staged QA.

### Modified Capabilities

- None.

## Impact

Developers get a simpler extension path for additional Damiao-based arms without introducing a large dynamic configuration format. OpenArm remains a named adapter with explicit OpenArm behavior, while shared Damiao code becomes easier to test and reuse.

Compatibility risk is mainly around preserving the current `openarm` adapter semantics while moving shared logic underneath it. Hardware safety QA must cover enable/disable, state read coherence, position/effort/MIT commands, gravity-compensation behavior, and mock/vcan smoke tests before real hardware validation. No new runtime dependency installation is planned.
