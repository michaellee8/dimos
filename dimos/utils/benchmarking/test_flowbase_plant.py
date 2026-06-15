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

"""Pure, fast unit tests for the FlowBase plant sim: the vendored FOPDT
fit is recoverable from simulated step responses, and the command-unit
limiter reproduces the firmware's Ruckig saturation behavior.
"""

from __future__ import annotations

import numpy as np
import pytest

from dimos.utils.benchmarking.plant import (
    FLOWBASE_CMD_MAX_ACC,
    FLOWBASE_CMD_MAX_VEL,
    FLOWBASE_PLANT_FITTED,
    FLOWBASE_PLANT_PROFILE,
    CommandLimiter,
    FopdtChannelParams,
    TwistBasePlantSim,
    flowbase_command_limiter,
)
from dimos.utils.characterization.modeling.fopdt import fit_fopdt

_DT = 0.01  # 100 Hz, the coordinator tick rate
_STEP_S = 6.0
_FIT_TOLERANCE = 0.02  # spec: sim reproduces K, tau, L within 2%


def _step_response(channel: str, amplitude: float) -> tuple[np.ndarray, np.ndarray]:
    """Command a step on one channel, return (t, body_velocity) traces."""
    sim = TwistBasePlantSim(FLOWBASE_PLANT_FITTED)
    sim.reset(0.0, 0.0, 0.0, _DT)
    cmds = {"vx": 0.0, "vy": 0.0, "wz": 0.0}
    cmds[channel] = amplitude
    n = int(_STEP_S / _DT)
    t = np.arange(1, n + 1) * _DT
    y = np.empty(n)
    for i in range(n):
        sim.step(cmds["vx"], cmds["vy"], cmds["wz"], _DT)
        y[i] = getattr(sim, channel)
    return t, y


@pytest.mark.parametrize(
    ("channel", "amplitude", "params"),
    [
        ("vx", 0.4, FLOWBASE_PLANT_FITTED.vx),
        ("vy", 0.4, FLOWBASE_PLANT_FITTED.vy),
        ("wz", 0.5, FLOWBASE_PLANT_FITTED.wz),
    ],
)
def test_step_response_recovers_vendored_fit(
    channel: str, amplitude: float, params: FopdtChannelParams
) -> None:
    t, y = _step_response(channel, amplitude)
    fit = fit_fopdt(t, y, amplitude)
    assert fit.converged
    assert fit.K == pytest.approx(params.K, rel=_FIT_TOLERANCE)
    assert fit.tau == pytest.approx(params.tau, rel=_FIT_TOLERANCE)
    # L is discretized to whole ticks in the sim (delay buffer), so allow
    # one sample period on top of the relative tolerance.
    assert fit.L == pytest.approx(params.L, rel=_FIT_TOLERANCE, abs=_DT)


def test_flowbase_profile_uses_flowbase_fit() -> None:
    assert FLOWBASE_PLANT_PROFILE.sim_plant is FLOWBASE_PLANT_FITTED


def test_limiter_clamps_velocity() -> None:
    limiter = flowbase_command_limiter()
    settle_s = 5.0
    out = (0.0, 0.0, 0.0)
    for _ in range(int(settle_s / _DT)):
        out = limiter.step((2.0, -2.0, 10.0), _DT)
    assert out[0] == pytest.approx(FLOWBASE_CMD_MAX_VEL[0])
    assert out[1] == pytest.approx(-FLOWBASE_CMD_MAX_VEL[1])
    assert out[2] == pytest.approx(FLOWBASE_CMD_MAX_VEL[2])


def test_limiter_rate_limits_step() -> None:
    limiter = flowbase_command_limiter()
    out = limiter.step((0.8, 0.0, 0.0), _DT)
    assert out[0] == pytest.approx(FLOWBASE_CMD_MAX_ACC[0] * _DT)
    out = limiter.step((0.8, 0.0, 0.0), _DT)
    assert out[0] == pytest.approx(2 * FLOWBASE_CMD_MAX_ACC[0] * _DT)


def test_limiter_transparent_within_planning_margins() -> None:
    """Commands that respect the 85% physical margin (in command units:
    0.85 * max_vel, ramped at <= 0.85 * max_acc) pass through untouched."""
    margin = 0.85
    limiter = flowbase_command_limiter()
    v_target = margin * FLOWBASE_CMD_MAX_VEL[0]
    ramp_rate = margin * FLOWBASE_CMD_MAX_ACC[0]
    n = int(2.0 / _DT)
    for i in range(1, n + 1):
        cmd = min(v_target, ramp_rate * i * _DT)
        out = limiter.step((cmd, 0.0, 0.0), _DT)
        assert out[0] == pytest.approx(cmd, abs=1e-12)


def test_limited_sim_saturates_above_command_ceiling() -> None:
    """Commanding 2x the ceiling yields the same steady-state velocity as
    commanding exactly the ceiling — the limiter, not the FOPDT gain,
    binds first."""
    settle_s = 8.0
    results = []
    for cmd in (FLOWBASE_CMD_MAX_VEL[0], 2 * FLOWBASE_CMD_MAX_VEL[0]):
        sim = TwistBasePlantSim(
            FLOWBASE_PLANT_FITTED,
            limiter=CommandLimiter(FLOWBASE_CMD_MAX_VEL, FLOWBASE_CMD_MAX_ACC),
        )
        sim.reset(0.0, 0.0, 0.0, _DT)
        for _ in range(int(settle_s / _DT)):
            sim.step(cmd, 0.0, 0.0, _DT)
        results.append(sim.vx)
    assert results[0] == pytest.approx(results[1])
    assert results[0] == pytest.approx(
        FLOWBASE_PLANT_FITTED.vx.K * FLOWBASE_CMD_MAX_VEL[0], rel=0.01
    )


def test_holonomic_integration_strafe() -> None:
    """A pure +vy command at yaw=90deg moves the robot in world -x."""
    sim = TwistBasePlantSim(FLOWBASE_PLANT_FITTED)
    yaw_90 = float(np.pi / 2)
    sim.reset(0.0, 0.0, yaw_90, _DT)
    for _ in range(int(2.0 / _DT)):
        sim.step(0.0, 0.4, 0.0, _DT)
    assert sim.x < -0.1
    assert abs(sim.y) < 0.02
