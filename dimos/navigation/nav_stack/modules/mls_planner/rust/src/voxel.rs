// Copyright 2026 Dimensional Inc.
// SPDX-License-Identifier: Apache-2.0

//! Voxel-grid coordinate math.

#![allow(dead_code)] // consumed incrementally by later stage modules

pub type VoxelKey = (i32, i32, i32);

#[inline]
pub fn voxelize(p: (f32, f32, f32), voxel_size: f32) -> VoxelKey {
    let inv = 1.0 / voxel_size;
    (
        (p.0 * inv).floor() as i32,
        (p.1 * inv).floor() as i32,
        (p.2 * inv).floor() as i32,
    )
}

/// XY centered in the cell, Z at the cell's top face.
#[inline]
pub fn surface_point_xyz(ix: i32, iy: i32, iz: i32, voxel_size: f32) -> (f32, f32, f32) {
    (
        (ix as f32 + 0.5) * voxel_size,
        (iy as f32 + 0.5) * voxel_size,
        (iz as f32 + 1.0) * voxel_size,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx_eq(a: f32, b: f32) {
        let eps = 1e-6;
        assert!((a - b).abs() < eps, "{a} != {b} (eps {eps})");
    }

    #[test]
    fn origin_cell_at_voxel_1() {
        let (x, y, z) = surface_point_xyz(0, 0, 0, 1.0);
        approx_eq(x, 0.5);
        approx_eq(y, 0.5);
        approx_eq(z, 1.0);
    }

    #[test]
    fn positive_cell_at_voxel_0_1() {
        let (x, y, z) = surface_point_xyz(3, 2, 5, 0.1);
        approx_eq(x, 0.35);
        approx_eq(y, 0.25);
        approx_eq(z, 0.6);
    }

    #[test]
    fn negative_cell() {
        let (x, y, z) = surface_point_xyz(-2, -1, -3, 1.0);
        approx_eq(x, -1.5);
        approx_eq(y, -0.5);
        approx_eq(z, -2.0);
    }
}
