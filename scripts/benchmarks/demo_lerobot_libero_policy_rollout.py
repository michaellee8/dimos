#!/usr/bin/env python3
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

"""Run the LeRobot VLA-JEPA LIBERO policy rollout gate through DimOS seams.

The default run evaluates the official `lerobot/VLA-JEPA-LIBERO` checkpoint over
the 50-episode LIBERO object matrix: task indices 0..9 crossed with init states
0..4. The pass condition is strict: success_rate > 0.50.

For a lightweight native-action smoke test that does not download LeRobot, pass
`--fake-backend --episodes-limit 1 --no-enforce-gate`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import asdict, is_dataclass
from io import BytesIO
import json
from pathlib import Path
import sys
import traceback
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SRC = REPO_ROOT / "packages" / "dimos-runtime-protocol" / "src"
LIBERO_PRO_SIDECAR_SRC = REPO_ROOT / "packages" / "dimos-libero-pro-sidecar" / "src"

for package_src in (PROTOCOL_SRC, LIBERO_PRO_SIDECAR_SRC):
    sys.path.insert(0, str(package_src))

from dimos_libero_pro_sidecar.blueprint import libero_pro_runtime_blueprint
from dimos_libero_pro_sidecar.module import LiberoProRuntimeModule
from dimos_libero_pro_sidecar.server import discover_libero_asset_roots
from dimos_runtime_protocol import (
    EpisodeResetRequest,
    EpisodeResetResponse,
    ObservationFrame,
    ObservationKind,
    StepRequest,
    StepResponse,
)
import numpy as np

from dimos.benchmark.runtime.artifacts import write_json
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.robot_learning.policy_rollout.backends.backend import PolicyBackend
from dimos.robot_learning.policy_rollout.evaluation import (
    BenchmarkEpisodeResult,
    BenchmarkEpisodeSpec,
    BenchmarkEvaluationSummary,
    BenchmarkPolicyEvalModule,
    libero_object_episode_matrix,
)
from dimos.robot_learning.policy_rollout.models import (
    BackendBatch,
    BackendOutputEnvelope,
    PolicyBackendDescription,
)
from dimos.robot_learning.policy_rollout.robot_policy_module import RobotPolicyModule
from dimos.robot_learning.policy_rollout.vla_jepa_libero_contract import (
    VlaJepaLiberoRobotContract,
)

DEFAULT_CAMERAS = ("agentview", "robot0_eye_in_hand")
DEFAULT_CHECKPOINT = "lerobot/VLA-JEPA-LIBERO"
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "artifacts" / "benchmark" / "lerobot-vla-jepa-libero"


class DescribedPolicyModule(Protocol):
    def describe_backend(self) -> PolicyBackendDescription: ...


class _Subscribable(Protocol):
    def subscribe(self, cb: Callable[..., object]) -> object: ...


class _ImageMessage(Protocol):
    data: object
    frame_id: str


class _LiberoProRuntime(Protocol):
    color_image: _Subscribable
    runtime_event: _Subscribable

    def reset(self, request: EpisodeResetRequest) -> EpisodeResetResponse: ...

    def step(self, request: StepRequest) -> StepResponse: ...

    def stop(self) -> None: ...


class FixedActionBackend:
    """PolicyBackend test double that exercises contract conversion without LeRobot."""

    def __init__(self, action: Sequence[float]) -> None:
        if len(action) != 7:
            raise ValueError("fixed action must have exactly 7 values")
        self._action = tuple(float(value) for value in action)
        self._initialized = False
        self._episode_resets = 0

    def initialize(self) -> None:
        self._initialized = True

    def reset_episode(self) -> None:
        self._episode_resets += 1

    def infer_batch(self, batch: BackendBatch) -> BackendOutputEnvelope:
        if not self._initialized:
            raise RuntimeError("FixedActionBackend was not initialized")
        return BackendOutputEnvelope(
            output=self._action,
            metadata={
                "backend_type": "fixed_action",
                "batch_metadata": dict(batch.metadata),
                "episode_resets": self._episode_resets,
            },
        )

    def close(self) -> None:
        self._initialized = False

    def describe(self) -> PolicyBackendDescription:
        return PolicyBackendDescription(
            backend_type="fixed_action",
            checkpoint_id=None,
            supports_episode_reset=True,
            metadata={"action": list(self._action), "episode_resets": self._episode_resets},
        )


class ModuleLiberoRuntimeClient:
    """Runtime-client surface backed by the placed LIBERO runtime module."""

    def __init__(self, runtime: _LiberoProRuntime, coordinator: ModuleCoordinator) -> None:
        self._runtime = runtime
        self._coordinator = coordinator
        self._images: list[_ImageMessage] = []
        self._runtime_events: list[ObservationFrame] = []
        self._payloads: dict[str, bytes] = {}
        runtime.color_image.subscribe(self._images.append)
        runtime.runtime_event.subscribe(self._record_runtime_event)

    def reset(self, request: EpisodeResetRequest) -> EpisodeResetResponse:
        response = self._runtime.reset(request)
        return response.model_copy(update={"observations": self._take_observations(0)})

    def step(self, request: StepRequest) -> StepResponse:
        response = self._runtime.step(request)
        return response.model_copy(
            update={"observations": self._take_observations(request.tick_id)}
        )

    def payload(self, data_ref: str) -> bytes:
        return self._payloads[data_ref.removeprefix("/payloads/")]

    def close(self) -> None:
        self._coordinator.stop()

    def _record_runtime_event(self, event: object) -> None:
        if isinstance(event, ObservationFrame):
            self._runtime_events.append(event)

    def _take_observations(self, tick_id: int) -> list[ObservationFrame]:
        observations = self._runtime_events
        self._runtime_events = []
        images = self._images
        self._images = []
        for image in images:
            frame_id = image.frame_id or "camera"
            array = np.asarray(image.data)
            payload_id = f"{frame_id}-{tick_id:06d}-{len(self._payloads):06d}.npy"
            payload = _npy_bytes(array)
            self._payloads[payload_id] = payload
            observations.append(
                ObservationFrame(
                    stream=frame_id,
                    kind=ObservationKind.IMAGE,
                    encoding="npy",
                    shape=[int(item) for item in array.shape],
                    dtype=str(array.dtype),
                    data_ref=f"/payloads/{payload_id}",
                    metadata={
                        "camera_name": frame_id,
                        "image_convention": "opengl",
                        "payload_bytes": len(payload),
                    },
                )
            )
        return observations


def run_policy_gate(args: argparse.Namespace) -> BenchmarkEvaluationSummary:
    artifact_dir = _repo_path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    episodes = _selected_episodes(args.episodes_limit)
    policy_module = _policy_module(args)
    results: list[BenchmarkEpisodeResult] = []
    cleanup: dict[str, object] = {"episodes": []}
    try:
        for episode in episodes:
            episode_dir = artifact_dir / "episodes" / episode.episode_id
            result = _run_one_episode(args, episode, policy_module, episode_dir, cleanup)
            results.append(result)
        summary = _summary(results, args.success_threshold)
        _write_aggregate_artifacts(artifact_dir, results, summary, policy_module, args, cleanup)
        if args.enforce_gate and not summary.passed:
            raise SystemExit(
                f"LeRobot LIBERO policy gate failed: "
                f"success_rate={summary.success_rate:.3f} <= {summary.success_threshold:.3f}"
            )
        return summary
    except Exception as exc:
        _write_setup_failure_artifacts(artifact_dir, policy_module, args, cleanup, exc)
        raise
    finally:
        policy_module.close()


def _run_one_episode(
    args: argparse.Namespace,
    episode: BenchmarkEpisodeSpec,
    policy_module: RobotPolicyModule,
    episode_dir: Path,
    cleanup: dict[str, object],
) -> BenchmarkEpisodeResult:
    client = _start_runtime(args, episode)
    cleanup_entry: dict[str, object] = {
        "episode_id": episode.episode_id,
        "runtime": "module-native",
    }
    cast_cleanup = cleanup.setdefault("episodes", [])
    if isinstance(cast_cleanup, list):
        cast_cleanup.append(cleanup_entry)
    try:
        eval_module = BenchmarkPolicyEvalModule(
            runtime_client=client,
            robot_policy_module=policy_module,
            artifact_dir=str(episode_dir),
            max_steps=args.max_steps,
            success_threshold=args.success_threshold,
            close_policy_on_finish=False,
            video_dir=str(episode_dir / "videos") if args.save_videos else None,
            video_streams=args.camera_names if args.save_videos else (),
            video_fps=args.control_step_hz,
        )
        try:
            eval_module.run_episodes([episode])
            if not eval_module.last_results:
                raise RuntimeError(f"episode {episode.episode_id} produced no result")
            return eval_module.last_results[0]
        finally:
            eval_module.close()
    finally:
        _stop_runtime(client, episode_dir, cleanup_entry)


def _selected_episodes(limit: int | None) -> list[BenchmarkEpisodeSpec]:
    episodes = libero_object_episode_matrix()
    return episodes if limit is None else episodes[:limit]


def _policy_module(args: argparse.Namespace) -> RobotPolicyModule:
    backend: PolicyBackend
    if args.fake_backend:
        backend = FixedActionBackend(_fixed_action_values(args.fixed_action))
        return RobotPolicyModule(backend=backend, contract=VlaJepaLiberoRobotContract())
    else:
        return RobotPolicyModule(
            backend_type="lerobot",
            backend_params={"checkpoint_id": args.checkpoint, "device": args.device},
            contract_type="vla_jepa_libero",
            contract_params={},
        )


def _start_runtime(
    args: argparse.Namespace, episode: BenchmarkEpisodeSpec
) -> ModuleLiberoRuntimeClient:
    blueprint = libero_pro_runtime_blueprint(
        bddl_root=args.bddl_root,
        init_states_root=args.init_states_root,
        benchmark_name="libero_object",
        robot_id="panda",
        task_order_index=0,
        task_index=episode.task_index,
        init_state_index=episode.init_state_index,
        action_mode="native",
        camera_names=tuple(args.camera_names),
        camera_height=args.camera_height,
        camera_width=args.camera_width,
        control_freq=args.control_step_hz,
        horizon=args.max_steps,
        seed=args.seed,
        allow_asset_bootstrap=args.allow_asset_bootstrap,
        visualize=args.visualize,
    ).global_config(viewer="none", n_workers=1)
    coordinator = ModuleCoordinator.build(blueprint)
    runtime = coordinator.get_instance(LiberoProRuntimeModule)
    return ModuleLiberoRuntimeClient(runtime, coordinator)


def _stop_runtime(
    client: ModuleLiberoRuntimeClient, episode_dir: Path, cleanup_entry: dict[str, object]
) -> None:
    client.close()
    episode_dir.mkdir(parents=True, exist_ok=True)
    cleanup_entry["runtime_stopped"] = True


def _summary(
    results: Sequence[BenchmarkEpisodeResult], success_threshold: float
) -> BenchmarkEvaluationSummary:
    successes = sum(1 for result in results if result.success)
    success_rate = successes / len(results) if results else 0.0
    return BenchmarkEvaluationSummary(
        episodes=len(results),
        successes=successes,
        success_rate=success_rate,
        success_threshold=success_threshold,
        passed=success_rate > success_threshold,
    )


def _write_aggregate_artifacts(
    artifact_dir: Path,
    results: Sequence[BenchmarkEpisodeResult],
    summary: BenchmarkEvaluationSummary,
    policy_module: DescribedPolicyModule,
    args: argparse.Namespace,
    cleanup: dict[str, object],
) -> None:
    write_json(artifact_dir / "summary.json", _json_ready(summary))
    _write_jsonl(artifact_dir / "episodes.jsonl", results)
    write_json(
        artifact_dir / "checkpoint_metadata.json", _json_ready(policy_module.describe_backend())
    )
    if results:
        _copy_if_present(
            artifact_dir / "episodes" / results[0].episode_id / "runtime_description.json",
            artifact_dir / "runtime_description.json",
        )
    write_json(
        artifact_dir / "run_config.json",
        {
            "checkpoint": args.checkpoint,
            "fake_backend": args.fake_backend,
            "episodes": len(results),
            "expected_gate_episodes": 50,
            "success_threshold": args.success_threshold,
            "enforce_gate": args.enforce_gate,
            "save_videos": args.save_videos,
            "video_streams": list(args.camera_names) if args.save_videos else [],
            "camera_names": list(args.camera_names),
            "camera_height": args.camera_height,
            "camera_width": args.camera_width,
            "max_steps": args.max_steps,
            "bddl_root": str(args.bddl_root),
            "init_states_root": str(args.init_states_root),
        },
    )
    write_json(artifact_dir / "cleanup_status.json", cleanup)


def _write_setup_failure_artifacts(
    artifact_dir: Path,
    policy_module: DescribedPolicyModule,
    args: argparse.Namespace,
    cleanup: dict[str, object],
    exc: Exception,
) -> None:
    write_json(
        artifact_dir / "setup_error.json",
        {
            "error_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "gate_verified": False,
            "policy_executed": False,
            "expected_gate_episodes": 50,
            "success_threshold": args.success_threshold,
            "hint": "Check per-episode sidecar logs and prepare LIBERO assets before rerunning.",
        },
    )
    write_json(
        artifact_dir / "checkpoint_metadata.json", _json_ready(policy_module.describe_backend())
    )
    write_json(
        artifact_dir / "run_config.json",
        {
            "checkpoint": args.checkpoint,
            "fake_backend": args.fake_backend,
            "expected_gate_episodes": 50,
            "success_threshold": args.success_threshold,
            "enforce_gate": args.enforce_gate,
            "save_videos": args.save_videos,
            "video_streams": list(args.camera_names) if args.save_videos else [],
            "camera_names": list(args.camera_names),
            "camera_height": args.camera_height,
            "camera_width": args.camera_width,
            "max_steps": args.max_steps,
            "bddl_root": str(args.bddl_root),
            "init_states_root": str(args.init_states_root),
            "allow_asset_bootstrap": args.allow_asset_bootstrap,
        },
    )
    write_json(artifact_dir / "cleanup_status.json", cleanup)


def _fixed_action_values(raw: str) -> tuple[float, ...]:
    values = tuple(float(value.strip()) for value in raw.split(",") if value.strip())
    if len(values) != 7:
        raise ValueError("--fixed-action must contain exactly 7 comma-separated values")
    return values


def _repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _resolve_asset_roots(
    bddl_root: Path | None, init_states_root: Path | None
) -> tuple[Path, Path]:
    explicit_bddl = _repo_path(bddl_root) if bddl_root is not None else None
    explicit_init = _repo_path(init_states_root) if init_states_root is not None else None
    if explicit_bddl is not None and explicit_init is not None:
        return explicit_bddl, explicit_init
    discovered = discover_libero_asset_roots()
    if discovered is None:
        raise SystemExit(
            "LIBERO assets were not provided and could not be discovered. Install the "
            "standard libero package or pass --bddl-root and --init-states-root."
        )
    discovered_bddl, discovered_init = discovered
    return explicit_bddl or discovered_bddl, explicit_init or discovered_init


def _write_jsonl(path: Path, rows: Sequence[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(_json_ready(row), sort_keys=True) + "\n" for row in rows))


def _copy_if_present(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _npy_bytes(value: object) -> bytes:
    buffer = BytesIO()
    np.save(buffer, np.asarray(value), allow_pickle=False)
    return buffer.getvalue()


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--runtime-host", default="127.0.0.1")
    parser.add_argument("--runtime-port", type=int, default=0)
    parser.add_argument("--startup-timeout-s", type=float, default=20.0)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument("--control-step-hz", type=int, default=20)
    parser.add_argument("--success-threshold", type=float, default=0.50)
    parser.add_argument("--checkpoint", default=DEFAULT_CHECKPOINT)
    parser.add_argument("--device", default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--episodes-limit", type=int, default=None)
    parser.add_argument("--no-enforce-gate", dest="enforce_gate", action="store_false")
    parser.set_defaults(enforce_gate=True)
    parser.add_argument("--fake-backend", action="store_true")
    parser.add_argument("--fixed-action", default="0,0,0,0,0,0,0")
    parser.add_argument("--camera-name", action="append", dest="camera_names")
    parser.add_argument("--camera-height", type=int, default=128)
    parser.add_argument("--camera-width", type=int, default=128)
    parser.add_argument("--bddl-root", type=Path, default=None)
    parser.add_argument("--init-states-root", type=Path, default=None)
    parser.add_argument("--allow-asset-bootstrap", action="store_true")
    parser.add_argument("--visualize", action="store_true")
    parser.add_argument(
        "--save-videos",
        action="store_true",
        help="Reserve video artifacts for real runs; full videos/images are not saved by default.",
    )
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    args.camera_names = tuple(args.camera_names or DEFAULT_CAMERAS)
    args.bddl_root, args.init_states_root = _resolve_asset_roots(
        args.bddl_root, args.init_states_root
    )
    summary = run_policy_gate(args)
    print(
        f"episodes={summary.episodes} successes={summary.successes} "
        f"success_rate={summary.success_rate:.3f} passed={summary.passed}"
    )


if __name__ == "__main__":
    main()
