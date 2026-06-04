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

"""Unit tests for the offline report functions (no hardware)."""

from __future__ import annotations

from typing import Any

import pytest

from dimos.manipulation.eval import report

_ALL_STAGES = ("scan", "grasp_gen", "plan_approach", "plan_grasp", "execute_pick", "execute_place")


def _result(success: bool, error_code: str | None = None) -> dict[str, Any]:
    return {"success": success, "error_code": error_code, "message": "", "duration_ms": 1.0}


def _episode(
    *,
    object_name: str = "cup",
    task_success: bool = True,
    stages: dict[str, Any] | None = None,
    pick: dict[str, Any] | None = None,
    place: dict[str, Any] | None = None,
    cycle_time_ms: float = 1000.0,
) -> dict[str, Any]:
    if stages is None:
        stages = {k: True for k in _ALL_STAGES}
    return {
        "object_name": object_name,
        "task_success": task_success,
        "stages": stages,
        "pick_result": pick,
        "place_result": place,
        "cycle_time_ms": cycle_time_ms,
    }


def test_task_success_rate() -> None:
    episodes = [
        _episode(task_success=True),
        _episode(task_success=True),
        _episode(task_success=False),
    ]
    assert report.task_success_rate(episodes) == pytest.approx(2 / 3)
    assert report.task_success_rate([]) == 0.0


def test_stage_breakdown() -> None:
    full = {k: True for k in _ALL_STAGES}
    grasp_fail = {
        "scan": True,
        "grasp_gen": False,
        "plan_approach": None,
        "plan_grasp": None,
        "execute_pick": None,
        "execute_place": None,
    }
    plan_fail = {
        "scan": True,
        "grasp_gen": True,
        "plan_approach": False,
        "plan_grasp": None,
        "execute_pick": None,
        "execute_place": None,
    }
    episodes = [_episode(stages=full), _episode(stages=grasp_fail), _episode(stages=plan_fail)]
    breakdown = report.stage_breakdown(episodes)

    assert breakdown["scan"] == {"attempted": 3, "passed": 3, "rate": 1.0}
    assert breakdown["grasp_gen"] == {"attempted": 3, "passed": 2, "rate": pytest.approx(2 / 3)}
    assert breakdown["plan_approach"] == {"attempted": 2, "passed": 1, "rate": 0.5}
    assert breakdown["plan_grasp"] == {"attempted": 1, "passed": 1, "rate": 1.0}


def test_per_object_success_rate() -> None:
    episodes = [
        _episode(object_name="cup", task_success=True),
        _episode(object_name="cup", task_success=False),
        _episode(object_name="bottle", task_success=True),
        _episode(object_name="bottle", task_success=True),
    ]
    rates = report.per_object_success_rate(episodes)
    assert rates["cup"] == pytest.approx(0.5)
    assert rates["bottle"] == pytest.approx(1.0)


def test_error_code_distribution() -> None:
    episodes = [
        _episode(task_success=False, pick=_result(False, "PLANNING_FAILED")),
        _episode(task_success=False, pick=_result(True), place=_result(False, "PLANNING_FAILED")),
        _episode(task_success=False, pick=_result(False, "GRASP_GENERATION_FAILED")),
        _episode(task_success=False, pick=_result(False, None)),  # pre-PR style -> UNKNOWN
        _episode(task_success=True, pick=_result(True), place=_result(True)),  # skipped
    ]
    dist = report.error_code_distribution(episodes)
    assert dist == {"PLANNING_FAILED": 2, "GRASP_GENERATION_FAILED": 1, "UNKNOWN": 1}


def test_cycle_time_stats() -> None:
    episodes = [_episode(cycle_time_ms=t) for t in (100.0, 200.0, 300.0)]
    stats = report.cycle_time_stats(episodes)
    assert stats["mean_ms"] == pytest.approx(200.0)
    assert stats["median_ms"] == pytest.approx(200.0)
    assert stats["min_ms"] == 100.0
    assert stats["max_ms"] == 300.0
    assert stats["n"] == 3
    # inclusive p95 interpolates near the top of a 3-sample set.
    assert stats["p95_ms"] == pytest.approx(290.0)

    # Single-sample edge: p95 falls back to that value (no crash).
    single = report.cycle_time_stats([_episode(cycle_time_ms=150.0)])
    assert single["p95_ms"] == pytest.approx(150.0)
    assert report.cycle_time_stats([])["n"] == 0


def test_sim_to_real_gap() -> None:
    full = {k: True for k in _ALL_STAGES}
    grasp_fail = {
        "scan": True,
        "grasp_gen": False,
        "plan_approach": None,
        "plan_grasp": None,
        "execute_pick": None,
        "execute_place": None,
    }
    sim = [_episode(stages=full, task_success=True), _episode(stages=full, task_success=True)]
    real = [
        _episode(stages=full, task_success=True),
        _episode(stages=grasp_fail, task_success=False),
    ]

    gap = report.sim_to_real_gap(sim, real)
    assert gap["sim_tsr"] == pytest.approx(1.0)
    assert gap["real_tsr"] == pytest.approx(0.5)
    assert gap["gap"] == pytest.approx(0.5)
    # grasp_gen: sim 1.0 vs real 0.5 -> delta 0.5
    assert gap["per_stage"]["grasp_gen"] == pytest.approx(0.5)
    assert gap["per_object"]["cup"] == pytest.approx(0.5)
