# DimOS Robotics

DimOS composes robot software from reusable modules and robot-specific descriptions. This context defines the language used when discussing robot model assets and how DimOS consumes them.

## Language

**Robot Description Source**:
An upstream repository that contains a robot's URDF, Xacro, MJCF, meshes, and related package files.
_Avoid_: URDF repo, asset repo, model repo

**Robot Asset Manager**:
A DimOS-facing service that resolves robot description sources into local filesystem paths for use by robot model consumers.
_Avoid_: LFS replacement, description downloader, asset loader

**Robot Asset Cache**:
The standard user cache directory where DimOS stores fetched robot description source checkouts for reuse across runs.
_Avoid_: Data directory, vendored assets, repository assets

**Robot Asset Manifest**:
A DimOS-maintained declaration of robot model assets, their robot description sources, default revisions, package roots, and provenance metadata. It may be represented as typed Python objects; it does not imply a YAML/TOML file.
_Avoid_: Registry, asset list, dependency file, YAML manifest

**ROS Package Root**:
The local directory corresponding to a ROS-style package name, used to resolve `package://...` URIs and `$(find package_name)` expressions in robot model files.
_Avoid_: Package path, asset package, Python package

**Artifact Role**:
A string key naming a supported robot model asset file or directory kind. Common roles include `urdf`, `mjcf`, `srdf`, and `mesh_dir`; extra role keys such as `urdf_ik` may be used when a robot needs additional files. Strings are the canonical internal representation.
_Avoid_: Parser mode, arbitrary attachment, file purpose

**DimOS Robot Model Config**:
A DimOS configuration object that names the model paths, package paths, joints, links, and robot-specific metadata needed by planning, control, simulation, or visualization.
_Avoid_: Robot description, URDF config

**Registered Description Module**:
An importable description entry provided by a third-party robot description registry.
_Avoid_: Robot description source, GitHub repo
