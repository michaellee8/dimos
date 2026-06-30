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

from dimos_runtime_protocol import ObservationFrame, ObservationKind, RuntimeDescription
import numpy as np
import pytest

from dimos.robot_learning.policy_rollout.evaluation import RuntimeObservationSample
from dimos.robot_learning.policy_rollout.models import BackendOutputEnvelope
from dimos.robot_learning.policy_rollout.vla_jepa_libero_contract import (
    VLA_JEPA_LIBERO_ACTION_SPACE_ID,
    VlaJepaLiberoRobotContract,
)


def test_contract_converts_runtime_sample_to_backend_batch() -> None:
    contract = VlaJepaLiberoRobotContract()
    sample = _sample()

    batch = contract.to_backend_batch(sample)

    assert batch.payload["observation.images.image"].shape == (128, 128, 3)
    assert batch.payload["observation.images.image2"].shape == (128, 128, 3)
    assert batch.payload["observation.state"].shape == (8,)
    assert batch.payload["task"] == "pick up the object"
    assert batch.metadata["agentview_stream"] == "agentview"
    assert batch.metadata["wrist_stream"] == "eye_in_hand"


def test_contract_rejects_missing_or_wrong_inputs() -> None:
    contract = VlaJepaLiberoRobotContract()
    with pytest.raises(ValueError, match="wrist"):
        contract.to_backend_batch(_sample(streams=("agentview", "robot_state")))
    with pytest.raises(ValueError, match="dtype uint8"):
        contract.to_backend_batch(_sample(agentview=np.zeros((128, 128, 3), dtype=np.float32)))
    with pytest.raises(ValueError, match=r"shape \(8,\)"):
        contract.to_backend_batch(_sample(state=[0.0] * 7))
    with pytest.raises(ValueError, match="task language"):
        contract.to_backend_batch(_sample(language=""))


def test_contract_converts_backend_output_to_runtime_action() -> None:
    contract = VlaJepaLiberoRobotContract()

    action = contract.from_backend_output(
        BackendOutputEnvelope(output=np.array([[0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0]]))
    )

    assert action.space_id == VLA_JEPA_LIBERO_ACTION_SPACE_ID
    assert action.values == pytest.approx((0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0))


def test_contract_rejects_invalid_backend_output() -> None:
    contract = VlaJepaLiberoRobotContract()
    with pytest.raises(ValueError, match="shape"):
        contract.from_backend_output(BackendOutputEnvelope(output=[0.0] * 6))
    with pytest.raises(ValueError, match="non-finite"):
        contract.from_backend_output(BackendOutputEnvelope(output=[0.0] * 6 + [float("nan")]))
    with pytest.raises(ValueError, match="within"):
        contract.from_backend_output(BackendOutputEnvelope(output=[0.0] * 6 + [2.0]))


def test_contract_description_documents_expected_io() -> None:
    description = VlaJepaLiberoRobotContract().describe()

    assert description.contract_type == "vla_jepa_libero"
    assert description.output_description["space_id"] == VLA_JEPA_LIBERO_ACTION_SPACE_ID
    assert description.input_description["state_shape"] == [8]


def _sample(
    *,
    streams: tuple[str, ...] = ("agentview", "eye_in_hand", "robot_state"),
    agentview: np.ndarray | None = None,
    wrist: np.ndarray | None = None,
    state: list[float] | None = None,
    language: str = "pick up the object",
) -> RuntimeObservationSample:
    agentview_payload = (
        agentview if agentview is not None else np.zeros((128, 128, 3), dtype=np.uint8)
    )
    wrist_payload = wrist if wrist is not None else np.ones((128, 128, 3), dtype=np.uint8)
    state_values = state if state is not None else [0.0] * 8
    frames = []
    payloads: dict[str, object] = {}
    if "agentview" in streams:
        frames.append(_image_frame("agentview"))
        payloads["agentview"] = agentview_payload
    if "eye_in_hand" in streams:
        frames.append(_image_frame("eye_in_hand"))
        payloads["eye_in_hand"] = wrist_payload
    if "robot_state" in streams:
        frames.append(
            ObservationFrame(
                stream="robot_state",
                kind=ObservationKind.STATE,
                metadata={"state": state_values},
            )
        )
    return RuntimeObservationSample(
        episode_id="ep-0",
        tick_id=0,
        task_id="libero_object",
        task_index=0,
        init_state_index=0,
        observations=tuple(frames),
        runtime_description=RuntimeDescription(
            runtime_id="libero-pro",
            backend="libero-pro",
            capabilities=["runtime-action"],
            robot_surfaces=[],
            control_step_hz=20,
            observation_streams=list(streams),
            metadata={"language": language},
        ),
        metadata={"payloads": payloads},
    )


def _image_frame(stream: str) -> ObservationFrame:
    return ObservationFrame(
        stream=stream,
        kind=ObservationKind.IMAGE,
        encoding="npy",
        shape=[128, 128, 3],
        dtype="uint8",
        data_ref=f"/payloads/{stream}.npy",
    )
