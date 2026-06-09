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

"""Unit tests for the AgiBot X2 decoupled RSL-RL WBC task."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
from pydantic import ValidationError
import pytest

from dimos.control.task import ControlMode, CoordinatorState, JointStateSnapshot
from dimos.control.tasks import x2_rsl_rl_wbc_task
from dimos.control.tasks.x2_rsl_rl_wbc_task import (
    X2RslRlWBCTask,
    X2RslRlWBCTaskConfig,
    X2RslRlWBCTaskParams,
)
from dimos.hardware.whole_body.spec import IMUState
from dimos.robot.agibot.x2_ultra.policy_constants import (
    X2_DEFAULT_POSITIONS,
    X2_JOINTS,
    X2_LEG_JOINTS,
    X2_POLICY_ACTION_SCALE,
    X2_POLICY_DEFAULT_POSITIONS,
    X2_POLICY_JOINTS,
    X2_UPPER_BODY_JOINTS,
)


class _StubSession:
    def __init__(self, action: np.ndarray, feeds: list[np.ndarray]) -> None:
        self._action = action
        self._feeds = feeds

        fake_input = MagicMock()
        fake_input.name = "obs"
        fake_input.shape = [1, 105]
        self._inputs = [fake_input]

        fake_output = MagicMock()
        fake_output.name = "actions"
        fake_output.shape = [1, 31]
        self._outputs = [fake_output]

    def get_inputs(self) -> list[Any]:
        return self._inputs

    def get_outputs(self) -> list[Any]:
        return self._outputs

    def run(self, _outputs: Any, feed: dict[str, np.ndarray]) -> list[np.ndarray]:
        self._feeds.append(feed["obs"].copy())
        return [self._action.reshape(1, -1)]


@pytest.fixture
def patched_ort(monkeypatch):
    feeds: list[np.ndarray] = []
    action = np.zeros(31, dtype=np.float32)
    action[:12] = 0.2
    action[12:] = 3.0

    def _factory(_path: str, providers: Any = None) -> _StubSession:
        return _StubSession(action=action, feeds=feeds)

    monkeypatch.setattr(x2_rsl_rl_wbc_task.ort, "InferenceSession", _factory)
    return action, feeds


@pytest.fixture
def stub_adapter():
    adapter = MagicMock()
    adapter.read_imu.return_value = IMUState(
        quaternion=(1.0, 0.0, 0.0, 0.0),
        gyroscope=(0.0, 0.0, 0.0),
        accelerometer=(0.0, 0.0, -9.81),
        linear_velocity=(0.0, 0.0, 0.0),
        rpy=(0.0, 0.0, 0.0),
    )
    return adapter


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    path = tmp_path / "x2.onnx"
    path.write_bytes(b"stub")
    return path


@pytest.fixture
def task(patched_ort, stub_adapter, policy_path) -> X2RslRlWBCTask:
    return X2RslRlWBCTask(
        name="x2_rsl_rl_wbc",
        config=X2RslRlWBCTaskConfig(
            policy_onnx=policy_path,
            joint_names=X2_LEG_JOINTS,
            all_joint_names=X2_POLICY_JOINTS,
            auto_arm=True,
            decimation=1,
        ),
        adapter=stub_adapter,
    )


def _state_at(t_now: float, offsets: dict[str, float] | None = None) -> CoordinatorState:
    positions = dict(zip(X2_JOINTS, X2_DEFAULT_POSITIONS, strict=True))
    if offsets:
        positions.update(offsets)
    snap = JointStateSnapshot(
        joint_positions=positions,
        joint_velocities={n: 0.0 for n in X2_JOINTS},
        joint_efforts={n: 0.0 for n in X2_JOINTS},
        timestamp=t_now,
    )
    imu = IMUState(
        quaternion=(1.0, 0.0, 0.0, 0.0),
        gyroscope=(0.0, 0.0, 0.0),
        accelerometer=(0.0, 0.0, -9.81),
        linear_velocity=(0.0, 0.0, 0.0),
        rpy=(0.0, 0.0, 0.0),
    )
    return CoordinatorState(joints=snap, imu={"x2": imu}, t_now=t_now, dt=0.004)


def test_claims_legs_only(task):
    claim = task.claim()
    assert claim.joints == frozenset(X2_LEG_JOINTS)
    assert not (claim.joints & frozenset(X2_UPPER_BODY_JOINTS))
    assert claim.priority == 50
    assert claim.mode == ControlMode.SERVO_POSITION


def test_policy_output_commands_only_leg_targets(task, patched_ort):
    _, feeds = patched_ort
    task.start()

    out = task.compute(_state_at(100.0))

    assert out is not None
    assert out.joint_names == X2_LEG_JOINTS
    assert len(out.positions) == 12
    expected = np.asarray(X2_POLICY_DEFAULT_POSITIONS[:12], dtype=np.float32) + (
        0.2 * np.asarray(X2_POLICY_ACTION_SCALE[:12], dtype=np.float32)
    )
    np.testing.assert_allclose(out.positions, expected, atol=1e-6)
    assert feeds and feeds[0].shape == (1, 105)


def test_upper_body_state_is_observed_but_not_commanded(task, patched_ort):
    action, feeds = patched_ort
    task.start()
    upper_joint = X2_POLICY_JOINTS[15]
    upper_pos = X2_POLICY_DEFAULT_POSITIONS[15] + 0.3

    out = task.compute(_state_at(100.0, offsets={upper_joint: upper_pos}))

    assert out is not None
    assert upper_joint not in out.joint_names
    obs = feeds[0][0]
    assert obs[9 + 15] == pytest.approx(0.3)
    np.testing.assert_array_equal(task._last_action, action)


def test_policy_observation_uses_policy_order_not_hardware_order(task, patched_ort):
    _, feeds = patched_ort
    assert X2_JOINTS[15] == "x2/head_yaw"
    assert X2_POLICY_JOINTS[15] == "x2/left_shoulder_pitch"
    assert X2_POLICY_JOINTS[29] == "x2/head_yaw"

    task.start()
    out = task.compute(
        _state_at(
            100.0,
            offsets={
                "x2/head_yaw": X2_POLICY_DEFAULT_POSITIONS[29] + 0.7,
                "x2/left_shoulder_pitch": X2_POLICY_DEFAULT_POSITIONS[15] + 0.3,
            },
        )
    )

    assert out is not None
    obs = feeds[0][0]
    assert obs[9 + 15] == pytest.approx(0.3)
    assert obs[9 + 29] == pytest.approx(0.7)


def test_default_decimation_matches_50hz_policy(patched_ort, stub_adapter, policy_path):
    _, feeds = patched_ort
    task = X2RslRlWBCTask(
        name="x2_rsl_rl_wbc",
        config=X2RslRlWBCTaskConfig(
            policy_onnx=policy_path,
            joint_names=X2_LEG_JOINTS,
            all_joint_names=X2_POLICY_JOINTS,
            auto_arm=True,
        ),
        adapter=stub_adapter,
    )

    task.start()
    for i in range(4):
        assert task.compute(_state_at(100.0 + i * 0.004)) is None
    out = task.compute(_state_at(100.016))

    assert out is not None
    assert len(feeds) == 1


def test_rejects_monolithic_31_joint_claim(patched_ort, stub_adapter, policy_path):
    with pytest.raises(ValueError, match="12 policy joints"):
        X2RslRlWBCTask(
            name="bad_x2",
            config=X2RslRlWBCTaskConfig(
                policy_onnx=policy_path,
                joint_names=X2_JOINTS,
                all_joint_names=X2_POLICY_JOINTS,
            ),
            adapter=stub_adapter,
        )


def test_params_require_explicit_policy_joint_order(policy_path):
    with pytest.raises(ValidationError, match="all_joint_names"):
        X2RslRlWBCTaskParams.model_validate(
            {
                "policy_onnx": policy_path,
                "hardware_id": "x2",
            }
        )
