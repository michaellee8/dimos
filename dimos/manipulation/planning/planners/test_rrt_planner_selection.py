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

"""Tests for selected-joint RRT planning group contracts."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np

from dimos.manipulation.planning.planners.rrt_planner import RRTConnectPlanner
from dimos.manipulation.planning.spec.config import RobotModelConfig
from dimos.manipulation.planning.spec.enums import PlanningStatus
from dimos.manipulation.planning.spec.models import ResolvedPlanningGroup
from dimos.manipulation.planning.spec.protocols import WorldSpec
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.JointState import JointState


def _pose() -> PoseStamped:
    return PoseStamped(position=[0, 0, 0], orientation=[0, 0, 0, 1])


def _robot_config(name: str, joint_names: list[str]) -> RobotModelConfig:
    return RobotModelConfig(
        name=name,
        model_path=Path("robot.urdf"),
        base_pose=_pose(),
        joint_names=joint_names,
        end_effector_link="tool0",
    )


def _joint_state(names: list[str], positions: list[float]) -> JointState:
    return JointState({"name": names, "position": positions})


def _group(
    group_id: str,
    robot_id: str,
    robot_name: str,
    joint_names: tuple[str, ...],
) -> ResolvedPlanningGroup:
    return ResolvedPlanningGroup(
        id=group_id,
        robot_id=robot_id,
        robot_name=robot_name,
        group_name=group_id.split("/", maxsplit=1)[1],
        joint_names=joint_names,
        local_joint_names=tuple(name.split("/", maxsplit=1)[1] for name in joint_names),
        base_link="base_link",
        tip_link="tool0",
    )


class _SelectionWorld:
    is_finalized = True

    def __init__(
        self,
        groups: dict[str, ResolvedPlanningGroup],
        robot_configs: dict[str, RobotModelConfig],
    ) -> None:
        self._groups = groups
        self._robot_configs = robot_configs

    def resolve_planning_groups(
        self, group_ids: tuple[str, ...]
    ) -> tuple[ResolvedPlanningGroup, ...]:
        return tuple(self._groups[group_id] for group_id in group_ids)

    def get_robot_config(self, robot_id: str) -> RobotModelConfig:
        return self._robot_configs[robot_id]

    def get_robot_ids(self) -> list[str]:
        return list(self._robot_configs)

    def check_config_collision_free(self, robot_id: str, joint_state: JointState) -> bool:
        return True

    def get_joint_limits(self, robot_id: str) -> tuple[np.ndarray, np.ndarray]:
        joint_count = len(self._robot_configs[robot_id].joint_names)
        return -np.ones(joint_count), np.ones(joint_count)

    def check_edge_collision_free(
        self,
        robot_id: str,
        start: JointState,
        goal: JointState,
        step_size: float,
    ) -> bool:
        return True


def test_plan_selected_joint_path_rejects_missing_and_extra_start_names() -> None:
    world = _SelectionWorld(
        groups={"arm/arm": _group("arm/arm", "robot_1", "arm", ("arm/joint1", "arm/joint2"))},
        robot_configs={"robot_1": _robot_config("arm", ["joint1", "joint2"])},
    )

    result = RRTConnectPlanner().plan_selected_joint_path(
        cast("WorldSpec", world),
        ["arm/arm"],
        start=_joint_state(["arm/joint1", "arm/extra"], [0.0, 0.0]),
        goal=_joint_state(["arm/joint1", "arm/joint2"], [0.0, 0.0]),
    )

    assert result.status == PlanningStatus.INVALID_START
    assert "missing" in result.message
    assert "extra" in result.message


def test_plan_selected_joint_path_rejects_missing_and_extra_goal_names() -> None:
    world = _SelectionWorld(
        groups={"arm/arm": _group("arm/arm", "robot_1", "arm", ("arm/joint1", "arm/joint2"))},
        robot_configs={"robot_1": _robot_config("arm", ["joint1", "joint2"])},
    )

    result = RRTConnectPlanner().plan_selected_joint_path(
        cast("WorldSpec", world),
        ["arm/arm"],
        start=_joint_state(["arm/joint1", "arm/joint2"], [0.0, 0.0]),
        goal=_joint_state(["arm/joint1", "arm/extra"], [0.0, 0.0]),
    )

    assert result.status == PlanningStatus.INVALID_GOAL
    assert "missing" in result.message
    assert "extra" in result.message


def test_plan_selected_joint_path_plans_cross_robot_full_group_selection() -> None:
    world = _SelectionWorld(
        groups={
            "left/arm": _group("left/arm", "left_robot", "left", ("left/joint1",)),
            "right/arm": _group("right/arm", "right_robot", "right", ("right/joint1",)),
        },
        robot_configs={
            "left_robot": _robot_config("left", ["joint1"]),
            "right_robot": _robot_config("right", ["joint1"]),
        },
    )
    joint_state = _joint_state(["left/joint1", "right/joint1"], [0.0, 0.0])

    result = RRTConnectPlanner().plan_selected_joint_path(
        cast("WorldSpec", world),
        ["left/arm", "right/arm"],
        start=joint_state,
        goal=_joint_state(["left/joint1", "right/joint1"], [0.1, -0.1]),
    )

    assert result.status == PlanningStatus.SUCCESS
    assert len(result.path) == 2
    assert result.path[0].name == ["left/joint1", "right/joint1"]
    assert result.path[-1].position == [0.1, -0.1]


def test_plan_selected_joint_path_rejects_single_robot_subset_selection() -> None:
    world = _SelectionWorld(
        groups={"arm/wrist": _group("arm/wrist", "robot_1", "arm", ("arm/joint2",))},
        robot_configs={"robot_1": _robot_config("arm", ["joint1", "joint2"])},
    )
    joint_state = _joint_state(["arm/joint2"], [0.0])

    result = RRTConnectPlanner().plan_selected_joint_path(
        cast("WorldSpec", world),
        ["arm/wrist"],
        start=joint_state,
        goal=joint_state,
    )

    assert result.status == PlanningStatus.UNSUPPORTED
