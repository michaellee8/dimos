## Why

The LCM topic selector now has a working backend shape: live LCM cataloging, staged topic selection, selected-only Rerun logging, and an embedded Rerun web viewer URL connected to the bridge gRPC proxy. The remaining friction is the frontend runtime. NiceGUI kept the first implementation Python-first, but matching the intended full-screen console from the design artifact requires increasing amounts of custom CSS, event-loop care, and framework-specific workarounds.

Reflex offers a Python-authored React/Next frontend model with explicit state, event handlers, reusable layout primitives, native iframe elements, and a clearer path toward a polished visual console. This change explores replacing the selector's NiceGUI frontend with Reflex while preserving the already-useful DimOS bridge and catalog contracts.

## What Changes

- Replace the selector web frontend implementation from NiceGUI to Reflex for selector-enabled visualization.
- Preserve the existing bridge/catalog behavior: live topic catalog snapshots, staged selection, explicit apply, clear staged selection, selected-only logging, and connected Rerun iframe URL semantics.
- Add a Reflex app/service runtime suitable for DimOS worker-managed visualization modules or a dedicated selector subprocess.
- Add configuration for Reflex frontend/backend ports and browser-facing API URLs where needed.
- Keep the standard `vis_module(...)` automatic Rerun path unchanged.
- Remove NiceGUI from the selector implementation once Reflex parity is achieved; dependency removal from extras is allowed if no other code uses NiceGUI.
- No **BREAKING** robot-control, MCP skill, hardware-safety, or default visualization behavior is intended.

## Affected DimOS Surfaces

- Modules/streams: Rerun selector UI module, Rerun bridge selection RPC boundary, LCM topic catalog presentation, visualization optional dependencies.
- Blueprints/CLI: selector-enabled visualization helper and the `demo-rerun-topic-selector` example blueprint; possible additional config for Reflex host/ports/API URL, but no required public CLI breakage.
- Skills/MCP: No skill or MCP tool behavior changes expected.
- Hardware/simulation/replay: Visualization-only behavior for real, simulation, and replay stacks that publish LCM topics; no robot command streams or hardware actuation semantics change.
- Docs/generated registries: visualization usage docs, contributor guidance for frontend dependencies/runtime, and focused tests. Generated blueprint registry should remain unchanged unless demo blueprint names or locations change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `rerun-topic-selection`: Replace the web frontend/runtime backing selector-enabled topic selection with Reflex while preserving observable selection, logging, and embedded viewer behavior.

## Impact

Users should see the same selector workflow with a more polished, design-faithful web console. Developers gain a more structured frontend state model for search, filters, status chips, row selection, and periodic catalog refresh, but the project takes on Reflex's runtime/build implications, including a React/Next frontend, backend websocket state server, and possible Node/Bun/npm tooling.

Compatibility risk is moderate around service startup, port allocation, browser API URLs, and packaging. The migration should be additive until parity is proven, then the NiceGUI selector path can be removed or left as a temporary fallback. Test scope should cover URL generation for the embedded Rerun viewer, periodic catalog refresh, staged/apply behavior, unsupported topic display, no native Rerun window behavior in the demo, and a real demo/replay smoke test.
