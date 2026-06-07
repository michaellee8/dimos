## Why

The manipulator adapter registry currently discovers adapters by importing every `dimos.hardware.manipulators.<adapter>.adapter` module at registry import time. That makes discovery depend on every adapter module being safe to import in every environment, even when a user only wants to list adapters or instantiate an unrelated adapter.

This is especially painful for optional hardware bindings such as the Rust-backed Damiao/OpenArm RS path: adapter implementation files must avoid normal imports and carry extra lazy-import/protocol/cast boilerplate so registry discovery does not fail or trigger heavy SDK side effects. DimOS already has a cleaner precedent in the control task registry: lightweight manifest modules advertise available names, while implementation imports happen only for the selected type.

## What Changes

- Modify manipulator adapter discovery to import lightweight per-adapter registry manifests instead of importing every adapter implementation module.
- Register adapter names to lazy factory import paths and resolve exactly one adapter implementation when `adapter_registry.create(name, **kwargs)` is called.
- Preserve the existing public `adapter_registry.available()` and `adapter_registry.create()` library surface.
- Preserve selected-adapter-scoped optional dependency failures: missing hardware bindings should not break discovery or unrelated adapters, and should fail clearly when the affected adapter is selected.
- Add compatibility support for existing direct `register(registry)` adapter modules during migration only if it does not reintroduce eager implementation imports.
- No **BREAKING** public API or CLI behavior is intended.

## Affected DimOS Surfaces

- Modules/streams: No stream contracts change. Control coordinator manipulator adapter creation continues through `HardwareComponent.adapter_type` and `adapter_registry.create()`.
- Blueprints/CLI: Existing blueprints and CLI runs that select manipulator adapters should keep the same adapter keys.
- Skills/MCP: No direct MCP or skill surface change.
- Hardware/simulation/replay: Manipulator hardware adapters, including `openarm`, `openarm_rs`, `xarm`, `piper`, `a750`, `mock`, and `sim_mujoco`, remain selectable by the same names. Optional SDK failures remain scoped to selected adapters.
- Docs/generated registries: Update manipulator adapter authoring docs to describe manifest-based lazy discovery. No generated blueprint registry changes are expected.

## Capabilities

### New Capabilities
- `manipulator-adapter-discovery`: Behavior for discovering, listing, and instantiating manipulator adapters without importing unselected adapter implementations.

### Modified Capabilities
- `openarm-rs-adapter-selection`: Preserve and clarify the requirement that missing `can_motor_control` fails only when `openarm_rs` is selected, not during registry discovery.
- `dm-motor-manipulator-adapters`: Preserve and clarify selected-adapter-scoped binding availability for Damiao/DMMotor-backed manipulator adapters.

## Impact

Users should see the same adapter names and selection behavior, but adapter listing/import becomes more reliable in partial installations. Developers can write adapter implementation modules with normal imports appropriate to selected-adapter runtime paths instead of keeping all implementation modules discovery-safe.

Compatibility risk is concentrated in registry migration: existing adapter keys must remain stable, duplicate manifests must be rejected clearly, and missing manifest or malformed import paths must produce actionable errors. Test coverage should prove that `available()` does not import adapter implementations, `create()` imports only the requested implementation, and missing optional bindings do not break unrelated adapters. Manual QA should exercise the library surface by listing adapters and creating at least mock plus one lazy-registered adapter path.
