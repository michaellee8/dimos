## User-Facing Docs

- Update `docs/capabilities/manipulation/adding_a_custom_arm.md` so new custom arm guidance uses Robot Asset Manager declarations instead of presenting `LfsPath` bundles as the canonical path.
- Update manipulation capability docs that list model paths for xArm, Piper, and A750 so they describe robot asset declarations, artifact roles, ROS package roots, and cache behavior.
- Add or update a user-facing section under `docs/usage/` or `docs/capabilities/manipulation/` explaining:
  - the Robot Asset Manager purpose,
  - supported artifact roles (`urdf`, `mjcf`, `srdf`, `mesh_dir`, plus extra string roles),
  - cache location and fresh-when-safe behavior,
  - when commit refs should be used,
  - why OpenArm remains on its current path for now.

## Contributor Docs

- Update contributor/development docs if implementation adds a new dependency or test workflow for robot assets.
- Document how to add a new typed robot asset declaration and how to choose package roots and artifact roles.
- Document test expectations for cache policy, dirty caches, update failures, and parser/planning compatibility.

## Coding-Agent Docs

- Update `AGENTS.md` or `docs/coding-agents/` only if the canonical workflow for adding robot model assets changes enough that coding agents need explicit instructions.
- Suggested coding-agent note: prefer Robot Asset Manager declarations for upstream robot description sources; use `LfsPath` only for assets that are intentionally vendored, locally modified, or not yet migrated.

## Doc Validation

- Run `uv run doclinks` after editing docs, if available in the environment.
- Run `md-babel-py run <doc>` only for docs containing executable Python snippets.
- Run targeted tests referenced by docs if examples are made executable.

## No Docs Needed

Documentation changes are needed because this change replaces the documented LFS-based manipulator onboarding pattern and introduces user-visible cache/update behavior.
