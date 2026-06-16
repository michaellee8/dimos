# Use a Git-backed Robot Asset Manager for robot model files

DimOS will replace selected Git LFS robot description bundles with a Git-backed Robot Asset Manager that resolves robot model files from upstream robot description sources into a standard user cache. The design prioritizes ease of use and avoiding copied asset bundles in the DimOS repo: model assets are declared robot-first with typed Python objects, use branch/tag/commit refs, deduplicate checkouts by source, update clean cached repos when upstream changes are available, warn and continue with cache on update failure, and skip updates when local cache changes are present.

We will build this as a thin DimOS layer over existing Git tooling rather than writing Git operations from scratch or depending on `robot_descriptions.py` as the primary abstraction. The robot asset layer exposes flat artifact keys such as `urdf`, `mjcf`, `srdf`, `mesh_dir`, and additional string keys when needed; Xacro files remain ordinary resolved artifacts and are processed by the existing model parsing and Drake preparation layers using declared ROS package roots and xacro arguments.

This accepts less strict reproducibility by default than commit-only pinning, but keeps commit refs available for cases that need them while making the common path simple and fresh against upstream robot description sources.
