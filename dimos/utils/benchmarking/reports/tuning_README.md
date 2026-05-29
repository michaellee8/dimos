# Twist-base controller tuning — operator guide

Two blueprints, run in order:

1. **`unitree-go2-characterization`** — measures the robot's FOPDT plant, writes a config JSON.
2. **`unitree-go2-benchmark`** — runs the baseline controller across a speed ladder, scores CTE, writes the operating-point map.

Both bundle GO2Connection + ControlCoordinator + pygame teleop + the relevant module + a per-session SQLite recorder. One terminal each.

## Prerequisites

1. From an X11 desktop terminal:
   ```
   cd ~/dimos && source .venv/bin/activate
   ```
2. Robot powered on, network reachable. Clear ~3m × 3m of floor space.

## Pygame controls (both blueprints)

Window must have focus. **WASD/QE** = reposition. **Enter** = advance. **K** = skip. **Backspace** = quit.

## Step 1 — characterization

```
dimos run unitree-go2-characterization
```

Per axis (vx, vy, wz on Go2), the SI loop runs three phases. One ENTER
per step. *"amp"* below = step amplitude (m/s for vx/vy, rad/s for wz).

```
for ch in (vx, vy, wz):
    floor_probe(amps=[0.02, 0.05, 0.10, 0.15])   # ~4 tiny amplitudes
    dense_sweep(amps=[0.2, 0.5, 1.0, 1.5, 2.0])  # 5 amplitudes, FOPDT fit each
    ceiling_probe(amps=[2.5, 3.0])               # ~2 supra-sweep amplitudes
```

**Floor probe** — smallest amplitude that actually moves the robot:
- AND-test (D3): `|v_body| > 0.02 m/s` **AND** `> 5%·|amp|`
- Sustained for ≥5 samples

**Dense sweep** — fit the linear-regime FOPDT:
- One FOPDT fit per amp.
- Canonical `K` = lowest amp with `r² > 0.9` (methodology v2 / D1).

**Ceiling probe** — max output the plant can actually deliver:
- Operational ceiling = `min(max(|K(amp)·amp|), profile.{vx,wz}_max)`
- Computed across the FULL sweep + ceiling-probe table.
- Uses output magnitude (`K·amp`), not `K` alone — robust to noisy fits.
- K-sag amp (where K drops 15% below linear K) saved as `saturating_at_amp` for forensics, **not** the cap.

Settling pre-roll (~1.5 s) happens *after* you press Enter — wait for
it. Each phase prints a banner so you know which sub-test is running.

**Space requirements**:
- Open, spacious area.
- A long corridor or basketball-court-sized space works.
- Each step needs clear run-out — several metres for high-amplitude vx.
- Cramped rooms force `--max-dist` cuts that bias the fit.

**Output** (same timestamp suffix):

```
data/characterization/go2/
├── go2_config_hw_concrete_<date>_<sha>.json   ← the tuning artifact
├── go2_config_hw_concrete_<date>_<sha>.png    ← fit-quality plot + K(amp) panel
└── go2_recording_<date>_<sha>.db              ← raw streams (cmd_vel, joint_state, odom, gate)
```

The `.json` is the **tuning artifact** — the single versioned source of
truth handed off to Step 2 (benchmark) and Step 3 (precision-nav).
Inside:

- `provenance` — robot_id, surface, gait mode, date, git sha, hw vs self-test.
- `plant` — fitted FOPDT `{K, τ, L}` per axis (vx, vy, wz). Canonical K = linear-regime fit (lowest amp with r²>0.9).
- `dynamics_by_amplitude` — the full per-amp `K(amp), τ(amp), L(amp), r²` table (sweep + ceiling probe). What lets future controllers interpolate without re-running.
- `floor_probe_results` — per-amp AND-test pass/fail and sustained-sample count for the floor sweep.
- `velocity_envelope` — measured floor + ceiling per channel (`saturating_at_amp` is forensic-only).
- `feedforward` — `1/K_linear` per axis + output clamps.
- `velocity_profile` — curvature speed profile (max linear/angular speed, accel, decel, lookahead).
- `recommended_controller` — baseline P-controller + plant-floor evidence string.
- `operating_point_map` — `null` until Step 2 fills it in.
- `caveats` — validity scope; self-test artifacts lead with a loud DO-NOT-TUNE banner.
- `valid_for_tuning` — `true` only for hw mode. `false` ⇒ refuse to apply.
- `schema_version` — bumped on breaking artifact changes.

## Step 2 — benchmark

```
dimos run unitree-go2-benchmark \
  -o benchmarker.config=/path/to/go2_config_hw_*.json     # bare baseline

dimos run unitree-go2-benchmark-rg \
  -o benchmarker.config=/path/to/go2_config_hw_*.json     # RG arm baked in (rg=true)
```

**Blueprint `-o` overrides**:
- `-o` is for runtime knobs only (artifact path, e_max sweeps).

**Per-run loop** — for each `(path, speed)`:
- Fixed path set: `straight_line`, `single_corner`, `square`, `circle`.
- CTE scored from the real trajectory.

**Comparison arms** (each measured *against* the bare physical limit):
- `-o benchmarker.ff=true` — apply derived feedforward.
- `-o benchmarker.profile=true` — apply derived curvature velocity profile.
- `-o benchmarker.rg=true -o benchmarker.e_max=0.20` — apply reference-governor per-waypoint cap (precision = `e_max / max(τ+L)`).

**RG arm caveats**:
- Go2 stalls below ~0.2 m/s commanded velocity, even when math says slower.
- `benchmarker.min_speed` (default `0.2`) is the floor; set `None` to use the artifact's value.
- Tight corners + tight `e_max` track badly — saturation-binding cells get floored above ω_max. Physical limit, not a bug.

**Output**:

```
data/benchmark/go2/
├── go2_benchmark_<date>_<sha>.png  ← XY trajectory overlay + CTE plot
├── …_<arm>_<date>_<sha>.json       ← per-arm operating-point map (bare run also appends section 5 to the input artifact)
└── go2_benchmark_<date>_<sha>.db   ← raw streams
```

## Step 3 — precision-controlled nav (end-to-end)

```
dimos run unitree-go2-precision-nav
```

Go2 coord + rerun + (VoxelGrid + CostMapper + ReplanningAStarPlanner) + KeyboardTeleop (0-9 e_max slider) + recorder.

Operator flow:

1. Open rerun (auto-launches with the blueprint). Click a point on the map.
2. `ReplanningAStarPlanner` consumes the click and emits `path: Path`.
3. `ControlCoordinator.path` receives the planned path; `_on_path`
   snapshots the latest odom and broadcasts `set_path(path, odom)` to
   any task with the method.
4. `PrecisionPathFollowerTask.set_path` delegates to its existing
   `start_path` (which lazy-loads the artifact, solves
   `solve_profile()`, and starts the state machine).
5. The coord's tick loop drives the precision controller's velocity
   commands to GO2Connection.

Live-tune precision: keys **0-9** in the pygame window set corridor
half-width 0.0-0.9 m. `PrecisionPathFollowerTask` re-solves the profile
on each keypress and atomically swaps the per-waypoint cap mid-path.

**Output**:

```
data/precision_nav/go2/
└── go2_precision_nav_<date>_<sha>.db    ← cmd_vel, joint_state, odom, gate
```

**Hardware notes**:

- `ReplanningAStarPlanner.nav_cmd_vel: Out[Twist]` is intentionally
  unwired — the precision controller, not the planner, drives the
  robot. **The planner is only used as a path source.**

## Reading recordings

```python
from dimos.memory2.store.sqlite import SqliteStore
from dimos.msgs.sensor_msgs.JointState import JointState
store = SqliteStore(path="<.db file>"); store.start()
for obs in store.stream("joint_state", JointState):
    ts, msg = obs.ts, obs.data   # re-fit, plot, etc.
```

Streams: `cmd_vel` (Twist), `joint_state` (JointState, x/y/yaw), `odom` (PoseStamped, raw), `gate` (Int8, operator events). The Step 3 (precision-nav) recording adds nothing new — same schema, different `tag`.

## Troubleshooting

- **Pygame window doesn't open**: X11 not reachable. `xeyes` test, then `export DISPLAY=:1; export XAUTHORITY=/run/user/$(id -u)/.Xauthority`.
- **Enter does nothing**: pygame window isn't focused. Click it before pressing.
- **Terminal flooded with TF warnings**: pipe through `grep --line-buffered -E 'Benchmarker|Characterizer|reject|aborted|arrived|timeout|configure|start_path|required|reposition'`.
- **Robot won't move on RG arm**: see `min_speed` note above. Try `-o benchmarker.e_max=0.2` first; if still stuck, raise `-o benchmarker.min_speed=0.25`.
- **Self-test (no robot)**: keep using the CLI: `uv run python -m dimos.utils.benchmarking.characterization --mode self-test`.
