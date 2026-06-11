## Context

DimOS visualization currently centers on `vis_module()`, which composes `RerunBridgeModule`, `RerunWebSocketServer`, and `WebsocketVisModule` for robot blueprints. `RerunBridgeModule` already accepts `SubscribeAllCapable` pubsubs, `visual_override`, `max_hz`, `topic_to_entity`, and Rerun blueprint configuration. In practice, the default path is LCM-oriented: `vis_module()` supplies `LCM()`, the bridge subscribes to all messages, and renderability is decided when messages arrive.

The current CLI topic tools and `lcmspy` prove that live LCM observation is already useful. Instead of solving transport-agnostic discovery in v1, this design intentionally targets LCM topics only. It should use LCM subscribe-all behavior and typed channel names such as `/topic#pkg.Msg` to discover, decode, classify, and selectively log topics. Coordinator metadata, SHM, ROS, DDS, and cross-transport catalog behavior are deferred to a later version.

Rerun's web embedding documentation offers two relevant modes. An iframe is simple and can display an RRD file or `rerun+http://.../proxy` serve connection, but it does not provide programmable control over the viewer. The JavaScript package provides APIs and callbacks, but requires a JavaScript build setup and version alignment with the Rerun SDK. This design uses iframe embedding first and keeps a future JS-viewer path open.

The downloaded `dimos rerun debugger.zip` handoff is a high-fidelity HTML/React design reference for the selector UI. It should guide visual fidelity, layout, and interaction behavior, but it is not production code to copy. The implementation target remains NiceGUI/Quasar backed by the real LCM catalog collector and Rerun bridge selection control.

## Goals / Non-Goals

**Goals:**

- Provide a runtime LCM topic catalog based on live LCM observation.
- Provide a NiceGUI-based web app that lets users search, group, and select visualizable LCM topics.
- Embed the Rerun web viewer in the same page with an iframe connected to the running Rerun gRPC server.
- Ensure selected-only logging for visualized topics so high-bandwidth topics are not converted and logged unless selected.
- Preserve existing `vis_module()` and automatic Rerun behavior for current blueprints unless the selector app is enabled.

**Non-Goals:**

- Building a full JavaScript frontend or adopting the `@rerun-io/web-viewer` package in the first implementation.
- Porting the handoff's React prototype directly into DimOS production code.
- Replacing the native `dimos-viewer` workflow.
- Supporting SHM, ROS, DDS, or transport-agnostic discovery in the first milestone.
- Adding coordinator metadata as a catalog source in the first milestone.
- Persisting user selections across runs in the first milestone.
- Exposing or changing robot control skills, MCP tools, or hardware command semantics.

## DimOS Architecture

The change should add a selector-oriented LCM visualization path beside the existing Rerun bridge path.

### Catalog model

Introduce a catalog data model that describes live LCM topics. A catalog entry should include:

- LCM channel string and normalized topic name
- decoded message type when available from the `#pkg.Msg` suffix or configured type resolver
- renderability status: native `to_rerun()`, configured visual converter, unsupported, or unknown
- live diagnostics: observed state, last seen, rate, approximate bandwidth, message count, and last decode/render error
- selection state for the current session

LCM channel names are the v1 source of truth. This is a deliberate simplification, not the final architecture. The catalog should still keep fields structured so a future version can add module metadata or non-LCM transports without replacing the UI model.

Untyped or undecodable LCM topics should still appear in the catalog with an unsupported or unknown renderability status. Users should be able to see that traffic exists even when the selector cannot render it.

### LCM discovery and diagnostics

Use the existing LCM subscribe-all mechanism as the v1 discovery source:

- subscribe to all LCM channels using the same underlying capability as the current bridge and `lcmspy`
- update catalog entries as messages arrive
- parse typed channel suffixes to identify message classes when possible
- track message count, last seen time, approximate rate, and approximate bandwidth
- classify renderability by decoded message support and configured visual overrides

The v1 implementation does not need new coordinator RPCs or new DimOS `Spec` Protocols. If a clean internal boundary is helpful, use a small Python Protocol for a catalog provider and a separate selection controller, but keep it local to the visualization app/bridge rather than making a new public module interface.

### Rerun bridge selection control

Refactor or wrap `RerunBridgeModule` so selection is applied before conversion and logging. The selected-only path should avoid work in this order where practical:

1. Subscribe to LCM broadly enough to maintain the live catalog.
2. Drop unselected topics before decode-heavy work, `visual_override`, and `to_rerun()` conversion when possible.
3. Decode and log selected topics to stable Rerun entity paths.
4. Send or update Rerun blueprints/layouts to reflect selected topics.

Existing automatic rendering should remain the default for current users. The selector app should opt into managed-selection mode or be added through a new visualization helper so existing blueprints do not silently lose streams.

### NiceGUI web app

Use NiceGUI for the first implementation because the desired UI can stay Python-first. NiceGUI runs on FastAPI/Starlette/uvicorn and uses a websocket-backed UI model, which fits DimOS's existing Python module style better than introducing a full JS application for the first milestone.

The app should provide:

- a full-viewport visual console with a header bar, fixed-width catalog rail, Rerun viewer panel, and selection tray
- a topic table with search, domain/type grouping, renderability badges, live status badges, and current-session selection controls
- filter chips for renderable, live, and selected topics
- a Rerun iframe panel connected to the active Rerun web viewer URL or `app.rerun.io` URL with the `rerun+http://.../proxy` target
- a Rerun toolbar with connection state, proxy URL, reconnect/open actions, and connection hints when the Rerun gRPC server or web viewer is not available
- a bridge footer that shows no-topic state or entity chips for currently applied/logging topics

The NiceGUI app should be a DimOS module or a module owned by the visualization blueprint so it can share lifecycle and global config with the bridge. It should not own robot command streams. For v1, backend APIs can be local to the visualization app and explicit bridge selection RPCs; coordinator RPCs are not required.

### Web UI/UX concept

The first UI should feel like a robotics mission-control surface rather than a generic admin table. The visual direction should follow the handoff closely: dark, dense, low-chroma chrome; high-contrast typography; compact status chips; mono telemetry for channels, types, URLs, rates, and counts; clear type/renderability badges; and a strong split between "what is flowing" and "what is currently rendered".

Suggested layout:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ DimOS Visual Console        run: unitree-go2-replay  LCM 31 ch  Rerun ok │
├─────────────────────────────┬──────────────────────────────────────────────┤
│ Catalog controls            │ Rerun viewer toolbar                         │
│ ┌ Search LCM topics...    ┐ │                                              │
│ │ Filters: render live sel │ │  iframe: app.rerun.io / local viewer        │
│ │ Groups: type/status      │ │                                              │
│ └──────────────────────────┘ │                                              │
│                             │                                              │
│ LCM topic catalog           │                                              │
│ ▣ /color_image  Image       │                                              │
│   14 Hz | renderable | live │                                              │
│ □ /global_map   PointCloud2 │                                              │
│   renderable | idle          │                                              │
│ □ /cmd_vel      Twist       │                                              │
│   unsupported | live        │                                              │
│                             │ BRIDGE: world/camera/color  world/tf         │
├─────────────────────────────┴──────────────────────────────────────────────┤
│ Selection tray: 3 staged | 2 logging | Apply selection | Clear             │
└────────────────────────────────────────────────────────────────────────────┘
```

Core interaction model:

- The left pane is the authoritative live LCM catalog for v1. Users select topics there; the Rerun iframe reflects what the bridge logs.
- Topic rows should show channel name, decoded type, renderability, and live status.
- Unsupported topics should remain visible but disabled by default with a short reason such as "no to_rerun()", "no visual converter", or "unknown message type".
- Bandwidth and rate should remain visible where available so users can understand logging cost, but this milestone should not introduce a formal heavy-topic classification rule.
- Applying selection should be explicit. Toggling a checkbox stages the change only; nothing starts or stops logging until an "Apply selection" action copies staged selection into the applied/logging selection. This avoids accidental high-bandwidth logging while a user is browsing.
- Applied/logging topics should be visually distinct from staged-only topics, including a row badge and entity chips in the Rerun bridge footer.
- Empty and degraded states matter: no LCM data, no Rerun server, no renderable topics, only untyped topics, and iframe connection failure should each have an actionable message.

NiceGUI implementation hints:

- Use a `ui.splitter` or responsive row layout with a fixed-width catalog rail and a flexible iframe panel.
- Default to a compact `ui.table`-style topic list; a card layout can remain a later option rather than a v1 requirement.
- Use `ui.badge`/chip-like elements for `renderable`, `converter`, `unsupported`, `unknown type`, `live`, `idle`, `latched`, `logging`, and message type labels.
- Use `ui.timer` for periodic catalog refresh, but keep refresh lightweight and avoid blocking the NiceGUI event loop.
- Use a plain `ui.html` iframe for the first Rerun embed; reserve a future custom component for the Rerun JS package path.
- Use custom CSS/classes where needed to match the handoff's dark tokens, compact spacing, 1px borders, mono telemetry, and low-animation interaction style. Do not depend on the handoff's React component structure.

### Blueprint composition and CLI

Keep `vis_module(viewer_backend=global_config.viewer, rerun_config=...)` working as-is. Add an opt-in path such as a selector-enabled visualization config or helper blueprint that composes:

- Rerun bridge in managed-selection mode
- Rerun web viewer serving/connection support
- NiceGUI selector app
- existing `RerunWebSocketServer` only for its current viewer-to-robot click/teleop role, not as the catalog API

The CLI may gain a flag or command later, but the first design should avoid requiring a new public CLI to use existing robot stacks. If a CLI surface is added, it should be additive and documented.

No MCP skill exposure is planned. The selector app is an operator/developer visualization surface, not an agent tool surface.

## Decisions

1. **Use live LCM observation as the v1 catalog.**
   - Rationale: LCM subscribe-all behavior already exists and gives the fastest useful selector for current Rerun-backed stacks.
   - Alternative: coordinator metadata first. Deferred because it makes v1 more complex and does not directly answer which topics are currently flowing.

2. **Defer transport-agnostic discovery.**
   - Rationale: SHM, ROS, DDS, and coordinator metadata can be added after the LCM UX and selected-only bridge behavior are proven.
   - Alternative: hybrid immediately. Rejected as over-designed for v1.

3. **Use NiceGUI for the first UI.**
   - Rationale: it keeps the UI Python-first, matches the user's preference, and avoids introducing a JS build for the first milestone.
   - Alternative: FastAPI plus static HTML. Lower dependency cost but slower to build an interactive topic table and selection UX.
   - Alternative: React/Vite plus Rerun JS viewer. More powerful but introduces JS build tooling and Rerun web-viewer version coupling.

4. **Embed Rerun with an iframe first.**
   - Rationale: iframe embedding is simple and works with Rerun's served recordings or gRPC proxy URLs.
   - Trade-off: the iframe does not provide programmable viewer control. Selection state must live in DimOS, and Rerun layout changes must be sent from Python via the bridge.

5. **Apply selection before conversion/logging.**
   - Rationale: images, point clouds, and maps can be expensive to decode, convert, and send to Rerun. Hiding after logging is not sufficient.
   - Alternative: log all topics and use Rerun entity visibility. Rejected for high-bandwidth default behavior, but still useful for cheap visibility/layout changes after a topic is selected.

6. **Session-only selection for the first milestone.**
   - Rationale: avoids config format and multi-user semantics while the catalog and bridge filtering behavior are stabilized.
   - Future: named local presets per blueprint or robot model can be added later.

7. **Use the React handoff as visual/interaction reference only.**
   - Rationale: the handoff captures the intended full-screen console, stage/apply flow, status chrome, and degraded states, but production should remain NiceGUI/Quasar.
   - Alternative: port the React prototype. Rejected because it would contradict the Python-first UI decision and introduce a JS application surface in v1.

8. **Defer quick presets.**
   - Rationale: the handoff intentionally removes presets from v1, keeping the first workflow focused on explicit user selection.
   - Future: add named local presets after the selector behavior is proven.

## Safety / Simulation / Replay

The selector app is visualization-only. It must not publish robot command streams, call movement skills, or change MCP-visible capabilities. Existing click-to-navigate and teleop behavior should remain owned by existing viewer websocket paths and must not be conflated with topic selection.

For real robots, the main safety constraint is resource pressure: the app should avoid accidentally enabling every high-bandwidth topic. Defaults should prefer catalog display first, then explicit user selection before any selected-only logging begins. The UI should keep rate and bandwidth diagnostics visible when available so users can make informed choices.

For simulation and replay, v1 should work when the stack publishes LCM topics during replay/simulation. Stored-but-not-publishing replay streams are out of scope for v1 and can be handled later by metadata or recorded-stream integrations. Manual QA should include at least one replay or simulation stack where LCM topics are actively flowing and no real hardware is required.

## Risks / Trade-offs

- **NiceGUI dependency and lifecycle:** NiceGUI is not currently a core DimOS dependency. Adding it increases dependency surface and introduces a websocket UI runtime. Mitigation: keep it in an optional visualization extra if possible and run it as a dedicated visualization module.
- **Single event loop sensitivity:** NiceGUI UI callbacks share an asyncio event loop. Blocking catalog scans or transport checks can freeze the UI. Mitigation: keep catalog snapshots lightweight and move blocking work to background tasks or threads.
- **High-fidelity UI in NiceGUI:** Matching the handoff may require custom CSS over Quasar defaults. Mitigation: treat the handoff's tokens, layout, and interaction flow as fidelity targets while keeping implementation idiomatic NiceGUI.
- **Iframe limitations:** iframe embedding cannot read viewer state or subscribe to selection callbacks. Mitigation: make DimOS selection state authoritative and use Rerun blueprints from Python for layout updates.
- **Rerun version mismatch:** Rerun's documentation currently describes web viewer packages at newer versions than this repo's pinned `rerun-sdk==0.32.0a1` and `dimos-viewer==0.32.0a1`. The iframe path reduces immediate JS package coupling, but URLs and serve behavior must be verified against the pinned SDK.
- **LCM-only scope:** v1 will not show SHM, ROS, DDS, or stored replay streams unless they are bridged to LCM. Mitigation: state this clearly in the UI/docs and keep the catalog model extensible.
- **Untyped LCM topics:** Some LCM channels may not include a type suffix and may be undecodable. Mitigation: show them as observed but unsupported unless the user/config provides a decoder.
- **Compatibility with automatic rendering:** Existing users expect topics to appear automatically. Mitigation: make managed selection opt-in and preserve current defaults.

## Migration / Rollout

Rollout should be additive:

1. Add an LCM topic catalog collector with typed-channel parsing and live stats.
2. Add managed-selection support to the Rerun bridge while preserving existing auto-render behavior.
3. Add the NiceGUI selector module with iframe embedding.
4. Compose the selector into an opt-in visualization helper or config path.
5. Document the v1 LCM-only scope in `docs/usage/visualization.md` and developer guidance for making LCM topics renderable.

If a new runnable blueprint is added, regenerate and verify the blueprint registry with `pytest dimos/robot/test_all_blueprints_generation.py`. If only `vis_module` configuration and modules are changed, no generated registry update should be required.

Rollback should be simple: disable the selector-enabled visualization helper and fall back to current `vis_module()` behavior.

## Future Work

- Add coordinator-derived stream metadata for module owner, direction, transport descriptor, and metadata-only streams.
- Add SHM, ROS, DDS, and recorded replay catalog sources.
- Add named/persistent presets once session-only selection behavior is proven.
- Add card layout, rail-docked tray, accent variants, and other prototype tweaks if the default table console proves insufficient.
- Consider a Rerun JS viewer integration when programmable viewer state is worth the build-tooling cost.

## Open Questions

- Should NiceGUI be a core dependency, part of the `visualization` extra, or a new optional extra for web visualization?
- What exact URL should the iframe use in production: locally served Rerun web viewer, `app.rerun.io/version/{RERUN_VERSION}`, or a DimOS-hosted static viewer asset?
- Should selector-enabled visualization be a global CLI flag, a new helper around `vis_module()`, or an explicit blueprint component?
- Should v1 allow manual type hints or decoder registration for untyped LCM channels?
- Should the first UI expose only renderable topics by default, or show all observed LCM topics with unsupported topics disabled?
