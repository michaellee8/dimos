## User-Facing Docs

- Update `docs/usage/` manipulation planning documentation to introduce planning groups as the user-facing planning selection unit.
- Document Planning Group IDs as `{robot_name}/{group_name}` and resolved joint names as `{robot_name}/{local_joint_name}`.
- Document supported SRDF forms:
  - `<group><chain base_link="..." tip_link="..."/></group>`
  - `<group><joint name="..."/>...</group>` when the joints validate as one serial chain.
- Document unsupported SRDF forms and warning behavior for skipped groups.
- Document fallback behavior for robots without SRDF: one generated `{robot_name}/manipulator` group only when configured controllable joints form one unambiguous serial chain.
- Document public planning API usage:
  - pose targets keyed by planning group
  - request-scoped `auxiliary_groups`
  - joint targets keyed by planning group
  - generated plans returned as the canonical artifact
- Document lazy preview/execution flow: generated plan first, then `preview_plan(plan)` and `execute_plan(plan)` project as needed.

## Contributor Docs

- Update `docs/development/` manipulation/planning contributor documentation, if present, to explain:
  - SRDF/fallback extraction responsibilities
  - local versus resolved joint-name layering
  - where group resolution belongs
  - why controllers should remain planning-group agnostic
- If no dedicated manipulation contributor doc exists, add the contributor notes to the user-facing manipulation planning doc or create a short development note for planning backends.

## Coding-Agent Docs

- Update `docs/coding-agents/` or `AGENTS.md` only if implementation introduces new recurring coding-agent guidance.
- Likely guidance:
  - do not add robot-scoped planning APIs for new manipulation work
  - use explicit Planning Group IDs in examples/tests
  - keep local URDF/SRDF names below parsing/backend internals
  - use resolved joint names in public paths/states

## Doc Validation

- Run doc link validation if available:
  - `uv run doclinks`
- For docs containing executable Python snippets, run the relevant markdown execution command if supported:
  - `uv run md-babel-py run <changed-doc>`
- Run relevant tests that exercise documented examples or API snippets after implementation.

## No Docs Needed

Documentation is needed. This change alters public manipulation planning concepts, API examples, naming conventions, SRDF support expectations, and migration guidance for existing callers.
