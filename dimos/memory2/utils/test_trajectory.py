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

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from dimos.memory2.utils.trajectory import PoseTrajectory
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped

_IDENTITY = [0.0, 0.0, 0.0, 1.0]


def _straight_line() -> PoseTrajectory:
    """x: 0 -> 10 over t: 0 -> 10, identity rotation throughout."""
    return PoseTrajectory(
        np.array([0.0, 10.0]),
        np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]),
        np.array([_IDENTITY, _IDENTITY]),
    )


def test_lerp_midpoint() -> None:
    ps = _straight_line().at(5.0)
    assert isinstance(ps, PoseStamped)
    assert ps.position.x == pytest.approx(5.0)
    assert ps.ts == pytest.approx(5.0)


def test_clamps_to_endpoints() -> None:
    traj = _straight_line()
    assert traj.at(-3.0).position.x == pytest.approx(0.0)
    assert traj.at(99.0).position.x == pytest.approx(10.0)


def test_nlerp_rotates_between_samples() -> None:
    # 0 -> 90deg yaw; the halfway pose should sit between, as a unit quaternion.
    q1 = Rotation.from_euler("z", 90, degrees=True).as_quat()  # xyzw
    traj = PoseTrajectory(
        np.array([0.0, 1.0]),
        np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        np.array([_IDENTITY, q1]),
    )
    o = traj.at(0.5).orientation
    q = np.array([o.x, o.y, o.z, o.w])
    assert np.linalg.norm(q) == pytest.approx(1.0)
    yaw = Rotation.from_quat(q).as_euler("zyx", degrees=True)[0]
    assert 0.0 < yaw < 90.0


def test_hemisphere_flip_avoids_degenerate_blend() -> None:
    # q and -q are the same rotation; a naive LERP halfway cancels to zero.
    # The hemisphere flip must keep the result a valid unit quaternion.
    traj = PoseTrajectory(
        np.array([0.0, 1.0]),
        np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
        np.array([_IDENTITY, [0.0, 0.0, 0.0, -1.0]]),
    )
    o = traj.at(0.5).orientation
    q = np.array([o.x, o.y, o.z, o.w])
    assert np.linalg.norm(q) == pytest.approx(1.0)


def test_from_poses_interpolates() -> None:
    traj = PoseTrajectory.from_poses(
        [
            (0.0, PoseStamped(ts=0.0, position=(0.0, 0.0, 0.0), orientation=_IDENTITY)),
            (2.0, PoseStamped(ts=2.0, position=(2.0, 4.0, 0.0), orientation=_IDENTITY)),
        ]
    )
    ps = traj.at(1.0)
    assert ps.position.x == pytest.approx(1.0)
    assert ps.position.y == pytest.approx(2.0)


def test_frame_id_passthrough() -> None:
    assert _straight_line().at(5.0, frame_id="world").frame_id == "world"


def test_empty_raises() -> None:
    with pytest.raises(ValueError):
        PoseTrajectory(np.array([]), np.array([]).reshape(0, 3), np.array([]).reshape(0, 4))
