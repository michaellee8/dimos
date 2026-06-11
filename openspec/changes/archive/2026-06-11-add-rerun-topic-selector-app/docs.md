## User-Facing Docs

- Update `docs/usage/visualization.md` with the selector-enabled visualization workflow:
  - Explain that v1 discovers live LCM topics only.
  - Show how users enable the selector path once the implementation exposes the opt-in helper, config, or CLI flag.
  - Describe the NiceGUI page layout: header status chips, LCM topic catalog rail, current-session staging controls, selection tray, bridge footer, and embedded Rerun iframe.
  - Document selected-only logging: topics are not converted or logged to Rerun until staged choices are explicitly applied in managed-selection mode.
  - Document unsupported topic states for untyped, undecodable, or non-renderable LCM topics.
  - Call out that SHM, ROS, DDS, coordinator metadata, and stored replay stream catalogs are future work unless those streams are bridged to LCM.
- If a new public CLI flag or command is added, update the relevant CLI docs under `docs/usage/cli.md` or the existing visualization CLI section.
- If selector-enabled visualization is exposed through blueprint composition, update the visualization examples to prefer the existing `vis_module` convention and show only the new opt-in selector path where needed.

## Contributor Docs

- Update `docs/development/conventions.md` only if implementation adds a new recommended visualization composition helper or changes the guidance around `vis_module`.
- Add contributor guidance in `docs/usage/visualization.md` or a linked development note for making LCM topics renderable:
  - Prefer message types with `to_rerun()` when possible.
  - Use configured visual converters for messages that cannot own rendering logic.
  - Keep high-bandwidth topic logging selected-only in managed-selection mode.
  - Avoid using the existing viewer websocket click/teleop path as the selector catalog API.
- No generated blueprint registry documentation is expected unless implementation adds a new runnable blueprint.

## Coding-Agent Docs

- No immediate `AGENTS.md` change is required for the OpenSpec phase.
- If implementation establishes a new standard selector helper, add a short note to repo coding-agent guidance so future agents use the helper instead of wiring `RerunBridgeModule` directly.
- If implementation adds optional dependencies for NiceGUI/web visualization, document the expected extra and verification command in coding-agent docs or the relevant development docs.

## Doc Validation

- Run markdown/link validation for any changed docs, for example:
  - `uv run doclinks docs/usage/visualization.md` if `doclinks` is available in the project environment.
  - `uv run doclinks docs/usage/cli.md` if CLI docs are changed.
- Run executable documentation checks only for docs that include runnable Python snippets:
  - `uv run md-babel-py run docs/usage/visualization.md` if the updated examples are intended to execute.
- If diagrams are added or changed, run the project diagram generation/validation command, such as `bin/gen-diagrams`, according to the existing docs workflow.

## No Docs Needed

Documentation changes are needed. This change introduces a new user-facing visualization workflow and a deliberately limited v1 scope, so users and contributors need clear docs for enabling it, understanding LCM-only discovery, and making topics renderable.
