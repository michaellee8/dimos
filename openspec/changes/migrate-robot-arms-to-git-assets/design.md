## Context

DimOS manipulation robot catalogs currently declare model assets through `LfsPath` values that unpack archives from `data/.lfs`. The affected surfaces include `dimos/robot/catalog/ufactory.py`, `dimos/robot/catalog/piper.py`, `dimos/robot/catalog/a750.py`, manipulator blueprints, teleop/control blueprint wiring, `RobotConfig`, model parsing, Drake preprocessing, and manipulation docs/tests.

The design decisions captured during exploration are recorded in `docs/adr/0001-git-backed-robot-asset-manager.md` and the glossary in `CONTEXT.md`. The change should migrate xArm, Piper, and A750, while leaving OpenArm on its current path because its description has local DimOS modifications.

## Goals / Non-Goals

**Goals:**

- Resolve xArm, Piper, and A750 model artifacts from upstream robot description sources instead of copied LFS bundles.
- Preserve existing catalog ergonomics: consumers should still receive `Path`-compatible model paths and `dict[str, Path]` package roots.
- Avoid network activity at import time by using a lazy Path-like adapter for catalog constants.
- Support branch, tag, and commit refs, with commit pinning available but not mandatory.
- Use a standard user cache such as `~/.cache/dimos/robot_assets`.
- Update clean cached checkouts when upstream changes are available; warn and use cache when update fails; warn and skip updates for dirty cached checkouts.
- Keep Xacro processing and Drake URDF preparation in the existing parser/preparation layers.

**Non-Goals:**

- Do not migrate Unitree robot descriptions in this change.
- Do not migrate OpenArm in this change.
- Do not add local override machinery in v1; local tests can pass explicit `Path` values where needed.
- Do not introduce a YAML/TOML manifest requirement; typed Python declarations are the initial declaration format.
- Do not change CLI, skill/MCP, stream, or hardware command behavior.

## DimOS Architecture

Add a small asset layer under the DimOS runtime codebase, with two responsibilities:

1. A generic Git cache component that resolves `(repo_url, ref)` into a local checkout path.
2. A robot-facing manager that resolves `(robot_model_name, artifact_role)` and ROS package roots from typed Python robot asset declarations.

The core concepts are:

- `GitAssetCache`: wraps Git operations and file locking. It clones missing repositories, checks whether cached repositories are dirty, fetches/checks out refs for clean repositories, and emits warnings/fallback reasons for update failures or dirty cache skips.
- `RobotAssetManager`: owns typed robot asset declarations and resolves artifact roles such as `urdf`, `mjcf`, `srdf`, `mesh_dir`, and extra string roles such as `urdf_ik`.
- `RobotAssetPath`: a lazy Path-like adapter used by catalog modules. It should not touch the network or filesystem at import time; it resolves only when a path operation requires a concrete filesystem path.
- Robot asset declarations: typed Python objects keyed by robot model name, containing a robot description source URL/ref, flat `artifacts: dict[str, str]`, `package_roots: dict[str, str]`, optional model-level `xacro_args`, and lightweight provenance fields such as source name/license when known.

No new DimOS `Spec` Protocol is required unless implementation discovers an RPC/module boundary. This is a local library/API layer used by catalogs and planning/control consumers, not a stream transport or module interface. Existing blueprint composition should continue to consume catalog constants. No skills/MCP exposure or CLI entry point is required for v1.

Package root handling must preserve existing parser behavior: declared ROS package roots are passed as `dict[str, Path]` to consumers that resolve `package://...` URIs and `$(find package_name)` expressions. Xacro files remain ordinary artifact paths; `dimos/robot/model_parser.py` and Drake preparation utilities remain responsible for Xacro expansion and mesh/package handling.

Dependencies: add `GitPython` for Git operations and `filelock` for cross-process cache locking. Keep direct shelling out to Git behind the library only if GitPython cannot cover a required operation.

## Decisions

- Use a Git-backed Robot Asset Manager instead of Git LFS bundles for xArm, Piper, and A750. This removes copied upstream robot description bundles from the common DimOS maintenance path.
- Use a thin DimOS wrapper over GitPython and filelock rather than `robot_descriptions.py`. `robot_descriptions.py` is useful as a curated registry, but this change needs arbitrary upstream robot description sources and DimOS-specific freshness policy.
- Use robot-model-first declarations. Catalogs should ask for assets by robot model name and artifact role; the manager deduplicates source checkouts internally by `(repo_url, ref)`.
- Use flat string artifact roles. Common role constants may exist for `urdf`, `mjcf`, `srdf`, and `mesh_dir`, but strings are canonical internally and extra roles remain possible.
- Allow branch, tag, and commit refs. Branch/tag defaults optimize ease of use and freshness; commit refs remain available for CI, releases, or fragile assets.
- Use “fresh-when-safe” cache behavior: clone missing cache, update clean cached repositories, warn/use cache on update failure, and warn/skip update for dirty cached repositories.
- Keep Xacro processing outside asset resolution. Asset resolution returns paths and package roots; existing model parsing and Drake preparation layers expand Xacro and normalize URDF/mesh details.

## Safety / Simulation / Replay

This change must not alter robot commands, control loops, skills, or stream contracts. Safety risk is indirect: an incorrect model asset can affect planning, FK/IK, visualization, or simulation. Implementation should verify resolved model paths for xArm, Piper, and A750 through existing parsing/planning entry points before using them in robot-facing blueprints.

Simulation and replay behavior should match current behavior after cache population. First-run network failures should fail clearly when no cached checkout exists. If a cached checkout exists and an upstream update check fails, DimOS should warn and continue with the cached copy.

Manual QA should cover at least one xArm blueprint path and one non-xArm migrated arm path where practical, using simulation/replay or parser-level checks before any real hardware run.

## Risks / Trade-offs

- Upstream repository layouts may differ from current LFS bundle layouts. Mitigation: declare artifact paths and package roots explicitly per robot model and test them.
- Branch/tag refs reduce strict reproducibility compared with commit-only pinning. Mitigation: allow commit refs and document when to pin.
- Freshness checks add network dependency to first resolution. Mitigation: continue with existing cache when update fails, and fail fast only when no cache exists.
- Dirty cache preservation may leave developers on locally modified assets. Mitigation: warn clearly and never overwrite local cache edits automatically.
- Lazy Path behavior can expose edge cases if consumers expect concrete `pathlib.Path` internals. Mitigation: keep the adapter small, test common path operations, and cast to concrete paths at integration boundaries if needed.

## Migration / Rollout

1. Add Git cache and robot asset manager code with tests.
2. Add typed asset declarations for xArm, Piper, and A750.
3. Migrate catalog constants and `RobotConfig.package_paths` declarations for xArm first, then Piper and A750.
4. Update tests and docs that mention `LfsPath` as the canonical manipulator asset pattern.
5. Keep existing LFS archives until migrated paths are verified and rollback is no longer needed.
6. If any catalog exports or blueprint registry behavior changes, run `pytest dimos/robot/test_all_blueprints_generation.py`; otherwise no generated blueprint registry update is expected.

Rollback is to restore affected catalog constants to `LfsPath` and keep the LFS archives in place.

## Open Questions

- Exact upstream robot description source URLs and refs for Piper and A750 need confirmation during implementation.
- Whether GitPython should be a core dependency or an optional extra depends on whether migrated manipulator catalogs are imported in minimal DimOS installs.
