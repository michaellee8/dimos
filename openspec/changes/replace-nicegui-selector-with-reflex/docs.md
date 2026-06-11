## User-Facing Docs

Update `docs/usage/visualization.md`:

- Replace NiceGUI-specific selector wording with Reflex selector wording.
- Keep the LCM-only v1 scope, selected-only logging behavior, stage/apply flow, unsupported topic states, and embedded Rerun viewer behavior.
- Document how to run the hardware-free demo blueprint after the migration.
- Document the expected selector URL, Reflex frontend/backend ports if exposed, and the embedded Rerun viewer URL shape with encoded `url=rerun%2Bhttp...%2Fproxy`.
- Clarify that the demo should not open a native Rerun window and that the embedded viewer is the primary workflow.

## Contributor Docs

Update `docs/development/conventions.md` or the most relevant visualization contributor document:

- Replace NiceGUI dependency/runtime guidance with Reflex dependency/runtime guidance.
- Explain whether Reflex runs as a subprocess or embedded service and which files own startup/shutdown.
- Document optional dependency expectations, frontend build/cache directories, and any generated files that must not be committed.
- Preserve guidance that `vis_module(...)` remains the default automatic visualization path and selector-enabled visualization is opt-in.

## Coding-Agent Docs

Update coding-agent guidance only if the implementation changes standard development workflow, such as:

- new commands needed to run or validate the Reflex selector locally;
- new optional dependency setup beyond `uv sync --extra visualization`;
- generated Reflex directories that agents should avoid editing directly.

If those details fit cleanly in `docs/development/conventions.md`, no separate coding-agent doc update is required.

## Doc Validation

Run documentation checks for changed docs:

```bash
uv run doclinks docs/usage/visualization.md
uv run md-babel-py run docs/usage/visualization.md
```

If contributor docs are changed, also run:

```bash
uv run doclinks docs/development/conventions.md
```

## No Docs Needed

Not applicable. This change replaces a user-facing web runtime and changes setup/dependency expectations, so user and contributor documentation updates are required.
