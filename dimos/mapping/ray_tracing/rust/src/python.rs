// Copyright 2026 Dimensional Inc.
// SPDX-License-Identifier: Apache-2.0

use numpy::ndarray::Array2;
use numpy::{IntoPyArray, PyArray2, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

use super::{update_map, VoxelMap, VoxelMapperConfig};

#[pyclass]
pub struct VoxelRayMap {
    config: VoxelMapperConfig,
    map: VoxelMap,
}

#[pymethods]
impl VoxelRayMap {
    #[new]
    #[pyo3(signature = (
        voxel_size,
        max_range,
        ray_subsample = 1,
        shadow_depth = 0.2,
        grace_depth = 0.2,
        min_health = -2,
        max_health = 1,
    ))]
    fn new(
        voxel_size: f32,
        max_range: f32,
        ray_subsample: u32,
        shadow_depth: f32,
        grace_depth: f32,
        min_health: i32,
        max_health: i32,
    ) -> PyResult<Self> {
        let config = VoxelMapperConfig {
            voxel_size,
            max_range,
            ray_subsample,
            shadow_depth,
            grace_depth,
            min_health,
            max_health,
        };
        config.validate().map_err(PyValueError::new_err)?;
        Ok(Self {
            config,
            map: VoxelMap::default(),
        })
    }

    fn add_frame(
        &mut self,
        points: PyReadonlyArray2<'_, f32>,
        origin: (f32, f32, f32),
    ) -> PyResult<()> {
        let arr = points.as_array();
        let shape = arr.shape();
        if shape.len() != 2 || shape[1] != 3 {
            return Err(PyValueError::new_err(format!(
                "points must be (N, 3) float32, got shape {:?}",
                shape
            )));
        }
        let n = shape[0];
        let pts: Vec<(f32, f32, f32)> = (0..n)
            .map(|i| (arr[[i, 0]], arr[[i, 1]], arr[[i, 2]]))
            .collect();
        update_map(&mut self.map, origin, &pts, &self.config);
        Ok(())
    }

    fn global_map<'py>(&self, py: Python<'py>) -> Bound<'py, PyArray2<f32>> {
        let voxel_size = self.config.voxel_size;
        let half = voxel_size * 0.5;
        let mut positions: Vec<f32> = Vec::with_capacity(self.map.voxels.len() * 3);
        for (&(kx, ky, kz), &health) in &self.map.voxels {
            if health <= 0 {
                continue;
            }
            positions.push(kx as f32 * voxel_size + half);
            positions.push(ky as f32 * voxel_size + half);
            positions.push(kz as f32 * voxel_size + half);
        }
        let n = positions.len() / 3;
        Array2::from_shape_vec((n, 3), positions)
            .expect("3 elements pushed per voxel")
            .into_pyarray_bound(py)
    }
}

#[pymodule]
fn _voxel_ray_tracing(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<VoxelRayMap>()?;
    Ok(())
}
