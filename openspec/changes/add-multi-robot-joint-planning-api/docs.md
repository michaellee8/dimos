# Documentation impact

## User-Facing Docs

- Update `dimos/manipulation/planning/README.md` to explain that a successful plan is a time-parameterized motion plan, not only a geometric path.
- Update `docs/capabilities/manipulation/readme.md` with the multi-robot joint planning flow once implementation confirms the final callable syntax.
- Update `docs/capabilities/manipulation/openarm_integration.md` if OpenArm dual-arm examples should use coordinated planning instead of independent left/right planning.
- Include examples for:
  - scalar single-robot `plan_to_joints` / `plan_to_pose` compatibility,
  - ordered multi-robot joint targets,
  - ordered multi-robot pose targets using current IK-then-joint-plan semantics,
  - explicit preview and execution of a selected robot set.
- Document non-goals explicitly: no SRDF parsing, no named planning groups, no true coupled multi-end-effector Cartesian IK, and no automatic hardware motion after planning.

## Contributor Docs

- No new contributor workflow docs are required.
- If implementation reveals a reusable testing procedure for multi-robot planning, add a short note to existing manipulation testing docs rather than creating a new contributor guide.

## Coding-Agent Docs

- No `AGENTS.md` or `docs/coding-agents/` update is expected.
- If implementation establishes new conventions for manipulation planning APIs, add them to the manipulation planning docs rather than coding-agent-specific docs.

## Doc Validation

- Run `openspec validate add-multi-robot-joint-planning-api`.
- For changed markdown docs, run the repository's relevant markdown/doc validation from `docs/development/openspec.md` and `docs/development/writing_docs.md` if available.
- For runnable Python snippets added to docs, run `md-babel-py run <doc>` when the snippet is intended to execute in docs validation.

## No Docs Needed

- Not applicable. This change alters developer-facing manipulation planning behavior and needs user-facing manipulation docs.
