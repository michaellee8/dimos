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

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Any

import numpy as np
from reactivex import interval
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.nav_msgs.Path import Path
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


@dataclass
class Scene:
    """Hand-crafted test world for the planner."""

    voxels: np.ndarray  # (N, 3) float32 world-frame coordinates of occupied voxel centers
    voxel_size: float
    start_position: tuple[float, float, float]
    start_orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    goal_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    goal_orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    name: str = "scene"


def _cell_centers(low: float, high: float, voxel_size: float) -> np.ndarray:
    """World-frame voxel-center positions for cells whose centers lie in [low, high].

    Generated via integer cell indices to avoid floating-point drift in
    ``np.arange(step=voxel_size)``, which would otherwise mis-bucket points
    at certain x and y values and produce missing stripes downstream.
    """
    i_min = math.floor(low / voxel_size)
    i_max = math.floor(high / voxel_size)
    return (np.arange(i_min, i_max + 1) + 0.5) * voxel_size


def _flat_floor(
    voxel_size: float,
    extent: tuple[float, float, float, float],
    z: float = 0.0,
    holes: list[tuple[float, float, float, float]] | None = None,
) -> np.ndarray:
    """Single-layer floor at height ``z`` over ``extent=(xmin, xmax, ymin, ymax)``,
    with rectangular ``holes`` cut out (e.g. footprints of objects sitting on it)."""
    xmin, xmax, ymin, ymax = extent
    xs = _cell_centers(xmin, xmax, voxel_size)
    ys = _cell_centers(ymin, ymax, voxel_size)
    z_center = (math.floor(z / voxel_size) + 0.5) * voxel_size
    fx, fy = np.meshgrid(xs, ys, indexing="ij")
    mask = np.ones(fx.shape, dtype=bool)
    for hx_min, hx_max, hy_min, hy_max in holes or []:
        mask &= ~((fx >= hx_min) & (fx <= hx_max) & (fy >= hy_min) & (fy <= hy_max))
    return np.stack([fx[mask], fy[mask], np.full(int(mask.sum()), z_center)], axis=1)


def _staircase(
    voxel_size: float,
    x_extent: tuple[float, float],
    y_start: float,
    n_steps: int,
    step_height: float,
    step_depth: float,
    base_z_voxel: int = 0,
) -> np.ndarray:
    """Staircase of ``n_steps`` ascending in +y starting at ``y_start``.

    Step ``k`` (1-indexed) has its tread top voxel at z-index
    ``base_z_voxel + k * step_height_voxels``, occupying a y-range of
    ``step_depth`` starting at ``y_start + (k-1) * step_depth``. For
    single-voxel-tall steps the tread corner doubles as the riser face;
    multi-voxel-tall steps also emit explicit riser voxels.
    """
    xmin, xmax = x_extent
    step_height_v = max(1, round(step_height / voxel_size))
    step_depth_v = max(1, round(step_depth / voxel_size))
    y_start_v = math.floor(y_start / voxel_size)
    x_min_v = math.floor(xmin / voxel_size)
    x_max_v = math.floor(xmax / voxel_size)
    half = 0.5 * voxel_size

    parts: list[np.ndarray] = []
    for k in range(1, n_steps + 1):
        z_top_v = base_z_voxel + k * step_height_v
        y_front_v = y_start_v + (k - 1) * step_depth_v
        y_back_v = y_start_v + k * step_depth_v - 1

        ix = np.arange(x_min_v, x_max_v + 1)
        iy = np.arange(y_front_v, y_back_v + 1)
        gx, gy = np.meshgrid(ix, iy, indexing="ij")
        tread = np.stack(
            [
                gx.ravel() * voxel_size + half,
                gy.ravel() * voxel_size + half,
                np.full(gx.size, z_top_v * voxel_size + half),
            ],
            axis=1,
        )
        parts.append(tread)

        if step_height_v > 1:
            iz = np.arange(z_top_v - step_height_v + 1, z_top_v)
            gx2, gz = np.meshgrid(ix, iz, indexing="ij")
            riser = np.stack(
                [
                    gx2.ravel() * voxel_size + half,
                    np.full(gx2.size, y_front_v * voxel_size + half),
                    gz.ravel() * voxel_size + half,
                ],
                axis=1,
            )
            parts.append(riser)

    return np.concatenate(parts, axis=0)


def _box_shell(
    voxel_size: float,
    bounds: tuple[float, float, float, float, float, float],
    include_bottom: bool = False,
) -> np.ndarray:
    """Hollow axis-aligned box: top face + 4 side walls. No interior.

    ``bounds=(xmin, xmax, ymin, ymax, zmin, zmax)``. ``include_bottom`` defaults
    False since boxes sitting on a floor occlude their bottom face from lidar.
    """
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    xs = _cell_centers(xmin, xmax, voxel_size)
    ys = _cell_centers(ymin, ymax, voxel_size)
    zs = _cell_centers(zmin, zmax, voxel_size)

    def _grid(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
        ga, gb, gc = np.meshgrid(a, b, c, indexing="ij")
        return np.stack([ga.ravel(), gb.ravel(), gc.ravel()], axis=1)

    faces = [
        _grid(xs, ys, zs[-1:]),  # top
        _grid(xs[:1], ys, zs),  # -x wall
        _grid(xs[-1:], ys, zs),  # +x wall
        _grid(xs, ys[:1], zs),  # -y wall
        _grid(xs, ys[-1:], zs),  # +y wall
    ]
    if include_bottom:
        faces.append(_grid(xs, ys, zs[:1]))
    return np.concatenate(faces, axis=0)


def default_scene(voxel_size: float = 0.1) -> Scene:
    """Lidar-realistic shell scene: floor + box obstacle + staircase.

    Robot starts at (-3, 0) on the floor and the goal is at (3, 0). A 1m square,
    0.3m-tall box sits at the origin. A staircase climbs from z=0 to z=2m in
    20 steps (each 0.1m tall, 0.2m deep) starting at the floor's -y edge and
    spanning over the floor in +y. This exercises the column walker's
    robot-height clearance check: columns under low steps see only the step
    (gap to floor too small); columns under high steps see both floor and step.
    Voxels are lidar-shells: only observable surfaces, no interiors or bottoms.
    """
    box = (-0.5, 0.5, -0.5, 0.5, 0.0, 0.3)
    floor = _flat_floor(
        voxel_size,
        extent=(-5.0, 5.0, -5.0, 5.0),
        holes=[(box[0], box[1], box[2], box[3])],
    )
    box_voxels = _box_shell(voxel_size, box)
    stairs = _staircase(
        voxel_size,
        x_extent=(-2.0, 2.0),
        y_start=-5.0,
        n_steps=20,
        step_height=0.1,
        step_depth=0.2,
    )
    voxels = np.concatenate([floor, box_voxels, stairs], axis=0).astype(np.float32)

    return Scene(
        voxels=voxels,
        voxel_size=voxel_size,
        start_position=(-3.0, 0.0, 0.5),
        goal_position=(3.0, 0.0, 0.5),
        name="default_floor_box_staircase",
    )


class EvaluatorConfig(ModuleConfig):
    world_frame: str = "world"
    body_frame: str = "body"
    publish_period: float = 5.0  # s — republish all messages this often


class Evaluator(Module):
    """Publishes a synthetic scene and evaluates the planner's returned path.

    Outputs the three inputs a planner expects (global_map, odometry, goal);
    subscribes to the planner's path output and logs basic metrics.
    """

    config: EvaluatorConfig

    global_map: Out[PointCloud2]
    odometry: Out[Odometry]
    goal: Out[PoseStamped]
    path: In[Path]

    def __init__(self, scene: Scene | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._scene: Scene = scene if scene is not None else default_scene()
        self._lock = threading.Lock()

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(Disposable(self.path.subscribe(self._on_path)))
        self.register_disposable(interval(self.config.publish_period).subscribe(self._publish_all))
        logger.info("Evaluator started with scene=%s", self._scene.name)

    @rpc
    def stop(self) -> None:
        super().stop()

    def _publish_all(self, _: Any) -> None:
        self._publish_map()
        self._publish_odom()
        self._publish_goal()

    def _publish_map(self) -> None:
        cloud = PointCloud2.from_numpy(
            points=self._scene.voxels,
            frame_id=self.config.world_frame,
            timestamp=time.time(),
        )
        self.global_map.publish(cloud)

    def _publish_odom(self) -> None:
        x, y, z = self._scene.start_position
        qx, qy, qz, qw = self._scene.start_orientation
        odom = Odometry(
            ts=time.time(),
            frame_id=self.config.world_frame,
            child_frame_id=self.config.body_frame,
            pose=Pose(position=Vector3(x, y, z), orientation=Quaternion(qx, qy, qz, qw)),
        )
        self.odometry.publish(odom)

    def _publish_goal(self) -> None:
        x, y, z = self._scene.goal_position
        qx, qy, qz, qw = self._scene.goal_orientation
        goal = PoseStamped(
            ts=time.time(),
            frame_id=self.config.world_frame,
            position=Vector3(x, y, z),
            orientation=Quaternion(qx, qy, qz, qw),
        )
        self.goal.publish(goal)
        logger.info("Evaluator published goal at %s", self._scene.goal_position)

    def _on_path(self, path: Path) -> None:
        n = len(path.poses)
        if n == 0:
            logger.warning("Evaluator received empty path")
            return
        total_xy = 0.0
        total_z = 0.0
        for a, b in zip(path.poses, path.poses[1:], strict=False):
            dx = b.position.x - a.position.x
            dy = b.position.y - a.position.y
            dz = b.position.z - a.position.z
            total_xy += (dx * dx + dy * dy) ** 0.5
            total_z += abs(dz)
        logger.info(
            "Evaluator received path: %d poses, xy_len=%.2fm, z_traveled=%.2fm",
            n,
            total_xy,
            total_z,
        )
