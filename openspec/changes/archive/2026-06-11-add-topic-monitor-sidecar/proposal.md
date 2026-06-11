## Why

The Rerun topic selector currently requires a blueprint to opt into selector wiring before the run starts. That makes the common workflow backwards: users must decide to embed visualization tooling while authoring or choosing a robot stack, rather than running a normal stack and attaching diagnostic visualization when they need it.

DimOS already has an attach-style mental model for diagnostics (`dtop`, `lcmspy`, `topic echo`). The topic selector should follow that model: start a foreground sidecar that observes live LCM traffic, lets users manually choose renderable topics, and logs selected topics to its own Rerun viewer without mutating the running robot or simulation stack.

## What Changes

- Add public CLI behavior: `dimos topic monitor` starts an interactive topic monitor sidecar.
- The monitor discovers all visible live LCM topics by default and uses the existing Reflex selector experience for search, filters, staged selection, apply/clear, and embedded Rerun viewing.
- The monitor runs in the foreground, opens the selector web page automatically by default, allocates isolated free ports for its own Rerun/Reflex/API services, and exits on Ctrl-C/SIGTERM.
- If a DimOS run is active, the monitor uses the latest or requested run only as metadata/context; if no run is active, it starts in explicit LCM bus-only mode.
- Remove selector-specific visualization wiring from normal/simulation blueprints and remove/deprecate `vis_module_with_selector(...)` as a general blueprint composition surface.
- Keep a dedicated hardware-free selector demo capability for smoke testing and onboarding.
- V1 is LCM-only and generic-rendering-only: typed LCM topics with native `to_rerun()` support are renderable; blueprint-specific `visual_override`/`static` presets are not loaded by `dimos topic monitor`.

## Affected DimOS Surfaces

- Modules/streams:
  - Rerun topic catalog and selector-managed bridge behavior.
  - Reflex selector API/UI lifecycle reused outside blueprint composition.
  - LCM raw topic subscription path for sidecar observation.
- Blueprints/CLI:
  - Add `dimos topic monitor` under the existing `topic` CLI namespace.
  - Remove selector-specific wiring from normal/simulation blueprints; keep only a dedicated demo selector blueprint if still useful.
  - Generated blueprint registry may change if selector-only blueprints are removed or demo names change.
- Skills/MCP:
  - No agent skill, MCP tool, or robot command behavior changes.
- Hardware/simulation/replay:
  - No hardware command changes.
  - Simulation and replay stacks can be monitored without pre-embedding selector modules when they publish LCM topics.
- Docs/generated registries:
  - Update visualization and CLI docs to make `dimos topic monitor` the recommended workflow.
  - Update contributor guidance to describe sidecar lifecycle and generated Reflex artifacts.
  - Regenerate `dimos/robot/all_blueprints.py` if blueprint exports change.

## Capabilities

### New Capabilities
- `topic-monitor-sidecar`: Foreground attach-style live LCM topic cataloging and selected-only visualization through an independent sidecar.

### Modified Capabilities
- `rerun-topic-selection`: Shift the recommended selector workflow from blueprint-embedded selector visualization to `dimos topic monitor`, while preserving selected-only logging semantics and the Reflex selector UX.

## Impact

Users can run ordinary robot or simulation blueprints and later attach a topic monitor without editing or choosing selector-enabled blueprints. The monitor does not control or disable visualization already running in the robot stack; it owns an independent Rerun viewer and selector service. This improves workflow ergonomics but means the monitor does not reduce publisher/network load or embedded visualization cost.

Developers need a small sidecar runtime entrypoint, CLI command, port allocation policy, lifecycle cleanup, docs, and tests. The visualization extra remains required because the monitor depends on Rerun, Reflex, FastAPI/Uvicorn, and generated web assets. Manual QA should cover bus-only mode, active-run metadata mode, isolated port behavior, browser opening, selected-only logging, and demo/simulation topic monitoring.
