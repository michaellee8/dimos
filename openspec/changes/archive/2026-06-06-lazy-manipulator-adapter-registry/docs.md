## User-Facing Docs

- Update `dimos/hardware/manipulators/README.md` to describe manifest-based adapter discovery instead of `adapter.py` auto-discovery.
- Update `docs/capabilities/manipulation/adding_a_custom_arm.md` so custom adapter instructions include:
  - creating `<adapter>/__registry__.py`,
  - mapping adapter keys to `"module:ClassOrFactory"` import paths,
  - keeping optional hardware SDK failures scoped to selected adapter creation/connect,
  - verifying `adapter_registry.available()` and `adapter_registry.create()`.
- Keep `docs/capabilities/manipulation/openarm_integration.md` wording that `openarm_rs` remains opt-in and missing `can_motor_control` fails only when selected. Update only if implementation changes the exact failure timing or wording.

## Contributor Docs

- No broad `docs/development/` update is required unless implementation introduces a new registry-generation or validation command.
- If registry tests add a dedicated contributor workflow for adapter manifests, document it near the manipulator docs rather than in general development docs.

## Coding-Agent Docs

- No `AGENTS.md` update is required for this change.
- Consider updating `docs/coding-agents/` only if there is an existing manipulator adapter authoring guide for coding agents; otherwise the user-facing custom-arm guide is sufficient.

## Doc Validation

- Run markdown/doc validation used by this repo for changed docs, such as `doclinks` if available.
- For changed Python snippets in `docs/capabilities/manipulation/adding_a_custom_arm.md`, run the repository's markdown Python snippet validator if configured, or manually inspect fenced snippets for import path accuracy.

## No Docs Needed

Documentation changes are needed because existing custom-arm docs currently teach `adapter.py` auto-discovery, which would become stale after manifest-based discovery.
