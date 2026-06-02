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

"""Smoke tests for the pyo3-bound VoxelRayMap."""

from __future__ import annotations

import numpy as np
import pytest

from dimos.mapping.ray_tracing.voxel_map import VoxelRayMap


def _config() -> dict[str, float | int]:
    return {
        "voxel_size": 1.0,
        "max_range": 100.0,
        "ray_subsample": 1,
        "shadow_depth": 0.0,
        "grace_depth": 0.0,
        "min_health": 0,
        "max_health": 1,
    }


def test_construct_valid_config() -> None:
    mapper = VoxelRayMap(**_config())
    assert len(mapper) == 0


def test_construct_rejects_zero_voxel_size() -> None:
    cfg = _config()
    cfg["voxel_size"] = 0.0
    with pytest.raises(ValueError, match="voxel_size"):
        VoxelRayMap(**cfg)


def test_construct_rejects_min_health_geq_max_health() -> None:
    cfg = _config()
    cfg["min_health"] = 5
    cfg["max_health"] = 1
    with pytest.raises(ValueError, match="min_health"):
        VoxelRayMap(**cfg)


def test_add_frame_inserts_hit_voxels() -> None:
    mapper = VoxelRayMap(**_config())
    points = np.array(
        [
            [5.5, 0.5, 0.5],
            [0.5, 5.5, 0.5],
        ],
        dtype=np.float32,
    )
    mapper.add_frame(points, (0.0, 0.0, 0.0))

    voxels = mapper.global_map()
    assert voxels.dtype == np.float32
    assert voxels.shape == (2, 3)
    assert len(mapper) == 2

    centers = {tuple(row) for row in voxels.tolist()}
    assert (5.5, 0.5, 0.5) in centers
    assert (0.5, 5.5, 0.5) in centers


def test_add_frame_rejects_wrong_shape() -> None:
    mapper = VoxelRayMap(**_config())
    bad = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    with pytest.raises(ValueError, match="N, 3"):
        mapper.add_frame(bad, (0.0, 0.0, 0.0))


def test_add_frame_drops_non_finite_points() -> None:
    mapper = VoxelRayMap(**_config())
    points = np.array(
        [
            [5.5, 0.5, 0.5],
            [float("nan"), 1.0, 1.0],
            [float("inf"), 2.0, 2.0],
        ],
        dtype=np.float32,
    )
    mapper.add_frame(points, (0.0, 0.0, 0.0))
    assert len(mapper) == 1


def test_local_map_clips_to_cylinder() -> None:
    mapper = VoxelRayMap(**_config())
    points = np.array(
        [
            [0.5, 0.5, 0.5],
            [10.5, 0.5, 0.5],
        ],
        dtype=np.float32,
    )
    mapper.add_frame(points, (0.0, 0.0, 0.0))

    nearby = mapper.local_map(origin=(0.0, 0.0, 0.0), radius=2.0, z_min=-1.0, z_max=1.0)
    assert nearby.shape == (1, 3)
    assert tuple(nearby[0].tolist()) == (0.5, 0.5, 0.5)


def test_clear_resets_map() -> None:
    mapper = VoxelRayMap(**_config())
    mapper.add_frame(
        np.array([[5.5, 0.5, 0.5]], dtype=np.float32),
        (0.0, 0.0, 0.0),
    )
    assert len(mapper) == 1
    mapper.clear()
    assert len(mapper) == 0
    assert mapper.global_map().shape == (0, 3)
