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

"""Diff two eval runs side-by-side with paired stats.

Usage:
    python -m misc.path_eval.compare runs/baseline runs/tweaked
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

# Per-trial metrics that get a paired test. (success is binary -> McNemar in spirit.)
_PAIRED_METRICS: tuple[str, ...] = (
    "distance_traveled",
    "path_efficiency",
    "min_obstacle_clearance",
    "mean_obstacle_clearance",
    "num_replans",
    "collision_avoided_count",
)


def _load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    aggregate = json.loads((run_dir / "aggregate.json").read_text())
    trials_dir = run_dir / "trials"
    trial_files = sorted(trials_dir.glob("*.json"))
    trials = [json.loads(p.read_text()) for p in trial_files]
    return aggregate, trials


def _trial_dict(trials: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {t["trial_id"]: t for t in trials}


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _print_aggregate_table(
    name_a: str, agg_a: dict[str, Any], name_b: str, agg_b: dict[str, Any]
) -> None:
    label_w = 30
    col_w = 12
    print(f"{'metric':<{label_w}}{name_a:>{col_w}}{name_b:>{col_w}}{'delta':>{col_w}}")
    print("-" * (label_w + col_w * 3))

    def row(label: str, a_val: float, b_val: float) -> None:
        delta = b_val - a_val
        print(
            f"{label:<{label_w}}{_fmt(a_val):>{col_w}}{_fmt(b_val):>{col_w}}{_fmt(delta):>{col_w}}"
        )

    row("composite_score", agg_a["composite_score"], agg_b["composite_score"])
    row("success_rate", agg_a["success_rate"], agg_b["success_rate"])
    for metric in agg_a["metrics"]:
        if metric not in agg_b["metrics"]:
            continue
        row(f"{metric}.mean", agg_a["metrics"][metric]["mean"], agg_b["metrics"][metric]["mean"])


def _print_paired_tests(
    name_a: str, trials_a: list[dict[str, Any]], name_b: str, trials_b: list[dict[str, Any]]
) -> None:
    a_by_id = _trial_dict(trials_a)
    b_by_id = _trial_dict(trials_b)
    common_ids = sorted(set(a_by_id) & set(b_by_id))
    if not common_ids:
        print("\n(no common trial IDs — cannot do paired comparison)")
        return
    print(f"\nPaired comparison on {len(common_ids)} matched trials (A={name_a}, B={name_b}):")
    label_w = 30
    col_w = 12
    print(f"{'metric':<{label_w}}{'mean_delta':>{col_w}}{'paired_t':>{col_w}}{'p_value':>{col_w}}")
    print("-" * (label_w + col_w * 3))
    for metric in _PAIRED_METRICS:
        a_vals = np.array([a_by_id[i][metric] for i in common_ids], dtype=float)
        b_vals = np.array([b_by_id[i][metric] for i in common_ids], dtype=float)
        delta = b_vals - a_vals
        if np.all(delta == 0):
            t_val, p_val = 0.0, 1.0
        else:
            t_res = stats.ttest_rel(b_vals, a_vals)
            t_val = float(t_res.statistic)
            p_val = float(t_res.pvalue)
        print(
            f"{metric:<{label_w}}{_fmt(float(delta.mean())):>{col_w}}{_fmt(t_val):>{col_w}}{_fmt(p_val):>{col_w}}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_a", type=Path)
    parser.add_argument("run_b", type=Path)
    args = parser.parse_args()

    agg_a, trials_a = _load_run(args.run_a)
    agg_b, trials_b = _load_run(args.run_b)

    name_a = args.run_a.name
    name_b = args.run_b.name

    _print_aggregate_table(name_a, agg_a, name_b, agg_b)
    _print_paired_tests(name_a, trials_a, name_b, trials_b)


if __name__ == "__main__":
    main()
