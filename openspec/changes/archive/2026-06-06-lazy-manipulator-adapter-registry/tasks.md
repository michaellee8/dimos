## 1. Registry Implementation

- [x] 1.1 Update `dimos/hardware/manipulators/registry.py` to store lazy adapter factory import paths alongside directly registered adapter classes.
- [x] 1.2 Add a `register_path(name, factory_path)`-style API with `module:attribute` validation, duplicate-key detection, and actionable errors for malformed paths.
- [x] 1.3 Change manipulator discovery to import `<adapter>.__registry__` manifests and read an `ADAPTER_FACTORIES` string mapping instead of importing `<adapter>.adapter` implementation modules.
- [x] 1.4 Resolve and cache the selected adapter implementation only inside `adapter_registry.create(name, **kwargs)`.
- [x] 1.5 Preserve existing `register(name, cls)` behavior for direct programmatic registration and existing adapter-level unit tests.
- [x] 1.6 Add lightweight `__registry__.py` manifests for built-in adapters: `a750`, `mock`, `openarm`, `openarm_rs`, `piper`, `sim`, and `xarm`.
- [x] 1.7 Keep current adapter keys unchanged: `a750`, `mock`, `openarm`, `openarm_rs`, `piper`, `sim_mujoco`, and `xarm`.

## 2. Adapter Cleanup Boundaries

- [x] 2.1 Review `dimos/hardware/manipulators/damiao/base_adapter.py` after lazy registry discovery is in place and simplify only import scaffolding that no longer protects registry listing.
- [x] 2.2 Preserve OpenArm RS selected-adapter missing-binding error behavior and install guidance for absent `can_motor_control`.
- [x] 2.3 Avoid changing hardware command semantics, gravity compensation behavior, state caching, or adapter constructor contracts while refactoring discovery.

## 3. Tests

- [x] 3.1 Add focused manipulator registry tests proving `adapter_registry.available()` does not import adapter implementation modules.
- [x] 3.2 Add tests proving `adapter_registry.create()` imports only the selected adapter implementation and passes constructor kwargs through.
- [x] 3.3 Add tests for malformed manifest entries, duplicate adapter keys, unknown adapter names, and missing selected implementation paths.
- [x] 3.4 Add or update tests proving registry discovery/listing remains healthy when `can_motor_control` is not importable.
- [x] 3.5 Update OpenArm RS/Damiao tests to preserve normal selected-path import style and clear missing-binding failure behavior.
- [x] 3.6 Add a regression test that expected built-in manipulator adapter keys remain available after manifest migration.

## 4. Documentation

- [x] 4.1 Update `docs/capabilities/manipulation/adding_a_custom_arm.md` to teach `__registry__.py` manifest-based discovery and lazy selected adapter imports.
- [x] 4.2 Update `dimos/hardware/manipulators/README.md` if its adapter structure or adding-a-new-arm section still describes eager `adapter.py` discovery.
- [x] 4.3 Review `docs/capabilities/manipulation/openarm_integration.md` and keep or adjust wording that `openarm_rs` remains opt-in and missing binding failures are selected-adapter scoped.

## 5. Verification

- [x] 5.1 Run `openspec validate lazy-manipulator-adapter-registry`.
- [x] 5.2 Run focused registry tests for `dimos/hardware/manipulators/registry.py` and built-in manipulator manifest discovery.
- [x] 5.3 Run focused OpenArm RS/Damiao adapter tests covering `can_motor_control` missing-binding behavior.
- [x] 5.4 Run focused tests for adapters whose manifests changed where construction is safe without hardware.
- [x] 5.5 Run lints/types for changed Python files, including `uv run mypy` or narrower type checks if the repository supports them for this area.
- [x] 5.6 Run documentation validation for changed docs, or manually inspect docs if no doc validation command is available.
- [x] 5.7 Manually QA through the library surface: import `adapter_registry`, call `available()`, create a `mock` adapter, and verify selecting `openarm_rs` without `can_motor_control` fails with a clear selected-adapter error while unrelated adapters remain listed.
