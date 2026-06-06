## 1. Shared Damiao Adapter Structure

- [x] 1.1 Add typed Damiao arm metadata structures for motor layout, gains, limits, gravity model, and optional binding/bus assumptions.
- [x] 1.2 Add a shared Damiao arm adapter base that centralizes reusable lifecycle, state-read, command-write, validation, and gravity-compensation behavior.
- [x] 1.3 Keep optional binding imports lazy so adapter discovery does not fail when optional Damiao bindings are unavailable.
- [x] 1.4 Add tests for shared metadata validation, including duplicate IDs, command length mismatch, joint-order preservation, and missing optional binding behavior.

## 2. OpenArm Compatibility Refactor

- [x] 2.1 Refactor `OpenArmAdapter` to use the shared Damiao base while preserving the `openarm` adapter registration key.
- [x] 2.2 Move OpenArm v10 motor tables, side-specific URDF/gravity paths, gains, limits, and side handling into OpenArm-specific typed specs.
- [x] 2.3 Preserve OpenArm constructor arguments and externally observable behavior for existing OpenArm hardware configs.
- [x] 2.4 Add focused OpenArm adapter parity tests for info, limits, gains, motor specs, lifecycle, state reads, supported command shapes, gravity compensation, and disconnect/stop behavior.

## 3. DMMotor Adapter Alignment

- [x] 3.1 Refactor `DMMotorArm` to reuse the shared Damiao base or become a thin compatibility wrapper around it.
- [x] 3.2 Preserve `dm_motor_arm` adapter registration and selected-adapter missing-binding errors.
- [x] 3.3 Preserve binding-backed mock/vcan behavior for connect, enable, coherent state reads, position writes, effort/MIT writes, gravity-only commands, and safe disconnect.
- [x] 3.4 Add focused `dm_motor_arm` tests proving OpenArm defaults are not treated as generic defaults for non-OpenArm Damiao subclasses.

## 4. Blueprints and Catalogs

- [x] 4.1 Keep existing OpenArm catalog helpers and blueprint names stable unless an explicit migration is required.
- [x] 4.2 Update opt-in DMMotor/OpenArm blueprint wiring only if needed to select the refactored adapter classes.
- [x] 4.3 Run `pytest dimos/robot/test_all_blueprints_generation.py` and update `dimos/robot/all_blueprints.py` only if runnable blueprint exports change.

## 5. Documentation

- [x] 5.1 Update `docs/capabilities/manipulation/openarm_integration.md` to explain that `openarm` remains explicit while shared Damiao behavior lives underneath it.
- [x] 5.2 Clarify the distinction between `openarm` and `dm_motor_arm` adapter paths if both remain user-selectable.
- [x] 5.3 Update manipulator driver/contributor docs only if the shared Damiao base becomes the recommended extension point for future Damiao arms.

## 6. Verification

- [x] 6.1 Run `openspec validate refactor-damiao-arm-adapters`.
- [x] 6.2 Run focused tests for `dimos/hardware/manipulators/openarm/`.
- [x] 6.3 Run focused tests for `dimos/hardware/manipulators/dm_motor_arm/` and any new shared Damiao adapter package.
- [x] 6.4 Run focused ControlCoordinator or hardware-interface tests if adapter/coordinator integration behavior changes.
- [x] 6.5 Run docs validation for changed docs, including `md-babel-py run docs/capabilities/manipulation/openarm_integration.md` if executable blocks are added or changed.
- [x] 6.6 Manually QA registry discovery through the library surface by confirming `openarm` and retained `dm_motor_arm` adapter keys are available.
- [x] 6.7 Manually QA mock/vcan adapter operation through the library or coordinator surface: connect, enable, read state, write a supported command, stop, and disconnect.
- [ ] 6.8 Manually QA real OpenArm hardware only after mock/vcan validation: one-arm enable/read, low-rate hold or gravity compensation, safe stop, and optional trajectory-control validation.
