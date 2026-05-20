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

"""Smoke tests for the path-planning eval simulator and trial loop."""

from __future__ import annotations

import numpy as np
import pytest

from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.nav_msgs.OccupancyGrid import CostValues, OccupancyGrid
from misc.path_eval.config import EvalConfig
from misc.path_eval.simulator import RevealedMapSimulator
from misc.path_eval.trial import TrialSpec, run_trial


def _make_true_grid(width: int, height: int, resolution: float = 0.05) -> OccupancyGrid:
    """Free everywhere except a 1-cell border of obstacles."""
    grid = np.zeros((height, width), dtype=np.int8)
    grid[0, :] = CostValues.OCCUPIED
    grid[-1, :] = CostValues.OCCUPIED
    grid[:, 0] = CostValues.OCCUPIED
    grid[:, -1] = CostValues.OCCUPIED
    return OccupancyGrid(grid=grid, resolution=resolution, origin=Pose())


def _make_wall_grid(width: int = 20, height: int = 20) -> OccupancyGrid:
    """20x20 grid with bordering obstacles and a vertical wall with a small gap.

    The wall is column 10, rows 1..15 (a gap at rows 16..18 lets the planner
    detour around the bottom).
    """
    g = _make_true_grid(width, height)
    g.grid[1:16, 10] = CostValues.OCCUPIED
    return g


def test_reveal_grows_known_cells():
    true = _make_true_grid(40, 40)
    cfg = EvalConfig(reveal_radius_m=0.5, reveal_ray_count=180)
    sim = RevealedMapSimulator(true, cfg)
    assert int(np.sum(sim.discovered_grid.grid != CostValues.UNKNOWN)) == 0

    revealed = sim.reveal_around((1.0, 1.0))
    after = int(np.sum(sim.discovered_grid.grid != CostValues.UNKNOWN))
    assert revealed > 0
    assert after == revealed

    # Revealing the same spot again should yield zero new cells.
    revealed_again = sim.reveal_around((1.0, 1.0))
    assert revealed_again == 0

    # Revealing further away should yield more cells.
    revealed_far = sim.reveal_around((1.5, 1.0))
    assert revealed_far > 0


def test_raycast_does_not_see_through_walls():
    """A vertical wall at x=col 10 should block rays cast from the left side."""
    true = _make_wall_grid(width=20, height=20)
    cfg = EvalConfig(
        reveal_radius_m=2.0, reveal_ray_count=360
    )  # huge radius -> would reach far side
    sim = RevealedMapSimulator(true, cfg)

    # Stand at world (0.25, 0.4) i.e. grid (5, 8). Wall is at column 10.
    sim.reveal_around((0.25, 0.4))

    disc = sim.discovered_grid.grid
    # On the near side (column 9) most cells in the y-band should be known.
    near_known = int(np.sum(disc[5:11, 9] != CostValues.UNKNOWN))
    assert near_known > 0, "cells immediately in front of wall should be revealed"

    # On the far side of the wall (column 11), in the wall's y-band (rows 1..15),
    # cells must remain unknown — rays would pass through column 10's obstacle first.
    far_known = int(np.sum(disc[1:16, 11] != CostValues.UNKNOWN))
    assert far_known == 0, f"cells behind the wall must stay unknown (got {far_known} known)"


def test_is_obstacle_step_detects_wall_crossing():
    true = _make_wall_grid(width=20, height=20)
    cfg = EvalConfig()
    sim = RevealedMapSimulator(true, cfg)

    # World coords: cell c -> world c * resolution = c * 0.05.
    # Wall is at column 10 (world x=0.5).
    crossing = sim.is_obstacle_step((0.4, 0.4), (0.6, 0.4))
    assert crossing is True

    not_crossing = sim.is_obstacle_step((0.4, 0.4), (0.45, 0.4))
    assert not_crossing is False


def test_current_costmap_matches_discovered_grid_shape():
    true = _make_true_grid(20, 20)
    cfg = EvalConfig(gradient_strategy="gradient", voronoi_max_distance=0.5)
    sim = RevealedMapSimulator(true, cfg)
    sim.reveal_around((0.5, 0.5))

    costmap = sim.current_costmap()
    assert costmap.width == true.width
    assert costmap.height == true.height
    assert costmap.resolution == true.resolution


@pytest.mark.parametrize("strategy", ["gradient", "voronoi"])
def test_trial_runs_on_synthetic_grid(strategy):
    """20x20 grid, robot detours around a wall to reach goal."""
    true = _make_wall_grid(width=20, height=20)
    # Generous tolerances so test isn't flaky against discretization.
    cfg = EvalConfig(
        run_seed=0,
        n_trials=1,
        reveal_radius_m=2.0,
        reveal_ray_count=180,
        step_m=0.1,
        goal_tolerance_m=0.15,
        max_distance_m=10.0,
        max_replans_per_trial=50,
        unknown_penalty=0.5,  # encourage going through unknowns
        gradient_strategy=strategy,
        voronoi_max_distance=0.3,
        robot_width=0.0,
    )
    sim = RevealedMapSimulator(true, cfg)

    # Start at left of wall, goal at right of wall. Both inside the border.
    start_world = (0.15, 0.45)  # grid (3, 9)
    goal_world = (0.8, 0.45)  # grid (16, 9)
    spec = TrialSpec(
        trial_id=0,
        start_world=start_world,
        goal_world=goal_world,
        oracle_path_length=0.85,  # ~0.65 direct + ~0.2 detour around the wall
    )

    result = run_trial(spec, sim, cfg)
    assert result.success, f"trial failed: {result.failure_reason} (result={result})"
    assert result.distance_traveled > 0
    # Direct line is 0.65m, but planner must detour around the wall.
    assert result.distance_traveled >= 0.65
