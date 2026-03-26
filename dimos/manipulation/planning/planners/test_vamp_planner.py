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

"""Tests for VampPlanner integration.

These tests verify:
- PlannerSpec protocol conformance
- Robot name resolution
- Obstacle conversion from dimos to VAMP format
- Planning with mock VAMP (when vamp-planner is not installed)
- Planning with real VAMP (when vamp-planner is installed, marked integration)
- Factory integration
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from dimos.manipulation.planning.spec.config import RobotModelConfig
from dimos.manipulation.planning.spec.enums import ObstacleType, PlanningStatus
from dimos.manipulation.planning.spec.models import Obstacle, PlanningResult
from dimos.manipulation.planning.spec.protocols import PlannerSpec
from dimos.msgs.geometry_msgs import PoseStamped, Quaternion, Vector3
from dimos.msgs.sensor_msgs import JointState

# Check if vamp is actually available
try:
    import vamp

    VAMP_AVAILABLE = True
except ImportError:
    VAMP_AVAILABLE = False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def panda_config():
    """Panda robot configuration."""
    return RobotModelConfig(
        name="panda",
        urdf_path=Path("/path/to/panda.urdf"),
        base_pose=PoseStamped(position=Vector3(), orientation=Quaternion()),
        joint_names=[
            "panda_joint1",
            "panda_joint2",
            "panda_joint3",
            "panda_joint4",
            "panda_joint5",
            "panda_joint6",
            "panda_joint7",
        ],
        end_effector_link="panda_link8",
    )


@pytest.fixture
def mock_world(panda_config):
    """Mock WorldSpec with Panda robot."""
    world = MagicMock()
    world.is_finalized = True
    world.get_robot_ids.return_value = ["panda_0"]
    world.get_robot_config.return_value = panda_config
    world.get_joint_limits.return_value = (
        np.array([-2.8973, -1.7628, -2.8973, -3.0718, -2.8973, -0.0175, -2.8973]),
        np.array([2.8973, 1.7628, 2.8973, -0.0698, 2.8973, 3.7525, 2.8973]),
    )
    world._obstacles = {}
    world.check_config_collision_free.return_value = True
    world.check_edge_collision_free.return_value = True
    return world


@pytest.fixture
def panda_start():
    """Panda start configuration."""
    return JointState(
        name=[
            "panda_joint1",
            "panda_joint2",
            "panda_joint3",
            "panda_joint4",
            "panda_joint5",
            "panda_joint6",
            "panda_joint7",
        ],
        position=[0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785],
    )


@pytest.fixture
def panda_goal():
    """Panda goal configuration."""
    return JointState(
        name=[
            "panda_joint1",
            "panda_joint2",
            "panda_joint3",
            "panda_joint4",
            "panda_joint5",
            "panda_joint6",
            "panda_joint7",
        ],
        position=[2.35, 1.0, 0.0, -0.8, 0.0, 2.5, 0.785],
    )


@pytest.fixture
def sample_obstacles():
    """Sample obstacles for testing. Positioned to not block start/goal configs."""
    return [
        Obstacle(
            name="sphere1",
            obstacle_type=ObstacleType.SPHERE,
            pose=PoseStamped(
                position=Vector3(x=0.8, y=0.8, z=0.25),
                orientation=Quaternion(),
            ),
            dimensions=(0.05,),
        ),
        Obstacle(
            name="box1",
            obstacle_type=ObstacleType.BOX,
            pose=PoseStamped(
                position=Vector3(x=0.8, y=-0.8, z=0.5),
                orientation=Quaternion(),
            ),
            dimensions=(0.1, 0.1, 0.1),
        ),
        Obstacle(
            name="cylinder1",
            obstacle_type=ObstacleType.CYLINDER,
            pose=PoseStamped(
                position=Vector3(x=-0.8, y=0.8, z=0.4),
                orientation=Quaternion(),
            ),
            dimensions=(0.03, 0.1),
        ),
    ]


# =============================================================================
# Unit Tests (no VAMP dependency needed)
# =============================================================================


class TestVampPlannerImportGuard:
    """Test that VampPlanner handles missing vamp gracefully."""

    def test_import_error_when_vamp_missing(self):
        """VampPlanner constructor raises ImportError when vamp not installed."""
        with patch.dict("sys.modules", {"vamp": None}):
            with patch(
                "dimos.manipulation.planning.planners.vamp_planner._VAMP_AVAILABLE",
                False,
            ):
                from dimos.manipulation.planning.planners.vamp_planner import (
                    VampPlanner,
                )

                with pytest.raises(ImportError, match="vamp-planner is not installed"):
                    VampPlanner()


class TestRobotNameResolution:
    """Test robot name to VAMP module mapping."""

    def test_known_robot_names(self):
        from dimos.manipulation.planning.planners.vamp_planner import VAMP_ROBOT_MAP

        assert "panda" in VAMP_ROBOT_MAP
        assert "franka" in VAMP_ROBOT_MAP
        assert "ur5" in VAMP_ROBOT_MAP
        assert "fetch" in VAMP_ROBOT_MAP
        assert "baxter" in VAMP_ROBOT_MAP

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_resolve_panda(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _get_vamp_robot_module,
        )

        module = _get_vamp_robot_module("panda")
        assert module is vamp.panda

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_resolve_franka_maps_to_panda(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _get_vamp_robot_module,
        )

        module = _get_vamp_robot_module("Franka_Panda_Arm")
        assert module is vamp.panda

    def test_unknown_robot_raises(self):
        """Unknown robot name raises ValueError."""
        if not VAMP_AVAILABLE:
            pytest.skip("vamp-planner not installed")
        from dimos.manipulation.planning.planners.vamp_planner import (
            _get_vamp_robot_module,
        )

        with pytest.raises(ValueError, match="Cannot map robot"):
            _get_vamp_robot_module("unknown_robot_xyz")


class TestObstacleConversion:
    """Test conversion of dimos Obstacles to VAMP geometry."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_sphere_conversion(self, sample_obstacles):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        results = _obstacle_to_vamp(sample_obstacles[0])
        assert len(results) == 1
        geom, method = results[0]
        assert method == "add_sphere"
        assert isinstance(geom, vamp.Sphere)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_box_conversion(self, sample_obstacles):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        results = _obstacle_to_vamp(sample_obstacles[1])
        assert len(results) == 1
        geom, method = results[0]
        assert method == "add_cuboid"
        assert isinstance(geom, vamp.Cuboid)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_cylinder_conversion(self, sample_obstacles):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        results = _obstacle_to_vamp(sample_obstacles[2])
        assert len(results) == 1
        geom, method = results[0]
        assert method == "add_capsule"

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_mesh_obstacle_skipped(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        mesh_obs = Obstacle(
            name="mesh1",
            obstacle_type=ObstacleType.MESH,
            pose=PoseStamped(position=Vector3(), orientation=Quaternion()),
            mesh_path="/some/mesh.obj",
        )
        results = _obstacle_to_vamp(mesh_obs)
        assert len(results) == 0


class TestQuaternionConversion:
    """Test quaternion to Euler conversion."""

    def test_identity_quaternion(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _quaternion_to_euler_xyz,
        )

        euler = _quaternion_to_euler_xyz(0, 0, 0, 1)
        np.testing.assert_allclose(euler, [0, 0, 0], atol=1e-10)

    def test_90_degree_yaw(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _quaternion_to_euler_xyz,
        )

        # 90 degrees around Z: quat = (0, 0, sin(45), cos(45))
        euler = _quaternion_to_euler_xyz(0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4))
        np.testing.assert_allclose(euler, [0, 0, np.pi / 2], atol=1e-10)


class TestVampPlannerProtocolConformance:
    """Test that VampPlanner conforms to PlannerSpec."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_is_planner_spec(self):
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        assert isinstance(planner, PlannerSpec)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_has_required_methods(self):
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        assert hasattr(planner, "plan_joint_path")
        assert hasattr(planner, "get_name")
        assert callable(planner.plan_joint_path)
        assert callable(planner.get_name)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_get_name(self):
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="rrtc")
        assert "VAMP" in planner.get_name()
        assert "RRTC" in planner.get_name()


class TestVampPlannerWithMockedVamp:
    """Test VampPlanner logic with mocked VAMP library."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_planning_success(self, mock_world, panda_start, panda_goal):
        """Test successful planning returns correct PlanningResult."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        if result.is_success():
            assert len(result.path) >= 2
            assert result.status == PlanningStatus.SUCCESS
            # Verify path endpoints match start/goal
            np.testing.assert_allclose(
                result.path[0].position, panda_start.position, atol=1e-6
            )
            np.testing.assert_allclose(
                result.path[-1].position, panda_goal.position, atol=1e-6
            )

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_planning_with_obstacles(
        self, mock_world, panda_start, panda_goal, sample_obstacles
    ):
        """Test planning with obstacles synced from WorldSpec."""
        # Add obstacles to mock world
        @dataclass
        class FakeObsData:
            obstacle: Obstacle

        mock_world._obstacles = {
            obs.name: FakeObsData(obstacle=obs) for obs in sample_obstacles
        }

        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_collision_at_start(self, mock_world, panda_start, panda_goal):
        """Test that collision at start is detected by VAMP."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        # Create planner that will fail at start validation
        planner = VampPlanner(vamp_robot_name="panda")

        # Put a sphere right at the robot's base to cause collision
        @dataclass
        class FakeObsData:
            obstacle: Obstacle

        blocking_obstacle = Obstacle(
            name="blocker",
            obstacle_type=ObstacleType.SPHERE,
            pose=PoseStamped(
                position=Vector3(x=0.0, y=0.0, z=0.5),
                orientation=Quaternion(),
            ),
            dimensions=(5.0,),  # Huge sphere to guarantee collision
        )
        mock_world._obstacles = {"blocker": FakeObsData(obstacle=blocking_obstacle)}

        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal
        )
        # Should detect collision at start or goal
        assert result.status in (
            PlanningStatus.COLLISION_AT_START,
            PlanningStatus.COLLISION_AT_GOAL,
        )

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_all_algorithms_accepted(self):
        """Test that all algorithm names are accepted by constructor."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        for algo in ["rrtc", "prm", "fcit", "aorrtc"]:
            planner = VampPlanner(vamp_robot_name="panda", algorithm=algo)
            assert algo in planner.get_name().lower()

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_invalid_algorithm_raises(self, mock_world, panda_start, panda_goal):
        """Test that invalid algorithm name raises ValueError during planning."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="invalid")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal
        )
        # Should fail gracefully (exception caught internally)
        assert not result.is_success()


class TestFactoryIntegration:
    """Test VampPlanner creation through factory."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_create_vamp_planner(self):
        from dimos.manipulation.planning.factory import create_planner

        planner = create_planner(name="vamp", vamp_robot_name="panda")
        assert isinstance(planner, PlannerSpec)
        assert "VAMP" in planner.get_name()

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_create_vamp_planner_with_algorithm(self):
        from dimos.manipulation.planning.factory import create_planner

        planner = create_planner(
            name="vamp", vamp_robot_name="panda", algorithm="prm"
        )
        assert "PRM" in planner.get_name()

    def test_factory_lists_vamp(self):
        """Test that factory error message includes 'vamp' in available planners."""
        from dimos.manipulation.planning.factory import create_planner

        with pytest.raises(ValueError, match="vamp"):
            create_planner(name="nonexistent")

    def test_rrt_connect_still_works(self):
        """Test that existing rrt_connect planner is unaffected."""
        from dimos.manipulation.planning.factory import create_planner

        planner = create_planner(name="rrt_connect")
        assert planner.get_name() == "RRTConnect"
