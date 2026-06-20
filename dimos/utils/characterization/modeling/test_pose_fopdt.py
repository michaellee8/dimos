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

"""Unit tests for the pose-domain FOPDT fitter: the closed-form step position is
correct, a clean synthetic step round-trips, the joint multi-amplitude fit breaks
the K/drift collinearity a single segment can't, deadtime profiling recovers L,
and the plausibility gate rejects out-of-bound fits."""

from __future__ import annotations

import numpy as np
import pytest

from dimos.utils.characterization.modeling.pose_fopdt import (
    estimate_deadtime,
    fit_pose_fopdt,
    fit_pose_fopdt_multi,
    pose_step_response,
)

_SAMPLE_DT = 1.0 / 18.0


def _step_pose(
    t: np.ndarray, K: float, tau: float, L: float, amp: float, drift: float = 0.0
) -> np.ndarray:
    return drift * t + pose_step_response(t, K, tau, L, amp)


def test_step_response_is_zero_before_deadtime() -> None:
    t = np.linspace(0.0, 2.0, 200)
    y = pose_step_response(t, K=1.0, tau=0.2, L=0.15, amp=0.5)
    assert np.all(y[t < 0.15] == 0.0)
    assert y[-1] > 0.0  # has risen by the end
    # far past L the position grows ~linearly at the steady velocity K*amp
    late = t > 1.5
    slope = np.gradient(y[late], t[late])
    assert slope.mean() == pytest.approx(1.0 * 0.5, rel=0.02)


def test_single_step_recovers_clean_params() -> None:
    t = np.arange(0.0, 4.0, _SAMPLE_DT)
    K, tau, L, amp = 0.92, 0.3, 0.1, 0.5
    p = _step_pose(t, K, tau, L, amp)
    fit = fit_pose_fopdt(t, p, amp, L)
    assert fit.converged and fit.valid
    assert fit.K == pytest.approx(K, rel=0.02)
    assert fit.tau == pytest.approx(tau, rel=0.05)


def test_joint_fit_beats_single_under_drift_collinearity() -> None:
    # Two amplitudes share one drift; a single segment can't separate K from
    # drift, the joint fit can. K_true must come back tight under real drift.
    K, tau, L, drift = 2.4, 0.3, 0.1, 0.05
    t = np.arange(0.0, 4.0, _SAMPLE_DT)
    segs = [(t, _step_pose(t, K, tau, L, amp, drift), amp) for amp in (0.5, 1.0)]
    joint = fit_pose_fopdt_multi(segs, L)
    assert joint.converged and joint.valid
    assert joint.K == pytest.approx(K, rel=0.02)
    assert joint.drift == pytest.approx(drift, abs=0.01)


def test_estimate_deadtime_recovers_l_within_one_sample() -> None:
    K, tau, amp = 1.0, 0.25, 0.5
    t = np.arange(0.0, 4.0, _SAMPLE_DT)
    for true_l in (0.05, 0.12, 0.2):
        p = _step_pose(t, K, tau, true_l, amp)
        best_l, _, _ = estimate_deadtime(t, p, amp)
        assert abs(best_l - true_l) <= _SAMPLE_DT


def test_plausibility_gate_rejects_out_of_bounds_tau() -> None:
    # A signal with tau well above the Go2 bound: the fit clamps and is flagged.
    t = np.arange(0.0, 4.0, _SAMPLE_DT)
    p = _step_pose(t, K=1.0, tau=2.0, L=0.1, amp=0.5)  # tau=2.0 >> 0.6 bound
    fit = fit_pose_fopdt(t, p, 0.5, 0.1, tau_bounds=(0.03, 0.6))
    assert not fit.valid


def test_too_few_samples_is_not_converged() -> None:
    t = np.array([0.0, 0.1, 0.2])
    fit = fit_pose_fopdt(t, t.copy(), 0.5, 0.1)
    assert not fit.converged and not fit.valid
