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

import pytest

from dimos.hardware.manipulators.damiao.base_adapter import DamiaoArmAdapterBase
from dimos.hardware.manipulators.damiao.specs import DamiaoArmSpec, DamiaoMotorSpec
from dimos.hardware.manipulators.spec import ControlMode


class _FakeRobot:
    def __init__(self) -> None:
        self.enable_calls: int = 0
        self.disable_calls: int = 0

    def enable(self) -> None:
        self.enable_calls += 1

    def disable(self) -> None:
        self.disable_calls += 1


def _arm_spec() -> DamiaoArmSpec:
    return DamiaoArmSpec(
        name="test_damiao",
        vendor="Damiao",
        model="TestArm",
        motors=(
            DamiaoMotorSpec("j1", "DM4310", 0x01, 0x11),
            DamiaoMotorSpec("j2", "DM4310", 0x02, 0x12),
        ),
        position_lower=(-1.0, -2.0),
        position_upper=(1.0, 2.0),
        velocity_max=(3.0, 4.0),
        kp=(5.0, 6.0),
        kd=(0.1, 0.2),
        gravity_torque_limits=(7.0, 8.0),
    )


def _attach_robot(
    adapter: DamiaoArmAdapterBase,
    robot: _FakeRobot,
    *,
    arm: object | None = None,
    enabled: bool | None = None,
) -> None:
    adapter._robot = robot
    if arm is not None:
        adapter._arm = arm
    if enabled is not None:
        adapter._enabled = enabled


def test_arm_spec_exposes_joint_order_for_backend_commands() -> None:
    spec = _arm_spec()

    assert spec.joint_names == ("j1", "j2")
    assert [motor.send_id for motor in spec.motors] == [0x01, 0x02]


def test_arm_spec_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate send_id"):
        DamiaoArmSpec(
            name="bad",
            vendor="Damiao",
            model="BadArm",
            motors=(
                DamiaoMotorSpec("j1", "DM4310", 0x01, 0x11),
                DamiaoMotorSpec("j2", "DM4310", 0x01, 0x12),
            ),
            position_lower=(-1.0, -2.0),
            position_upper=(1.0, 2.0),
            velocity_max=(3.0, 4.0),
            kp=(5.0, 6.0),
            kd=(0.1, 0.2),
        ).validate()


def test_arm_spec_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="kp length 1 does not match dof 2"):
        DamiaoArmSpec(
            name="bad",
            vendor="Damiao",
            model="BadArm",
            motors=(
                DamiaoMotorSpec("j1", "DM4310", 0x01, 0x11),
                DamiaoMotorSpec("j2", "DM4310", 0x02, 0x12),
            ),
            position_lower=(-1.0, -2.0),
            position_upper=(1.0, 2.0),
            velocity_max=(3.0, 4.0),
            kp=(5.0,),
            kd=(0.1, 0.2),
        ).validate()


def test_base_adapter_reports_limits_and_accepts_supported_mode() -> None:
    adapter = DamiaoArmAdapterBase(arm_spec=_arm_spec())

    assert adapter.get_dof() == 2
    limits = adapter.get_limits()
    assert limits.position_lower == [-1.0, -2.0]
    assert limits.position_upper == [1.0, 2.0]
    assert adapter.set_control_mode(ControlMode.TORQUE) is True
    assert adapter.get_control_mode() == ControlMode.TORQUE
    assert adapter.set_control_mode(ControlMode.VELOCITY) is False


def test_write_stop_gravity_comp_holds_current_position(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = DamiaoArmAdapterBase(arm_spec=_arm_spec(), gravity_comp=True)
    robot = _FakeRobot()
    _attach_robot(adapter, robot, arm=object(), enabled=True)
    captured_commands: dict[str, list[float]] = {}

    def read_positions() -> list[float]:
        return [0.1, -0.2]

    def write_mit_commands(
        *, q: list[float], dq: list[float], kp: list[float], kd: list[float], tau: list[float]
    ) -> bool:
        captured_commands.update(q=q, dq=dq, kp=kp, kd=kd, tau=tau)
        return True

    monkeypatch.setattr(adapter, "read_joint_positions", read_positions)
    monkeypatch.setattr(adapter, "write_mit_commands", write_mit_commands)

    assert adapter.write_stop() is True
    assert captured_commands == {
        "q": [0.1, -0.2],
        "dq": [0.0, 0.0],
        "kp": [5.0, 6.0],
        "kd": [0.1, 0.2],
        "tau": [0.0, 0.0],
    }
    assert robot.disable_calls == 0


def test_write_stop_gravity_comp_read_failure_disables_robot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = DamiaoArmAdapterBase(arm_spec=_arm_spec(), gravity_comp=True)
    robot = _FakeRobot()
    _attach_robot(adapter, robot, arm=object(), enabled=True)

    def read_positions() -> list[float]:
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(adapter, "read_joint_positions", read_positions)

    assert adapter.write_stop() is False
    assert robot.disable_calls == 1
    assert adapter.read_enabled() is False


def test_write_enable_startup_hold_failure_disables_robot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = DamiaoArmAdapterBase(arm_spec=_arm_spec(), gravity_comp=True)
    robot = _FakeRobot()
    _attach_robot(adapter, robot)

    def read_positions() -> list[float]:
        return [0.1, -0.2]

    def reject_hold(_positions: list[float], _velocity: float = 1.0) -> bool:
        return False

    monkeypatch.setattr(adapter, "read_joint_positions", read_positions)
    monkeypatch.setattr(adapter, "write_joint_positions", reject_hold)

    assert adapter.write_enable(True) is False
    assert robot.enable_calls == 1
    assert robot.disable_calls == 1
    assert adapter.read_enabled() is False
