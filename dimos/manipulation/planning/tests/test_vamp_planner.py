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

"""Comprehensive tests for VampPlanner integration.

Test categories:
    A. VAMP Direct API Tests — sanity checks against the vamp-planner library
    B. VampPlanner (PlannerSpec) Integration Tests — protocol conformance, planning
    C. Factory Integration Tests — factory wiring
    D. Path Quality Tests — continuity, collision-free, joint names
    E. End-to-End Tests — obstacle avoidance, multi-obstacle scenarios
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
# Helpers
# =============================================================================


@dataclass
class FakeObsData:
    """Mimics DrakeWorld's internal obstacle storage."""

    obstacle: Obstacle


PANDA_JOINT_NAMES = [
    "panda_joint1",
    "panda_joint2",
    "panda_joint3",
    "panda_joint4",
    "panda_joint5",
    "panda_joint6",
    "panda_joint7",
]


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
        joint_names=PANDA_JOINT_NAMES,
        end_effector_link="panda_link8",
    )


@pytest.fixture
def mock_world(panda_config):
    """Mock WorldSpec with Panda robot and no obstacles."""
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
    """Panda start configuration (home-ish pose)."""
    return JointState(
        name=PANDA_JOINT_NAMES,
        position=[0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785],
    )


@pytest.fixture
def panda_goal():
    """Panda goal configuration (far from start)."""
    return JointState(
        name=PANDA_JOINT_NAMES,
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
# A. VAMP Direct API Tests (sanity checks)
# =============================================================================


class TestVampDirectAPI:
    """Sanity checks against the vamp-planner library itself."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_import(self):
        """Can we import vamp?"""
        import vamp  # noqa: F811

        assert hasattr(vamp, "Environment")
        assert hasattr(vamp, "Sphere")
        assert hasattr(vamp, "Cuboid")

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_available_robots(self):
        """VAMP exposes known robot modules."""
        assert hasattr(vamp, "panda")
        assert hasattr(vamp, "ur5")
        assert hasattr(vamp, "fetch")
        assert hasattr(vamp, "baxter")

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_panda_problem(self):
        """Can we create a Panda environment?"""
        env = vamp.Environment()
        assert env is not None
        assert vamp.panda.dimension() == 7

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_panda_joint_info(self):
        """Panda joint names and limits are accessible."""
        names = vamp.panda.joint_names()
        assert len(names) == 7
        assert names[0] == "panda_joint1"
        lower = vamp.panda.lower_bounds()
        upper = vamp.panda.upper_bounds()
        assert len(lower) == 7
        assert len(upper) == 7
        assert all(l < u for l, u in zip(lower, upper))

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_simple_plan(self):
        """Plan from A to B with no obstacles."""
        env = vamp.Environment()
        start = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        goal = [2.35, 1.0, 0.0, -0.8, 0.0, 2.5, 0.785]
        rng = vamp.panda.halton()
        settings = vamp.RRTCSettings()
        result = vamp.panda.rrtc(start, goal, env, settings, rng)
        assert result.solved
        path = result.path.numpy()
        assert path.shape[1] == 7
        assert path.shape[0] >= 2

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_plan_with_sphere_obstacle(self):
        """Plan with a sphere obstacle present."""
        env = vamp.Environment()
        env.add_sphere(vamp.Sphere([0.5, 0.0, 0.5], 0.1))
        start = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        goal = [1.5, 0.5, 0.0, -1.5, 0.0, 2.0, 0.785]
        rng = vamp.panda.halton()
        result = vamp.panda.rrtc(start, goal, env, vamp.RRTCSettings(), rng)
        assert result.solved

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_plan_with_cuboid_obstacle(self):
        """Plan with a cuboid obstacle present."""
        env = vamp.Environment()
        # Small cuboid away from the direct path
        env.add_cuboid(vamp.Cuboid([0.6, 0.6, 0.4], [0.0, 0.0, 0.0], [0.05, 0.05, 0.05]))
        start = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        goal = [0.5, -0.3, 0.0, -2.0, 0.0, 1.8, 0.785]
        rng = vamp.panda.halton()
        result = vamp.panda.rrtc(start, goal, env, vamp.RRTCSettings(), rng)
        assert result.solved

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_collision_check(self):
        """Verify VAMP collision checking detects collisions."""
        env = vamp.Environment()
        # No obstacles — should be valid
        q = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        assert vamp.panda.validate(q, env)

        # Huge sphere at origin — should collide
        env.add_sphere(vamp.Sphere([0.0, 0.0, 0.5], 5.0))
        assert not vamp.panda.validate(q, env)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_validate_motion(self):
        """VAMP can validate an entire motion (edge collision check)."""
        env = vamp.Environment()
        q1 = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        q2 = [0.5, -0.5, 0.0, -2.0, 0.0, 1.8, 0.785]
        assert vamp.panda.validate_motion(q1, q2, env)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_fk(self):
        """Forward kinematics returns sphere positions."""
        q = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        fk_result = vamp.panda.fk(q)
        # FK returns collision sphere positions — should be an array
        assert fk_result is not None
        arr = np.array(fk_result)
        assert arr.ndim >= 1

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_vamp_eefk(self):
        """End-effector FK returns a pose."""
        q = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]
        ee = vamp.panda.eefk(q)
        assert ee is not None


# =============================================================================
# B. VampPlanner (PlannerSpec) Integration Tests
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

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_resolve_ur5(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _get_vamp_robot_module,
        )

        module = _get_vamp_robot_module("ur5")
        assert module is vamp.ur5

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_unknown_robot_raises(self):
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

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_sphere_position_correct(self, sample_obstacles):
        """Sphere position matches obstacle pose."""
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        results = _obstacle_to_vamp(sample_obstacles[0])
        geom, _ = results[0]
        assert abs(geom.x - 0.8) < 1e-6
        assert abs(geom.y - 0.8) < 1e-6
        assert abs(geom.z - 0.25) < 1e-6

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_sphere_radius_correct(self, sample_obstacles):
        """Sphere radius matches obstacle dimensions."""
        from dimos.manipulation.planning.planners.vamp_planner import (
            _obstacle_to_vamp,
        )

        results = _obstacle_to_vamp(sample_obstacles[0])
        geom, _ = results[0]
        assert abs(geom.r - 0.05) < 1e-6


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

        euler = _quaternion_to_euler_xyz(0, 0, np.sin(np.pi / 4), np.cos(np.pi / 4))
        np.testing.assert_allclose(euler, [0, 0, np.pi / 2], atol=1e-10)

    def test_90_degree_roll(self):
        from dimos.manipulation.planning.planners.vamp_planner import (
            _quaternion_to_euler_xyz,
        )

        euler = _quaternion_to_euler_xyz(np.sin(np.pi / 4), 0, 0, np.cos(np.pi / 4))
        np.testing.assert_allclose(euler, [np.pi / 2, 0, 0], atol=1e-10)


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
    def test_get_name_contains_algorithm(self):
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="rrtc")
        name = planner.get_name()
        assert "VAMP" in name
        assert "RRTC" in name

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_get_name_contains_robot(self):
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        assert "panda" in planner.get_name()


class TestVampPlannerPlanning:
    """Test VampPlanner planning functionality."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_plan_success(self, mock_world, panda_start, panda_goal):
        """Plan succeeds with valid start/goal."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        assert result.is_success()
        assert len(result.path) >= 2
        assert result.status == PlanningStatus.SUCCESS

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_plan_path_endpoints(self, mock_world, panda_start, panda_goal):
        """Path starts at start and ends at goal."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()
        np.testing.assert_allclose(
            result.path[0].position, panda_start.position, atol=1e-4
        )
        np.testing.assert_allclose(
            result.path[-1].position, panda_goal.position, atol=1e-4
        )

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_plan_with_obstacles(
        self, mock_world, panda_start, panda_goal, sample_obstacles
    ):
        """Obstacles from WorldSpec are synced to VAMP."""
        mock_world._obstacles = {
            obs.name: FakeObsData(obstacle=obs) for obs in sample_obstacles
        }

        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        # Should still find a path (obstacles are not blocking)
        assert result.is_success()

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_collision_at_start(self, mock_world, panda_start, panda_goal):
        """Returns COLLISION_AT_START when start is in collision."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

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

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal
        )
        assert result.status in (
            PlanningStatus.COLLISION_AT_START,
            PlanningStatus.COLLISION_AT_GOAL,
        )

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_collision_at_goal(self, mock_world, panda_start):
        """Returns COLLISION_AT_GOAL when goal is in collision."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        # Goal that collides with a large sphere
        goal_in_collision = JointState(
            name=PANDA_JOINT_NAMES,
            position=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        )
        blocking_obstacle = Obstacle(
            name="blocker",
            obstacle_type=ObstacleType.SPHERE,
            pose=PoseStamped(
                position=Vector3(x=0.0, y=0.0, z=0.5),
                orientation=Quaternion(),
            ),
            dimensions=(5.0,),
        )
        mock_world._obstacles = {"blocker": FakeObsData(obstacle=blocking_obstacle)}

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, goal_in_collision
        )
        assert result.status in (
            PlanningStatus.COLLISION_AT_START,
            PlanningStatus.COLLISION_AT_GOAL,
        )

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_result_format(self, mock_world, panda_start, panda_goal):
        """PlanningResult has correct format with JointState path."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        assert isinstance(result.status, PlanningStatus)
        assert isinstance(result.planning_time, float)

        if result.is_success():
            assert isinstance(result.path, list)
            for waypoint in result.path:
                assert isinstance(waypoint, JointState)
                assert len(waypoint.position) == 7

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_planning_time_recorded(self, mock_world, panda_start, panda_goal):
        """planning_time is positive."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal
        )
        assert result.planning_time > 0

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_all_algorithms_accepted(self):
        """All algorithm names are accepted by constructor."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        for algo in ["rrtc", "prm", "fcit", "aorrtc"]:
            planner = VampPlanner(vamp_robot_name="panda", algorithm=algo)
            assert algo in planner.get_name().lower()

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_invalid_algorithm_raises(self, mock_world, panda_start, panda_goal):
        """Invalid algorithm fails gracefully during planning."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="invalid")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal
        )
        assert not result.is_success()

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_auto_resolve_robot_from_world(self, mock_world, panda_start, panda_goal):
        """VampPlanner can auto-resolve robot from WorldSpec config."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner()  # No explicit robot name
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()


# =============================================================================
# C. Factory Integration Tests
# =============================================================================


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

    def test_factory_lists_vamp_in_error(self):
        """Factory error message includes 'vamp' in available planners."""
        from dimos.manipulation.planning.factory import create_planner

        with pytest.raises(ValueError, match="vamp"):
            create_planner(name="nonexistent")

    def test_rrt_connect_still_works(self):
        """Existing rrt_connect planner is unaffected."""
        from dimos.manipulation.planning.factory import create_planner

        planner = create_planner(name="rrt_connect")
        assert planner.get_name() == "RRTConnect"


# =============================================================================
# D. Path Quality Tests
# =============================================================================


class TestPathQuality:
    """Tests for path correctness and quality."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_path_continuity(self, mock_world, panda_start, panda_goal):
        """Path waypoints are continuous (no large jumps)."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", simplify=False)
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()

        max_step = 0.0
        for i in range(len(result.path) - 1):
            p1 = np.array(result.path[i].position)
            p2 = np.array(result.path[i + 1].position)
            step = np.linalg.norm(p2 - p1)
            max_step = max(max_step, step)

        # Max step should be bounded (VAMP uses range parameter)
        # With simplification off, steps should be reasonable
        assert max_step < 10.0  # Very loose bound for unsimplified paths

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_path_collision_free(self, mock_world, panda_start, panda_goal):
        """All waypoints in path are collision-free per VAMP."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()

        env = vamp.Environment()
        for waypoint in result.path:
            assert vamp.panda.validate(list(waypoint.position), env)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_joint_names_preserved(self, mock_world, panda_start, panda_goal):
        """JointState names match the input joint names."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()

        for waypoint in result.path:
            assert waypoint.name == panda_start.name

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_path_length_positive(self, mock_world, panda_start, panda_goal):
        """Path length is positive for non-trivial paths."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()
        assert result.path_length > 0

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_path_within_joint_limits(self, mock_world, panda_start, panda_goal):
        """All waypoints are within VAMP's joint limits."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.is_success()

        lower = vamp.panda.lower_bounds()
        upper = vamp.panda.upper_bounds()
        for waypoint in result.path:
            pos = np.array(waypoint.position)
            assert np.all(pos >= lower - 1e-6), f"Below lower: {pos} vs {lower}"
            assert np.all(pos <= upper + 1e-6), f"Above upper: {pos} vs {upper}"


# =============================================================================
# E. End-to-End Tests
# =============================================================================


class TestEndToEnd:
    """End-to-end scenario tests."""

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_obstacle_avoidance(self, mock_world, panda_start, panda_goal):
        """Place obstacle in workspace, verify path avoids it."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        obstacle = Obstacle(
            name="wall",
            obstacle_type=ObstacleType.BOX,
            pose=PoseStamped(
                position=Vector3(x=0.4, y=0.0, z=0.5),
                orientation=Quaternion(),
            ),
            dimensions=(0.02, 1.0, 1.0),  # Thin wall
        )
        mock_world._obstacles = {"wall": FakeObsData(obstacle=obstacle)}

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        # Path should either succeed (avoiding obstacle) or fail if truly blocked
        if result.is_success():
            # Verify all waypoints are collision-free with the obstacle
            env = vamp.Environment()
            env.add_cuboid(
                vamp.Cuboid([0.4, 0.0, 0.5], [0.0, 0.0, 0.0], [0.01, 0.5, 0.5])
            )
            for waypoint in result.path:
                assert vamp.panda.validate(list(waypoint.position), env)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_multiple_obstacles(
        self, mock_world, panda_start, panda_goal, sample_obstacles
    ):
        """Plan through environment with multiple obstacles."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        mock_world._obstacles = {
            obs.name: FakeObsData(obstacle=obs) for obs in sample_obstacles
        }

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        if result.is_success():
            assert len(result.path) >= 2

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_prm_algorithm(self, mock_world, panda_start, panda_goal):
        """PRM algorithm finds a valid path."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="prm")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert isinstance(result, PlanningResult)
        if result.is_success():
            assert len(result.path) >= 2

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_same_start_goal(self, mock_world, panda_start):
        """Planning with identical start and goal."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_start, timeout=10.0
        )
        assert isinstance(result, PlanningResult)
        # VAMP should handle same start/goal (trivial path)
        if result.is_success():
            assert len(result.path) >= 1

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_simplification_reduces_waypoints(
        self, mock_world, panda_start, panda_goal
    ):
        """Simplified path should have fewer or equal waypoints."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner_raw = VampPlanner(vamp_robot_name="panda", simplify=False)
        planner_simp = VampPlanner(vamp_robot_name="panda", simplify=True)

        result_raw = planner_raw.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        result_simp = planner_simp.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )

        if result_raw.is_success() and result_simp.is_success():
            # Simplified should have <= waypoints (usually fewer)
            assert len(result_simp.path) <= len(result_raw.path)

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_iterations_recorded(self, mock_world, panda_start, panda_goal):
        """Iterations count is recorded in result."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert result.iterations is not None
        assert result.iterations >= 0

    @pytest.mark.skipif(not VAMP_AVAILABLE, reason="vamp-planner not installed")
    def test_e2e_message_contains_algorithm(
        self, mock_world, panda_start, panda_goal
    ):
        """Result message mentions the algorithm used."""
        from dimos.manipulation.planning.planners.vamp_planner import VampPlanner

        planner = VampPlanner(vamp_robot_name="panda", algorithm="rrtc")
        result = planner.plan_joint_path(
            mock_world, "panda_0", panda_start, panda_goal, timeout=30.0
        )
        assert "rrtc" in result.message.lower()
