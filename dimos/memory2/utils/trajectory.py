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

from collections.abc import Iterable
from typing import Any

import numpy as np

from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped


class PoseTrajectory:
    """Timestamped poses with interpolated lookup at arbitrary times.

    Build from a pose stream, then call :meth:`at` for the pose at any time.
    Interpolation LERPs position and NLERPs orientation (xyzw) between the two
    samples bracketing the query, clamping at the endpoints. Use it to stamp a
    pose onto sensor frames whose timestamps don't line up with the pose stream
    -- e.g. lidar clouds against a separate odometry stream.
    """

    def __init__(self, times: np.ndarray, positions: np.ndarray, quats: np.ndarray) -> None:
        if len(times) == 0:
            raise ValueError("PoseTrajectory needs at least one pose")
        self._t = np.asarray(times, dtype=float)
        self._pos = np.asarray(positions, dtype=float)
        self._quat = np.asarray(quats, dtype=float)

    @classmethod
    def from_poses(cls, poses: Iterable[tuple[float, Any]]) -> PoseTrajectory:
        """Build from ``(ts, pose)`` pairs; ``pose`` needs ``.position``/``.orientation``."""
        times: list[float] = []
        pos: list[list[float]] = []
        quat: list[list[float]] = []
        for ts, pose in poses:
            p, o = pose.position, pose.orientation
            times.append(ts)
            pos.append([p.x, p.y, p.z])
            quat.append([o.x, o.y, o.z, o.w])
        return cls(np.array(times), np.array(pos), np.array(quat))

    def at(self, ts: float, frame_id: str = "") -> PoseStamped:
        """Interpolated pose at ``ts`` (clamped to the trajectory's time range)."""
        i = int(np.clip(np.searchsorted(self._t, ts), 1, len(self._t) - 1))
        t0, t1 = self._t[i - 1], self._t[i]
        f = 0.0 if t1 == t0 else float(np.clip((ts - t0) / (t1 - t0), 0.0, 1.0))
        p = self._pos[i - 1] * (1 - f) + self._pos[i] * f
        q0, q1 = self._quat[i - 1], self._quat[i].copy()
        # NLERP along the shorter arc: flip a sample into the same hemisphere.
        if float(q0 @ q1) < 0:
            q1 = -q1
        q = q0 * (1 - f) + q1 * f
        q /= np.linalg.norm(q)
        return PoseStamped(ts=ts, frame_id=frame_id, position=p.tolist(), orientation=q.tolist())
