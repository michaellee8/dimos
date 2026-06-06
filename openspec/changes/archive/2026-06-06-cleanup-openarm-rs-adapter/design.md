## Context

DimOS manipulator hardware is selected through `HardwareComponent.adapter_type`, discovered by the manipulator adapter registry, and consumed by `ControlCoordinator` through the existing `ManipulatorAdapter` protocol. The current branch has two OpenArm-related paths: the existing `openarm` adapter with an in-tree SocketCAN Damiao driver, and a newer binding-backed path currently named `dm_motor_arm` that imports `can_motor_control` lazily and drives an OpenArm-style arm through a Rust-backed Python binding.

The prior refactor moved `OpenArmAdapter` onto a shared Damiao base. The updated cleanup direction is stricter: keep the original `openarm` adapter source and behavior stable, and isolate the binding-backed path under an explicit OpenArm RS name. Shared Damiao metadata helpers remain useful, but they should not force the original OpenArm adapter to inherit new behavior.

Relevant surfaces include `dimos/hardware/manipulators/openarm/adapter.py`, `dimos/hardware/manipulators/dm_motor_arm/adapter.py`, `dimos/hardware/manipulators/damiao/specs.py`, `dimos/hardware/manipulators/damiao/base_adapter.py`, `dimos/hardware/manipulators/registry.py`, `dimos/robot/manipulators/openarm/blueprints.py`, `dimos/robot/all_blueprints.py`, and `docs/capabilities/manipulation/openarm_integration.md`.

## Goals / Non-Goals

**Goals:**

- Keep `adapter_type="openarm"` and `OpenArmAdapter` as the stable in-tree OpenArm CAN adapter.
- Restore or preserve the original OpenArm adapter source-level boundary so this cleanup does not change its implementation behavior.
- Rename the binding-backed OpenArm path to `openarm_rs` and expose it as OpenArm-only.
- Keep lazy optional import behavior for the binding-backed path so adapter discovery works without `can_motor_control` installed.
- Keep ControlCoordinator, joint-state streams, joint command streams, task configs, and MCP/skills unchanged.
- Add readable docstrings to Damiao metadata helpers.
- Update docs, tests, and generated blueprint registry entries to match the new names.

**Non-Goals:**

- Do not build or vendor the Rust binding in DimOS.
- Do not introduce a broad dynamic YAML/TOML schema for arbitrary Damiao arms.
- Do not make `openarm_rs` a generic Damiao/DMMotor adapter in this cleanup.
- Do not change the public ControlCoordinator stream contract or add new MCP/skill tools.
- Do not perform real hardware validation as part of artifact generation; leave that as staged QA.

## DimOS Architecture

External coordinator shape after cleanup:

```text
ControlCoordinator
  -> HardwareComponent(adapter_type="openarm" | "openarm_rs")
    -> manipulator adapter registry
      -> OpenArmAdapter       # original in-tree OpenArm CAN path
      -> OpenArmRSAdapter     # Rust-backed binding path for OpenArm only
```

Recommended code shape:

```text
dimos/hardware/manipulators/openarm/adapter.py
  OpenArmAdapter              # standalone/stable source-level OpenArm adapter

dimos/hardware/manipulators/openarm_rs/adapter.py
  OpenArmRSAdapter            # renamed binding-backed OpenArm adapter

dimos/hardware/manipulators/damiao/
  specs.py                    # typed Damiao metadata and validation helpers
  base_adapter.py             # shared metadata/limits/control-mode/gravity helpers for adapters that opt in
```

The binding-backed adapter should continue to satisfy `ManipulatorAdapter`. It may inherit from `DamiaoArmAdapterBase` if that remains useful for validation, limits, and gravity helpers. The original `OpenArmAdapter` should not be forced through the shared base in this cleanup; preserving its current stable behavior is the compatibility target.

No new DimOS `Spec` Protocol is required. No module streams, transports, RPC references, skills, or MCP tools change. If runnable blueprint variable names change from `coordinator_dm_motor_openarm*` to `coordinator_openarm_rs*`, regenerate `dimos/robot/all_blueprints.py` with `pytest dimos/robot/test_all_blueprints_generation.py`.

## Decisions

- **Rename by user-facing role, not motor family.** The adapter is used as an OpenArm binding-backed path, so `openarm_rs` is clearer than `dm_motor_arm`.
- **Keep `openarm` source-level stable.** The existing in-tree OpenArm adapter is the stable path; source-level changes risk hardware behavior drift even if tests pass.
- **Keep optional binding failures selected-adapter scoped.** Import `can_motor_control` only when the `openarm_rs` adapter is selected or connected.
- **Do not preserve unreleased generic configurability.** If the current branch allowed arbitrary non-OpenArm `motor_specs`, remove it or require a future explicit generic Damiao adapter change.
- **Keep shared Damiao helpers modest.** `damiao/specs.py` and `base_adapter.py` should provide metadata validation, limits, control-mode state, and gravity helpers, not own all binding lifecycle details.
- **Treat blueprint renames as public CLI changes.** Runnable names exposed by `dimos list` / `dimos run` need docs and generated registry updates.

## Safety / Simulation / Replay

Hardware assumptions:

- `openarm` remains the stable OpenArm hardware path using the in-tree SocketCAN driver.
- `openarm_rs` requires the Rust-backed `can_motor_control` Python binding from the manipulation extra on supported platforms.
- Binding-backed operation may use CAN-FD and staged mock/vcan validation before real hardware.
- Gravity compensation requires a valid OpenArm model path, joint ordering, signs, and measured state.

Safety constraints:

- Do not silently migrate existing OpenArm blueprints from `openarm` to `openarm_rs`.
- Preserve disable-on-disconnect and safe stop behavior for both adapter paths.
- Keep gravity-compensation-only commands free-moving by using zero position stiffness where applicable.
- Keep missing-binding errors explicit and selected-adapter scoped.
- Validate mock/vcan before real hardware; real hardware QA should start with supported one-arm low-rate tests.

Simulation/replay:

- Replay is out of scope.
- Existing OpenArm mock/planner blueprints should remain available.
- Binding-backed mock/vcan tests should cover registry discovery, connect, enable, state reads, command writes, stop, and disconnect.

Manual QA surface:

- Library surface: discover `openarm` and `openarm_rs` adapter keys.
- CLI surface: `dimos list` includes renamed `openarm_rs` runnable blueprints if names change.
- Binding surface: missing `can_motor_control` produces a clear selected-adapter error.
- Mock/vcan surface: `openarm_rs` can connect, enable, read one coherent state snapshot, write a supported command, stop, and disconnect.

## Risks / Trade-offs

- **Reverting OpenArm refactor may duplicate small helpers.** This is acceptable to protect stable hardware behavior; shared helpers can still serve the binding-backed path.
- **Renaming branch-only surfaces may require broad updates.** Mitigate by searching docs, tests, blueprints, registry output, and adapter strings for `dm_motor_arm` and `coordinator-dm-motor-openarm`.
- **`openarm_rs` may imply a specific upstream crate.** Document that the adapter consumes the currently selected `can_motor_control` Python binding and does not vendor Rust crates.
- **Generated registry drift.** Mitigate by running the blueprint generation test whenever runnable blueprint exports change.
- **Hardware safety drift.** Mitigate with focused adapter parity tests and staged mock/vcan before real hardware.

## Migration / Rollout

1. Restore or preserve `openarm/adapter.py` as the stable standalone adapter while keeping `adapter_type="openarm"` unchanged.
2. Move or rename `dm_motor_arm` to `openarm_rs`, including class names, package exports, registry key, tests, and missing-binding messages.
3. Narrow the renamed adapter to OpenArm-specific defaults and reject or remove generic non-OpenArm construction paths.
4. Add Damiao metadata docstrings without changing metadata behavior.
5. Rename OpenArm binding-backed blueprints and task names from `dm_motor` wording to `openarm_rs` wording.
6. Update docs and generated registry output if blueprint exports change.
7. Run OpenSpec validation, focused tests, blueprint generation validation, docs validation, and manual QA through registry/CLI/mock surfaces.

Rollback is straightforward if changes stay isolated: keep the original `openarm` adapter untouched, and revert the `openarm_rs` package/blueprint/docs rename if the binding-backed path needs more design work.

## Open Questions

- Should the old `dm_motor_arm` registry key exist as a temporary alias during this unreleased branch, or should it be removed entirely to avoid confusion?
- Should package naming be `openarm_rs` only, or should docs describe it as “OpenArm RS / Rust-backed OpenArm” for readability?
- Should the future generic Damiao adapter be planned as a separate change after OpenArm RS lands?
