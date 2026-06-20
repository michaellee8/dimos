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

"""Tests for the offline pose-domain reprocess pipeline: segmentation finds the
commanded steps, the fitter recovers injected K (~5%) / tau (~15%) / L (1 sample)
on sim recordings across regimes and seeds, and reprocess() writes a TuningConfig
artifact plus a fit-quality sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dimos.utils.benchmarking.plant import FopdtChannelParams, TwistBasePlantParams
from dimos.utils.benchmarking.tuning import TuningConfig
from dimos.utils.characterization.recording_io import load_recording, segment_steps
from dimos.utils.characterization.reprocess import fit_recording_pose_domain, reprocess
from dimos.utils.characterization.sim_ground_truth import (
    multistep_excitation,
    synthesize_recording,
)

_SAMPLE_DT = 1.0 / 18.0
_EXCITATION = multistep_excitation(
    vx_amps=(0.3, 0.6), vy_amps=(), wz_amps=(0.5, 1.0), hold_s=4.0, settle_s=2.0
)
# A few regimes spanning the fast Go2 corner and the vendored values.
_REGIMES = [(0.2, 0.15), (0.4, 0.05), (0.15, 0.1)]


def _plant(tau: float, dead_time: float) -> TwistBasePlantParams:
    return TwistBasePlantParams(
        vx=FopdtChannelParams(K=0.92, tau=tau, L=dead_time),
        vy=FopdtChannelParams(K=0.92, tau=tau, L=dead_time),
        wz=FopdtChannelParams(K=2.45, tau=tau, L=dead_time),
    )


def test_segmentation_finds_the_commanded_steps(tmp_path: Path) -> None:
    rec_path = synthesize_recording(
        _plant(0.2, 0.15), db_path=tmp_path / "s.db", segments=_EXCITATION, seed=0
    ).db_path
    spans = segment_steps(load_recording(rec_path))
    axes = [s.axis for s in spans]
    assert axes.count("vx") == 2  # two vx amplitudes
    assert axes.count("wz") == 2
    assert {round(abs(s.amplitude), 2) for s in spans if s.axis == "vx"} == {0.3, 0.6}


@pytest.mark.parametrize(("tau", "dead_time"), _REGIMES)
def test_pose_domain_recovers_injected_params(tau: float, dead_time: float, tmp_path: Path) -> None:
    k_ok, tau_ok, l_ok = [], [], []
    for seed in range(3):
        plant = _plant(tau, dead_time)
        rec = synthesize_recording(
            plant, db_path=tmp_path / f"r{seed}.db", segments=_EXCITATION, seed=seed
        )
        fit = fit_recording_pose_domain(load_recording(rec.db_path), estimate_l=True)
        for axis, true in (("vx", plant.vx), ("wz", plant.wz)):
            f = fit.axes[axis]
            k_ok.append(abs(f.K - true.K) / abs(true.K))
            tau_ok.append(abs(f.tau - true.tau) / true.tau)
            l_ok.append(abs(f.L - true.L))
    assert max(k_ok) < 0.05  # K within ~5%
    assert max(tau_ok) < 0.15  # tau within ~15%
    assert max(l_ok) <= _SAMPLE_DT  # L within one odom sample


def test_reprocess_writes_artifact_and_quality_sidecar(tmp_path: Path) -> None:
    rec = synthesize_recording(
        _plant(0.3, 0.1), db_path=tmp_path / "sess.db", segments=_EXCITATION, seed=1
    )
    artifact = reprocess(
        rec.db_path, robot_id="go2_u01", sim_or_hw="hw", out_dir=tmp_path, git_sha="testsha"
    )
    assert artifact.exists()
    config = TuningConfig.from_json(artifact)
    assert config.plant.vx.tau == pytest.approx(0.3, rel=0.15)

    quality = json.loads((artifact.parent / f"{artifact.stem}_quality.json").read_text())
    assert "vx" in quality and "r_squared" in quality["vx"]
    assert quality["vx"]["valid"] is True
    # pose-domain r^2 on a clean sim recording should be high.
    assert quality["vx"]["r_squared"] > 0.99
