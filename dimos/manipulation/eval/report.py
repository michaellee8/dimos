# Copyright 2025-2026 Dimensional Inc.
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

"""Offline analysis over recorded benchmark episodes (a JSONL file or a list).

Pure read-only functions over the episode dicts written by ``EpisodeRecorder``.
Uses only the standard library (``statistics`` — no numpy) so it imports anywhere
without hardware dependencies. ``sim_to_real_gap`` doubles as the before/after
comparator (pass the two episode lists).
"""

from __future__ import annotations

import json
from pathlib import Path
import statistics
from typing import Any

from dimos.manipulation.eval.recorder import STAGE_KEYS

Episode = dict[str, Any]


def load_episodes(path: str | Path) -> list[Episode]:
    """Read a JSONL file written by ``EpisodeRecorder`` into a list of dicts."""
    episodes: list[Episode] = []
    with Path(path).expanduser().open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                episodes.append(json.loads(line))
    return episodes


def episode_error_code(episode: Episode) -> str | None:
    """Return the terminal failure error_code for an episode, else ``None``.

    Prefers the pick failure, then the place failure. Returns ``None`` for a
    successful episode or a failure that carried no code (e.g. a pre-PR string
    failure or a scan miss).
    """
    pick = episode.get("pick_result")
    if pick and not pick.get("success"):
        return pick.get("error_code")
    place = episode.get("place_result")
    if place and not place.get("success"):
        return place.get("error_code")
    return None


def task_success_rate(episodes: list[Episode]) -> float:
    """Fraction of episodes with ``task_success`` true (0.0 for empty input)."""
    if not episodes:
        return 0.0
    return sum(1 for ep in episodes if ep.get("task_success")) / len(episodes)


def stage_breakdown(episodes: list[Episode]) -> dict[str, dict[str, Any]]:
    """Per-stage ``{attempted, passed, rate}``.

    ``attempted`` counts episodes where the stage was reached (flag not null);
    ``passed`` counts those where it was true. ``None`` (not reached) is excluded
    from both, so the rate is conditional on the stage being reached.
    """
    out: dict[str, dict[str, Any]] = {}
    for stage in STAGE_KEYS:
        attempted = 0
        passed = 0
        for ep in episodes:
            value = (ep.get("stages") or {}).get(stage)
            if value is None:
                continue
            attempted += 1
            if value:
                passed += 1
        out[stage] = {
            "attempted": attempted,
            "passed": passed,
            "rate": (passed / attempted) if attempted else 0.0,
        }
    return out


def per_object_success_rate(episodes: list[Episode]) -> dict[str, float]:
    """Map ``object_name -> task success rate``."""
    totals: dict[str, list[int]] = {}
    for ep in episodes:
        name = ep.get("object_name", "unknown")
        bucket = totals.setdefault(name, [0, 0])  # [total, passed]
        bucket[0] += 1
        if ep.get("task_success"):
            bucket[1] += 1
    return {name: (passed / total if total else 0.0) for name, (total, passed) in totals.items()}


def error_code_distribution(episodes: list[Episode]) -> dict[str, int]:
    """Count terminal error codes across *failed* episodes.

    Failures with no machine-readable code (pre-PR string stack, scan misses,
    uncaught exceptions without a code) are bucketed as ``"UNKNOWN"`` so they
    remain visible in the distribution.
    """
    counts: dict[str, int] = {}
    for ep in episodes:
        if ep.get("task_success"):
            continue
        code = episode_error_code(ep) or "UNKNOWN"
        counts[code] = counts.get(code, 0) + 1
    return counts


def cycle_time_stats(episodes: list[Episode]) -> dict[str, float]:
    """``{mean_ms, median_ms, p95_ms, min_ms, max_ms, n}`` over cycle times."""
    values = sorted(
        float(ep["cycle_time_ms"]) for ep in episodes if ep.get("cycle_time_ms") is not None
    )
    if not values:
        return {
            "mean_ms": 0.0,
            "median_ms": 0.0,
            "p95_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "n": 0,
        }
    n = len(values)
    # statistics.quantiles needs >= 2 points; for a single sample p95 == that value.
    p95 = values[-1] if n < 2 else statistics.quantiles(values, n=20, method="inclusive")[18]
    return {
        "mean_ms": statistics.fmean(values),
        "median_ms": statistics.median(values),
        "p95_ms": float(p95),
        "min_ms": values[0],
        "max_ms": values[-1],
        "n": n,
    }


def sim_to_real_gap(sim_episodes: list[Episode], real_episodes: list[Episode]) -> dict[str, Any]:
    """Compare two runs. Doubles as the before/after comparator (before=sim, after=real).

    ``gap`` and the per-stage / per-object deltas are ``sim - real`` (positive
    means the first set performed better — i.e. a sim-to-real drop, or a
    before/after regression).
    """
    sim_tsr = task_success_rate(sim_episodes)
    real_tsr = task_success_rate(real_episodes)

    sim_stage = stage_breakdown(sim_episodes)
    real_stage = stage_breakdown(real_episodes)
    per_stage = {s: sim_stage[s]["rate"] - real_stage[s]["rate"] for s in STAGE_KEYS}

    sim_obj = per_object_success_rate(sim_episodes)
    real_obj = per_object_success_rate(real_episodes)
    per_object = {
        name: sim_obj.get(name, 0.0) - real_obj.get(name, 0.0)
        for name in set(sim_obj) | set(real_obj)
    }

    return {
        "sim_tsr": sim_tsr,
        "real_tsr": real_tsr,
        "gap": sim_tsr - real_tsr,
        "per_stage": per_stage,
        "per_object": per_object,
    }


def print_report(episodes: list[Episode], title: str = "Benchmark Report") -> None:
    """Print a human-readable ASCII report of all metrics."""
    bar = "=" * 66
    n = len(episodes)
    passed = sum(1 for ep in episodes if ep.get("task_success"))
    cts = cycle_time_stats(episodes)

    lines = [bar, title, bar, f"episodes        : {n}"]
    lines.append(f"task success    : {task_success_rate(episodes):6.1%}  ({passed}/{n})")
    lines.append(
        "cycle time (ms) : "
        f"mean={cts['mean_ms']:.0f} median={cts['median_ms']:.0f} "
        f"p95={cts['p95_ms']:.0f} min={cts['min_ms']:.0f} max={cts['max_ms']:.0f}"
    )

    lines.append("")
    lines.append("stage breakdown (passed/attempted):")
    breakdown = stage_breakdown(episodes)
    for stage in STAGE_KEYS:
        d = breakdown[stage]
        lines.append(f"  {stage:<14} {d['passed']:>3}/{d['attempted']:<3}  {d['rate']:6.1%}")

    lines.append("")
    lines.append("per-object success:")
    for name, rate in sorted(per_object_success_rate(episodes).items()):
        lines.append(f"  {name:<14} {rate:6.1%}")

    lines.append("")
    lines.append("error codes (failed episodes):")
    distribution = error_code_distribution(episodes)
    if distribution:
        for code, cnt in sorted(distribution.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {code:<28} {cnt}")
    else:
        lines.append("  (none)")

    lines.append(bar)
    print("\n".join(lines))
