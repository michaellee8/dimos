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

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from io import BytesIO
import json
from pathlib import Path
from typing import Protocol, cast

from dimos_runtime_protocol import (
    EpisodeResetRequest,
    EpisodeResetResponse,
    ObservationFrame,
    RuntimeActionFrame,
    RuntimeDescription,
    StepRequest,
    StepResponse,
)
import imageio.v2 as imageio
import numpy as np

from dimos.benchmark.runtime.artifacts import write_json
from dimos.robot_learning.policy_rollout.models import (
    JsonObject,
    RuntimeActionOutput,
)
from dimos.robot_learning.policy_rollout.robot_policy_module import RobotPolicyModule


@dataclass(frozen=True)
class BenchmarkEpisodeSpec:
    """One benchmark episode selected by the evaluation runner."""

    episode_id: str
    task_id: str
    task_index: int
    init_state_index: int
    seed: int | None = None
    options: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeObservationSample:
    """Sidecar observation sample passed to a robot policy module."""

    episode_id: str
    tick_id: int
    task_id: str
    task_index: int
    init_state_index: int
    observations: tuple[ObservationFrame, ...]
    runtime_description: RuntimeDescription
    reward: float = 0.0
    done: bool = False
    success: bool | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkEpisodeResult:
    """Serializable per-episode policy evaluation artifact."""

    episode_id: str
    task_id: str
    task_index: int
    init_state_index: int
    success: bool
    steps: int
    reward_sum: float
    done: bool
    failure_reason: str | None
    action_shape: tuple[int, ...]
    action_min: float | None
    action_max: float | None
    observed_streams: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkEvaluationSummary:
    """Serializable aggregate policy evaluation artifact."""

    episodes: int
    successes: int
    success_rate: float
    success_threshold: float
    passed: bool


class RuntimeClient(Protocol):
    """Subset of RuntimeSidecarClient used by policy evaluation."""

    def reset(self, request: EpisodeResetRequest) -> EpisodeResetResponse: ...

    def step(self, request: StepRequest) -> StepResponse: ...

    def payload(self, data_ref: str) -> bytes: ...


class BenchmarkPolicyEvalRunner:
    """Own benchmark lifecycle and execute robot-policy actions through runtime client.

    RobotPolicyModule owns inference only. This runner owns episode selection,
    runtime reset/step timing, policy reset calls, metrics, success gates, and
    artifact output.
    """

    def __init__(
        self,
        *,
        runtime_client: RuntimeClient,
        robot_policy_module: RobotPolicyModule[RuntimeObservationSample],
        artifact_dir: Path,
        max_steps: int,
        success_threshold: float = 0.50,
        close_policy_on_finish: bool = True,
        video_dir: Path | None = None,
        video_streams: Sequence[str] = (),
        video_fps: int = 20,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if video_fps <= 0:
            raise ValueError("video_fps must be positive")
        self._runtime_client = runtime_client
        self._robot_policy_module = robot_policy_module
        self._artifact_dir = artifact_dir
        self._max_steps = max_steps
        self._success_threshold = success_threshold
        self._close_policy_on_finish = close_policy_on_finish
        self._video_dir = video_dir
        self._video_streams = tuple(video_streams)
        self._video_fps = video_fps
        self._last_results: tuple[BenchmarkEpisodeResult, ...] = ()

    @property
    def last_results(self) -> tuple[BenchmarkEpisodeResult, ...]:
        """Most recent episode results written by this runner."""

        return self._last_results

    def run(self, episodes: Sequence[BenchmarkEpisodeSpec]) -> BenchmarkEvaluationSummary:
        """Run all episodes and write required benchmark artifacts."""

        results: list[BenchmarkEpisodeResult] = []
        runtime_description: RuntimeDescription | None = None
        try:
            for episode in episodes:
                result, runtime_description = self._run_episode(episode)
                results.append(result)
        finally:
            if self._close_policy_on_finish:
                self._robot_policy_module.close()

        self._last_results = tuple(results)
        summary = self._summary(results)
        self._write_artifacts(results, summary, runtime_description)
        return summary

    def _run_episode(
        self, episode: BenchmarkEpisodeSpec
    ) -> tuple[BenchmarkEpisodeResult, RuntimeDescription]:
        reset_response = self._runtime_client.reset(
            EpisodeResetRequest(
                episode_id=episode.episode_id,
                task_id=episode.task_id,
                seed=episode.seed,
                options={
                    **dict(episode.options),
                    "task_index": episode.task_index,
                    "init_state_index": episode.init_state_index,
                },
            )
        )
        self._robot_policy_module.reset(episode_id=episode.episode_id)

        runtime_description = reset_response.runtime_description
        observations = tuple(reset_response.observations)
        reward_sum = 0.0
        done = False
        success: bool | None = None
        failure_reason: str | None = None
        last_action: RuntimeActionOutput | None = None
        observed_streams: tuple[str, ...] = tuple(frame.stream for frame in observations)
        video_frames: dict[str, list[np.ndarray]] = {stream: [] for stream in self._video_streams}
        steps = 0

        for tick_id in range(self._max_steps):
            payloads = self._payloads(observations)
            self._append_video_frames(video_frames, payloads)
            sample = RuntimeObservationSample(
                episode_id=episode.episode_id,
                tick_id=tick_id,
                task_id=episode.task_id,
                task_index=episode.task_index,
                init_state_index=episode.init_state_index,
                observations=observations,
                runtime_description=runtime_description,
                reward=reward_sum,
                done=done,
                success=success,
                metadata={"payloads": payloads},
            )
            action = self._robot_policy_module.infer_action(sample)
            frame = _runtime_action_frame(action, tick_id=tick_id)
            step_response = self._runtime_client.step(
                StepRequest(
                    episode_id=episode.episode_id,
                    tick_id=tick_id,
                    action=frame,
                )
            )
            steps = tick_id + 1
            last_action = action
            reward_sum += step_response.reward
            done = step_response.done
            success = step_response.success
            observations = tuple(step_response.observations)
            observed_streams = tuple(frame.stream for frame in observations)
            if done:
                break

        episode_success = bool(success)
        if not episode_success:
            failure_reason = "done_without_success" if done else "max_steps_without_success"

        action_values = last_action.values if last_action is not None else ()
        self._write_videos(episode.episode_id, video_frames)
        return BenchmarkEpisodeResult(
            episode_id=episode.episode_id,
            task_id=episode.task_id,
            task_index=episode.task_index,
            init_state_index=episode.init_state_index,
            success=episode_success,
            steps=steps,
            reward_sum=reward_sum,
            done=done,
            failure_reason=failure_reason,
            action_shape=(len(action_values),),
            action_min=min(action_values) if action_values else None,
            action_max=max(action_values) if action_values else None,
            observed_streams=observed_streams,
        ), runtime_description

    def _append_video_frames(
        self, video_frames: dict[str, list[np.ndarray]], payloads: dict[str, object]
    ) -> None:
        for stream in self._video_streams:
            payload = payloads.get(stream)
            if not isinstance(payload, np.ndarray):
                continue
            if payload.ndim != 3 or payload.shape[2] != 3:
                continue
            video_frames[stream].append(payload.astype(np.uint8, copy=False))

    def _write_videos(self, episode_id: str, video_frames: dict[str, list[np.ndarray]]) -> None:
        if self._video_dir is None:
            return
        for stream, frames in video_frames.items():
            if not frames:
                continue
            stream_name = stream.replace("/", "_")
            video_path = self._video_dir / episode_id / f"{stream_name}.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            imageio.mimsave(video_path, frames, fps=self._video_fps)  # type: ignore[arg-type]

    def _summary(self, results: Sequence[BenchmarkEpisodeResult]) -> BenchmarkEvaluationSummary:
        successes = sum(1 for result in results if result.success)
        success_rate = successes / len(results) if results else 0.0
        return BenchmarkEvaluationSummary(
            episodes=len(results),
            successes=successes,
            success_rate=success_rate,
            success_threshold=self._success_threshold,
            passed=success_rate > self._success_threshold,
        )

    def _write_artifacts(
        self,
        results: Sequence[BenchmarkEpisodeResult],
        summary: BenchmarkEvaluationSummary,
        runtime_description: RuntimeDescription | None,
    ) -> None:
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        write_json(self._artifact_dir / "summary.json", _json_ready(summary))
        if runtime_description is not None:
            write_json(self._artifact_dir / "runtime_description.json", runtime_description)
        write_json(
            self._artifact_dir / "contract_description.json",
            _json_ready(self._robot_policy_module.describe_contract()),
        )
        write_json(
            self._artifact_dir / "checkpoint_metadata.json",
            _json_ready(self._robot_policy_module.describe_backend()),
        )
        _write_jsonl(self._artifact_dir / "episodes.jsonl", results)

    def _payloads(self, observations: Sequence[ObservationFrame]) -> dict[str, object]:
        payload_reader = cast(
            "Callable[[str], bytes] | None", getattr(self._runtime_client, "payload", None)
        )
        if payload_reader is None:
            return {}
        values: dict[str, object] = {}
        for frame in observations:
            if frame.data_ref is None:
                continue
            values[frame.stream] = np.load(
                BytesIO(payload_reader(frame.data_ref)), allow_pickle=False
            )
        return values


def libero_object_episode_matrix(
    *, init_state_indices: Sequence[int] = (0, 1, 2, 3, 4)
) -> list[BenchmarkEpisodeSpec]:
    """Return the required 50-episode LIBERO object gate matrix."""

    return [
        BenchmarkEpisodeSpec(
            episode_id=f"libero_object_task{task_index}_init{init_state_index}",
            task_id="libero_object",
            task_index=task_index,
            init_state_index=init_state_index,
        )
        for task_index in range(10)
        for init_state_index in init_state_indices
    ]


def _runtime_action_frame(action: RuntimeActionOutput, *, tick_id: int) -> RuntimeActionFrame:
    return RuntimeActionFrame(
        frame_type="runtime_action",
        space_id=action.space_id,
        values=list(action.values),
        sequence=action.sequence,
        tick_id=tick_id if action.sequence is None else None,
    )


def _write_jsonl(path: Path, rows: Sequence[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(_json_ready(row), sort_keys=True) + "\n" for row in rows))


def _json_ready(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
