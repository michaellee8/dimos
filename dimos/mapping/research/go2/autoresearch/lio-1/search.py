# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Hyperparameter search over the Point-LIO CONFIG. This is a tuning problem,
not open-ended research: the knobs are numeric, evaluate() is a scalar
objective, and a run is ~12 s. So we drive a classical optimizer (simulated
annealing) over algo.run(overrides) -> val_ate_xy.

Covariances span orders of magnitude, so those are searched in log10 space.
Each trial is logged to search_log.tsv; the best config is printed and written
to best_config.json. Run: `python search.py --iters 200`.
"""

import argparse
from datetime import datetime
import json
import math
import os
import subprocess
import time

import algo
import evaluate
from scipy.optimize import dual_annealing

# Search space: (name, kind, lo, hi) in NATURAL units. "log" params are searched
# in log10 space (they span decades); "lin" linearly; "int" rounded. Everything
# not listed stays fixed at algo.CONFIG (physical/mount params: acc_norm,
# extrinsic_R, lidar_type, scan_line, imu_time_inte, ...).
SPACE = [
    ("lidar_meas_cov", "log", 1e-4, 1.0),
    ("acc_cov_output", "log", 1e1, 1e4),
    ("gyr_cov_output", "log", 1e1, 1e4),
    ("b_acc_cov", "log", 1e-6, 1e-2),
    ("b_gyr_cov", "log", 1e-6, 1e-2),
    ("imu_meas_acc_cov", "log", 1e-3, 1e1),
    ("imu_meas_omg_cov", "log", 1e-3, 1e1),
    ("gyr_cov_input", "log", 1e-4, 1.0),
    ("acc_cov_input", "log", 1e-3, 1e1),
    ("filter_size_surf", "lin", 0.05, 0.5),
    ("filter_size_map", "lin", 0.05, 0.5),
    ("plane_thr", "lin", 0.01, 0.5),
    ("match_s", "int", 5, 200),
]

PENALTY = 1e3  # objective value for a crashed / timed-out run (>> baseline ~11)
LOG_PATH = os.path.join(evaluate.HERE, "search_log.tsv")
BEST_PATH = os.path.join(evaluate.HERE, "best_config.json")


def bounds():
    return [
        (math.log10(lo), math.log10(hi)) if kind == "log" else (lo, hi) for _, kind, lo, hi in SPACE
    ]


def decode(x):
    """Optimizer vector -> CONFIG override dict (undo the log/int transforms)."""
    out = {}
    for (name, kind, _, _), xi in zip(SPACE, x, strict=False):
        if kind == "log":
            out[name] = float(10**xi)
        elif kind == "int":
            out[name] = round(xi)
        else:
            out[name] = float(xi)
    return out


def encode(cfg):
    """CONFIG -> optimizer vector (for seeding SA's x0)."""
    return [
        math.log10(cfg[name]) if kind == "log" else float(cfg[name]) for name, kind, _, _ in SPACE
    ]


def _clip(x):
    """Keep a vector inside the search box (a stored best could sit on/past an
    edge, and dual_annealing requires x0 within bounds)."""
    return [min(max(xi, lo), hi) for xi, (lo, hi) in zip(x, bounds(), strict=False)]


def warm_start_x0(cold=False):
    """SA seed: the best config found so far (best_config.json) if present, else
    the v2_imu baseline. `cold=True` forces the baseline. Returns (x0, source)."""
    cfg = dict(algo.CONFIG)
    src = "baseline (v2_imu)"
    if not cold and os.path.exists(BEST_PATH):
        try:
            best = json.load(open(BEST_PATH))
            cfg.update(best.get("overrides", {}))
            src = f"best_config.json (val_ate_xy {best['val_ate_xy']:.4f})"
        except Exception:
            pass
    return _clip(encode(cfg)), src


class Objective:
    """val_ate_xy as a function of the optimizer vector, with trial logging."""

    def __init__(self):
        self.n = 0
        self.best_val = math.inf
        self.best_overrides = None
        self.run = datetime.now().strftime("%Y%m%d-%H%M%S")  # tags this run's rows
        # Append-only: NEVER truncate prior runs. Header written once; the `run`
        # column lets you separate / compare runs in the same file.
        if not os.path.exists(LOG_PATH) or os.path.getsize(LOG_PATH) == 0:
            cols = ["run", "iter", "val_ate_xy", "status"] + [name for name, *_ in SPACE]
            with open(LOG_PATH, "w") as f:
                f.write("\t".join(cols) + "\n")

    def __call__(self, x):
        self.n += 1
        overrides = decode(x)
        try:
            m = algo.run(overrides)
            val, status = m["val_ate_xy"], "ok"
        except subprocess.TimeoutExpired:
            val, status = PENALTY, "timeout"
        except Exception:
            val, status = PENALTY, "crash"

        if val < self.best_val:
            self.best_val, self.best_overrides = val, overrides

        with open(LOG_PATH, "a") as f:
            vals = "\t".join(f"{overrides[name]:g}" for name, *_ in SPACE)
            f.write(f"{self.run}\t{self.n}\t{val:.6f}\t{status}\t{vals}\n")
        print(
            f"[{self.n:4d}] val_ate_xy={val:10.4f} ({status:7s})  best={self.best_val:.4f}",
            flush=True,
        )
        return val


def main():
    ap = argparse.ArgumentParser(description="Simulated-annealing tuning of Point-LIO CONFIG.")
    ap.add_argument(
        "--runs",
        type=int,
        default=200,
        help="point_lio run budget (max objective evals; ~12 s each)",
    )
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--cold",
        action="store_true",
        help="ignore best_config.json and start from the v2_imu baseline",
    )
    args = ap.parse_args()

    if not os.path.exists(evaluate.POINTLIO_BIN):
        raise SystemExit("pointlio binary not built — run ./setup.sh first.")

    x0, x0_src = warm_start_x0(cold=args.cold)
    print(f">> warm-start from {x0_src}")

    obj = Objective()
    t0 = time.time()
    # Pure SA: no_local_search=True avoids the gradient finite-diff local polish,
    # which is wasteful here (noisy, partly-integer objective; each eval ~12 s).
    # Budget is maxfun (total objective evals = point_lio runs) — NOT maxiter,
    # which counts SA temperature steps and triggers many evals each.
    res = dual_annealing(
        obj,
        bounds(),
        x0=x0,
        maxfun=args.runs,
        seed=args.seed,
        no_local_search=True,
    )
    dt = time.time() - t0

    best = obj.best_overrides or decode(res.x)
    print("\n=== search done ===")
    print(f"trials:        {obj.n}")
    print(f"best val_ate_xy: {obj.best_val:.6f}  (baseline ~10.97)")
    print(f"wall_clock:    {dt / 60:.1f} min")

    # Keep the GLOBAL best across runs — only overwrite best_config.json if this
    # run actually beat the stored best (so a worse run can't clobber a good one).
    prev = None
    if os.path.exists(BEST_PATH):
        try:
            prev = json.load(open(BEST_PATH))
        except Exception:
            prev = None
    if prev is None or obj.best_val < prev.get("val_ate_xy", math.inf):
        with open(BEST_PATH, "w") as f:
            json.dump({"val_ate_xy": obj.best_val, "run": obj.run, "overrides": best}, f, indent=2)
        print(f"new global best — wrote {BEST_PATH}")
    else:
        print(
            f"kept existing {BEST_PATH} (stored {prev['val_ate_xy']:.4f} ≤ this run {obj.best_val:.4f})"
        )

    # Re-run the best config to leave viz.png + traj_ds.tsv for it.
    try:
        algo.run(best, render=True)
    except Exception as e:
        print(f"(best-config re-render skipped: {e})")


if __name__ == "__main__":
    main()
