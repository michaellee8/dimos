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

from types import SimpleNamespace

import pytest

from dimos.robot_learning.policy_rollout.lerobot_backend import LeRobotBackend
from dimos.robot_learning.policy_rollout.models import BackendBatch


class FakeNoGrad:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakePolicy:
    def __init__(self) -> None:
        self.config = SimpleNamespace(device="cpu", n_action_steps=7, action_dim=7)
        self.eval_called = False
        self.reset_called = False
        self.selected_batches: list[object] = []
        self.chunk_batches: list[object] = []
        self.to_devices: list[str] = []

    def eval(self) -> None:
        self.eval_called = True

    def to(self, device: str) -> None:
        self.to_devices.append(device)

    def reset(self) -> None:
        self.reset_called = True

    def select_action(self, batch: object) -> tuple[float, ...]:
        self.selected_batches.append(batch)
        return (0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0)

    def predict_action_chunk(self, batch: object) -> tuple[tuple[float, ...], ...]:
        self.chunk_batches.append(batch)
        return ((0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0),)


class FakePolicyClass:
    policy = FakePolicy()
    checkpoint_ids: list[str] = []

    @classmethod
    def from_pretrained(cls, pretrained_name_or_path: str) -> FakePolicy:
        cls.checkpoint_ids.append(pretrained_name_or_path)
        return cls.policy


def test_lerobot_backend_import_boundary_without_lerobot() -> None:
    backend = LeRobotBackend()

    description = backend.describe()

    assert description.backend_type == "lerobot"
    assert description.checkpoint_id == "lerobot/VLA-JEPA-LIBERO"


def test_initialize_loads_policy_sets_device_eval_and_processors(mocker) -> None:
    policy = FakePolicy()
    FakePolicyClass.policy = policy
    FakePolicyClass.checkpoint_ids = []
    preprocessor_calls: list[object] = []
    postprocessor_calls: list[object] = []

    def fake_import_module(name: str) -> object:
        if name == "lerobot.policies.vla_jepa.modeling_vla_jepa":
            return SimpleNamespace(VLAJEPAPolicy=FakePolicyClass)
        if name == "lerobot.policies.vla_jepa.processor_vla_jepa":
            return SimpleNamespace(
                make_vla_jepa_pre_post_processors=lambda config, dataset_stats=None: (
                    lambda batch: _record(preprocessor_calls, batch),
                    lambda output: _record(postprocessor_calls, output),
                )
            )
        if name == "torch":
            return SimpleNamespace(no_grad=FakeNoGrad)
        raise ImportError(name)

    mocker.patch("importlib.import_module", side_effect=fake_import_module)
    backend = LeRobotBackend(checkpoint_id="lerobot/VLA-JEPA-LIBERO", device="cpu")

    backend.initialize()
    output = backend.infer_batch(BackendBatch(payload={"observation.state": "state"}))
    backend.reset_episode()
    description = backend.describe()

    assert FakePolicyClass.checkpoint_ids == ["lerobot/VLA-JEPA-LIBERO"]
    assert policy.eval_called
    assert policy.to_devices == ["cpu"]
    assert policy.reset_called
    assert preprocessor_calls == [{"observation.state": "state"}]
    assert postprocessor_calls == [(0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0)]
    assert output.output == (0.0, 0.1, -0.1, 0.2, -0.2, 0.3, 1.0)
    assert output.metadata["inference_method"] == "select_action"
    assert output.metadata["output_shape"] == [7]
    assert description.policy_class is not None
    assert description.device == "cpu"


def test_lerobot_backend_can_route_to_action_chunk(mocker) -> None:
    policy = FakePolicy()
    FakePolicyClass.policy = policy
    FakePolicyClass.checkpoint_ids = []

    def fake_import_module(name: str) -> object:
        if name == "lerobot.policies.vla_jepa.modeling_vla_jepa":
            return SimpleNamespace(VLAJEPAPolicy=FakePolicyClass)
        if name == "lerobot.policies.vla_jepa.processor_vla_jepa":
            raise ImportError(name)
        if name == "torch":
            return SimpleNamespace(no_grad=FakeNoGrad)
        raise ImportError(name)

    mocker.patch("importlib.import_module", side_effect=fake_import_module)
    backend = LeRobotBackend(use_action_chunk=True, use_processors=False)

    output = backend.infer_batch(BackendBatch(payload={"observation.state": "state"}))

    assert policy.selected_batches == []
    assert policy.chunk_batches == [{"observation.state": "state"}]
    assert output.metadata["inference_method"] == "predict_action_chunk"
    assert output.metadata["output_shape"] == [1, 7]


def test_lerobot_backend_missing_dependency_error(mocker) -> None:
    mocker.patch("importlib.import_module", side_effect=ImportError("missing"))
    backend = LeRobotBackend()

    with pytest.raises(RuntimeError, match="Install LeRobot"):
        backend.initialize()


def _record(calls: list[object], value: object) -> object:
    calls.append(value)
    return value
