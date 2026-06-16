## 1. Implementation

- [x] 1.1 Add runtime dependencies for Git-backed asset resolution (`GitPython` and `filelock`) in project dependency configuration.
- [x] 1.2 Implement a generic Git asset cache with clone-on-miss, clean-cache update, update-failure fallback, dirty-cache skip, and per-source file locking.
- [x] 1.3 Add unit tests for Git asset cache behavior, including missing cache failure, successful clean update, update failure with cached fallback, and dirty cache preservation.
- [x] 1.4 Implement typed robot asset declarations with robot-model-first lookup, flat artifact role strings, ROS package roots, optional model-level Xacro args, and source checkout deduplication by `(repo_url, ref)`.
- [x] 1.5 Implement `RobotAssetManager` resolution for artifact paths and package roots, including explicit errors for unknown robot models or undeclared artifact roles.
- [x] 1.6 Implement `RobotAssetPath` as a lazy Path-like catalog adapter that avoids network/filesystem resolution at import time and resolves only when a concrete path is needed.
- [x] 1.7 Add unit tests for robot asset declaration lookup, package root resolution, lazy import behavior, and common path-like operations used by existing consumers.
- [x] 1.8 Identify and verify upstream robot description source URLs, refs, artifact paths, and ROS package roots for xArm, Piper, and A750.
- [x] 1.9 Add xArm, Piper, and A750 robot asset declarations for `urdf`, any required FK/IK URDF role such as `urdf_ik`, `mjcf` where applicable, `srdf` where applicable, and `mesh_dir` where applicable.
- [x] 1.10 Migrate xArm catalog constants and package roots from `LfsPath` to robot asset declarations and `RobotAssetPath`.
- [x] 1.11 Migrate Piper catalog constants and package roots from `LfsPath` to robot asset declarations and `RobotAssetPath`.
- [x] 1.12 Migrate A750 catalog constants and package roots from `LfsPath` to robot asset declarations and `RobotAssetPath`.
- [x] 1.13 Keep OpenArm catalog behavior unchanged and add comments/tests where useful to make the intentional non-migration clear.
- [x] 1.14 Update tests or fixtures that directly reference `get_data("xarm_description")`, Piper LFS paths, or A750 LFS paths so they validate the new asset resolution path instead.
- [x] 1.15 If catalog exports, blueprint names, or generated registry inputs change, regenerate and verify the blueprint registry with `pytest dimos/robot/test_all_blueprints_generation.py`.

## 2. Documentation

- [x] 2.1 Update `docs/capabilities/manipulation/adding_a_custom_arm.md` to describe Robot Asset Manager declarations as the preferred upstream robot description source workflow.
- [x] 2.2 Update xArm, Piper, and A750 manipulation docs to describe resolved artifact roles, ROS package roots, cache behavior, and any changed model path examples.
- [x] 2.3 Add or update a user-facing Robot Asset Manager documentation section covering purpose, cache location, fresh-when-safe behavior, supported artifact roles, and branch/tag/commit ref guidance.
- [x] 2.4 Update contributor docs if new dependency, cache testing, or robot asset declaration workflow details need contributor guidance.
- [x] 2.5 Update `AGENTS.md` or `docs/coding-agents/` if the implementation changes the recommended coding-agent workflow for adding robot model assets.

## 3. Verification

- [x] 3.1 Run `openspec validate migrate-robot-arms-to-git-assets`.
- [x] 3.2 Run focused unit tests for the Git asset cache and robot asset manager.
- [x] 3.3 Run focused catalog/model parsing tests for xArm, Piper, and A750 migrated paths.
- [x] 3.4 Run existing manipulation planning/control tests affected by catalog model path changes, including the current `dimos/manipulation/test_manipulation_module.py` target if still applicable.
- [x] 3.5 Run `uv run pytest dimos/robot/test_all_blueprints_generation.py` if blueprint registry inputs or generated registry output may have changed.
- [x] 3.6 Run `uv run doclinks` after documentation updates.
- [x] 3.7 Run `md-babel-py run <doc>` for any changed documentation file that contains executable Python snippets.
- [x] 3.8 Manually QA at least one migrated xArm path and one non-xArm migrated path through parser/planning or simulation/replay before any real hardware use.
