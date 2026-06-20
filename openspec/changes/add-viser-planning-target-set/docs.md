## User-Facing Docs

- Update manipulation/Viser usage documentation to describe the Planning Target Set workflow:
  - selecting one or more planning groups;
  - using group-keyed target gizmos;
  - understanding auxiliary groups as selected groups without direct gizmos;
  - planning, previewing, and executing the whole target set;
  - using the workflow with single xArm and dual xArm mock blueprints.
- If no dedicated Viser usage page exists, add the workflow to the closest manipulation usage or capability document.
- Include an example command for launching xArm planner/coordinator with Viser enabled and execution opt-in clearly marked.

## Contributor Docs

- Update manipulation planning contributor notes if they describe robot-scoped Viser behavior or single-target IK assumptions.
- Mention that Viser placement is URDF-authored for this workflow and that `base_pose` is not automatically applied by Viser.

## Coding-Agent Docs

- No required `AGENTS.md` update is expected.
- If `docs/coding-agents/` contains manipulation-specific guidance, add a short note that target-set UI state is whole-set scoped and should not reintroduce per-robot Plan/Preview/Execute state.

## Doc Validation

- Run link validation for changed docs if available:
  - `doclinks`
- If docs contain executable Python snippets, run:
  - `md-babel-py run <changed-doc>`
- Run normal formatting/lint checks for any touched docs if configured in the repository.

## No Docs Needed

Documentation changes are needed because this change introduces a new user-facing Viser manipulation workflow and changes the mental model from robot selection to planning target sets.
