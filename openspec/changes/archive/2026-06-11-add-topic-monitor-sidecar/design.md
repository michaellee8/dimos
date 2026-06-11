## Context

The selector stack now has the useful backend pieces: a raw LCM catalog path, renderability classification, staged/apply topic selection, selected-only Rerun logging, a Reflex selector UI, and a hardware-free demo. The remaining UX problem is where that selector lives. Today, users must choose a selector-enabled blueprint before starting the robot or simulation, which turns a diagnostic tool into blueprint composition burden.

DimOS already has a CLI diagnostic pattern: `dimos top`, `dimos lcmspy`, `dimos topic echo`, and related tools attach to a running environment without changing the robot stack. `dimos topic monitor` should follow that model. It should be an independent foreground sidecar that observes the shared LCM bus, owns its own Rerun/Reflex services, and uses active-run metadata only as context.

Important constraint: this is not “control the existing visualizer.” LCM is bus-level; a sidecar can observe live traffic, but it cannot reliably isolate topics by run or disable an embedded bridge already logging data. The monitor must be framed as an independent selected-only view.

## Goals / Non-Goals

**Goals:**

- Add `dimos topic monitor` as the default attach-style workflow for interactive topic cataloging and selected visualization.
- Run in the foreground, open the selector webpage automatically when possible, and exit on Ctrl-C/SIGTERM.
- Discover all visible live LCM topics by default with no include/exclude programming burden.
- Allocate isolated free ports for the sidecar Rerun gRPC server, Rerun web viewer, selector API, selector frontend, and Reflex backend.
- Support active-run metadata mode and no-run bus-only mode.
- Reuse the Reflex selector UI and selected-only bridge/catalog behavior from the previous selector work.
- Remove selector-specific wiring from ordinary/simulation blueprints and remove/deprecate `vis_module_with_selector(...)` as a public composition path.
- Keep a dedicated demo blueprint for smoke testing and onboarding.

**Non-Goals:**

- Controlling, disabling, or reconfiguring a Rerun bridge already embedded in the running blueprint.
- Reducing publisher CPU, LCM network traffic, or cost from any existing embedded visualization.
- SHM, ROS, DDS, JPEG, or replay database catalog discovery in v1 unless those streams are actively bridged to LCM.
- Loading blueprint-specific `visual_override`, static Rerun scene config, or custom topic-to-entity mappings in v1.
- Terminal-only fallback if visualization dependencies are missing.
- Persistent topic selections, multi-user auth, HTTPS, or remote access hardening beyond local-host defaults.

## DimOS Architecture

### Runtime shape

```text
normal DimOS run or external publishers
        │
        ▼
   LCM multicast bus
        │
        ▼
┌─────────────────────────────────────────┐
│ dimos topic monitor                     │
│                                         │
│ raw LCM catalog                         │
│     │                                   │
│     ├── selector API ◀── Reflex UI      │
│     │          │             │          │
│     ▼          ▼             ▼          │
│ selected-only Rerun bridge ─ iframe URL │
└─────────────────────────────────────────┘
```

The sidecar should be implemented as CLI-owned runtime, not as a module injected into an existing coordinator. It can reuse lower-level components from `RerunBridgeModule` and `RerunTopicSelectorModule`, but it must not require `autoconnect(...)` or blueprint wiring.

### CLI entry point

Add a `monitor` command under the existing `topic` Typer namespace:

```bash
dimos topic monitor
dimos topic monitor --no-open
dimos topic monitor --run latest
dimos topic monitor --run <run-id>
```

V1 should not add include/exclude topic filters. The app is the filtering surface.

The command should:

1. Look up the latest active run through the run registry unless `--run` is provided.
2. If no active run exists, print a bus-only mode message and continue.
3. Allocate an isolated free port set.
4. Start the selected-only bridge/catalog sidecar, selector API, Reflex frontend/backend, and Rerun web viewer.
5. Open the selector UI automatically by default when interactive.
6. Print the selected run context, actual URLs, and Ctrl-C stop instruction.
7. Keep running until Ctrl-C/SIGTERM regardless of whether the target run exits.

### Port allocation

The sidecar must not silently reuse the default Rerun ports. Existing Rerun startup can connect to an already-bound gRPC server; that behavior is useful in embedded mode but dangerous in sidecar mode because it undermines isolated selected-only logging.

Use auto-isolated ports by default. If explicit ports are later added and any are occupied, fail loudly rather than falling back to an existing server. The port set must cover:

- Rerun gRPC/proxy source URL
- Rerun web viewer URL
- selector API
- selector frontend
- Reflex backend websocket/API

The selector iframe must continue to use a connected Rerun web URL with encoded `url=rerun%2Bhttp...%2Fproxy` source query.

### Selector/Rerun components

The current `RerunTopicSelectorModule` combines two concerns: a selector API that forwards to bridge selection methods, and a Reflex subprocess lifecycle. For sidecar mode, factor or wrap these concerns so the CLI can start them without a DimOS Module/Blueprint. The code-level contract can remain conceptually similar to `RerunTopicSelectionSpec`:

- get catalog snapshot
- stage topics
- apply staged topics
- clear staged topics
- set applied topics when needed

The sidecar bridge/catalog should use raw LCM observation and selected-only decode/log behavior. Generic renderability comes from typed LCM channels and native `to_rerun()` support. Unknown and unsupported topics remain visible but not selectable.

### Blueprint and registry cleanup

Remove selector wiring from normal/simulation blueprints that only existed to provide QA for embedded selector mode, especially selector-specific simulation blueprints. Keep a dedicated selector demo blueprint as the demo capability. If removing or renaming exported blueprint variables changes registry output, regenerate with:

```bash
CI=true uv run pytest dimos/robot/test_all_blueprints_generation.py -q
```

The standard `vis_module(...)` automatic visualization behavior should remain unchanged. `vis_module_with_selector(...)` should be removed or deprecated after `dimos topic monitor` replaces it as the supported workflow; if the implementation keeps a private helper for demo/testing, it should not be documented as the recommended user surface.

### Dependencies

`dimos topic monitor` requires the visualization extra. Missing Rerun/Reflex/FastAPI/Uvicorn dependencies should fail with a clear installation hint:

```bash
uv sync --extra visualization
```

The Reflex split-port runtime caveat remains relevant: current local service topology should use the verified split-port mode rather than assuming Reflex production mode supports separate frontend/backend ports.

## Decisions

1. **Use an independent sidecar, not existing-bridge control.**
   - Rationale: works with ordinary blueprints and avoids requiring pre-enabled selector RPCs.
   - Alternative: control an existing selector-enabled bridge. Rejected for v1 because it preserves the pre-embedding burden.

2. **Use `dimos topic monitor` as the canonical command.**
   - Rationale: it belongs with `topic echo` and `topic send`; the product is a live topic catalog and visualization monitor, not a Rerun-specific command.

3. **Run foreground and auto-open the selector UI.**
   - Rationale: matches diagnostic tools and makes lifecycle obvious. Browser-open failure should be non-fatal and print the URL.

4. **Keep running until Ctrl-C, even if the target run exits.**
   - Rationale: the monitor observes the bus, and external publishers or late restarts may still be useful.

5. **Allow bus-only mode when no DimOS run is active.**
   - Rationale: LCM observation is useful for manual publishers, partially broken runs, and external tools. CLI output should make this explicit.

6. **Do not warn about existing visualization in v1.**
   - Rationale: the monitor is intentionally independent; extra detection logic is not needed for v1.

7. **Discover all visible LCM topics by default.**
   - Rationale: the interactive app is the filtering surface; v1 should avoid programming burden through include/exclude flags.

8. **Generic rendering only.**
   - Rationale: sidecar mode cannot assume access to blueprint-specific visual config. Custom config plugins can be a future feature.

9. **Remove embedded selector as the normal blueprint model, keep demo capability.**
   - Rationale: recommended workflow should be run-normal-then-monitor. A dedicated demo remains useful for smoke tests.

## Safety / Simulation / Replay

The topic monitor is visualization-only. It subscribes to LCM and logs selected topics to its own Rerun viewer; it must not publish robot command streams, call skills, or modify MCP-exposed tools. Stage/apply actions affect only the monitor's own logging selection.

Simulation QA should use a normal simulation stack plus `dimos topic monitor`, not a selector-wired simulation blueprint. Replay QA is in scope only when replay publishes live LCM topics. Hardware QA should verify the monitor can attach to a running robot stack without changing robot behavior.

## Risks / Trade-offs

- **Run identity ambiguity:** LCM traffic is bus-level, so active run metadata does not guarantee topic isolation. Mitigation: document and print bus-only/observing wording.
- **Port collisions:** Fixed default ports can accidentally connect to existing servers. Mitigation: auto-isolated ports and fail on explicit conflicts.
- **Resource cost:** The sidecar still receives all LCM bytes and does not reduce upstream publisher/network load. Mitigation: selected-only decode/log and UI bandwidth warnings; CLI include/exclude deferred.
- **Lost blueprint-specific rendering:** Custom visual overrides are unavailable. Mitigation: generic rendering scope in v1; future config plugin if needed.
- **Reflex lifecycle:** The sidecar must clean up Reflex/API/Rerun children on Ctrl-C. Mitigation: foreground owner process and focused lifecycle tests.
- **Two selector models during migration:** Embedded helper and sidecar can confuse docs. Mitigation: docs make `dimos topic monitor` recommended; remove/deprecate helper.

## Migration / Rollout

1. Introduce sidecar runtime helpers and `dimos topic monitor` CLI.
2. Reuse/refactor the Reflex selector app and selected-only catalog/bridge behavior for non-blueprint lifecycle.
3. Add auto port allocation and connected Rerun URL generation for sidecar mode.
4. Remove selector wiring from normal/simulation blueprints and remove/deprecate `vis_module_with_selector(...)` as public API.
5. Keep and verify a dedicated demo blueprint.
6. Update docs and generated registry if blueprint exports change.

Rollback is straightforward: leave `dimos topic monitor` undocumented/disabled and keep the existing embedded selector demo path until sidecar issues are fixed.

## Open Questions

- Should the sidecar runtime be a reusable Python function in visualization code or a CLI-only module under `dimos/robot/cli/`?
- What exact auto port allocation range should be preferred before falling back to OS-assigned ports?
- Should browser auto-open be disabled automatically when stdout is not a TTY, or only through `--no-open`?
- Should the dedicated demo blueprint keep selector pre-wiring long-term, or eventually become a publisher-only demo paired with `dimos topic monitor`?
