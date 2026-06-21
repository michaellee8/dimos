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

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from dimos.manipulation.planning.spec.models import PlanningGroupID, RobotName, WorldRobotID
from dimos.manipulation.visualization.types import (
    PlanningGroupInfo,
    RobotInfo,
    TargetSetEvaluation,
)
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.JointState import JointState

if TYPE_CHECKING:
    from dimos.manipulation.manipulation_module import ManipulationModule
    from dimos.manipulation.planning.groups.models import PlanningGroup
    from dimos.manipulation.planning.monitor.world_monitor import WorldMonitor
    from dimos.manipulation.planning.spec.config import RobotModelConfig


def copy_joint_state(joint_state: JointState | None) -> JointState | None:
    """Make a local copy of a JointState-like message for rendering."""
    return None if joint_state is None else JointState(joint_state)


class ViserModuleAccess:
    """Direct in-process access from Viser UI code to ManipulationModule primitives."""

    def __init__(
        self, world_monitor: WorldMonitor, manipulation_module: ManipulationModule
    ) -> None:
        self._world_monitor = world_monitor
        self._module = manipulation_module

    def list_robots(self) -> list[RobotName]:
        return list(self._module.list_robots())

    def robot_items(self) -> list[tuple[RobotName, WorldRobotID, RobotModelConfig]]:
        return self._module.robot_items()

    def robot_id_for_name(self, robot_name: RobotName) -> WorldRobotID | None:
        return self._module.robot_id_for_name(robot_name)

    def robot_name_for_id(self, robot_id: WorldRobotID) -> RobotName | None:
        return self._module.robot_name_for_id(robot_id)

    def get_robot_config(self, robot_name: RobotName) -> RobotModelConfig | None:
        return self._module.get_robot_config(robot_name)

    def get_robot_info(self, robot_name: RobotName) -> RobotInfo | None:
        info = self._module.get_robot_info(robot_name)
        if info is None:
            return None
        return {
            "name": str(info["name"]),
            "world_robot_id": str(info["world_robot_id"]),
            "joint_names": [str(name) for name in info["joint_names"]],
            "end_effector_link": str(info["end_effector_link"]),
            "base_link": str(info["base_link"]),
            "max_velocity": float(info["max_velocity"]),
            "max_acceleration": float(info["max_acceleration"]),
            "has_joint_name_mapping": bool(info.get("has_joint_name_mapping", False)),
            "coordinator_task_name": None
            if info["coordinator_task_name"] is None
            else str(info["coordinator_task_name"]),
            "home_joints": None
            if info["home_joints"] is None
            else [float(value) for value in info["home_joints"]],
            "pre_grasp_offset": float(info["pre_grasp_offset"]),
            "init_joints": None
            if info["init_joints"] is None
            else [float(value) for value in info["init_joints"]],
            "planning_groups": [
                {
                    "id": str(group["id"]),
                    "name": str(group["name"]),
                    "robot_name": str(info["name"]),
                    "joint_names": [str(name) for name in group["joint_names"]],
                    "local_joint_names": [str(name) for name in group["local_joint_names"]],
                    "base_link": str(group["base_link"]),
                    "tip_link": None if group["tip_link"] is None else str(group["tip_link"]),
                    "has_pose_target": bool(group["has_pose_target"]),
                    "source": str(group["source"]),
                }
                for group in info.get("planning_groups", [])
            ],
        }

    def list_planning_groups(self) -> list[PlanningGroupInfo]:
        groups: list[PlanningGroupInfo] = []
        for robot_name in self.list_robots():
            info = self.get_robot_info(robot_name)
            if info is not None:
                groups.extend(info.get("planning_groups", []))
        return groups

    def get_init_joints(self, robot_name: RobotName) -> JointState | None:
        return copy_joint_state(self._module.get_init_joints(robot_name))

    def get_current_joint_state(self, robot_name: RobotName) -> JointState | None:
        current = self._module.get_current_joint_state(robot_name)
        if current is None:
            robot_id = self.robot_id_for_name(robot_name)
            if robot_id is not None:
                current = self._world_monitor.get_current_joint_state(robot_id)
        return copy_joint_state(current)

    def is_state_stale(self, robot_name: RobotName, max_age: float = 1.0) -> bool:
        robot_id = self.robot_id_for_name(robot_name)
        return True if robot_id is None else self._world_monitor.is_state_stale(robot_id, max_age)

    def get_ee_pose(
        self, robot_name: RobotName, joint_state: JointState | None = None
    ) -> PoseStamped | Pose | None:
        group_id = self._primary_pose_group_id(robot_name)
        if group_id is None:
            return None
        fk = self._module.forward_kinematics(group_id, copy_joint_state(joint_state))
        if fk.pose is not None:
            return fk.pose
        robot_id = self.robot_id_for_name(robot_name)
        if robot_id is None:
            return None
        get_ee_pose = getattr(self._world_monitor, "get_ee_pose", None)
        if callable(get_ee_pose):
            return cast(
                "PoseStamped | Pose | None", get_ee_pose(robot_id, copy_joint_state(joint_state))
            )
        return None

    def get_module_state(self) -> str:
        return str(self._module.get_state())

    def get_error(self) -> str:
        return self._module.get_error()

    def reset(self) -> bool:
        result = self._module.reset()
        return result if isinstance(result, bool) else result.is_success()

    def plan_target_set(self, joint_targets: dict[PlanningGroupID, JointState]) -> bool:
        return self._module.plan_to_joint_targets(
            cast("dict[PlanningGroupID | PlanningGroup, JointState]", joint_targets)
        )

    def preview_plan(self, robot_name: RobotName | None = None) -> bool:
        return self._module.preview_plan(robot_name=robot_name)

    def execute(self) -> bool:
        return self._module.execute()

    def cancel(self) -> bool:
        return self._module.cancel()

    def clear_planned_path(self) -> bool:
        return self._module.clear_planned_path()

    def evaluate_joint_target_set(
        self, joint_targets: Mapping[PlanningGroupID, JointState]
    ) -> TargetSetEvaluation:
        if not joint_targets:
            return {"success": False, "status": "INVALID", "message": "No joint target"}
        names: list[str] = []
        positions: list[float] = []
        for target in joint_targets.values():
            copied = copy_joint_state(target)
            if copied is None:
                continue
            names.extend(str(name) for name in copied.name)
            positions.extend(float(position) for position in copied.position)
        return self._evaluate_global_target_set(
            tuple(joint_targets), JointState({"name": names, "position": positions})
        )

    def evaluate_pose_target_set(
        self,
        pose_targets: Mapping[PlanningGroupID, Pose | PoseStamped],
        auxiliary_groups: Sequence[PlanningGroupID] = (),
        seed: JointState | None = None,
        check_collision: bool = True,
    ) -> TargetSetEvaluation:
        if not pose_targets:
            return {"success": False, "status": "INVALID", "message": "No pose target"}
        stamped_targets = {
            group_id: self._stamped_pose(pose) for group_id, pose in pose_targets.items()
        }
        group_ids = tuple(dict.fromkeys((*stamped_targets.keys(), *auxiliary_groups)))
        ik = self._module.inverse_kinematics(
            pose_targets=stamped_targets,
            auxiliary_group_ids=auxiliary_groups,
            seed=copy_joint_state(seed),
        )
        if not ik.is_success() or ik.joint_state is None:
            return {
                "success": False,
                "status": ik.status.name,
                "message": ik.message,
                "collision_free": False,
                "group_ids": group_ids,
                "target_joints": None,
                "position_error": ik.position_error,
                "orientation_error": ik.orientation_error,
            }
        return self._evaluate_global_target_set(
            group_ids,
            ik.joint_state,
            status=ik.status.name,
            message=ik.message,
            position_error=ik.position_error,
            orientation_error=ik.orientation_error,
            check_collision=check_collision,
        )

    def _evaluate_global_target_set(
        self,
        group_ids: tuple[PlanningGroupID, ...],
        target_joints: JointState,
        *,
        status: str = "FEASIBLE",
        message: str = "Target is collision-free",
        position_error: float = 0.0,
        orientation_error: float = 0.0,
        check_collision: bool = True,
    ) -> TargetSetEvaluation:
        target = copy_joint_state(target_joints)
        if target is None:
            return {"success": False, "status": "INVALID", "message": "No target joints"}
        collision = self._module.check_collision(target) if check_collision else None
        collision_free = True if collision is None else collision.collision_free is True
        diagnostics = {
            group_id: "Target collision check skipped" if collision is None else collision.message
            for group_id in group_ids
        }
        result_message = message
        if collision is None:
            result_message = "Target collision check skipped"
        elif not collision_free:
            result_message = collision.message
        group_poses: dict[PlanningGroupID, PoseStamped | Pose | None] = {}
        for group_id in group_ids:
            fk = self._module.forward_kinematics(group_id, target)
            if fk.pose is not None:
                group_poses[group_id] = fk.pose
            elif fk.status != "INVALID":
                group_poses[group_id] = None
        return {
            "success": collision_free,
            "status": status
            if collision_free
            else collision.status
            if collision is not None
            else "COLLISION",
            "message": result_message,
            "collision_free": collision_free,
            "group_ids": group_ids,
            "target_joints": target,
            "group_diagnostics": diagnostics,
            "group_poses": group_poses,
            "position_error": position_error,
            "orientation_error": orientation_error,
        }

    def _primary_pose_group_id(self, robot_name: RobotName) -> PlanningGroupID | None:
        for group in self.list_planning_groups():
            if str(group["robot_name"]) == robot_name and bool(group["has_pose_target"]):
                return str(group["id"])
        return None

    @staticmethod
    def _stamped_pose(pose: Pose | PoseStamped) -> PoseStamped:
        if isinstance(pose, PoseStamped):
            return pose
        return PoseStamped(frame_id="world", position=pose.position, orientation=pose.orientation)

    @staticmethod
    def joints_from_values(joint_names: Sequence[str], values: Sequence[float]) -> JointState:
        return JointState(
            {"name": list(joint_names), "position": [float(value) for value in values]}
        )
