## ADDED Requirements

### Requirement: Resolve robot model artifacts by role

DimOS SHALL resolve declared robot model artifacts for supported manipulation robot models by robot model name and artifact role.

#### Scenario: Resolve a migrated arm URDF
- **GIVEN** a migrated robot model such as xArm, Piper, or A750 has a declared `urdf` artifact role
- **WHEN** a DimOS catalog or model consumer requests that artifact
- **THEN** DimOS returns a local filesystem path to the declared URDF or Xacro file
- **AND** existing model parsing consumers can use the returned path as a normal path-like model input.

#### Scenario: Resolve additional flat artifact roles
- **GIVEN** a migrated robot model declares artifact roles such as `mjcf`, `srdf`, `mesh_dir`, or an extra string role such as `urdf_ik`
- **WHEN** a consumer requests one of those declared roles
- **THEN** DimOS returns the local filesystem path for that role
- **AND** DimOS reports an explicit error when the requested role is not declared for that robot model.

### Requirement: Resolve ROS package roots for model consumers

DimOS SHALL provide ROS package root mappings for migrated robot models when their model files require package-based resource resolution.

#### Scenario: Resolve package URI resources
- **GIVEN** a migrated robot model declares a ROS package root for a package used by `package://...` URIs
- **WHEN** a parser, planner, or Drake preparation layer receives the model path and package roots
- **THEN** the consumer can resolve package-based mesh and resource references using the declared package root
- **AND** DimOS preserves compatibility with existing `dict[str, Path]` package root consumers.

#### Scenario: Resolve Xacro find expressions
- **GIVEN** a migrated robot model declares a ROS package root for a package used by `$(find package_name)` in Xacro
- **WHEN** existing Xacro processing expands the model file
- **THEN** the package name resolves to the declared local package root
- **AND** Xacro processing remains the responsibility of the existing parser or Drake preparation layer.

### Requirement: Populate and reuse a standard robot asset cache

DimOS SHALL store fetched robot description sources in a standard user cache and reuse cached sources across runs.

#### Scenario: Cache is missing
- **GIVEN** a requested migrated robot model has no cached source checkout
- **WHEN** DimOS resolves one of its artifacts
- **THEN** DimOS fetches the declared robot description source into the standard robot asset cache
- **AND** DimOS fails with a clear error if the source cannot be fetched and no cached checkout exists.

#### Scenario: Cache is present and update succeeds
- **GIVEN** a requested migrated robot model has a clean cached source checkout
- **WHEN** DimOS resolves one of its artifacts and the upstream source has changed for the declared ref
- **THEN** DimOS updates the cached checkout before returning the artifact path
- **AND** the returned path points into the updated cached checkout.

#### Scenario: Cache is present and update fails
- **GIVEN** a requested migrated robot model has a cached source checkout
- **WHEN** DimOS cannot check for or apply an upstream update
- **THEN** DimOS warns about the update failure
- **AND** DimOS continues using the cached checkout.

#### Scenario: Cache has local changes
- **GIVEN** a requested migrated robot model has a cached source checkout with local changes
- **WHEN** DimOS resolves one of its artifacts
- **THEN** DimOS warns that the cache has local changes and skips upstream update
- **AND** DimOS returns paths from the dirty cached checkout without overwriting local edits.

### Requirement: Preserve catalog path compatibility

DimOS SHALL expose migrated robot assets through catalog declarations that remain compatible with existing path-based robot model consumers.

#### Scenario: Catalog import remains lightweight
- **GIVEN** a module imports xArm, Piper, or A750 catalog constants
- **WHEN** the import completes
- **THEN** DimOS does not fetch robot description sources during import
- **AND** any network or cache resolution work is deferred until a concrete filesystem path is needed.

#### Scenario: Existing RobotConfig consumers receive compatible paths
- **GIVEN** a migrated catalog creates a DimOS Robot Model Config with a model path and package roots
- **WHEN** an existing planner, parser, simulation, or visualization consumer reads that config
- **THEN** the model path behaves as a path-like filesystem value
- **AND** package roots remain compatible with existing `dict[str, Path]` expectations.

### Requirement: Support flexible source refs

DimOS SHALL support branch, tag, and commit refs in robot asset declarations for migrated robot models.

#### Scenario: Declaration uses branch or tag ref
- **GIVEN** a migrated robot model declaration uses an upstream branch or tag ref
- **WHEN** DimOS resolves an artifact for that model
- **THEN** DimOS fetches and checks out the declared ref according to the cache freshness policy
- **AND** developers can use upstream-moving refs when ease of use and freshness are preferred.

#### Scenario: Declaration uses commit ref
- **GIVEN** a migrated robot model declaration uses a commit ref
- **WHEN** DimOS resolves an artifact for that model
- **THEN** DimOS checks out that commit in the cache
- **AND** releases, CI, or fragile assets can use pinned refs when stronger reproducibility is required.
