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

"""Run a full eval: load ply, sample trials, run them, write JSON results.

Usage:
    python -m misc.path_eval.run_eval --name baseline
    python -m misc.path_eval.run_eval --config eval.json --name big_run
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

from dimos.utils.logging_config import setup_logger
from misc.path_eval.config import EvalConfig
from misc.path_eval.metrics import aggregate
from misc.path_eval.sampling import sample_trials
from misc.path_eval.simulator import RevealedMapSimulator
from misc.path_eval.trial import TrialResult, TrialSpec, run_trial
from misc.path_eval.true_grid_cache import load_or_build_true_grid

logger = setup_logger()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, help="Path to JSON config (overrides defaults)")
    p.add_argument("--name", required=True, help="Run name; results saved to <out-dir>/<name>/")
    p.add_argument("--out-dir", type=Path, default=Path("misc/path_eval/runs"))
    p.add_argument(
        "--n-workers",
        type=int,
        default=max(1, (os.cpu_count() or 1) - 1),
        help="Process pool size (default: cpu_count-1). Use 1 to disable parallelism.",
    )
    p.add_argument("--n-trials", type=int, default=None, help="Override cfg.n_trials")
    p.add_argument("--seed", type=int, default=None, help="Override cfg.run_seed")
    p.add_argument(
        "--unknown-penalty", type=float, default=None, help="Override cfg.unknown_penalty"
    )
    p.add_argument(
        "--gradient-strategy",
        choices=["voronoi", "gradient"],
        default=None,
        help="Override cfg.gradient_strategy",
    )
    return p.parse_args()


def _resolve_config(args: argparse.Namespace) -> EvalConfig:
    cfg = EvalConfig.load(args.config) if args.config else EvalConfig()
    if args.n_trials is not None:
        cfg.n_trials = args.n_trials
    if args.seed is not None:
        cfg.run_seed = args.seed
    if args.unknown_penalty is not None:
        cfg.unknown_penalty = args.unknown_penalty
    if args.gradient_strategy is not None:
        cfg.gradient_strategy = args.gradient_strategy
    return cfg


def _write_trials(run_dir: Path, trials: list[TrialSpec]) -> None:
    (run_dir / "trials.json").write_text(json.dumps([asdict(t) for t in trials], indent=2))


def _run_one(spec: TrialSpec, cfg: EvalConfig) -> TrialResult:
    """Worker entry point. Loads true grid from cache and runs the trial."""
    true_grid = load_or_build_true_grid(cfg.pointcloud_name)
    sim = RevealedMapSimulator(true_grid, cfg)
    return run_trial(spec, sim, cfg)


def main() -> None:
    args = _parse_args()
    cfg = _resolve_config(args)

    run_dir: Path = args.out_dir / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    trials_dir = run_dir / "trials"
    trials_dir.mkdir(exist_ok=True)
    cfg.dump(run_dir / "config.json")
    logger.info("Run dir: %s", run_dir)

    true_grid = load_or_build_true_grid(cfg.pointcloud_name)
    logger.info(
        "True grid: %dx%d cells @ %.3f m/cell",
        true_grid.width,
        true_grid.height,
        true_grid.resolution,
    )

    trials = sample_trials(true_grid, cfg)
    _write_trials(run_dir, trials)

    results: list[TrialResult] = []
    run_t0 = time.perf_counter()

    def _record(result: TrialResult) -> None:
        results.append(result)
        (trials_dir / f"{result.trial_id:04d}.json").write_text(
            json.dumps(asdict(result), indent=2)
        )
        logger.info(
            "Trial %d: success=%s dist=%.2fm replans=%d (%.0fms)",
            result.trial_id,
            result.success,
            result.distance_traveled,
            result.num_replans,
            result.wall_time_ms,
        )

    if args.n_workers <= 1:
        for spec in trials:
            _record(_run_one(spec, cfg))
    else:
        with ProcessPoolExecutor(max_workers=args.n_workers) as pool:
            futures = {pool.submit(_run_one, spec, cfg): spec for spec in trials}
            for future in as_completed(futures):
                _record(future.result())
        results.sort(key=lambda r: r.trial_id)
    elapsed = time.perf_counter() - run_t0

    agg = aggregate(results, cfg)
    (run_dir / "aggregate.json").write_text(json.dumps(agg.to_dict(), indent=2))

    print()
    print(f"=== Run '{args.name}' done in {elapsed:.1f}s ===")
    print(f"Success rate: {agg.success_rate * 100:.1f}% ({agg.n_success}/{agg.n_trials})")
    print(f"Composite score: {agg.composite_score:.3f}")
    if agg.failure_reasons:
        print("Failures:", agg.failure_reasons)
    for fld, stats in agg.metrics.items():
        print(
            f"  {fld}: mean={stats['mean']:.3f}, median={stats['median']:.3f}, p95={stats['p95']:.3f}"
        )
    print(f"Results in: {run_dir}")


if __name__ == "__main__":
    main()
