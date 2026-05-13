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

"""Binary-driven raycasting-clearing test.

Verifies the user-required default ``Grid/RayTracing=true`` behavior by
checking that the OctoMap published by the real rtab_map binary contains
obstacles at the actual obstacle distance, AND does NOT contain occupied
voxels in the straight-line region between the sensor and the obstacle —
those would have been "phantom" cells if raycasting weren't actually
clearing the ray path.
"""

from __future__ import annotations

import numpy as np
import pytest

from dimos.navigation.nav_stack.modules.rtab_map.tests.conftest import (
    RtabHarness,
    identity_quat,
)

pytestmark = [pytest.mark.self_hosted]

_OBSTACLE_X = 2.0


def _corridor_scan() -> np.ndarray:
    """Body-frame scan of a corridor with one wall obstacle at +x=_OBSTACLE_X.

    Dense enough that rtabmap's keyframe selector + ICP have enough features
    to work with. Floor at z=-0.5, side walls at y=±1.5, obstacle wall slice
    in front at z in [0.1, 0.9].
    """
    # Front-facing obstacle wall.
    obs_y = np.linspace(-0.4, 0.4, 9)
    obs_z = np.linspace(0.1, 0.9, 9)
    yy_o, zz_o = np.meshgrid(obs_y, obs_z)
    obstacle = np.stack([np.full(yy_o.size, _OBSTACLE_X), yy_o.ravel(), zz_o.ravel()], axis=1)
    # Dense floor along the corridor.
    floor_x = np.linspace(0.2, _OBSTACLE_X + 0.5, 24)
    floor_y = np.linspace(-1.4, 1.4, 12)
    xx_f, yy_f = np.meshgrid(floor_x, floor_y)
    floor = np.stack([xx_f.ravel(), yy_f.ravel(), -0.5 * np.ones(xx_f.size)], axis=1)
    # Side walls so rtabmap's ICP sees consistent features when the robot
    # nudges along -x between frames.
    wall_x = np.linspace(0.0, _OBSTACLE_X + 0.5, 16)
    wall_z = np.linspace(0.0, 1.2, 8)
    xx_w, zz_w = np.meshgrid(wall_x, wall_z)
    left = np.stack([xx_w.ravel(), np.full(xx_w.size, 1.5), zz_w.ravel()], axis=1)
    right = np.stack([xx_w.ravel(), np.full(xx_w.size, -1.5), zz_w.ravel()], axis=1)
    cloud = np.concatenate([obstacle, floor, left, right]).astype(np.float32)
    return np.column_stack([cloud, np.ones(len(cloud), dtype=np.float32)])


def test_raycast_clears_cells_between_sensor_and_obstacle(
    rtab_harness: RtabHarness,
) -> None:
    """Drive the binary with a stable corridor scene that has a single wall
    obstacle at x=2.0. With ``Grid/RayTracing=true``, the OctoMap must
    contain occupied voxels at x≈2.0 (the obstacle) AND must NOT contain
    occupied voxels along the centerline y≈0 between the sensor and the
    obstacle (those rays passed through empty space and should be cleared).
    """
    scan = _corridor_scan()
    # Small backward nudges so rtabmap admits each frame as a keyframe
    # without putting the obstacle out of Grid/RangeMax (default 8 m).
    for i in range(14):
        ts = float(i) * 0.3
        rtab_harness.publish_odom(np.array([-0.1 * i, 0.0, 0.0]), identity_quat(), ts)
        rtab_harness.publish_scan(scan, ts)
        rtab_harness.drain(seconds=0.15)

    rtab_harness.drain(seconds=3.0)

    non_empty = [msg for msg in rtab_harness.octomap.messages if len(msg.as_numpy()[0]) > 0]
    assert non_empty, "expected at least one non-empty octomap message"
    pts, _ = non_empty[-1].as_numpy()

    # The obstacle wall at x≈_OBSTACLE_X should be in the octomap.
    obstacle_voxels = np.sum(
        (np.abs(pts[:, 0] - _OBSTACLE_X) < 0.25) & (np.abs(pts[:, 1]) < 0.6) & (pts[:, 2] > 0.0)
    )
    assert obstacle_voxels > 0, (
        f"expected wall voxels near x={_OBSTACLE_X} in the octomap, got "
        f"pts={pts.shape}; x range [{pts[:, 0].min():.2f}, {pts[:, 0].max():.2f}]"
    )

    # No occupied voxels should sit between the sensor (around x=-1.3 by
    # final frame) and the obstacle along the y=0 ray — the rays from
    # sensor → obstacle pass through here every frame and ray tracing
    # should have cleared them.
    ray_voxels = np.sum(
        (pts[:, 0] > 0.5)
        & (pts[:, 0] < _OBSTACLE_X - 0.25)
        & (np.abs(pts[:, 1]) < 0.3)
        & (pts[:, 2] > 0.05)
        & (pts[:, 2] < 0.9)
    )
    assert ray_voxels == 0, (
        f"expected the ray path between sensor and obstacle to be cleared by "
        f"raycasting; found {ray_voxels} stray occupied voxels in the ray zone"
    )
