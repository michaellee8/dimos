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

"""Cache the expensive `height_cost_occupancy` call as .npy on disk.

The numba JIT in `height_cost_occupancy` warms up over several seconds on the
first call per process. Across many eval runs and multiprocessing workers, that
cost is unacceptable. We hash the pointcloud path + relevant config and cache
the resulting OccupancyGrid (grid + origin + resolution) to disk.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from dimos.mapping.pointclouds.occupancy import height_cost_occupancy
from dimos.mapping.pointclouds.util import read_pointcloud
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.nav_msgs.OccupancyGrid import OccupancyGrid
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.utils.data import get_data
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "dimos_path_eval"


def load_or_build_true_grid(
    pointcloud_name: str, cache_dir: Path = _DEFAULT_CACHE_DIR
) -> OccupancyGrid:
    """Load cached true occupancy grid for `pointcloud_name`, or build and cache it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha1(pointcloud_name.encode("utf-8")).hexdigest()[:16]
    grid_path = cache_dir / f"{cache_key}.npy"
    meta_path = cache_dir / f"{cache_key}.meta.json"

    if grid_path.exists() and meta_path.exists():
        logger.info("Loading cached true grid from %s", grid_path)
        meta = json.loads(meta_path.read_text())
        grid = np.load(grid_path)
        origin = Pose(meta["origin_x"], meta["origin_y"], 0.0)
        return OccupancyGrid(
            grid=grid,
            resolution=meta["resolution"],
            origin=origin,
            frame_id=meta["frame_id"],
        )

    logger.info("Building true grid from %s (this may take a few seconds)", pointcloud_name)
    cloud_path = get_data(pointcloud_name)
    data = read_pointcloud(cloud_path)
    cloud = PointCloud2.from_numpy(np.asarray(data.points), frame_id="")
    occupancy = height_cost_occupancy(cloud)

    np.save(grid_path, occupancy.grid)
    meta_path.write_text(
        json.dumps(
            {
                "pointcloud_name": pointcloud_name,
                "resolution": occupancy.resolution,
                "frame_id": occupancy.frame_id,
                "origin_x": occupancy.origin.position.x,
                "origin_y": occupancy.origin.position.y,
                "width": occupancy.width,
                "height": occupancy.height,
            },
            indent=2,
        )
    )
    logger.info("Cached true grid to %s", grid_path)
    return occupancy
