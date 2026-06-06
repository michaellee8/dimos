## Why

The current Damiao/OpenArm adapter changes have blurred two separate surfaces: the existing `openarm` adapter, which should remain the stable in-tree OpenArm CAN path, and the newer Rust-backed binding path currently named `dm_motor_arm`. The binding-backed path is being used as an OpenArm bring-up adapter, but its generic name and configurable defaults make it look like a general Damiao arm adapter.

This cleanup matters now because the branch is close to landing and hardware-facing adapter naming, safety behavior, and compatibility expectations need to be clear before implementation accumulates more call sites. The goal is to keep existing OpenArm users on the unchanged `openarm` adapter while making the Rust-backed OpenArm path explicit and easier to reason about.

## What Changes

- Rename and scope the Rust-backed OpenArm adapter path from the generic `dm_motor_arm` surface to an explicit `openarm_rs` surface.
- Preserve the existing `openarm` adapter as the stable OpenArm adapter and avoid source-level changes to its behavior in this cleanup.
- Keep shared Damiao metadata and validation helpers under `dimos/hardware/manipulators/damiao/` for the Rust-backed OpenArm path and future Damiao adapters.
- Add clearer class/function docstrings to Damiao metadata helpers so motor specs, arm specs, validation, and recv-id defaults are understandable.
- Update OpenArm blueprints, docs, tests, and generated registry entries that currently expose the `dm_motor_arm` OpenArm path.
- **BREAKING** for unreleased branch-only usage: the binding-backed OpenArm adapter key and blueprint names should use `openarm_rs` instead of `dm_motor_arm` / `coordinator-dm-motor-openarm`.

## Affected DimOS Surfaces

- Modules/streams: manipulator adapter implementations and tests; no changes to ControlCoordinator streams or joint command/state message contracts.
- Blueprints/CLI: OpenArm blueprint exports and `dimos run` blueprint names for the binding-backed OpenArm path; adapter registry key for the binding-backed path.
- Skills/MCP: no skill or MCP tool changes.
- Hardware/simulation/replay: OpenArm hardware adapter selection and binding-backed mock/vcan bring-up path; no replay behavior changes.
- Docs/generated registries: OpenArm integration docs, possible manipulator contributor docs, and `dimos/robot/all_blueprints.py` if runnable blueprint names change.

## Capabilities

### New Capabilities

- `openarm-rs-adapter-selection`: User-visible selection, naming, and safety expectations for the Rust-backed OpenArm adapter path.
- `damiao-adapter-metadata-docs`: Developer-visible readability and documentation expectations for Damiao arm metadata helpers.

### Modified Capabilities

- `openarm-adapter-compatibility`: Preserve the existing `openarm` adapter path while adding the explicit `openarm_rs` path.
- `dm-motor-manipulator-adapters`: Rename and narrow the current binding-backed OpenArm behavior so it is not presented as a generic Damiao/DMMotor adapter.

## Impact

Existing `openarm` users should see no behavior change: adapter selection, constructor arguments, blueprints, safety behavior, and in-tree CAN driver operation remain stable. Developers using the branch-only `dm_motor_arm` OpenArm path will need to switch to `openarm_rs` names before implementation or docs are considered complete.

Compatibility risk is concentrated around registry discovery, blueprint generation, and documentation drift. Testing should cover adapter registry keys, OpenArm compatibility tests, Rust-backed OpenArm mock/vcan behavior, focused Damiao metadata validation, OpenSpec validation, blueprint registry generation if names change, and manual QA through the library or `dimos run` surfaces.
