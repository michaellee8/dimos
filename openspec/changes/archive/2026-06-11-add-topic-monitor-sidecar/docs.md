## User-Facing Docs

Update `docs/usage/visualization.md`:

- Make `dimos topic monitor` the recommended topic selector workflow.
- Explain foreground lifecycle, auto-open behavior, Ctrl-C shutdown, active-run metadata mode, and no-run LCM bus-only mode.
- Document that the monitor owns an independent Rerun viewer and does not control or disable visualization already embedded in a running blueprint.
- Document local service URLs using actual printed auto ports rather than fixed defaults.
- Explain v1 scope: LCM-only, generic typed messages with native `to_rerun()`, visible unsupported/unknown topics, no blueprint-specific visual overrides.
- Keep a short section for the dedicated demo blueprint.

Update CLI docs if they list `dimos topic` subcommands, adding `topic monitor` with examples:

```bash
dimos topic monitor
dimos topic monitor --no-open
dimos topic monitor --run latest
```

## Contributor Docs

Update `docs/development/conventions.md` or nearby visualization contributor guidance:

- Describe the sidecar ownership model and why selector logic should not be wired into ordinary blueprints.
- Document Reflex generated/cache artifacts and that they should not be source-edited.
- Document the required registry regeneration if selector-only blueprints are removed or renamed.

## Coding-Agent Docs

Update coding-agent guidance only if implementation introduces new generated artifacts, new command sequencing, or new cleanup requirements beyond existing Reflex selector guidance. If no new guidance is needed, note that `docs/development/conventions.md` covers the generated-file rules.

## Doc Validation

Run docs validation for every changed documentation file, including at minimum:

```bash
uv run doclinks docs/usage/visualization.md
uv run md-babel-py run docs/usage/visualization.md
```

If contributor docs change:

```bash
uv run doclinks docs/development/conventions.md
```

If CLI docs change:

```bash
uv run doclinks docs/usage/cli.md
uv run md-babel-py run docs/usage/cli.md
```

## No Docs Needed

Not applicable. This change introduces a public CLI workflow and changes the recommended visualization usage model, so user-facing and contributor documentation are required.
