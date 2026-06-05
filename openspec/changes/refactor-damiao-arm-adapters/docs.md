## User-Facing Docs

- Update `docs/capabilities/manipulation/openarm_integration.md` to explain that `openarm` remains the explicit OpenArm adapter while shared Damiao behavior lives underneath it.
- Clarify the distinction between the existing `openarm` adapter path and the opt-in `dm_motor_arm` binding-backed path if both remain user-selectable.
- Update any OpenArm bring-up section only if constructor kwargs, blueprint names, or recommended validation order changes.

## Contributor Docs

- No broad contributor documentation is required unless the implementation introduces a reusable pattern that future adapter authors should follow.
- If the shared Damiao base becomes a recommended extension point, add a short note to manipulation contributor docs or the manipulator driver README describing how to add a Damiao-based arm subclass.

## Coding-Agent Docs

- No AGENTS.md change is required for the refactor itself.
- If implementation creates a reusable adapter pattern that coding agents should prefer, update `docs/coding-agents/` only after the pattern stabilizes in code and tests.

## Doc Validation

- Run documentation link validation for changed docs if available in the repo workflow.
- Run `md-babel-py run docs/capabilities/manipulation/openarm_integration.md` only if executable code blocks in that document are added or changed.
- If blueprint names are changed in docs, also run `pytest dimos/robot/test_all_blueprints_generation.py` after registry regeneration.

## No Docs Needed

Documentation updates are needed if the user-visible adapter distinction or extension story changes. If implementation is purely internal and preserves all documented names/commands, docs can be limited to a short architecture note in the OpenArm integration guide.
