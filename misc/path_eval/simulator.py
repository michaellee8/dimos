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

"""Simulator that maintains a discovered occupancy grid revealed by raycast.

`RevealedMapSimulator` holds the true grid (ground truth) and a separate
discovered grid that starts all UNKNOWN. As the robot moves, `reveal_around`
casts rays into the true grid and copies values into the discovered grid up to
the first occupied cell — anything behind it stays UNKNOWN. The costmap fed to
the planner is computed from the discovered grid only.
"""

from __future__ import annotations

from collections.abc import Iterator
import math

import numpy as np
from scipy import ndimage

from dimos.mapping.occupancy.gradient import gradient, voronoi_gradient
from dimos.msgs.nav_msgs.OccupancyGrid import CostValues, OccupancyGrid
from misc.path_eval.config import EvalConfig


class RevealedMapSimulator:
    """Manage a discovered grid revealed from a true grid via raycasting."""

    def __init__(self, true_grid: OccupancyGrid, cfg: EvalConfig) -> None:
        self.true_grid = true_grid
        self.cfg = cfg
        self.discovered_grid = OccupancyGrid(
            grid=np.full((true_grid.height, true_grid.width), CostValues.UNKNOWN, dtype=np.int8),
            resolution=true_grid.resolution,
            origin=true_grid.origin,
            frame_id=true_grid.frame_id,
        )

        self._reveal_radius_cells = math.ceil(cfg.reveal_radius_m / true_grid.resolution)
        self._ray_endpoints = self._build_ray_endpoints(
            cfg.reveal_ray_count, self._reveal_radius_cells
        )

        self._true_clearance_m: np.ndarray | None = None

    @staticmethod
    def _build_ray_endpoints(n_rays: int, radius_cells: int) -> np.ndarray:
        """Precompute (dx, dy) cell offsets at the perimeter for each ray angle."""
        angles = np.linspace(0.0, 2 * math.pi, n_rays, endpoint=False)
        dx = np.round(np.cos(angles) * radius_cells).astype(np.int32)
        dy = np.round(np.sin(angles) * radius_cells).astype(np.int32)
        return np.stack([dx, dy], axis=1)

    def reveal_around(self, world_xy: tuple[float, float]) -> int:
        """Reveal cells via Bresenham raycast from world_xy. Returns # newly known."""
        center = self.true_grid.world_to_grid(world_xy)
        cx, cy = int(center.x), int(center.y)
        w, h = self.true_grid.width, self.true_grid.height
        true = self.true_grid.grid
        disc = self.discovered_grid.grid
        obstacle_threshold = self.cfg.obstacle_threshold
        newly_revealed = 0

        for dx, dy in self._ray_endpoints:
            tx = cx + int(dx)
            ty = cy + int(dy)
            for gx, gy in _bresenham(cx, cy, tx, ty):
                if not (0 <= gx < w and 0 <= gy < h):
                    break
                true_val = true[gy, gx]
                if disc[gy, gx] == CostValues.UNKNOWN and true_val != CostValues.UNKNOWN:
                    disc[gy, gx] = true_val
                    newly_revealed += 1
                if true_val != CostValues.UNKNOWN and true_val >= obstacle_threshold:
                    break

        return newly_revealed

    def current_costmap(self) -> OccupancyGrid:
        """Compute the costmap from the discovered grid per cfg.gradient_strategy."""
        if self.cfg.gradient_strategy == "voronoi":
            return voronoi_gradient(
                self.discovered_grid,
                obstacle_threshold=self.cfg.obstacle_threshold,
                max_distance=self.cfg.voronoi_max_distance,
            )
        return gradient(
            self.discovered_grid,
            obstacle_threshold=self.cfg.obstacle_threshold,
            max_distance=self.cfg.voronoi_max_distance,
        )

    def is_obstacle_step(self, prev_xy: tuple[float, float], next_xy: tuple[float, float]) -> bool:
        """True if the line from prev_xy to next_xy crosses a true-grid obstacle."""
        p = self.true_grid.world_to_grid(prev_xy)
        n = self.true_grid.world_to_grid(next_xy)
        w, h = self.true_grid.width, self.true_grid.height
        true = self.true_grid.grid
        obstacle_threshold = self.cfg.obstacle_threshold
        for gx, gy in _bresenham(int(p.x), int(p.y), int(n.x), int(n.y)):
            if not (0 <= gx < w and 0 <= gy < h):
                return True
            val = true[gy, gx]
            if val != CostValues.UNKNOWN and val >= obstacle_threshold:
                return True
        return False

    def cell_value(self, world_xy: tuple[float, float], grid: str = "true") -> int:
        target = self.true_grid if grid == "true" else self.discovered_grid
        v = target.world_to_grid(world_xy)
        gx, gy = int(v.x), int(v.y)
        if not (0 <= gx < target.width and 0 <= gy < target.height):
            return CostValues.UNKNOWN
        return int(target.grid[gy, gx])

    def clearance_at(self, world_xy: tuple[float, float]) -> float:
        """Distance from world_xy to the nearest true-grid obstacle (in meters)."""
        if self._true_clearance_m is None:
            obstacle_mask = self.true_grid.grid >= self.cfg.obstacle_threshold
            distance_cells: np.ndarray = ndimage.distance_transform_edt(~obstacle_mask)  # type: ignore[assignment]
            self._true_clearance_m = distance_cells * self.true_grid.resolution

        v = self.true_grid.world_to_grid(world_xy)
        gx, gy = int(v.x), int(v.y)
        if not (0 <= gx < self.true_grid.width and 0 <= gy < self.true_grid.height):
            return 0.0
        return float(self._true_clearance_m[gy, gx])


def _bresenham(x0: int, y0: int, x1: int, y1: int) -> Iterator[tuple[int, int]]:
    """Yield cells from (x0,y0) to (x1,y1) inclusive (Bresenham line)."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        yield x, y
        if x == x1 and y == y1:
            return
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
