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

"""Blueprint + entrypoint for the path-planner evaluator.

Wires the Evaluator and StraightLinePlanner together and bridges all
streams to rerun. Run with::

    python -m dimos.navigation.nav_stack.evaluator.main
"""

from __future__ import annotations

from typing import Any

from dimos.core.coordination.blueprints import Blueprint, autoconnect
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.navigation.nav_stack.evaluator.evaluator import Evaluator
from dimos.navigation.nav_stack.modules.mls_planner.mls_planner import MLSPlanner
from dimos.visualization.rerun.bridge import RerunBridgeModule

_POSE_MARKER_RADIUS = 0.4


def _render_start_pose(msg: Any) -> Any:
    import rerun as rr

    return rr.Points3D(
        positions=[[msg.x, msg.y, msg.z]],
        colors=[[0, 255, 0]],  # green
        radii=[_POSE_MARKER_RADIUS],
    )


def _render_goal_pose(msg: Any) -> Any:
    import rerun as rr

    return rr.Points3D(
        positions=[[msg.x, msg.y, msg.z]],
        colors=[[255, 0, 0]],  # red
        radii=[_POSE_MARKER_RADIUS],
    )


def _render_global_map(msg: Any) -> Any:
    return msg.to_rerun(voxel_size=0.03)


def _render_surface_map(msg: Any) -> Any:
    return msg.to_rerun(mode="spheres", voxel_size=0.05, colors=[128, 0, 128])  # purple


# raise the path and way points out of the surface
_GRAPH_Z_LIFT = 0.1


def _render_waypoints(msg: Any) -> Any:
    import rerun as rr

    pts, _ = msg.as_numpy()
    if pts is None or len(pts) == 0:
        return rr.Points3D([])
    pts = pts.copy()
    pts[:, 2] += _GRAPH_Z_LIFT
    return rr.Points3D(positions=pts, colors=[[75, 156, 211]], radii=[0.15])  # Carolina Blue


def _render_waypoint_edges(msg: Any) -> Any:
    return msg.to_rerun(z_offset=_GRAPH_Z_LIFT, radii=0.04)


def create_evaluator_blueprint() -> Blueprint:
    return autoconnect(
        Evaluator.blueprint(),
        MLSPlanner.blueprint(),
        RerunBridgeModule.blueprint(
            visual_override={
                "world/start_pose": _render_start_pose,
                "world/goal_pose": _render_goal_pose,
                "world/global_map": _render_global_map,
                "world/surface_map": _render_surface_map,
                "world/waypoints": _render_waypoints,
                "world/waypoint_edges": _render_waypoint_edges,
            }
        ),
    )


if __name__ == "__main__":
    ModuleCoordinator.build(create_evaluator_blueprint()).loop()
