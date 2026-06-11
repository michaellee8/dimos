## 1. Implementation

- [x] 1.1 Spike the Reflex runtime model in this repo: confirm whether the selector should run as a subprocess/service or can be embedded safely in a dedicated DimOS worker.
- [x] 1.2 Add Reflex to the appropriate optional dependency group and document any Node/Bun/npm build/runtime requirements discovered by the spike.
- [x] 1.3 Create the Reflex selector app structure with state for catalog rows, search, renderable/live/selected filters, staged counts, logging counts, refresh status, errors, and Rerun viewer URL.
- [x] 1.4 Implement Reflex events for catalog refresh, search/filter updates, topic staging, applying staged selection, and clearing staged selection against the existing bridge selection RPC contract.
- [x] 1.5 Implement the Reflex visual console layout: header/status chips, fixed-width catalog rail, compact topic rows, renderability/live/logging badges, selection tray, degraded states, and embedded Rerun iframe.
- [x] 1.6 Preserve the connected Rerun iframe URL behavior using an encoded `url=rerun%2Bhttp...%2Fproxy` source URL, including wildcard bind host rewriting for browser-facing URLs.
- [x] 1.7 Wire selector-enabled visualization composition and the hardware-free demo blueprint to use the Reflex selector runtime while preserving default `vis_module(...)` automatic visualization behavior.
- [x] 1.8 Remove the NiceGUI selector implementation and dependency if Reflex reaches parity, or gate NiceGUI as an explicitly temporary fallback if removal is too risky.

## 2. Documentation

- [x] 2.1 Update `docs/usage/visualization.md` with the Reflex selector workflow, demo run command, selector/Reflex/Rerun URLs, selected-only logging behavior, unsupported topic states, and embedded viewer troubleshooting.
- [x] 2.2 Update contributor guidance with Reflex runtime/dependency conventions, generated/cache directory handling, and the distinction between default `vis_module(...)` and selector-enabled visualization.
- [x] 2.3 Update coding-agent guidance only if Reflex introduces new required local commands or generated files that agents must avoid editing directly.

## 3. Verification

- [x] 3.1 Run `openspec validate replace-nicegui-selector-with-reflex`.
- [x] 3.2 Run focused tests for Reflex state/event behavior, Rerun viewer URL generation, and selected-only bridge interaction.
- [x] 3.3 Run focused tests proving existing automatic Rerun visualization behavior remains unchanged when selector mode is disabled.
- [x] 3.4 Run lint/format checks for changed Python code and generated-free Reflex source files.
- [x] 3.5 Run docs validation: `uv run doclinks docs/usage/visualization.md` and `uv run md-babel-py run docs/usage/visualization.md`; also run `uv run doclinks docs/development/conventions.md` if contributor docs change.
- [x] 3.6 Run `CI=true uv run pytest dimos/robot/test_all_blueprints_generation.py -q` if blueprint registry inputs or generated registry output change.
- [x] 3.7 Smoke test the hardware-free demo with `uv run dimos --viewer rerun run demo-rerun-topic-selector --daemon`: confirm the Reflex selector URL responds, no native Rerun window opens, the embedded viewer URL includes encoded `url=rerun%2Bhttp...%2Fproxy`, selected topics appear in the embedded viewer, and clearing/applying stops subsequent logging.
- [x] 3.8 Manually QA through at least one replay or simulation stack that publishes LCM topics, confirming live catalog refresh, search/filtering, stage-without-logging, apply/clear behavior, unsupported topic display, applied/logging indicators, and Rerun viewer unavailable diagnostics.
