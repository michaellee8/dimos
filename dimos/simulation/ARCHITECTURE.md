# The dimos simulation architecture

This package is the bedrock for testing dimos systems — the same
blueprints, modules, and agentic stack that run on real robots — in
simulation. This document is the normative description of its structure:
what the layers are, what each contract promises, and what it means for
something to *be* a dimos simulator.

## The axiom

**The robot stack only ever talks to the world through topics, and it
cannot tell simulation from hardware.** Actuation goes in as `/cmd_vel`
(mobile base) or joint commands through the `ControlCoordinator`'s
whole-body plane; observation comes out as `/odom`, `/lidar`, images,
IMU. Everything simulation-only — world authoring, clock ownership,
human rendering — lives on separate surfaces the robot never sees. A
policy or planner that works in sim works on hardware *because it cannot
express a dependency on sim*. No side doors.

## The layers

Layered architecture in the strict sense: layer *n* serves layer *n+1*
and may only reach *down* to *n−1*. Imports are the enforcement — a
review that sees `sensors/` importing `backend/mujoco/` internals, or
anything outside `backend/mujoco/` importing `mujoco`, is seeing an
architecture violation.

```
dimos/simulation/
├── spec/          CONTRACTS — the standard's law, as code
│                    PhysicsAuthority · EntityConsumer · SceneControl
├── scene/         LAYER 1 · the static world, cooked once
│                    package.py (ScenePackage) · catalog.py · entity.py
│                    (EntityDescriptor / EntityStateBatch) · cook pipeline
├── backend/       LAYER 2 · the ONLY engine-specific runtime code
│                    base.py (PhysicsEngine ABC) · mujoco/
├── sensors/       LAYER 3 · backend-agnostic observation producers
│                    scene_lidar (Rust BVH) · mesh_camera · splat_camera
├── sim_module.py  LAYER 4 · the sim graph node (one per process graph)
├── api.py         LAYER 4 · SceneControl facade (PimSimClient)
├── adapters/      robot-shaped facades over the SHM joint plane
├── bridges/       out-of-process worlds (dimsim, unity) that satisfy
│                    PhysicsAuthority over a wire
├── testing/       e2e scenario drivers (not simulator internals)
└── legacy/        quarantined subprocess stack — deleted once Go2/G1
                     migrate onto the standard
```

### Layer 1 — scene

The static world is **cooked once** into a `ScenePackage` (visual GLB,
collision GLB, convex hulls, entity metadata, MJCF wrapper, alignment)
and consumed by every layer above through `scene/catalog.py`. Entities —
the dynamic things in a scene — have exactly one noun: `EntityDescriptor`
(what a thing is) plus a streamed pose (`EntityStateBatch`, what/where it
is now). Consumers key on `entity_id` and never learn which backend
moved it.

### Layer 2 — backend

`backend/base.py::PhysicsEngine` is the seam a new in-process engine
(Isaac, Genesis, MJX, …) implements: dynamics stepping, joint state and
actuation, reset/respawn, root pose — plus *optional* fast-paths
(raycast, native cameras) that default to "unsupported." **Engines are
values, not modules**: adding an engine adds a plugin behind this ABC,
never a new graph node, so engine count and module count are decoupled
by construction.

Engine-native handles (MuJoCo's `MjModel`/`MjData`) are private to
`backend/mujoco/`. Everything outside talks through named accessors —
that privacy is what keeps every other layer portable.

### Layer 3 — sensors

Sensors are **consumers, not backend features**. The Rust scene lidar
raycasts the cooked collision GLB plus live `entity_state_batch` poses;
the mesh camera samples the cooked visual GLB's textures at
barycentric-interpolated UVs from the robot's FK pose; the splat camera
renders a Gaussian splat from the same pose. None of them import an
engine, which is why they run identically over any backend and on
headless CI. Engine-native sensing (MuJoCo `mj_multiRay` lidar, MuJoCo
render cameras) exists as an *opt-in fast-path* on layer 2 — an
optimization, never the architecture.

### Layer 4 — module and control

`MujocoSimModule` is the one simulation graph node: it owns exactly one
`PhysicsEngine`, wires it to ports (`odom`, `entity_state_batch`, `imu`,
images, `cmd_vel` in), bridges the whole-body SHM joint plane, and
exposes the privileged verbs (`reset`, `respawn_at`) as RPCs. It is
slated to become the engine-generic `SimModule` (config-selected
backend via factory); its class name is retained until a second
in-process engine exists.

`SceneControl` (implemented by `PimSimClient` and the DimSim client) is
the out-of-process authoring surface tests use: pose the embodiment,
add obstacles, send goals. It is deliberately the *minimal common
denominator* every backend — and a real arena — can honor.

## The contracts (design by contract)

The spec follows the classical discipline: **weak preconditions, strong
postconditions, strong invariants**, and behavioral subtyping for
implementations.

- `PhysicsEngine` implementations must be **Liskov-substitutable**: a
  subtype may not weaken a postcondition (e.g. `get_root_pose` returns
  the *current stepped* state, not a stale mirror). This is precisely
  why an out-of-process world cannot implement `PhysicsEngine`: across a
  wire, every read is "latest known" and every call gains failure modes —
  weakened postconditions, a subtyping violation. Remote worlds instead
  satisfy…
- `PhysicsAuthority` — the topic-level *role*: publish
  `entity_state_batch` + `odom` each tick, consume `/cmd_vel`, honor
  `spawn_entity`, declare `capabilities`. Both the in-process module and
  the bridges satisfy it; consumers bind to this role only.
- `EntityConsumer` — anything that reads the entity stream. Blind to the
  authority behind it.

The conformance test (`spec/test_spec_conformance.py`) is the start of
the standard's teeth: **a dimos simulator is anything that passes the
conformance suite** — consumer-driven contract testing, with the e2e
suite as the integration-level check. Verification ("did we build it
right") is the unit + conformance layer; validation ("did we build the
right thing") is a robot exploring a scene package on command.

## Two faces, one world

The live face above (sim free-runs, robot in the loop) is what
sim==hardware needs. A second, *episodic* face — client-owned clock,
seeded `reset`, `step`, score — is what benchmark/policy evaluation
needs, and is deliberately kept out of `PhysicsAuthority` (a capability
to add behind `capabilities`, not a redesign). Benchmark harnesses that
drive third-party environments (LIBERO/robosuite sidecars) are
*consumers* of simulators, not simulators; they meet this package only
at the ControlCoordinator's motor plane and, eventually, as clients of
the episodic face.
