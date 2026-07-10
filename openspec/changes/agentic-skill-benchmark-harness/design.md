## Context

The short-term evaluation target is an agent's ability to interpret a fixed, imperfect indoor map and answer grounded questions. Map production is intentionally outside the evaluated boundary: maps are generated once, versioned as benchmark data, and supplied identically to every later evaluation system.

DimOS currently accumulates world-frame lidar observations through `VoxelGridMapper` and publishes the final healthy voxel centers as `PointCloud2`. It does not publish a serializable voxel-grid object. The corpus therefore stores the mapper's native `PointCloud2` output instead of inventing a parallel map representation.

Structured3D supplies authoritative geometry, room regions, and openings suitable for deterministic labels. It does not supply the imperfect lidar maps required by this benchmark, so an offline generation pipeline must simulate finite noisy observations and mild correlated pose drift before running the real DimOS mapper.

The pilot is intentionally small: 30 scenes, one fixed full-coverage trajectory per scene, one clean and two seeded noisy map variants, approximately 14 physical questions per scene, and approximately 1,260 map-question instances.

## Goals / Non-Goals

**Goals:**

- Produce a reproducible, versioned corpus of static imperfect maps and geometry-derived spatial questions.
- Preserve paired clean/noisy comparisons without changing the physical question or oracle answer.
- Keep agent-visible corpus data physically separate from authoritative geometry, topology, and answers.
- Cover local embodiment-aware clearance, room inventory, and direct room topology without requiring action rollout.
- Make generator failures inspectable through a minimal read-only Viser view.
- Keep generated output deterministic while recording manual exclusions or corrections separately.

**Non-Goals:**

- Evaluating SLAM, map quality, trajectory estimation, or the mapping stack.
- Defining the later agent-facing rendering, prompt, tools, result records, or scoring harness.
- Supplying lidar replay, RGB, RGB-D, or authoritative geometry to an agent.
- Route planning, interactive exploration, task completion, or simulator rollout.
- Object-relation, semantic room-name, stair, slope, climbability, or other 3D questions.
- A general-purpose dataset platform, hosted review service, or content-addressed distribution system.

## Decisions

### 1. Treat the generated map as canonical benchmark data

The offline pipeline is:

```text
Structured3D geometry
  -> fixed full-coverage trajectory
  -> clean or seeded noisy lidar observations and poses
  -> DimOS VoxelGridMapper
  -> immutable PointCloud2 benchmark map
```

Mapping runs during corpus generation, not during evaluation. Every later system receives the same stored map variant. This isolates map interpretation while retaining realistic omissions and distortions.

Alternative considered: store raw lidar replay and rerun mapping for every system. Rejected because it would evaluate map production, contrary to the benchmark objective.

### 2. Store the native `VoxelGridMapper` output

Each map variant stores one final `global_map.pc2.lcm`, the native `PointCloud2` emitted by `VoxelGridMapper`. A small `snapshot.json` records identity, terminal pose, artifact hash, mapper configuration, noise profile, and seed.

Alternative considered: define a new serialized sparse voxel grid, TSDF, or occupancy raster. Rejected for the base corpus because the current mapper does not emit those as its canonical output. Agent-specific 2D projections or renders can be designed later without changing the source corpus.

### 3. Use snapshot-centric hierarchical bundles

The pilot uses filesystem bundles rather than normalized tables or content-addressed shards:

```text
spatial-benchmark-v1/
├── manifest.json
├── schemas/
├── public/scenes/<scene_id>/
│   ├── scene.json
│   └── trajectories/<trajectory_id>/
│       ├── trajectory.json
│       ├── questions.jsonl
│       └── variants/<clean|noisy-01|noisy-02>/
│           ├── snapshot.json
│           ├── global_map.pc2.lcm
│           └── instances.jsonl
└── oracle/scenes/<scene_id>/
    ├── source.json
    ├── geometry.json
    ├── topology.json
    └── trajectories/<trajectory_id>/
        ├── answers.jsonl
        └── review_overrides.jsonl
```

Files use relative paths and stable opaque IDs. Schemas are versioned. Binary artifacts carry checksums. The public and oracle roots can be distributed or mounted independently.

Alternative considered: normalized Parquet catalogs. Rejected for the pilot because roughly 90 maps and 1,260 instances remain easy to inspect and validate as bundles. A later release may add an index without changing logical records.

### 4. Separate physical questions, map-specific instances, and answers

`questions.jsonl` stores each physical question once, including its predicate, wording, parameter contract, and answer type. `instances.jsonl` binds that question to one map variant and contains any map-frame pose or neutral marker coordinates required for that variant. `answers.jsonl` stores exactly one authoritative answer per question, shared across all variants.

```text
question_id -> one oracle answer
            -> clean instance
            -> noisy-01 instance
            -> noisy-02 instance
```

This prevents answer drift while permitting variant-specific coordinates when correlated pose drift changes map alignment.

### 5. Generate seven deterministic predicates

The pilot contains:

1. Whether the fixed square robot footprint plus safety margin can occupy a marked pose.
2. Whether that footprint can complete a fixed-distance straight translation at fixed yaw.
3. Whether that footprint can complete an in-place rotation through a specified yaw delta.
4. The number of eligible Benchmark rooms on the floor.
5. Whether two neutral markers lie in the same Benchmark room.
6. Whether the distinct rooms containing two markers share one direct traversable opening.
7. The number of rooms directly connected to the room containing one marker.

Collision labels use continuous swept 2D geometry, not endpoint or point-robot checks. Candidate examples within a configured geometric uncertainty margin are rejected.

Alternative considered: cardinal heading and route-choice questions. Cardinal directions lack a meaningful indoor frame, while route choice can collapse to a planner call; both are excluded.

### 6. Derive a private navigable-room graph

A Benchmark room is a Structured3D-annotated navigable region whose boundary is physically represented by walls and explicit openings. Open-plan semantic subdivisions, closets, stairs, and inaccessible regions are excluded. Direct connections are traversable openings joining exactly two eligible rooms.

The generator constructs a versioned private room graph, validates symmetric adjacency and node degrees, and rejects malformed or ambiguous scenes. Neutral public markers identify query locations without exposing room IDs, boundaries, semantics, or graph edges.

### 7. Use one clean control and two realistic noisy variants

Noise is introduced before mapping and is deterministic from a versioned profile and seed. The realistic profile includes finite sensing range and angular resolution, physical occlusion, range error, beam dropout, finite trajectory coverage, and mild temporally correlated pose drift. The clean variant validates the harness; noisy variants define the intended benchmark condition.

Noise is never applied by corrupting the finished map. All three variants use the same source scene, trajectory intent, physical questions, and answers.

### 8. Validate automatically and inspect manually when needed

Automated generation checks cover:

- Coordinate handedness, units, gravity axis, yaw convention, and transform round trips.
- Deterministic mapper output and artifact integrity.
- Continuous collision labels under tolerance perturbations.
- Room membership, symmetric direct adjacency, and neighbor-count consistency.
- One answer per question and complete clean/noisy instance pairing.
- Scene-disjoint development and held-out splits.
- Public-package scans for answers, room IDs, authoritative geometry, or private paths.
- Balanced labels and nuisance correlations such as template, marker order, map extent, and point count.

A minimal read-only Viser tool loads an instance, displays the `PointCloud2`, robot pose and footprint, markers or motion overlays, and exact question, and can toggle private oracle geometry/topology for diagnosis. It does not edit records or manage review state.

Human-discovered isolated problems are recorded in `review_overrides.jsonl` as exclusions or corrections. Repeated failure patterns require changing the generator policy and regenerating the release rather than accumulating overrides.

### 9. Version releases immutably

The dataset manifest records schema version, release ID, generator revision, mapper configuration digest, source dataset revision, scene-level split, and artifact hashes. Published releases are immutable. Changes to coordinate conventions, predicate semantics, room policy, noise semantics, or identity rules require a new major dataset version; corrected artifacts or labels create a new release rather than replacing existing files.

## Risks / Trade-offs

- **A physical oracle answer may not be inferable from a sparse point cloud** -> reject known boundary and coverage failures automatically; use Viser to diagnose human-discovered ambiguous cases and exclude them through review overrides.
- **Frame or unit mismatches can silently corrupt all labels** -> validate transforms on asymmetric calibration scenes and persist complete frame provenance privately.
- **Room topology may not match physical navigability** -> derive topology from geometry and traversable openings, enforce graph invariants, and reject open-plan or malformed cases.
- **Pose drift can invalidate shared marker coordinates** -> store map-specific coordinates in instances while keeping physical identity and answers question-scoped.
- **Clean counterparts can make noisy questions easier if exposed together** -> corpus storage keeps variants paired for analysis, but the later evaluation harness must control which artifacts an agent can access.
- **Questions from the same scene are correlated** -> split and later aggregate by scene, and describe 30 scenes rather than 1,260 episodes as the independent sample count.
- **Structured3D redistribution may be restricted** -> verify source and derivative-data terms before publishing; keep gated data internal if required.
- **Native LCM serialization couples data to DimOS message compatibility** -> pin the message/schema version and provide integrity/decode validation for every release.

## Migration Plan

This is a new offline capability with no runtime migration. Build and validate a small development subset first, then generate the 30-scene pilot. A failed release is rolled back by discarding its immutable release directory and retaining the previous release; generated data is never mutated in place.

## Open Questions

- Exact numeric values for the fixed square footprint, safety margin, mapper configuration, and realistic noise profile must be calibrated before corpus generation.
- Structured3D access and derivative-artifact redistribution terms must be confirmed.
- The later evaluation change must define the PointCloud2-to-agent representation, artifact access boundary, answer protocol, and scoring methodology.
