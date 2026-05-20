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

"""Aggregate per-trial results into a single run summary with a composite score."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from misc.path_eval.config import EvalConfig
from misc.path_eval.trial import TrialResult

# Normalization references for the composite score. Clearance saturates at this
# value; replan count past this is fully penalized. Chosen so values match the
# scale of `voronoi_max_distance` and reasonable per-trial replan counts.
_CLEARANCE_REF_M = 1.0
_REPLAN_REF = 20.0


@dataclass
class AggregateResult:
    n_trials: int
    n_success: int
    success_rate: float
    composite_score: float
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    failure_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_METRIC_FIELDS: tuple[str, ...] = (
    "distance_traveled",
    "oracle_path_length",
    "path_efficiency",
    "num_steps",
    "min_obstacle_clearance",
    "mean_obstacle_clearance",
    "unknown_steps",
    "num_replans",
    "collision_avoided_count",
    "total_planning_time_ms",
    "wall_time_ms",
)


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "std": 0.0}
    arr = np.asarray(values, dtype=float)
    return {
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "std": float(arr.std(ddof=0)),
    }


def aggregate(results: list[TrialResult], cfg: EvalConfig) -> AggregateResult:
    n = len(results)
    successes = [r for r in results if r.success]
    success_rate = len(successes) / n if n else 0.0

    metrics: dict[str, dict[str, float]] = {}
    for fld in _METRIC_FIELDS:
        # Restrict path_efficiency to successful runs so failures don't pull it to 0.
        sample = successes if fld == "path_efficiency" else results
        metrics[fld] = _stats([float(getattr(r, fld)) for r in sample])

    metrics["unknown_fraction_traversed"] = _stats([r.unknown_fraction_traversed for r in results])
    metrics["unknown_traversal_payoff"] = _stats(
        [r.unknown_traversal_payoff for r in results if r.unknown_steps > 0]
    )

    failure_reasons: dict[str, int] = {}
    for r in results:
        if r.success or r.failure_reason is None:
            continue
        failure_reasons[r.failure_reason] = failure_reasons.get(r.failure_reason, 0) + 1

    composite = _composite_score(results, success_rate, cfg)
    return AggregateResult(
        n_trials=n,
        n_success=len(successes),
        success_rate=success_rate,
        composite_score=composite,
        metrics=metrics,
        failure_reasons=failure_reasons,
    )


def _composite_score(results: list[TrialResult], success_rate: float, cfg: EvalConfig) -> float:
    """Weighted sum of normalized sub-scores. All sub-scores are in [0, 1]."""
    successes = [r for r in results if r.success]
    if not successes:
        return 0.0

    eff = float(np.mean([r.path_efficiency for r in successes]))
    eff = max(0.0, min(1.0, eff))

    mean_clearance = float(np.mean([r.min_obstacle_clearance for r in successes]))
    clearance_score = max(0.0, min(1.0, mean_clearance / _CLEARANCE_REF_M))

    mean_replans = float(np.mean([r.num_replans for r in successes]))
    low_thrash = max(0.0, min(1.0, 1.0 - mean_replans / _REPLAN_REF))

    w = cfg.score_weights
    parts = {
        "success_rate": (w.get("success_rate", 0.0), success_rate),
        "path_efficiency": (w.get("path_efficiency", 0.0), eff),
        "clearance": (w.get("clearance", 0.0), clearance_score),
        "low_thrash": (w.get("low_thrash", 0.0), low_thrash),
    }
    total_weight = sum(weight for weight, _ in parts.values())
    if total_weight <= 0:
        return 0.0
    weighted = sum(weight * value for weight, value in parts.values())
    return weighted / total_weight
