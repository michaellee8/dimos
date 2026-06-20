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

"""Offline re-fit of a stored recording into a plant model + tuning artifact.

This is the pose-domain pipeline end to end, with no robot: load a recording,
segment it, estimate deadtime L per axis (decoupled from tau), fit (K, tau) on
the raw pose, and emit the standard ``TuningConfig`` artifact plus a fit-quality
sidecar (r_squared/RMSE on pose + the plausibility verdict). The existing
``characterization --mode re-derive`` only re-applies the envelope; it does NOT
re-fit the dynamics. This does.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import warnings

import numpy as np

from dimos.utils.benchmarking.plant import FopdtChannelParams, TwistBasePlantParams
from dimos.utils.benchmarking.tuning import Provenance, derive_config, git_sha
from dimos.utils.characterization.modeling.pose_fopdt import (
    PoseFopdtParams,
    estimate_deadtime,
    fit_pose_fopdt_multi,
)
from dimos.utils.characterization.recording_io import (
    Recording,
    StepSpan,
    load_recording,
    segment_steps,
    step_pose_channel,
)

_AXES = ("vx", "vy", "wz")
# Nominal deadtime if an axis can't be estimated (mid-range of the Go2 bound).
_NOMINAL_L_S = 0.15


@dataclass
class AxisFit:
    """Per-axis pose-domain result aggregated over that axis's step segments."""

    axis: str
    K: float
    tau: float
    L: float
    l_estimates: list[float]  # per-segment L estimates (Phase 3 spread)
    r_squared: float
    rmse: float
    valid: bool
    segment_fits: list[PoseFopdtParams] = field(default_factory=list)


@dataclass
class PoseDomainFit:
    """Whole-recording pose-domain fit: per-axis results + assembled plant."""

    plant: TwistBasePlantParams
    axes: dict[str, AxisFit]
    per_amplitude: dict[str, list[dict[str, float]]]


def _median(values: list[float]) -> float:
    return float(np.median(values)) if values else float("nan")


def _fit_axis(
    recording: Recording,
    axis: str,
    spans: list[StepSpan],
    *,
    estimate_l: bool,
    l_fixed: float | None,
    tau_bounds: tuple[float, float],
    l_bounds: tuple[float, float],
) -> AxisFit:
    """Estimate L (decoupled), then fit (K, tau) per segment and aggregate."""
    channels = [(span, *step_pose_channel(recording, span)) for span in spans]
    channels = [(span, t, p) for span, t, p in channels if t.size >= 4]

    if not channels:
        return AxisFit(
            axis=axis,
            K=float("nan"),
            tau=float("nan"),
            L=l_fixed if l_fixed is not None else _NOMINAL_L_S,
            l_estimates=[],
            r_squared=float("nan"),
            rmse=float("nan"),
            valid=False,
        )

    l_estimates: list[float] = []
    if estimate_l:
        for span, t_rel, p_meas in channels:
            best_l, _, _ = estimate_deadtime(
                t_rel, p_meas, span.amplitude, l_bounds=l_bounds, tau_bounds=tau_bounds
            )
            l_estimates.append(best_l)
        axis_l = _median(l_estimates)
    else:
        axis_l = l_fixed if l_fixed is not None else _NOMINAL_L_S

    # Joint fit across all amplitudes (shared K/tau/drift) -- breaks the
    # steady-slope vs drift collinearity that biases single-segment K.
    joint = fit_pose_fopdt_multi(
        [(t_rel, p_meas, span.amplitude) for span, t_rel, p_meas in channels],
        axis_l,
        tau_bounds=tau_bounds,
        l_bounds=l_bounds,
    )
    return AxisFit(
        axis=axis,
        K=joint.K,
        tau=joint.tau,
        L=axis_l,
        l_estimates=l_estimates,
        r_squared=joint.r_squared,
        rmse=joint.rmse,
        valid=joint.valid,
        segment_fits=[joint],
    )


def fit_recording_pose_domain(
    recording: Recording,
    *,
    estimate_l: bool = True,
    l_by_axis: dict[str, float] | None = None,
    tau_bounds: tuple[float, float] = (0.03, 0.6),
    l_bounds: tuple[float, float] = (0.05, 0.30),
) -> PoseDomainFit:
    """Fit a recording with the pose-domain (output-error) method, per axis."""
    spans = segment_steps(recording)
    by_axis: dict[str, list[StepSpan]] = {a: [] for a in _AXES}
    for span in spans:
        by_axis[span.axis].append(span)

    axes: dict[str, AxisFit] = {}
    for axis in _AXES:
        l_fixed = None if l_by_axis is None else l_by_axis.get(axis)
        axes[axis] = _fit_axis(
            recording,
            axis,
            by_axis[axis],
            estimate_l=estimate_l and l_fixed is None,
            l_fixed=l_fixed,
            tau_bounds=tau_bounds,
            l_bounds=l_bounds,
        )

    # vy often has no excitation on Go2 (no native strafe) -> fall back to vx.
    if np.isnan(axes["vy"].K) and not np.isnan(axes["vx"].K):
        axes["vy"] = AxisFit(
            axis="vy",
            K=axes["vx"].K,
            tau=axes["vx"].tau,
            L=axes["vx"].L,
            l_estimates=[],
            r_squared=float("nan"),
            rmse=float("nan"),
            valid=False,
        )

    plant = TwistBasePlantParams(
        vx=FopdtChannelParams(K=axes["vx"].K, tau=axes["vx"].tau, L=axes["vx"].L),
        vy=FopdtChannelParams(K=axes["vy"].K, tau=axes["vy"].tau, L=axes["vy"].L),
        wz=FopdtChannelParams(K=axes["wz"].K, tau=axes["wz"].tau, L=axes["wz"].L),
    )
    per_amplitude: dict[str, list[dict[str, float]]] = {}
    for axis in _AXES:
        axis_k = axes[axis].K
        if np.isnan(axis_k):
            continue
        rows = [{"amplitude": abs(span.amplitude), "K": axis_k} for span in by_axis[axis]]
        if rows:
            per_amplitude[axis] = rows
    return PoseDomainFit(plant=plant, axes=axes, per_amplitude=per_amplitude)


def reprocess(
    db_path: str | Path,
    *,
    robot_id: str = "go2",
    surface: str = "concrete",
    mode: str = "default",
    sim_or_hw: str = "hw",
    out_dir: str | Path | None = None,
    git_sha: str = "unknown",
    estimate_l: bool = True,
    l_by_axis: dict[str, float] | None = None,
) -> Path:
    """Re-fit ``db_path`` with the pose-domain method and write a TuningConfig.

    Returns the artifact path. Also writes a ``*_posefit_quality.json`` sidecar
    with per-axis r_squared/RMSE (on pose) and the plausibility verdict, and
    warns loudly if any axis fit is implausible.
    """
    db_path = Path(db_path)
    recording = load_recording(db_path)
    fit = fit_recording_pose_domain(recording, estimate_l=estimate_l, l_by_axis=l_by_axis)

    implausible = [a for a, f in fit.axes.items() if not f.valid]
    if implausible:
        warnings.warn(
            f"{db_path.name}: pose-domain fit implausible on {implausible} "
            f"(outside physical bounds) -- artifact marked not-for-tuning",
            stacklevel=2,
        )

    provenance = Provenance(
        robot_id=robot_id,
        surface=surface,
        mode=mode,
        date=date.today().isoformat(),
        git_sha=git_sha,
        sim_or_hw=sim_or_hw if not implausible else "self-test",
        characterization_session_dir=str(db_path),
    )
    config = derive_config(fit.plant, provenance, per_amplitude=fit.per_amplitude or None)

    out_dir = Path(out_dir) if out_dir else db_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{robot_id}_config_{mode}_{surface}_{date.today().isoformat()}_{git_sha}_posedomain"
    artifact_path = out_dir / f"{stem}.json"
    config.to_json(artifact_path)

    quality = {
        axis: {
            "K": f.K,
            "tau": f.tau,
            "L": f.L,
            "r_squared": f.r_squared,
            "rmse": f.rmse,
            "valid": f.valid,
            "l_estimates": f.l_estimates,
        }
        for axis, f in fit.axes.items()
    }
    (out_dir / f"{stem}_quality.json").write_text(json.dumps(quality, indent=2))
    return artifact_path


def main() -> None:
    """CLI: pose-domain re-fit of a recording -> TuningConfig artifact.

    Example::

        python -m dimos.utils.characterization.reprocess \\
            data/characterization/go2/go2_recording_default_2026-06-19_<sha>.db \\
            --robot-id go2_u01 --surface concrete --sim-or-hw hw
    """
    parser = argparse.ArgumentParser(
        description="Re-fit a characterization recording with the pose-domain "
        "(output-error) FOPDT method and write a TuningConfig artifact."
    )
    parser.add_argument("db", help="path to the recording .db to re-fit")
    parser.add_argument("--robot-id", default="go2", help="per-unit id, e.g. go2_u01")
    parser.add_argument("--surface", default="concrete")
    parser.add_argument("--mode", default="default", help="gait mode")
    parser.add_argument(
        "--sim-or-hw",
        default="hw",
        choices=["hw", "sim", "self-test"],
        help="hw -> artifact is valid_for_tuning; sim/self-test -> not",
    )
    parser.add_argument("--out", default=None, help="output dir (default: alongside the .db)")
    parser.add_argument("--git-sha", default=git_sha(), help="provenance git sha")
    parser.add_argument(
        "--no-estimate-l",
        action="store_true",
        help="skip deadtime profiling; use --l-vx/--l-vy/--l-wz (or nominal) instead",
    )
    parser.add_argument("--l-vx", type=float, default=None, help="fixed deadtime L for vx (s)")
    parser.add_argument("--l-vy", type=float, default=None, help="fixed deadtime L for vy (s)")
    parser.add_argument("--l-wz", type=float, default=None, help="fixed deadtime L for wz (s)")
    args = parser.parse_args()

    l_by_axis: dict[str, float] | None = None
    fixed = {
        a: v for a, v in (("vx", args.l_vx), ("vy", args.l_vy), ("wz", args.l_wz)) if v is not None
    }
    if fixed:
        l_by_axis = fixed

    artifact = reprocess(
        args.db,
        robot_id=args.robot_id,
        surface=args.surface,
        mode=args.mode,
        sim_or_hw=args.sim_or_hw,
        out_dir=args.out,
        git_sha=args.git_sha,
        estimate_l=not args.no_estimate_l,
        l_by_axis=l_by_axis,
    )
    quality = json.loads((artifact.parent / f"{artifact.stem}_quality.json").read_text())
    print(f"\nartifact: {artifact}")
    print(f"quality:  {artifact.parent / (artifact.stem + '_quality.json')}\n")
    print(f"{'axis':5s} {'K':>8s} {'tau(s)':>8s} {'L(s)':>8s} {'r²':>7s}  valid")
    for axis in _AXES:
        q = quality[axis]
        print(
            f"{axis:5s} {q['K']:8.3f} {q['tau']:8.3f} {q['L']:8.3f} "
            f"{q['r_squared']:7.3f}  {q['valid']}"
        )


__all__ = [
    "AxisFit",
    "PoseDomainFit",
    "fit_recording_pose_domain",
    "reprocess",
]


if __name__ == "__main__":
    main()
