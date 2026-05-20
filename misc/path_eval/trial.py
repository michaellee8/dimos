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

"""Run a single eval trial: plan, walk, reveal, replan, score."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time
from typing import Any

from dimos.mapping.occupancy.gradient import gradient
from dimos.msgs.nav_msgs.OccupancyGrid import CostValues
from dimos.msgs.nav_msgs.Path import Path
from dimos.navigation.replanning_a_star.min_cost_astar import min_cost_astar
from misc.path_eval.config import EvalConfig
from misc.path_eval.simulator import RevealedMapSimulator


@dataclass
class TrialSpec:
    trial_id: int
    start_world: tuple[float, float]
    goal_world: tuple[float, float]
    oracle_path_length: float


@dataclass
class TrialResult:
    trial_id: int
    success: bool
    failure_reason: str | None
    # Path
    distance_traveled: float
    oracle_path_length: float
    path_efficiency: float  # oracle / distance, in [0, 1] for successful runs
    num_steps: int
    # Safety (against true grid)
    min_obstacle_clearance: float
    mean_obstacle_clearance: float
    # Risk taking
    unknown_steps: int
    unknown_steps_that_were_free: int
    # Planning
    num_replans: int
    collision_avoided_count: int
    total_planning_time_ms: float
    # Wall clock
    wall_time_ms: float

    @property
    def unknown_fraction_traversed(self) -> float:
        return self.unknown_steps / self.num_steps if self.num_steps > 0 else 0.0

    @property
    def unknown_traversal_payoff(self) -> float:
        if self.unknown_steps == 0:
            return 0.0
        return self.unknown_steps_that_were_free / self.unknown_steps


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class _State:
    """Mutable bookkeeping for a single trial run."""

    wall_t0: float
    robot: tuple[float, float]
    distance_traveled: float = 0.0
    num_replans: int = 0
    collision_avoided_count: int = 0
    total_planning_time_ms: float = 0.0
    num_steps: int = 0
    min_obstacle_clearance: float = math.inf
    clearance_sum: float = 0.0
    unknown_steps: int = 0
    unknown_steps_that_were_free: int = 0

    def record_position(self, sim: RevealedMapSimulator) -> None:
        clearance = sim.clearance_at(self.robot)
        self.num_steps += 1
        self.clearance_sum += clearance
        if clearance < self.min_obstacle_clearance:
            self.min_obstacle_clearance = clearance

    def finalize(
        self, spec: TrialSpec, *, success: bool, failure_reason: str | None
    ) -> TrialResult:
        mean_clearance = self.clearance_sum / self.num_steps if self.num_steps else 0.0
        min_clearance = (
            self.min_obstacle_clearance if math.isfinite(self.min_obstacle_clearance) else 0.0
        )
        path_efficiency = (
            spec.oracle_path_length / self.distance_traveled
            if success and self.distance_traveled > 0
            else 0.0
        )
        return TrialResult(
            trial_id=spec.trial_id,
            success=success,
            failure_reason=failure_reason,
            distance_traveled=self.distance_traveled,
            oracle_path_length=spec.oracle_path_length,
            path_efficiency=path_efficiency,
            num_steps=self.num_steps,
            min_obstacle_clearance=min_clearance,
            mean_obstacle_clearance=mean_clearance,
            unknown_steps=self.unknown_steps,
            unknown_steps_that_were_free=self.unknown_steps_that_were_free,
            num_replans=self.num_replans,
            collision_avoided_count=self.collision_avoided_count,
            total_planning_time_ms=self.total_planning_time_ms,
            wall_time_ms=(time.perf_counter() - self.wall_t0) * 1000.0,
        )


def _plan(
    sim: RevealedMapSimulator,
    robot: tuple[float, float],
    goal: tuple[float, float],
    cfg: EvalConfig,
) -> Path | None:
    """Plan with the configured strategy; fall back to gradient if voronoi fails."""
    costmap = sim.current_costmap()
    path = min_cost_astar(
        costmap,
        goal,
        robot,
        cost_threshold=cfg.obstacle_threshold,
        unknown_penalty=cfg.unknown_penalty,
        use_cpp=True,
    )
    if path is not None:
        return path
    if cfg.gradient_strategy != "voronoi":
        return None
    fallback = gradient(
        sim.discovered_grid,
        obstacle_threshold=cfg.obstacle_threshold,
        max_distance=cfg.voronoi_max_distance,
    )
    return min_cost_astar(
        fallback,
        goal,
        robot,
        cost_threshold=cfg.obstacle_threshold,
        unknown_penalty=cfg.unknown_penalty,
        use_cpp=True,
    )


def run_trial(spec: TrialSpec, sim: RevealedMapSimulator, cfg: EvalConfig) -> TrialResult:
    state = _State(wall_t0=time.perf_counter(), robot=spec.start_world)
    goal = spec.goal_world

    sim.reveal_around(state.robot)
    state.record_position(sim)

    while True:
        if _dist(state.robot, goal) <= cfg.goal_tolerance_m:
            return state.finalize(spec, success=True, failure_reason=None)
        if state.distance_traveled >= cfg.max_distance_m:
            return state.finalize(spec, success=False, failure_reason="max_distance")
        if state.num_replans > cfg.max_replans_per_trial:
            return state.finalize(spec, success=False, failure_reason="too_many_replans")

        plan_t0 = time.perf_counter()
        path = _plan(sim, state.robot, goal, cfg)
        state.total_planning_time_ms += (time.perf_counter() - plan_t0) * 1000.0
        if path is None:
            return state.finalize(spec, success=False, failure_reason="no_path")

        # Snapshot discovered-grid values for path cells at planning time.
        # Used to attribute risk-taking metrics to the planner's choice, not to
        # the post-step reveal that may have already lit up the next cell.
        was_unknown_at_plan = [
            sim.cell_value((p.position.x, p.position.y), grid="discovered") == CostValues.UNKNOWN
            for p in path.poses
        ]

        for i, pose in enumerate(path.poses[1:], start=1):
            next_xy = (pose.position.x, pose.position.y)
            if sim.is_obstacle_step(state.robot, next_xy):
                sim.reveal_around(state.robot)
                state.collision_avoided_count += 1
                break

            if was_unknown_at_plan[i]:
                state.unknown_steps += 1
                if sim.cell_value(next_xy, grid="true") == CostValues.FREE:
                    state.unknown_steps_that_were_free += 1

            state.distance_traveled += _dist(state.robot, next_xy)
            state.robot = next_xy
            sim.reveal_around(state.robot)
            state.record_position(sim)

            if _dist(state.robot, goal) <= cfg.goal_tolerance_m:
                return state.finalize(spec, success=True, failure_reason=None)
            if state.distance_traveled >= cfg.max_distance_m:
                break

        state.num_replans += 1


def trial_result_to_dict(result: TrialResult) -> dict[str, Any]:
    return asdict(result)
