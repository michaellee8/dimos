## Context

`dimos.hardware.manipulators.registry.AdapterRegistry` currently discovers adapters by scanning `dimos/hardware/manipulators/` and importing each `<adapter>/adapter.py` module during registry import. That makes a simple `from dimos.hardware.manipulators.registry import adapter_registry` execute implementation modules for `xarm`, `piper`, `openarm_rs`, `sim_mujoco`, and other adapters before a user has selected an adapter.

This conflicts with existing requirements for optional hardware bindings. `openarm_rs` must remain discoverable when `can_motor_control` is not installed, and missing binding errors must be scoped to selecting or connecting `openarm_rs`. The current Damiao/OpenArm RS base compensates by keeping binding imports lazy and typing them through local Protocols. That preserves behavior but makes implementation code harder to read and maintain.

The control-task registry already solves the same class of problem. `dimos/control/tasks/registry.py` imports lightweight `__registry__.py` manifests containing string import paths, and imports the real task implementation only when the selected task is created.

## Goals / Non-Goals

**Goals:**

- Make manipulator adapter discovery metadata-only: listing adapters must not import unselected adapter implementation modules.
- Preserve existing adapter keys and the `adapter_registry.available()` / `adapter_registry.create(name, **kwargs)` API.
- Keep optional dependency failures selected-adapter scoped, especially for `openarm_rs` and future Damiao-backed adapters.
- Establish a contributor pattern for adding manipulator adapters through lightweight manifests.
- Enable follow-up simplification of Damiao/OpenArm RS implementation imports where normal selected-path imports are clearer.

**Non-Goals:**

- Do not change stream contracts, coordinator task behavior, blueprint names, or MCP/skill exposure.
- Do not migrate drive-train or whole-body registries in this change, though they may benefit from the same pattern later.
- Do not introduce setuptools entry points or third-party plugin packaging for in-tree adapters now.
- Do not make `openarm_rs` a generic Damiao adapter or change its hardware safety semantics.

## DimOS Architecture

The affected runtime path is the manipulator adapter selection path used by `ControlCoordinator._create_adapter()`:

```text
HardwareComponent(adapter_type=...)
  -> ControlCoordinator._create_adapter()
     -> adapter_registry.create(adapter_type, dof=..., address=..., hardware_id=..., **kwargs)
        -> selected manipulator adapter instance
```

No `In[T]`/`Out[T]` stream names or transport choices change. The `ManipulatorAdapter` Protocol remains the adapter surface. No new DimOS `Spec` Protocol, RPC contract, skill, or MCP tool is required.

The registry should mirror the control-task lazy registry structure:

```text
dimos/hardware/manipulators/<adapter>/__registry__.py
  ADAPTER_FACTORIES = {
      "adapter_key": "dimos.hardware.manipulators.<adapter>.adapter:AdapterClass"
  }

dimos/hardware/manipulators/registry.py
  discover() imports only __registry__.py manifests
  available() returns manifest keys
  create(name, **kwargs) resolves the selected import path and instantiates it
```

The registry should cache resolved factories/classes after the first selected import, like `ControlTaskRegistry._factories`, so repeated `create()` calls for the same adapter do not repeatedly import the module.

## Decisions

1. **Use per-adapter `__registry__.py` manifests for built-in adapters.**
   - Rationale: This is the closest in-repo precedent and works for source-tree adapters without packaging entry points.
   - Alternative considered: Python package entry points. They are a good long-term extension point for third-party adapter packages, but they add packaging complexity and are unnecessary for in-tree adapters.

2. **Store adapter factories as `"module:attr"` strings.**
   - Rationale: Strings are safe to read during discovery and keep implementation modules unimported until selected.
   - The registry should validate the colon format, duplicate adapter keys, and non-string mappings when reading manifests.

3. **Preserve `register(name, cls)` for direct tests/manual registration, but make discovery use `register_path()`.**
   - Rationale: Existing adapter unit tests call `register(registry)` directly and external code may construct an `AdapterRegistry` for tests. Keeping direct registration avoids unnecessary churn.
   - Discovery should not call old adapter-level `register()` functions because doing so requires importing implementation modules.

4. **Fail clearly on selected adapter load errors.**
   - Unknown adapter names should list `available()` keys.
   - Missing implementation module or attribute should identify the selected adapter key and import path.
   - Optional dependency errors should remain adapter-specific. `openarm_rs` should keep its current clear missing-binding error when the selected path reaches its binding import.

5. **Update all built-in manipulator adapters in one migration.**
   - Rationale: Partial migration could make `available()` omit existing adapters or keep eager imports for some adapters. Each existing adapter package should get a manifest preserving its current key.

## Safety / Simulation / Replay

This change should not alter hardware commands or simulation behavior. It only changes when adapter implementation modules are imported.

Safety-relevant expectations:

- Listing adapters must be safe in environments without hardware SDKs or platform-gated extras.
- Selecting an adapter that needs a missing SDK must fail before unsafe hardware commands are issued.
- `openarm_rs` must preserve its staged validation path: binding availability, mock/virtual CAN validation, then real hardware gravity/trajectory validation.
- `sim_mujoco` should remain selectable by key without causing simulation imports during unrelated adapter listing.

Manual QA should use the library surface: import the registry, list adapters, create a mock adapter, and exercise selected-adapter missing-binding behavior for an optional adapter in a controlled test environment.

## Risks / Trade-offs

- **Manifest drift:** A manifest path can point at a missing module or attribute. Mitigate with focused registry tests that resolve every built-in adapter factory in an environment with project extras available, plus clear selected-path errors.
- **Duplicate keys:** Multiple manifests can claim the same adapter key. Mitigate by rejecting conflicting registrations during discovery.
- **Behavioral timing shift:** Some import-time errors move from registry import to `create()` or adapter connect. This is intentional for optional dependencies, but selected-path errors must remain actionable.
- **Docs mismatch:** Existing docs describe `adapter.py` auto-discovery. Update adapter authoring docs so new adapters add a manifest.
- **Scope creep:** Drive-train and whole-body registries use similar eager patterns, but migrating them is out of scope for this change.

## Migration / Rollout

1. Add lazy path registration support to `AdapterRegistry` while preserving direct class registration for tests.
2. Change manipulator discovery to import `<adapter>.__registry__` manifests instead of `<adapter>.adapter` modules.
3. Add `__registry__.py` manifests for each existing built-in manipulator adapter key.
4. Update tests to assert that registry import/listing does not import adapter implementation modules and that `create()` imports only the selected adapter.
5. Update OpenArm RS and Damiao binding tests to preserve selected-adapter-scoped missing-binding behavior.
6. Update manipulator adapter authoring documentation.

No generated blueprint registry update is expected. Rollback is straightforward: restore eager adapter module discovery and remove manifests, but that would also restore registry-time optional import pressure.

## Open Questions

- Should external third-party manipulator adapters eventually use Python entry points in addition to in-tree manifests?
- Should drive-train and whole-body registries be migrated to the same manifest pattern in a follow-up change?
