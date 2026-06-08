## User-Facing Docs

None. This change does not alter user-facing DimOS behavior, hardware setup, CLI commands, skills/MCP tools, or platform capability guides.

## Contributor Docs

No broad contributor-process update is required in `docs/development/`. The existing `docs/development/testing.md` already covers test location, pytest usage, fixtures, mocking, options, and markers.

## Coding-Agent Docs

Do not add this guidance to `docs/coding-agents/testing.md`. The durable location is the OpenSpec schema instructions that generate and apply implementation task lists, because the mistake occurs when agents plan and execute test tasks.

Update `openspec/schemas/dimos-capability/schema.yaml` so future `tasks` and `apply` instructions tell agents to write behavior-focused tests: set up the test, execute functionality, and check the desired result. The prompt guidance should warn against tests that only construct objects and assert private fields, full metadata snapshots, default tables, or fake backend internals.

## Doc Validation

- `openspec validate improve-behavior-focused-test-guidelines`
- Manually inspect the OpenSpec instructions output for a future apply/tasks flow if prompt wording changes are significant.

## No Docs Needed

User-facing documentation is not needed because runtime behavior does not change. The guidance belongs in OpenSpec prompt instructions rather than general coding-agent docs.
