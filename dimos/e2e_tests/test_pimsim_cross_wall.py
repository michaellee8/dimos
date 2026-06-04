# Copyright 2025-2026 Dimensional Inc.
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

"""Cross-wall routing on the pimsim (Babylon) simulator.

The pimsim analogue of ``test_cross_wall_planning_simple`` / the dimsim
``test_dimsim_path_replaning``: wire the nav stack onto the browser-physics box
sim, drop a wall (with a doorway) between the robot and a goal, publish the
goal, and assert the planner routes through the gap and the box reaches it.

Wiring (everything else is autoconnected by stream name):
- ``BabylonSceneViewerModule`` integrates ``/nav_cmd_vel`` and publishes
  ``/odom`` (PoseStamped); the rust ``SceneLidarModule`` publishes ``/lidar``.
- ``PoseStampedToOdometry`` republishes ``/odom`` -> ``/odometry`` (Odometry),
  which ``TerrainAnalysis`` + the planners consume.
- ``/lidar`` is bridged to the nav stack's ``registered_scan`` input.
- the goal is a ``PointStamped`` on ``/clicked_point``.

Platform: the nav-stack planners (``TerrainAnalysis``, ``LocalPlanner``) are
Nix-built native binaries, so like the other cross-wall tests this is
``skipif_macos`` + ``self_hosted`` — it runs on a Linux runner, not macOS.
"""

from __future__ import annotations

from pathlib import Path
import time

import lcm as lcmlib
import pytest

pytest.importorskip("gtsam")

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.transport import LCMTransport
from dimos.experimental.pimsim.blueprints.babylon_smoketest import build_babylon_sim
from dimos.experimental.pimsim.client import PimSimClient
from dimos.experimental.pimsim.headless import HeadlessBrowser
from dimos.experimental.pimsim.odometry_adapter import OdomTfBroadcaster, PoseStampedToOdometry
from dimos.msgs.geometry_msgs.PointStamped import PointStamped
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.navigation.movement_manager.movement_manager import MovementManager
from dimos.navigation.nav_stack.main import create_nav_stack
from dimos.protocol.service.lcmservice import _DEFAULT_LCM_URL
from dimos.simulation.scene_assets.cook import cook_scene_package
from dimos.simulation.scene_assets.mesh_scene import SceneMeshAlignment
from dimos.simulation.scene_assets.spec import BrowserVisualSpec, MujocoSceneSpec

pytestmark = [pytest.mark.self_hosted, pytest.mark.skipif_in_ci]

ODOM_TOPIC = "/odom#geometry_msgs.PoseStamped"
GOAL_TOPIC = "/clicked_point#geometry_msgs.PointStamped"
WORLD_FRAME = "map"

# The office origin is too cluttered for a clean route, so this runs on an open
# floor (cooked on demand) where the spawned wall is the only obstacle.
FLOOR_SCENE_DIR = Path.home() / ".cache" / "dimos" / "scene_packages" / "pimsim_flat_floor"

# Robot starts at the origin; a wall spans +y with the doorway pushed off to the
# right, so the only way to the goal at (0, 4) is to detour around through it.
ROBOT_START = (0.0, 0.0)
WALL_Y = 2.0
WALL_X_MIN = -4.0
WALL_X_MAX = 5.0
DOOR_X_MIN = 0.9
DOOR_X_MAX = 3.1
GOAL = (0.0, 4.0)
# The planner stops within WAYPOINT_THRESHOLD_M of the goal; the test asserts the
# box ended within the looser REACH_THRESHOLD_M so a clean stop counts as reached.
WAYPOINT_THRESHOLD_M = 0.6
REACH_THRESHOLD_M = 1.2
WARMUP_SEC = 15.0
GOAL_TIMEOUT_SEC = 150.0


def _ensure_floor_scene() -> str:
    """Cook (once) a 40x40 m flat floor scene; return its scene.meta.json path."""
    meta = FLOOR_SCENE_DIR / "scene.meta.json"
    if meta.exists():
        return str(meta)
    import trimesh

    floor = trimesh.creation.box(extents=[40.0, 40.0, 0.1])
    floor.apply_translation([0.0, 0.0, -0.05])
    glb = FLOOR_SCENE_DIR.parent / "pimsim_flat_floor.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    trimesh.Scene(floor).export(str(glb))
    package = cook_scene_package(
        glb,
        output_dir=FLOOR_SCENE_DIR,
        alignment=SceneMeshAlignment(scale=1.0, y_up=False),
        visual_spec=BrowserVisualSpec(optimizer="copy"),
        mujoco_spec=MujocoSceneSpec(enabled=False),
    )
    return str(package.metadata_path)


def _babylon_nav_blueprint():
    """pimsim sim (open floor) + odom adapter + nav stack, wired for routing."""
    sim = build_babylon_sim(_ensure_floor_scene())
    odom_adapter = PoseStampedToOdometry.blueprint().transports(
        {
            ("pose", PoseStamped): LCMTransport("/odom", PoseStamped),
            ("odometry", Odometry): LCMTransport("/odometry", Odometry),
        }
    )
    odom_adapter = PoseStampedToOdometry.blueprint().transports(
        {
            ("pose", PoseStamped): LCMTransport("/odom", PoseStamped),
            ("odometry", Odometry): LCMTransport("/odometry", Odometry),
        }
    )
    # SimplePlanner reads the robot pose from TF (map -> body); the sim only
    # publishes /odom, so broadcast that TF edge.
    tf_broadcaster = OdomTfBroadcaster.blueprint().transports(
        {("pose", PoseStamped): LCMTransport("/odom", PoseStamped)}
    )
    nav_stack = create_nav_stack(
        planner="simple",
        vehicle_height=0.40,
        max_speed=0.8,
        waypoint_threshold=WAYPOINT_THRESHOLD_M,
    ).transports(
        {
            # The pimsim lidar already publishes a world-frame cloud, so it is
            # the nav stack's registered scan.
            ("registered_scan", PointCloud2): LCMTransport("/lidar", PointCloud2),
        }
    )
    # MovementManager relays /clicked_point -> the planner's goal stream (and
    # muxes velocity). Its way_point output is remapped away to avoid colliding
    # with SimplePlanner's way_point. The browser reads PathFollower's
    # /nav_cmd_vel directly.
    movement_manager = MovementManager.blueprint()
    return (
        autoconnect(sim, odom_adapter, tf_broadcaster, nav_stack, movement_manager)
        .remappings([(MovementManager, "way_point", "_mgr_way_point_unused")])
        .global_config(simulation=True)
    )


def _spawn_wall_with_doorway(client: PimSimClient) -> None:
    client.add_wall(WALL_X_MIN, WALL_Y, DOOR_X_MIN, WALL_Y)
    client.add_wall(DOOR_X_MAX, WALL_Y, WALL_X_MAX, WALL_Y)


def test_pimsim_cross_wall() -> None:
    coordinator = ModuleCoordinator.build(_babylon_nav_blueprint())

    robot_x = robot_y = 0.0
    odom_seen = 0
    max_x = 0.0
    crossed_wall = False

    def _on_odom(_channel: str, data: bytes) -> None:
        nonlocal robot_x, robot_y, odom_seen, max_x, crossed_wall
        msg = PoseStamped.lcm_decode(data)
        robot_x, robot_y, odom_seen = msg.x, msg.y, odom_seen + 1
        max_x = max(max_x, msg.x)
        if msg.y >= WALL_Y:
            crossed_wall = True

    lcm = lcmlib.LCM(_DEFAULT_LCM_URL)
    lcm.subscribe(ODOM_TOPIC, _on_odom)

    browser = HeadlessBrowser()
    client = PimSimClient()
    try:
        browser.start()
        client.start()
        client.set_agent_position(*ROBOT_START)

        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline and odom_seen == 0:
            lcm.handle_timeout(200)
        assert odom_seen > 0, "no /odom from pimsim — sim not running"

        _spawn_wall_with_doorway(client)
        warmup_end = time.monotonic() + WARMUP_SEC
        while time.monotonic() < warmup_end:
            lcm.handle_timeout(200)

        goal = PointStamped(x=GOAL[0], y=GOAL[1], z=0.0, ts=time.time(), frame_id=WORLD_FRAME)
        lcm.publish(GOAL_TOPIC, goal.lcm_encode())

        reached = False
        goal_end = time.monotonic() + GOAL_TIMEOUT_SEC
        while time.monotonic() < goal_end:
            lcm.handle_timeout(200)
            if ((robot_x - GOAL[0]) ** 2 + (robot_y - GOAL[1]) ** 2) ** 0.5 < REACH_THRESHOLD_M:
                reached = True
                break

        print(
            f"[cross_wall] final=({robot_x:.2f},{robot_y:.2f}) goal={GOAL} "
            f"max_x={max_x:.2f} crossed_wall={crossed_wall} reached={reached}"
        )
        assert crossed_wall, "box never crossed the wall plane (y >= WALL_Y)"
        assert reached, (
            f"box did not reach the goal past the wall: "
            f"final ({robot_x:.2f}, {robot_y:.2f}), goal {GOAL}"
        )
    finally:
        browser.stop()
        client.stop()
        coordinator.stop()
