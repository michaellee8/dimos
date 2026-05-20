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

"""Sample reproducible (start, goal) trial pairs with oracle path lengths."""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from dimos.mapping.occupancy.gradient import voronoi_gradient
from dimos.msgs.nav_msgs.OccupancyGrid import CostValues, OccupancyGrid
from dimos.navigation.replanning_a_star.min_cost_astar import min_cost_astar
from dimos.utils.logging_config import setup_logger
from misc.path_eval.config import EvalConfig
from misc.path_eval.trial import TrialSpec

logger = setup_logger()

# Cap how hard we look for valid pairs before giving up. Misses indicate the
# map is too small or `min_separation_m`/`min_clearance_m` are too restrictive.
_MAX_SAMPLE_ATTEMPTS_PER_TRIAL = 200


def _path_length(path) -> float:  # type: ignore[no-untyped-def]
    total = 0.0
    prev = path.poses[0].position
    for pose in path.poses[1:]:
        total += math.hypot(pose.position.x - prev.x, pose.position.y - prev.y)
        prev = pose.position
    return total


def sample_trials(true_grid: OccupancyGrid, cfg: EvalConfig) -> list[TrialSpec]:
    """Produce a reproducible list of N trials with oracle path lengths."""
    rng = np.random.default_rng(cfg.run_seed)

    # Spawnable pool: cells that are FREE in the true grid AND at least
    # min_clearance_m from the nearest obstacle. This avoids spawning robots
    # right next to a desk leg.
    obstacle_mask = true_grid.grid >= cfg.obstacle_threshold
    distance_cells: np.ndarray = ndimage.distance_transform_edt(~obstacle_mask)  # type: ignore[assignment]
    clearance_m = distance_cells * true_grid.resolution
    spawnable_mask = (true_grid.grid == CostValues.FREE) & (clearance_m >= cfg.min_clearance_m)
    spawnable_idx = np.argwhere(spawnable_mask)  # (N, 2) of (row, col)
    if len(spawnable_idx) == 0:
        raise RuntimeError(
            f"No spawnable cells with clearance >= {cfg.min_clearance_m} m. "
            "Decrease min_clearance_m or check the true grid."
        )
    logger.info(
        "Spawnable pool: %d cells (%.1f%% of grid)",
        len(spawnable_idx),
        100 * len(spawnable_idx) / true_grid.grid.size,
    )

    # Build true-grid costmap once for oracle pathfinding.
    oracle_costmap = voronoi_gradient(
        true_grid,
        obstacle_threshold=cfg.obstacle_threshold,
        max_distance=cfg.voronoi_max_distance,
    )

    resolution = true_grid.resolution
    ox = true_grid.origin.position.x
    oy = true_grid.origin.position.y

    def cell_to_world(cell: np.ndarray) -> tuple[float, float]:
        row, col = int(cell[0]), int(cell[1])
        return (ox + col * resolution, oy + row * resolution)

    trials: list[TrialSpec] = []
    attempts = 0
    while len(trials) < cfg.n_trials and attempts < cfg.n_trials * _MAX_SAMPLE_ATTEMPTS_PER_TRIAL:
        attempts += 1
        start_idx, goal_idx = rng.choice(len(spawnable_idx), size=2, replace=False)
        start_world = cell_to_world(spawnable_idx[start_idx])
        goal_world = cell_to_world(spawnable_idx[goal_idx])
        if (
            math.hypot(start_world[0] - goal_world[0], start_world[1] - goal_world[1])
            < cfg.min_separation_m
        ):
            continue
        oracle_path = min_cost_astar(
            oracle_costmap,
            goal_world,
            start_world,
            cost_threshold=cfg.obstacle_threshold,
            unknown_penalty=0.99,  # not relevant; true grid has no unknowns
            use_cpp=True,
        )
        if oracle_path is None:
            continue
        trials.append(
            TrialSpec(
                trial_id=len(trials),
                start_world=start_world,
                goal_world=goal_world,
                oracle_path_length=_path_length(oracle_path),
            )
        )

    if len(trials) < cfg.n_trials:
        raise RuntimeError(
            f"Only sampled {len(trials)} reachable trials in "
            f"{attempts} attempts. Loosen separation/clearance or check the map."
        )
    logger.info("Sampled %d trials in %d attempts", len(trials), attempts)
    return trials
