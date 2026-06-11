## 1. Implementation

- [x] 1.1 Add an LCM topic catalog collector that observes live LCM channels, tracks last seen time, message count, approximate rate, approximate bandwidth, and decode/render errors.
- [x] 1.2 Add typed-channel parsing and message type resolution for observed LCM topics, including visible unsupported status for untyped or undecodable channels.
- [x] 1.3 Add renderability classification for observed LCM topics using native Rerun conversion support and configured visual converters.
- [x] 1.4 Add managed-selection behavior for the Rerun logging path so unselected topics are dropped before expensive decode/conversion/logging work where practical.
- [x] 1.5 Preserve current automatic Rerun visualization behavior for existing `vis_module()` users unless selector-enabled visualization is explicitly enabled.
- [x] 1.6 Add a NiceGUI visual console with header status chips, fixed-width searchable topic catalog rail, renderable/live/selected filters, staged current-session selection, explicit apply/clear actions, bridge entity footer, and embedded Rerun iframe panel.
- [x] 1.7 Add an opt-in selector-enabled visualization composition path using the existing visualization conventions and without reusing `RerunWebSocketServer` as the catalog API.
- [x] 1.8 Add user-facing degraded states for no LCM data, no renderable topics, untyped-only topics, unavailable Rerun viewer, and iframe connection failure.

## 2. Documentation

- [x] 2.1 Update `docs/usage/visualization.md` with the LCM-only selector workflow, selected-only logging behavior, unsupported topic states, and Rerun iframe behavior.
- [x] 2.2 Update CLI or blueprint usage docs if the implementation exposes selector mode through a public CLI flag, command, or helper.
- [x] 2.3 Update contributor or coding-agent guidance if the implementation adds a new standard selector helper, optional dependency extra, or visualization composition convention.

## 3. Verification

- [x] 3.1 Run `openspec validate add-rerun-topic-selector-app`.
- [x] 3.2 Run focused tests for the LCM catalog collector, typed-channel parsing, renderability classification, and managed-selection filtering.
- [x] 3.3 Run focused tests or a small integration test proving existing automatic Rerun visualization behavior remains unchanged when selector mode is disabled.
- [x] 3.4 Run UI-level verification for the NiceGUI selector app, including topic search/filtering, stage-without-logging behavior, apply/clear behavior, unsupported topic display, applied/logging indicators, and Rerun viewer unavailable state.
- [x] 3.5 Run docs validation for changed docs, such as `uv run doclinks docs/usage/visualization.md` and `uv run md-babel-py run docs/usage/visualization.md` when examples are executable.
- [x] 3.6 Run `pytest dimos/robot/test_all_blueprints_generation.py` if implementation adds or renames runnable blueprints or changes generated blueprint registry inputs.
- [ ] 3.7 Manually QA through a replay or simulation stack that publishes LCM topics: start selector-enabled visualization, confirm live topics appear, select a renderable topic, observe it in the embedded Rerun viewer, clear it, and confirm subsequent data stops logging for that topic.
