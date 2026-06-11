# FlowBase Precision-Control Tuning — Results

Bringing the **FlowBase** holonomic base toward the Go2's FOPDT precision
path-following (PR #2274). This documents what was measured, every knob swept
with its numbers, and what shipped.

## TL;DR

1. **The FOPDT precision (corridor) controller gives *no benefit* on FlowBase** —
   it's too snappy (τ ≈ 0.1–0.3 s) to have the high-speed overshoot the corridor
   controller is designed to fix. Precision ≈ baseline, slightly worse on corners.
2. **The real tracking error is a pure-pursuit *lookahead chord* offset**, fixed
   by shrinking the follower lookahead **0.5 → 0.25 m**: circle CTE **10.2 → 2.3 cm
   (~4.5×)**, corner ~2×, square better, no regressions, stable to 0.6 m/s.
3. **Shipped:** `lookahead_dist = 0.25` as the FlowBase follower default (global
   default unchanged at 0.5 → Go2 unaffected), new `flowbase-benchmark[-rg]`
   blueprints, and benchmark tuning knobs (`k_angular`/`lookahead_dist` + one-run
   sweeps).

All numbers are hardware runs on concrete. CTE = cross-track error.

---

## 1. Plant characterization (FOPDT, dense fit)

Artifact: `flowbase_config_hw_concrete_2026-06-09_704a591f5.json` (17 sweep points/axis).

| axis | K | τ (s) | L (s) | r² |
|------|------|-------|-------|------|
| vx (fwd)   | 0.778 | 0.288 | 0.010 | 0.85 |
| vy (strafe)| 0.773 | 0.267 | 0.033 | 0.87 |
| wz (yaw)   | 2.929 | 0.607 | 0.017 | 0.89 |

- **Real speed envelope ≈ 0.63 m/s** (vx/vy). Ceiling probes (commanding 2.5 / 3.0)
  saturate at ~0.62 m/s (apparent K collapses to 0.25 / 0.21) — confirms the limit.
- Firmware caps `max_vel = [0.8, 0.8, 3.0]`. **No firmware command-deadman →
  physical e-stop is mandatory.**

## 2. Benchmark: precision follower vs baseline follower

Operating-point benchmark, full speed ladder 0.2–0.6 m/s × 4 paths, hardware.
Knobs held fixed: `e_max = 0.20`, `lookahead = 0.5`, `k_angular = 0.5`.
Arms: **bare** = `path_follower`, **rg** = `precision_follower`.

`cte_max` (cm), **bare baseline**:

| path | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 |
|------|-----|-----|-----|-----|-----|
| straight_line | 0.3 | 0.3 | 0.4 | 0.5 | 0.5 |
| single_corner | 15.5 | 14.8 | 13.8 | 11.2 | 9.9 |
| square | 15.4 | 15.1 | 12.5 | 10.3 | 11.1 |
| circle | 11.2 | 10.3 | 10.3 | 10.8 | 11.2 |

**rg − bare** deltas: straight ≈ 0; corner/square `cte_rms` **worse by +0.3…+1.8 cm**;
circle ≈ 0. XY traces for the two arms are visually indistinguishable.

**→ Precision = baseline (slightly worse on cornering). The FOPDT corridor's only
lever is speed-vs-curvature; FlowBase is already snappy enough that speed isn't the
bottleneck, so it buys nothing.** Notable side-findings:
- Corner/square error *decreases* with speed (15 → 10 cm) — opposite of overshoot.
- Circle error is **flat ~10 cm at every speed** → a systematic *geometric* offset.

## 3. Isolating the real error — knob sweeps (circle @ 0.4 m/s)

Target: the circle's flat ~10 cm offset.

| knob swept | values | circle `cte_max` (cm) | verdict |
|------------|--------|------------------------|---------|
| **e_max** (corridor half-width) | 0.1 / 0.2 / 0.5 | 10.9 / 11.2 / 10.2 | flat → speed irrelevant |
| **k_angular** (heading P-gain) | 0.5 / 1.0 / 1.5 / 2.0 | 10.4 / 10.4 / 10.5 / 10.4 | flat → **not** the lever |
| **lookahead_dist** | 0.5 / 0.35 / 0.25 / 0.15 | **10.2 / 4.9 / 2.2 / 0.8** | **THE lever (error ∝ L²)** |

**Root cause:** the path-follower is a **unicycle pure-pursuit** controller (fixed
lookahead carrot + `k_angular` heading gain; it does *not* use FlowBase's holonomic
`vy`). Pure pursuit cuts inside curves by ≈ `lookahead² / (2·R)` =
`0.5² / (2·1.0)` = **12.5 cm**, matching the observed ~10–11 cm — and the L² scaling
in the sweep confirms it. `e_max` and `k_angular` only change speed/heading-gain, so
they can't move a steady-state geometric chord offset; lookahead can.

## 4. Validation across shapes & speeds (lookahead 0.15 vs 0.25)

All 4 paths × {0.4, 0.6} m/s, `cte_max` (cm):

| path | L=0.15 (0.4 / 0.6) | L=0.25 (0.4 / 0.6) | baseline L=0.5 |
|------|--------------------|--------------------|----------------|
| straight_line | 0.6 / 1.4 | 0.5 / 0.7 | ~0.5 |
| single_corner | 11.2 / 9.0 | 6.6 / 8.4 | ~13.8 |
| square | 7.7 / **13.4** | 6.4 / 10.8 | ~12.5 |
| circle | 0.8 / 0.8 | 2.3 / 2.5 | ~10.2 |

**Trade-off:** smaller lookahead helps smooth curvature (circle) + straight line but
**hurts sharp corners** — a close carrot can't anticipate a 90° corner, so it turns
late and overshoots. `L=0.15` over-fits the circle (0.8 cm) but **regresses square @
0.6 to 13.4 cm** (worse than baseline) and barely helps the corner.

**Winner: `lookahead_dist = 0.25`** — improves *every* path vs baseline (circle ~4.5×,
corner ~2×, square better), no regressions, no wobble up to 0.6 m/s.

## 5. What shipped

- **`_FLOWBASE_LOOKAHEAD = 0.25`** applied per-task to the FlowBase followers:
  `coordinator-flowbase-precision-nav`, `flowbase-benchmark` / `-rg`,
  `coordinator-flowbase-keyboard-teleop`. **Global `PathFollowerTaskConfig.lookahead_dist`
  stays 0.5 → Go2 and other robots unaffected.**
- **`flowbase-benchmark` / `flowbase-benchmark-rg`** — operating-point benchmark
  blueprints (mirror the Go2 benchmark; bare vs precision arms).
- **Benchmark tuning knobs** (no plant-artifact mutation):
  `-o benchmarker.k_angular=` / `-o benchmarker.lookahead_dist=` (single), and one-run
  sweeps `-o benchmarker.k_angular_sweep=` / `-o benchmarker.lookahead_sweep=`.
- **`lookahead_dist` plumbed** through `PathDistancer → PathFollowerTaskConfig →
  configure() → PathFollowerTaskParams/create_task` (and the precision task).

## 6. Generic findings (for Go2 / nav-stack maintainers)

1. The path-follower is **unicycle pure-pursuit** with a **0.5 m default lookahead
   that is too large for tight curves**. **Per-robot lookahead is the real accuracy
   lever** — not the FOPDT corridor controller, which is a no-op on a snappy
   holonomic base.
2. The holonomic base is driven by a controller that **ignores `vy`**; a true
   holonomic cross-track controller (correct laterally with `vy`) is the deeper fix.
3. The nav stack's `SimplePlanner.lookahead_distance` (FlowBase default **2.0**) has
   the same chord-cutting effect; `coordinator-flowbase-nav-tuned` (1.0) was added
   for future click-to-go tuning.

## 7. Not pursued / open items

- **Click-to-go nav CTE comparison** (precision-nav / nav-tuned vs the Phase-0
  baseline `20260603-164011`): **shelved** — recorded `path` and `odometry` are in
  different frames (needs per-path frame alignment) *and* the comparison wouldn't
  isolate the lookahead fix (different planner + follower). The fixed-path benchmark
  in §2–§4 is the clean before/after.
- **precision-nav click-to-goal navigation**: its voxel/A* map has **no terrain
  ground-removal**, so on FlowBase the floor reads as obstacles → "no path found".
  Needs the terrain-aware costmap (like the working `coordinator-flowbase-nav`) +
  LiDAR mount calibration. Separate effort.
- **LiDAR mount** is still the old guess `Pose(0.20, -0.20, 0.10)`; measured is
  `Pose(0.22, -0.185, 0.381)` (Z off ~28 cm).

## 8. Reproduce

```bash
# Benchmark baseline vs precision (full ladder):
dimos run flowbase-benchmark    -o benchmarker.config=<dense_fit.json> -o benchmarker.speeds=0.2,0.3,0.4,0.5,0.6
dimos run flowbase-benchmark-rg -o benchmarker.config=<dense_fit.json> -o benchmarker.speeds=0.2,0.3,0.4,0.5,0.6

# Lookahead sweep in one run (circle @ 0.4):
dimos run flowbase-benchmark -o benchmarker.config=<dense_fit.json> \
    -o benchmarker.speeds=0.4 -o benchmarker.lookahead_sweep=0.5,0.35,0.25,0.15
```
Gated in the pygame window (ENTER run, K skip, Backspace quit). E-stop mandatory.

## Commits (branch `krishna/flowbase-precision-control`)

| commit | change |
|--------|--------|
| `c63f3ea26` | `flowbase-benchmark` + `-rg` blueprints |
| `dd3ee7e64` | `k_angular` + `lookahead_dist` benchmark overrides; lookahead plumbing |
| `6565b43fc` | `k_angular_sweep` (one-run sweep) |
| `5e660b4c3` | `lookahead_sweep` (one-run sweep) |
| `1006aa729` | deploy `lookahead_dist = 0.25` for FlowBase followers |
| `4dc82c51f` / `51e1e3e23` | precision-nav recording (`NavRecord`) + stream-conflict fix |
| `8b6ed762a` | `coordinator-flowbase-nav-tuned` (planner lookahead 2.0 → 1.0) |
