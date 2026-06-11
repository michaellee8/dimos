## Context

The current selector implementation from `add-rerun-topic-selector-app` establishes the important backend behavior: `RerunBridgeModule` can catalog live LCM traffic, classify renderability, stage/apply selected topics through RPC, and avoid logging unselected topics before expensive conversion. It also introduced an opt-in selector visualization helper and a hardware-free `demo-rerun-topic-selector` blueprint.

The UI layer is the part under reconsideration. The current NiceGUI module runs a FastAPI/NiceGUI app from a dedicated DimOS worker and uses a timer to poll `get_topic_catalog()`. It embeds Rerun with an iframe, and the iframe source must include an encoded Rerun source URL such as `http://localhost:9878/?url=rerun%2Bhttp%3A%2F%2F127.0.0.1%3A9877%2Fproxy`. This URL contract should not change.

Reflex is a Python-authored web framework that compiles a React/Next frontend and runs a backend state server over websockets. That model appears closer to the desired design artifact: declarative layout, explicit state variables, event handlers, reusable component composition, and a browser app that can grow beyond a server-rendered table. The cost is operational: Reflex introduces a frontend build/runtime surface and likely Node/Bun/npm tooling.

## Goals / Non-Goals

**Goals:**

- Replace the selector's NiceGUI frontend/runtime with a Reflex-based selector app.
- Preserve the existing selector backend contract and behavior: catalog polling, staged selection, apply/clear actions, selected-only logging, and connected Rerun iframe.
- Move UI state into a clear Reflex state model with typed-ish rows, filters, status summaries, and event handlers.
- Match the current design artifact more closely: dark mission-control layout, fixed catalog rail, status chips, compact telemetry, disabled unsupported topics, and an embedded Rerun panel.
- Keep `vis_module(...)` default automatic visualization unchanged.

**Non-Goals:**

- Rewriting the LCM catalog collector or Rerun bridge selection behavior.
- Changing robot command streams, click-to-navigate, teleop, MCP skills, or hardware control semantics.
- Adding SHM/ROS/DDS/catalog metadata support.
- Persisting topic selections across runs.
- Building a custom Rerun JavaScript viewer integration; the iframe remains the first target.
- Requiring a new public CLI flag before the selector can be used.

## DimOS Architecture

The change should preserve this boundary:

```text
LCM traffic ──▶ RerunBridgeModule ──▶ Rerun gRPC proxy ──▶ Rerun web viewer
                    ▲       │                                  ▲
                    │       │                                  │
                    │       └── catalog + selection RPCs        │
                    │                                          iframe
                    └──────────── Reflex selector app ◀─────────┘
```

### Backend contract

Continue using the existing selector bridge RPC shape rather than inventing a new transport:

- `get_topic_catalog() -> list[dict[str, Any]]`
- `stage_topics(topics: list[str]) -> list[str]`
- `apply_staged_topics() -> list[str]`
- `clear_staged_topics() -> list[str]`
- `set_applied_topics(topics: list[str]) -> list[str]`

If the current `RerunTopicSelectionSpec` DimOS `Spec` Protocol remains useful, keep it as the code-level contract. The OpenSpec capability requirement is the observable behavior, not the Python Protocol name.

### Reflex app structure

The Reflex app should model the UI as explicit state:

- catalog rows returned by the bridge
- search query
- renderable/live/selected filter booleans
- staged and logging counts
- live/renderable channel counts
- last refresh time and last error
- connected Rerun viewer URL

Events should include:

- refresh catalog
- update search and filters
- toggle topic staged selection
- apply staged selection
- clear staged selection

Periodic refresh can begin with a simple one-second event trigger. If refresh calls block or overlap, the implementation should move to Reflex background events or a controlled polling loop.

### Service/runtime shape

There are two plausible runtime patterns:

1. **Standalone Reflex subprocess owned by the selector module.**
   - The DimOS module starts/stops a Reflex process or command.
   - This isolates Reflex's frontend/backend runtime from the worker process.
   - It likely fits Reflex's CLI/build assumptions better.

2. **Embedded Reflex backend in a dedicated worker.**
   - The selector module starts the Reflex backend/frontend from inside its worker.
   - This keeps lifecycle local but may fight Reflex's expected project and process model.

The proposal should prefer the standalone subprocess unless investigation proves an embedded API is stable. DimOS already learned that UI frameworks can behave differently in non-main worker processes; this migration should verify Reflex with a real `dimos run`, not import-only tests.

### Ports and URLs

The selector config should include or derive:

- selector frontend host/port
- Reflex backend/API host/port if separate from frontend
- browser-facing Reflex API URL when frontend and backend are served on different origins
- Rerun web viewer URL
- Rerun source connect URL (`rerun+http://.../proxy`)

The Rerun iframe source must be generated with the encoded `url=` query parameter. This is not optional: the bare Rerun web viewer root can load without data.

### Blueprint composition and registry

Keep the selector-enabled visualization helper as the public composition surface. The demo blueprint should remain PC-runnable without hardware. The generated registry only needs regeneration if blueprint names or module-level blueprint variables change; replacing internals should not require registry changes.

### Dependencies

Reflex should be added to an optional visualization/web extra rather than core DimOS unless later evidence shows it is required broadly. NiceGUI can be removed from that extra only after no code imports it. The implementation must document any Node/Bun/npm requirement Reflex introduces and how `uv sync --extra visualization` behaves on a clean machine.

## Decisions

1. **Replace only the UI/runtime layer, not the bridge/catalog layer.**
   - Rationale: the current backend behavior is the valuable stable contract, and the observed failures were viewer URL/runtime/UI framework issues.
   - Alternative: rewrite the entire selector stack. Rejected as unnecessary risk.

2. **Use Reflex state/events as the primary UI model.**
   - Rationale: search, filters, staged rows, badges, and status summaries map naturally to state and events.
   - Alternative: keep NiceGUI and add more CSS. Lower dependency churn but likely slower to match the design artifact.

3. **Prefer a standalone Reflex service/process first.**
   - Rationale: Reflex has a frontend build/server model and backend websocket state server; owning it as a small service is less likely to conflict with DimOS worker internals.
   - Alternative: embed Reflex directly in the module worker. Keep as a spike if subprocess lifecycle is too heavy.

4. **Keep iframe-based Rerun embedding.**
   - Rationale: the connected Rerun web URL is now understood and avoids Rerun JS package coupling.
   - Alternative: use the Rerun JS package. Deferred until programmable viewer control is needed.

5. **Keep NiceGUI as a temporary fallback only if migration risk is high.**
   - Rationale: a fallback may help during rollout, but long-term dual frontend implementations increase maintenance.

## Safety / Simulation / Replay

This is visualization-only. It must not publish robot command streams, call movement skills, or change MCP-visible tools. Existing Rerun websocket click/teleop behavior remains separate from selector catalog APIs.

Manual QA should use the hardware-free demo and at least one replay or simulation stack that publishes live LCM topics. QA should confirm that selecting a renderable topic logs subsequent data to the embedded Rerun viewer, clearing and applying stops subsequent logging, unsupported topics stay visible but disabled, and no native Rerun viewer opens for the demo.

## Risks / Trade-offs

- **Reflex build/runtime cost:** Reflex may require frontend tooling and generated assets. Mitigation: keep it in an optional extra and document clean-environment setup.
- **DimOS worker lifecycle mismatch:** Reflex may assume a project/process layout that does not embed cleanly. Mitigation: prefer a standalone subprocess and verify with real `dimos run`.
- **Port/API URL complexity:** Reflex frontend/backend and Rerun viewer/proxy add multiple browser-facing URLs. Mitigation: centralize URL generation and test it.
- **Two frontend stacks during migration:** Keeping NiceGUI and Reflex together can confuse users and developers. Mitigation: define a short-lived fallback window or remove NiceGUI once Reflex parity is proven.
- **State synchronization:** Reflex state can drift from bridge state if polling fails. Mitigation: treat bridge catalog snapshots as authoritative and surface refresh errors in the UI.

## Migration / Rollout

1. Build a Reflex selector app against the existing bridge RPC contract.
2. Add runtime configuration and startup/shutdown handling for the Reflex app.
3. Wire the selector-enabled visualization helper and demo blueprint to the Reflex UI.
4. Preserve or temporarily gate the NiceGUI selector until Reflex reaches parity.
5. Update docs and optional dependencies.
6. Remove NiceGUI selector code/dependency if no fallback is kept.

Rollback should disable the Reflex selector path and restore the NiceGUI selector or standard `vis_module()` behavior.

## Open Questions

- Should Reflex run as a subprocess controlled by `RerunTopicSelectorModule`, or should the module embed a Reflex app directly?
- Which ports should be defaults for Reflex frontend/backend relative to the Rerun viewer and existing DimOS web ports?
- Can Reflex be installed and run reliably through the existing `visualization` extra on clean Linux machines without manual Node/Bun setup?
- Should the first Reflex implementation keep a NiceGUI fallback flag, or should it replace NiceGUI outright once parity tests pass?
- How should Reflex-generated files/cache directories be handled in the repo and `.gitignore`?
