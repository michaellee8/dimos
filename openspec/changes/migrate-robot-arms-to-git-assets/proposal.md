## Why

DimOS currently keeps several manipulation robot description bundles in Git LFS archives under `data/.lfs`. That makes routine development depend on copied binary/source asset bundles inside this repository, increases repository-specific asset maintenance, and makes it harder to track upstream robot description changes for supported arms.

This change migrates the xArm, Piper, and A750 manipulation robot model assets to a Git-backed Robot Asset Manager. DimOS should resolve robot description sources from upstream repositories into a standard user cache while preserving the existing model-path and package-path behavior used by planning, control, parsing, simulation, and documentation.

## What Changes

- Add a Git-backed robot asset resolution capability for selected manipulation robot model files and package roots.
- Add typed Python robot asset declarations for xArm, Piper, and A750, with robot-model-first lookup and internal source checkout deduplication.
- Add a lazy Path-like adapter so existing `RobotConfig.model_path` and `package_paths` consumers can keep receiving filesystem paths without network access at import time.
- Migrate xArm, Piper, and A750 catalog model paths and package roots away from LFS-backed `LfsPath` declarations where suitable upstream robot description sources are available.
- Keep OpenArm on its current path for now because it has local DimOS modifications.
- Preserve Xacro, package URI, `$(find ...)`, MJCF/SRDF, and mesh directory compatibility through existing parser and Drake preparation layers.
- No **BREAKING** CLI, skill/MCP, or hardware-safety behavior changes are intended.

## Affected DimOS Surfaces

- Modules/streams: manipulation planning and control modules that consume `RobotConfig.model_path`, FK/IK model paths, package paths, Xacro inputs, MJCF files, SRDF files, and mesh directories.
- Blueprints/CLI: xArm, Piper, and A750 manipulator blueprints and teleop/control blueprint wiring that reference catalog constants; no CLI command behavior changes are intended.
- Skills/MCP: no direct skill or MCP tool behavior changes are intended.
- Hardware/simulation/replay: xArm, Piper, and A750 real/sim manipulation stacks may resolve model assets from the user cache instead of LFS bundles; OpenArm remains unchanged.
- Docs/generated registries: manipulation docs and tests that describe LFS-backed onboarding or hardcoded model bundle paths need updates; no generated blueprint registry changes are expected unless catalog exports change.

## Capabilities

### New Capabilities

- `robot-asset-resolution`: Resolving robot model artifacts and ROS package roots from upstream robot description sources into local filesystem paths for DimOS consumers.

### Modified Capabilities

- None.

## Impact

Developers get easier robot asset maintenance and less need to copy upstream description bundles into DimOS. First use of a migrated arm may require network access to populate `~/.cache/dimos/robot_assets`; later uses can continue from the cached copy if upstream update checks fail. Clean cached repositories update when upstream changes are available, while dirty cached repositories are preserved with warnings.

Compatibility risk is concentrated around upstream repository layout differences, package path resolution, Xacro expansion, and FK/IK model constants. The change needs unit tests for cache/update policy and asset path resolution, plus integration coverage for xArm, Piper, and A750 catalog paths through existing model parsing/planning entry points. Documentation should explain the new asset declarations, cache behavior, supported artifact roles, and the temporary split where OpenArm remains LFS-backed.
