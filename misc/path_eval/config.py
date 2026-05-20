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

"""Configuration for path-planning eval framework."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Literal

GradientStrategy = Literal["voronoi", "gradient"]


@dataclass
class EvalConfig:
    """Configuration for one eval run.

    Note on unknown_penalty: 1.0 makes unknown cells strictly untraversable, because
    `min_cost_astar` computes `cell_cost = cost_threshold * unknown_penalty` (= 100)
    and rejects cells with `cell_cost >= cost_threshold`. Use 0.99 if you want
    unknowns traversable but very expensive.
    """

    # Trial set
    run_seed: int = 42
    n_trials: int = 30
    pointcloud_name: str = "big_office.ply"

    # Sampling
    min_separation_m: float = 5.0
    min_clearance_m: float = 0.3

    # Sensor / reveal
    reveal_radius_m: float = 5.0
    reveal_ray_count: int = 360

    # Robot stepping
    step_m: float = 0.1
    goal_tolerance_m: float = 0.3
    max_distance_m: float = 100.0
    max_replans_per_trial: int = 100

    # Planner
    unknown_penalty: float = 0.8
    obstacle_threshold: int = 100
    gradient_strategy: GradientStrategy = "voronoi"
    voronoi_max_distance: float = 1.5
    robot_width: float = 0.3

    # Composite score weights (per metric, sum doesn't need to be 1)
    score_weights: dict[str, float] = field(
        default_factory=lambda: {
            "success_rate": 1.0,
            "path_efficiency": 0.4,
            "clearance": 0.4,
            "low_thrash": 0.2,
        }
    )

    def dump(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> EvalConfig:
        data = json.loads(path.read_text())
        return cls(**data)
