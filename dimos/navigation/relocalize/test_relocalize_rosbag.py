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

"""Slow rosbag-backed integration test for Relocalize's two-stage ICP.

Builds a prior map by stitching the bag's registered (world-frame) scans
together and voxel-downsampling, then feeds a sampled subset back through
``two_stage_icp`` with an identity initial guess. On a self-consistent SLAM
track the recovered correction should stay near identity — convergence
ratio ≥ 80%, translation drift < 0.5m, rotation drift < 5°.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import open3d as o3d
import pytest
from scipy.spatial.transform import Rotation

from dimos.navigation.nav_stack.tests.rosbag_fixtures import (
    ROSBAG_FIXTURE_60S,
    load_rosbag_window,
)
from dimos.navigation.relocalize.relocalize import (
    ICPParams,
    two_stage_icp,
    voxel_downsample,
)

pytestmark = [pytest.mark.slow]

# Number of scans between samples — every 10th scan gives ~20 test ticks
# across the 208 scans in og_nav_60s.npz.
TEST_SCAN_STRIDE = 10

# How aggressively to thin the scans when stitching the prior map.
# Every 2nd is plenty given the trajectory length and avoids OOM on big bags.
PRIOR_SCAN_STRIDE = 2
PRIOR_VOXEL_SIZE = 0.1

CONVERGENCE_RATIO_MIN = 0.80
TRANSLATION_MAX_M = 0.5
ROTATION_MAX_DEG = 5.0


def _build_prior_map(
    scans: list[tuple[float, np.ndarray]], voxel_size: float = PRIOR_VOXEL_SIZE
) -> o3d.geometry.PointCloud:
    """Stitch a subset of registered scans into one voxel-downsampled cloud."""
    blocks: list[np.ndarray] = []
    for _ts, points in scans[::PRIOR_SCAN_STRIDE]:
        if points.size == 0:
            continue
        blocks.append(points[:, :3].astype(np.float64))
    if not blocks:
        raise ValueError("no usable scans to build prior map")
    stitched = np.concatenate(blocks)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(stitched)
    return cloud.voxel_down_sample(voxel_size)


def test_relocalize_recovers_identity_on_rosbag():
    """Two-stage ICP against a rosbag-derived prior map stays near identity."""
    if not Path(ROSBAG_FIXTURE_60S).exists():
        pytest.skip(f"Rosbag fixture not found: {ROSBAG_FIXTURE_60S}")

    window = load_rosbag_window()
    assert len(window.scans) > 0, "rosbag has no scans"

    params = ICPParams()

    prior_map = _build_prior_map(window.scans)
    rough_target = voxel_downsample(prior_map, params.rough_map_resolution)
    refine_target = voxel_downsample(prior_map, params.refine_map_resolution)
    assert len(rough_target.points) > 0
    assert len(refine_target.points) > 0

    test_indices = list(range(0, len(window.scans), TEST_SCAN_STRIDE))
    assert len(test_indices) >= 20, (
        f"need >= 20 sampled scans, got {len(test_indices)} "
        f"(scans={len(window.scans)}, stride={TEST_SCAN_STRIDE})"
    )

    initial_guess = np.eye(4)

    converged_count = 0
    trans_errs_m: list[float] = []
    rot_errs_deg: list[float] = []

    for index in test_indices:
        _ts, points = window.scans[index]
        if points.size == 0:
            continue
        source = o3d.geometry.PointCloud()
        source.points = o3d.utility.Vector3dVector(points[:, :3].astype(np.float64))

        converged, transform = two_stage_icp(
            source, rough_target, refine_target, initial_guess, params
        )

        if not converged:
            continue
        converged_count += 1
        trans_errs_m.append(float(np.linalg.norm(transform[:3, 3])))
        rot_errs_deg.append(math.degrees(Rotation.from_matrix(transform[:3, :3]).magnitude()))

    convergence_ratio = converged_count / len(test_indices)
    assert convergence_ratio >= CONVERGENCE_RATIO_MIN, (
        f"ICP convergence ratio {convergence_ratio:.2%} < {CONVERGENCE_RATIO_MIN:.0%} "
        f"({converged_count}/{len(test_indices)})"
    )

    max_trans = max(trans_errs_m) if trans_errs_m else 0.0
    max_rot = max(rot_errs_deg) if rot_errs_deg else 0.0

    assert max_trans < TRANSLATION_MAX_M, (
        f"max recovered translation {max_trans:.3f}m exceeded {TRANSLATION_MAX_M}m"
    )
    assert max_rot < ROTATION_MAX_DEG, (
        f"max recovered rotation {max_rot:.3f}deg exceeded {ROTATION_MAX_DEG}deg"
    )
