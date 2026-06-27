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

from collections.abc import Callable, Iterator
import inspect
import json
from typing import TypeAlias, cast, get_type_hints

import pytest

from dimos.agents.skill_result import SkillResult
from dimos.manipulation.agentic_manipulation_module import AgenticManipulationModule
from dimos.manipulation.skill_errors import ManipulationSkillError

Call: TypeAlias = tuple[str, tuple[str | None, ...]]
GetStateMethod: TypeAlias = Callable[
    [AgenticManipulationModule, str | None], SkillResult[ManipulationSkillError]
]
MoveToJointsMethod: TypeAlias = Callable[
    [AgenticManipulationModule, str, str | None], SkillResult[ManipulationSkillError]
]


class FakeManipulationProvider:
    def __init__(self, result: SkillResult[ManipulationSkillError]) -> None:
        self.result = result
        self.calls: list[Call] = []

    def get_robot_state(self, robot_name: str | None = None) -> SkillResult[ManipulationSkillError]:
        self.calls.append(("get_robot_state", (robot_name,)))
        return self.result

    def move_to_joints(
        self, joints: str, robot_name: str | None = None
    ) -> SkillResult[ManipulationSkillError]:
        self.calls.append(("move_to_joints", (joints, robot_name)))
        return self.result

    def open_gripper(self, robot_name: str | None = None) -> SkillResult[ManipulationSkillError]:
        self.calls.append(("open_gripper", (robot_name,)))
        return self.result

    def close_gripper(self, robot_name: str | None = None) -> SkillResult[ManipulationSkillError]:
        self.calls.append(("close_gripper", (robot_name,)))
        return self.result


@pytest.fixture
def skill_result() -> SkillResult[ManipulationSkillError]:
    return SkillResult[ManipulationSkillError].ok("provider result", state="ready")


@pytest.fixture
def provider(skill_result: SkillResult[ManipulationSkillError]) -> FakeManipulationProvider:
    return FakeManipulationProvider(skill_result)


@pytest.fixture
def module(provider: FakeManipulationProvider) -> Iterator[AgenticManipulationModule]:
    agentic_module = AgenticManipulationModule()
    agentic_module._manipulation = provider
    try:
        yield agentic_module
    finally:
        agentic_module.stop()


def test_get_robot_state_delegates_exact_arguments_and_result(
    module: AgenticManipulationModule,
    provider: FakeManipulationProvider,
    skill_result: SkillResult[ManipulationSkillError],
) -> None:
    get_robot_state = cast("GetStateMethod", AgenticManipulationModule.get_robot_state.__wrapped__)

    result = get_robot_state(module, "left_arm")

    assert result is skill_result
    assert provider.calls == [("get_robot_state", ("left_arm",))]


def test_move_to_joints_delegates_exact_arguments_and_result(
    module: AgenticManipulationModule,
    provider: FakeManipulationProvider,
    skill_result: SkillResult[ManipulationSkillError],
) -> None:
    joints = "0.1, -0.5, 1.2, 0.0, 0.3, -0.1"
    move_to_joints = cast(
        "MoveToJointsMethod", AgenticManipulationModule.move_to_joints.__wrapped__
    )

    result = move_to_joints(module, joints, "right_arm")

    assert result is skill_result
    assert provider.calls == [("move_to_joints", (joints, "right_arm"))]


def test_open_gripper_delegates_exact_arguments_and_result(
    module: AgenticManipulationModule,
    provider: FakeManipulationProvider,
    skill_result: SkillResult[ManipulationSkillError],
) -> None:
    open_gripper = cast("GetStateMethod", AgenticManipulationModule.open_gripper.__wrapped__)

    result = open_gripper(module, None)

    assert result is skill_result
    assert provider.calls == [("open_gripper", (None,))]


def test_close_gripper_delegates_exact_arguments_and_result(
    module: AgenticManipulationModule,
    provider: FakeManipulationProvider,
    skill_result: SkillResult[ManipulationSkillError],
) -> None:
    close_gripper = cast("GetStateMethod", AgenticManipulationModule.close_gripper.__wrapped__)

    result = close_gripper(module, "left_arm")

    assert result is skill_result
    assert provider.calls == [("close_gripper", ("left_arm",))]


def test_decorated_skill_call_preserves_provider_result_semantics(
    module: AgenticManipulationModule,
    provider: FakeManipulationProvider,
    skill_result: SkillResult[ManipulationSkillError],
) -> None:
    result = module.get_robot_state("left_arm")

    assert result is not skill_result
    assert result.success == skill_result.success
    assert result.message == skill_result.message
    assert result.error_code == skill_result.error_code
    assert result.metadata == skill_result.metadata
    assert result.duration_ms >= 0.0
    assert provider.calls == [("get_robot_state", ("left_arm",))]


@pytest.mark.parametrize(
    ("method_name", "expected_params"),
    [
        ("get_robot_state", {"robot_name": str | None}),
        ("move_to_joints", {"joints": str, "robot_name": str | None}),
        ("open_gripper", {"robot_name": str | None}),
        ("close_gripper", {"robot_name": str | None}),
    ],
)
def test_skill_methods_have_schema_safe_metadata(
    method_name: str, expected_params: dict[str, type | object]
) -> None:
    method = getattr(AgenticManipulationModule, method_name)
    signature = inspect.signature(method)
    type_hints = get_type_hints(method)

    assert getattr(method, "__skill__", False) is True
    assert inspect.getdoc(method)
    for name, annotation in expected_params.items():
        assert name in signature.parameters
        assert type_hints[name] == annotation
    for name, parameter in signature.parameters.items():
        if name == "self":
            continue
        assert parameter.annotation is not inspect.Parameter.empty
        assert name in expected_params


def test_skill_methods_generate_get_skills_schemas(module: AgenticManipulationModule) -> None:
    skills = {skill.func_name: skill for skill in module.get_skills()}

    assert set(skills) == {"close_gripper", "get_robot_state", "move_to_joints", "open_gripper"}
    for method_name in skills:
        schema = json.loads(skills[method_name].args_schema)
        assert schema["type"] == "object"
        assert "properties" in schema
    move_schema = json.loads(skills["move_to_joints"].args_schema)
    assert "joints" in move_schema["properties"]
    assert "robot_name" in move_schema["properties"]
    assert move_schema["required"] == ["joints"]
