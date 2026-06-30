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

from dataclasses import dataclass, field
from io import BytesIO
import json
from pathlib import Path

from dimos_runtime_protocol import (
    EpisodeResetRequest,
    EpisodeResetResponse,
    MotorStateFrame,
    ObservationFrame,
    ObservationKind,
    RuntimeDescription,
    StepRequest,
    StepResponse,
)
import numpy as np
import pytest
from pytest_mock import MockerFixture

from dimos.robot_learning.policy_rollout.evaluation import (
    BenchmarkEpisodeSpec,
    BenchmarkPolicyEvalRunner,
    RuntimeObservationSample,
)
from dimos.robot_learning.policy_rollout.models import (
    PolicyBackendDescription,
    RobotPolicyContractDescription,
    RuntimeActionOutput,
)


@dataclass
class FakeRuntimeClient:
    success_by_episode: dict[str, bool]
    reset_requests: list[EpisodeResetRequest] = field(default_factory=list)
    step_requests: list[StepRequest] = field(default_factory=list)

    def reset(self, request: EpisodeResetRequest) -> EpisodeResetResponse:
        self.reset_requests.append(request)
        return EpisodeResetResponse(
            episode_id=request.episode_id,
            runtime_description=_runtime_description(),
            observations=[_observation("agentview")],
        )

    def step(self, request: StepRequest) -> StepResponse:
        self.step_requests.append(request)
        success = self.success_by_episode[request.episode_id]
        return StepResponse(
            episode_id=request.episode_id,
            tick_id=request.tick_id,
            motor_state=MotorStateFrame(robot_id="panda", names=[], q=[], dq=[], tau=[]),
            observations=[_observation("agentview"), _observation("eye_in_hand")],
            reward=1.0 if success else 0.0,
            done=True,
            success=success,
        )

    def payload(self, data_ref: str) -> bytes:
        del data_ref
        buffer = BytesIO()
        np.save(buffer, np.zeros((4, 4, 3), dtype=np.uint8), allow_pickle=False)
        return buffer.getvalue()


@dataclass
class FakeRobotPolicyModule:
    fail_on_infer: bool = False
    reset_episode_ids: list[str | None] = field(default_factory=list)
    samples: list[RuntimeObservationSample] = field(default_factory=list)
    closed: bool = False

    def reset(self, episode_id: str | None = None) -> None:
        self.reset_episode_ids.append(episode_id)

    def infer_action(self, sample: RuntimeObservationSample) -> RuntimeActionOutput:
        if self.fail_on_infer:
            raise ValueError("contract mismatch")
        self.samples.append(sample)
        return RuntimeActionOutput(
            space_id="libero.ee_delta_6d_gripper.normalized.v1",
            values=(0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0),
        )

    def close(self) -> None:
        self.closed = True

    def describe_backend(self) -> PolicyBackendDescription:
        return PolicyBackendDescription(
            backend_type="fake", checkpoint_id="lerobot/VLA-JEPA-LIBERO"
        )

    def describe_contract(self) -> RobotPolicyContractDescription:
        return RobotPolicyContractDescription(contract_type="fake-contract")


def test_runner_owns_runtime_reset_step_policy_reset_and_artifacts(tmp_path: Path) -> None:
    runtime = FakeRuntimeClient(success_by_episode={"ep-0": True})
    policy = FakeRobotPolicyModule()
    runner = BenchmarkPolicyEvalRunner(
        runtime_client=runtime,
        robot_policy_module=policy,  # type: ignore[arg-type]
        artifact_dir=tmp_path,
        max_steps=3,
    )

    summary = runner.run(
        [
            BenchmarkEpisodeSpec(
                episode_id="ep-0",
                task_id="libero_object",
                task_index=0,
                init_state_index=1,
                seed=7,
            )
        ]
    )

    assert summary.episodes == 1
    assert summary.successes == 1
    assert summary.passed
    assert policy.reset_episode_ids == ["ep-0"]
    assert policy.closed
    assert runtime.reset_requests[0].options["task_index"] == 0
    assert runtime.reset_requests[0].options["init_state_index"] == 1
    assert len(runtime.step_requests) == 1
    action = runtime.step_requests[0].action
    assert action.frame_type == "runtime_action"
    assert action.tick_id == 0
    assert action.space_id == "libero.ee_delta_6d_gripper.normalized.v1"
    assert policy.samples[0].observations[0].stream == "agentview"

    summary_json = json.loads((tmp_path / "summary.json").read_text())
    assert summary_json["success_rate"] == 1.0
    assert (tmp_path / "runtime_description.json").exists()
    assert (tmp_path / "contract_description.json").exists()
    assert (tmp_path / "checkpoint_metadata.json").exists()
    episode_records = (tmp_path / "episodes.jsonl").read_text().splitlines()
    assert len(episode_records) == 1
    assert json.loads(episode_records[0])["action_shape"] == [7]


def test_runner_continues_after_policy_episode_failure(tmp_path: Path) -> None:
    runtime = FakeRuntimeClient(success_by_episode={"ep-0": False, "ep-1": True})
    policy = FakeRobotPolicyModule()
    runner = BenchmarkPolicyEvalRunner(
        runtime_client=runtime,
        robot_policy_module=policy,  # type: ignore[arg-type]
        artifact_dir=tmp_path,
        max_steps=1,
    )

    summary = runner.run(
        [
            BenchmarkEpisodeSpec("ep-0", "libero_object", 0, 0),
            BenchmarkEpisodeSpec("ep-1", "libero_object", 1, 0),
        ]
    )

    assert summary.episodes == 2
    assert summary.successes == 1
    assert not summary.passed
    assert [request.episode_id for request in runtime.reset_requests] == ["ep-0", "ep-1"]
    assert [request.episode_id for request in runtime.step_requests] == ["ep-0", "ep-1"]
    episode_records = [
        json.loads(line) for line in (tmp_path / "episodes.jsonl").read_text().splitlines()
    ]
    assert episode_records[0]["failure_reason"] == "done_without_success"
    assert episode_records[1]["success"] is True


def test_runner_aborts_setup_or_contract_error(tmp_path: Path) -> None:
    runtime = FakeRuntimeClient(success_by_episode={"ep-0": True})
    policy = FakeRobotPolicyModule(fail_on_infer=True)
    runner = BenchmarkPolicyEvalRunner(
        runtime_client=runtime,
        robot_policy_module=policy,  # type: ignore[arg-type]
        artifact_dir=tmp_path,
        max_steps=1,
    )

    with pytest.raises(ValueError, match="contract mismatch"):
        runner.run([BenchmarkEpisodeSpec("ep-0", "libero_object", 0, 0)])

    assert len(runtime.step_requests) == 0
    assert policy.closed


def test_runner_writes_video_frames_when_enabled(tmp_path: Path, mocker: MockerFixture) -> None:
    video_writer = mocker.patch("dimos.robot_learning.policy_rollout.evaluation.imageio.mimsave")
    runtime = FakeRuntimeClient(success_by_episode={"ep-0": True})
    policy = FakeRobotPolicyModule()
    runner = BenchmarkPolicyEvalRunner(
        runtime_client=runtime,
        robot_policy_module=policy,  # type: ignore[arg-type]
        artifact_dir=tmp_path,
        max_steps=1,
        video_dir=tmp_path / "videos",
        video_streams=("agentview",),
        video_fps=12,
    )

    runner.run([BenchmarkEpisodeSpec("ep-0", "libero_object", 0, 0)])

    video_writer.assert_called_once()
    assert video_writer.call_args.args[0] == tmp_path / "videos" / "ep-0" / "agentview.mp4"
    assert len(video_writer.call_args.args[1]) == 1
    assert video_writer.call_args.kwargs["fps"] == 12


def _runtime_description() -> RuntimeDescription:
    return RuntimeDescription(
        runtime_id="libero-pro",
        backend="libero-pro",
        capabilities=["native-runtime-action"],
        robot_surfaces=[],
        control_step_hz=20,
        observation_streams=["agentview", "eye_in_hand", "robot_state"],
        metadata={"language": "pick up the object"},
    )


def _observation(stream: str) -> ObservationFrame:
    return ObservationFrame(
        stream=stream,
        kind=ObservationKind.IMAGE,
        shape=[128, 128, 3],
        dtype="uint8",
        data_ref=f"/payloads/{stream}.npy",
    )
