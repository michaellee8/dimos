## 1. Adapter Boundary Cleanup

- [x] 1.1 Restore or preserve `dimos/hardware/manipulators/openarm/adapter.py` as the stable standalone OpenArm adapter with `adapter_type="openarm"` unchanged.
- [x] 1.2 Create `dimos/hardware/manipulators/openarm_rs/` from the binding-backed adapter path and export an OpenArm-specific adapter class.
- [x] 1.3 Register the binding-backed adapter under `openarm_rs` and update selected-adapter missing-binding messages to reference `adapter_type="openarm_rs"`.
- [x] 1.4 Remove or reject generic non-OpenArm construction paths from the renamed binding-backed adapter so OpenArm defaults are not treated as generic Damiao defaults.
- [x] 1.5 Keep lazy `can_motor_control` imports scoped to OpenArm RS selection or connection so unrelated adapter discovery remains healthy.

## 2. Damiao Metadata Readability

- [x] 2.1 Add class and function docstrings to `dimos/hardware/manipulators/damiao/specs.py` explaining motor metadata, receive-ID defaulting, arm metadata, validation, and coercion behavior.
- [x] 2.2 Confirm Damiao metadata validation behavior remains unchanged after docstring-only edits.

## 3. Blueprints, Registry, and Tests

- [x] 3.1 Rename binding-backed OpenArm blueprint variables and runnable names from `dm_motor_openarm` / `dm-motor-openarm` wording to `openarm_rs` / `openarm-rs` wording.
- [x] 3.2 Update OpenArm RS tests to assert the `openarm_rs` registry key, class/package names, missing-binding message, OpenArm-only scope, and mock/vcan lifecycle behavior.
- [x] 3.3 Update OpenArm adapter compatibility tests to prove the stable `openarm` key and observable OpenArm behavior remain unchanged.
- [x] 3.4 Regenerate `dimos/robot/all_blueprints.py` with `pytest dimos/robot/test_all_blueprints_generation.py` if runnable blueprint exports change.

## 4. Documentation

- [x] 4.1 Update `docs/capabilities/manipulation/openarm_integration.md` to describe `openarm` and `openarm_rs` adapter paths and staged OpenArm RS validation.
- [x] 4.2 Replace user-facing `dm_motor_arm` / `coordinator-dm-motor-openarm*` references with `openarm_rs` / renamed blueprint references where this cleanup changes the surface.
- [x] 4.3 Update contributor or coding-agent docs only if they mention the old binding-backed adapter key or recommend editing the original OpenArm adapter for OpenArm RS work.

## 5. Verification

- [x] 5.1 Run `openspec validate cleanup-openarm-rs-adapter`.
- [x] 5.2 Run focused tests for `dimos/hardware/manipulators/openarm/`, `dimos/hardware/manipulators/openarm_rs/`, and `dimos/hardware/manipulators/damiao/`.
- [x] 5.3 Run `pytest dimos/robot/test_all_blueprints_generation.py` when blueprint names or exports change, and keep `dimos/robot/all_blueprints.py` current.
- [x] 5.4 Run docs validation for changed docs, including `md-babel-py run docs/capabilities/manipulation/openarm_integration.md` if executable blocks are added or changed.
- [x] 5.5 Manually QA adapter registry discovery through the library surface by confirming `openarm` and `openarm_rs` keys are available and `dm_motor_arm` is absent or intentionally handled.
- [x] 5.6 Manually QA OpenArm RS mock/vcan operation through the library or coordinator surface: connect, enable, read a coherent state snapshot, write a supported command, stop, and disconnect.
- [ ] 5.7 Manually QA real OpenArm RS hardware only after mock/vcan validation: one-arm enable/read, low-rate hold or gravity compensation, safe stop, and optional trajectory-control validation.
