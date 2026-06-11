## Why

DimOS visualization currently relies on Rerun bridge configuration that is mostly fixed at blueprint startup. Developers can customize conversion, throttling, and layouts through `rerun_config`, but users do not have a runtime app for discovering live LCM topics and choosing which ones should be sent to Rerun.

The v1 opportunity is intentionally narrow: DimOS already has LCM subscribe-all behavior and typed channel conventions that can support a useful topic selector quickly. A focused LCM-first selector reduces architecture risk while still solving the immediate problem of avoiding blueprint edits and avoiding automatic logging of every visualizable high-bandwidth topic.

## What Changes

- Add a runtime LCM topic catalog experience based on live LCM topic observation and known typed LCM channel conventions.
- Add a topic selection UI that lets users choose which discovered LCM topics are displayed through Rerun.
- Extend Rerun visualization behavior so selected streams can be enabled, disabled, grouped, searched, and reflected in the viewer layout without restarting the robot stack when possible.
- Preserve existing automatic Rerun rendering for current blueprints while adding a more explicit selection path for high-bandwidth or optional streams.
- Defer SHM, ROS, DDS, coordinator-metadata-first discovery, and cross-transport catalog support to a later version.
- No **BREAKING** public API, CLI, or hardware-safety behavior is intended in this change.

## Affected DimOS Surfaces

- Modules/streams: Rerun visualization modules, LCM topic observation, renderability detection for decoded messages with `to_rerun()` or configured visual converters.
- Blueprints/CLI: `vis_module`-based visualization composition, Rerun bridge configuration, possible new or extended CLI surface for listing/selecting visualizable streams.
- Skills/MCP: No direct skill behavior changes expected; MCP-visible robot skills should remain unaffected.
- Hardware/simulation/replay: Applies to real robot, simulation, and replay stacks using visualization; must avoid subscribing/logging unnecessary high-bandwidth streams by default.
- Docs/generated registries: User-facing visualization docs and developer guidance for adding visualizable streams; no generated blueprint registry changes expected unless new runnable blueprints are introduced.

## Capabilities

### New Capabilities

- `lcm-topic-catalog`: Runtime discovery and presentation of live LCM topics, including topic name, decoded message type when available, renderability, and live status.
- `rerun-topic-selection`: User-controlled selection of visualizable streams and synchronization of selected streams with Rerun logging and viewer layout.

### Modified Capabilities

- None.

## Impact

Users gain a clearer visualization workflow for LCM-backed robot stacks: they can discover live topics, find the topics they care about, and render selected data in Rerun without editing blueprint-level configuration for every run. Developers gain a smaller first implementation that preserves existing `vis_module` and Rerun bridge behavior.

Compatibility risk is moderate around visualization startup and bridge filtering because existing stacks rely on automatic rendering. The change should keep current defaults working and introduce selection as an additive LCM-focused capability. Test and QA scope should cover live typed LCM topics, untyped or undecodable LCM topics, non-renderable topics, high-bandwidth topics, and existing LCM-backed blueprints.
