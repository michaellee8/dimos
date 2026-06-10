// Copyright 2026 Dimensional Inc.
// SPDX-License-Identifier: Apache-2.0

use ahash::{AHashMap, AHashSet};
use nalgebra::{Matrix3, Vector3};
use serde::Deserialize;
use validator::{Validate, ValidationError};

pub type VoxelKey = (i32, i32, i32);
pub type VoxelHealth = i32;

#[derive(Debug, Deserialize, Validate)]
#[serde(deny_unknown_fields)]
#[validate(schema(function = "validate_health_range"))]
pub struct Config {
    #[validate(range(exclusive_min = 0.0))]
    pub voxel_size: f32,
    #[validate(range(min = 0.0))]
    pub max_range: f32,
    #[validate(range(min = 1))]
    pub ray_subsample: u32,
    #[validate(range(min = 0.0))]
    pub shadow_depth: f32,
    #[validate(range(min = 0.0))]
    pub grace_depth: f32,
    pub min_health: i32,
    #[validate(range(min = 1))]
    pub max_health: i32,
    /// Spare a clearing miss when |ray · surface normal| is below this. Larger
    /// spares steeper grazes: 0.5 clears anything hit past 30 deg off the
    /// surface, 0.7 past ~45 deg. Raise it to stop grazing rays eroding floors,
    /// treads and landings (whose slope can exceed 30 deg).
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default = "default_graze_cos")]
    pub graze_cos: f32,
}

fn default_graze_cos() -> f32 {
    0.7
}

fn validate_health_range(cfg: &Config) -> Result<(), ValidationError> {
    if cfg.min_health >= cfg.max_health {
        return Err(ValidationError::new("min_health_lt_max_health"));
    }
    Ok(())
}

#[derive(Default)]
pub struct VoxelMap {
    pub voxels: AHashMap<VoxelKey, Voxel>,
}

impl VoxelMap {
    pub fn healthy_count(&self) -> usize {
        self.voxels.values().filter(|c| c.health > 0).count()
    }

    /// Fold a return into its voxel's covariance, relative to the voxel center.
    fn accumulate(&mut self, point: (f32, f32, f32), voxel_size: f32) {
        let key = world_to_voxel(point.0, point.1, point.2, 1.0 / voxel_size);
        let center = Vector3::new(
            (key.0 as f32 + 0.5) * voxel_size,
            (key.1 as f32 + 0.5) * voxel_size,
            (key.2 as f32 + 0.5) * voxel_size,
        );
        self.voxels
            .entry(key)
            .or_default()
            .observe(Vector3::new(point.0, point.1, point.2) - center);
    }

    #[cfg(test)]
    fn set(&mut self, key: VoxelKey, health: VoxelHealth) {
        self.voxels.insert(key, Voxel::with_health(health));
    }

    #[cfg(test)]
    fn health(&self, key: VoxelKey) -> Option<VoxelHealth> {
        self.voxels.get(&key).map(|c| c.health)
    }
}

/// Minimum points before a voxel's surface normal is trusted.
const NORMAL_MIN_POINTS: u32 = 3;
/// A voxel is planar when its smallest covariance eigenvalue is below this
/// fraction of the next-smallest.
const NORMAL_PLANAR_RATIO: f32 = 0.15;
/// A patch is a line with no defined normal when its middle eigenvalue is below
/// this fraction of the largest (e.g. a single grazing scan-line on a floor).
const NORMAL_LINE_RATIO: f32 = 0.15;

/// One voxel: occupancy health plus a running point covariance used to estimate
/// the local surface normal. Points are accumulated relative to the voxel center
/// to keep the moments small and f32-stable. The covariance lives and dies with
/// the voxel entry.
#[derive(Clone)]
pub struct Voxel {
    pub health: VoxelHealth,
    num_pts: u32,
    sum: Vector3<f32>,
    m2: Matrix3<f32>,
}

impl Default for Voxel {
    fn default() -> Self {
        Self {
            health: 0,
            num_pts: 0,
            sum: Vector3::zeros(),
            m2: Matrix3::zeros(),
        }
    }
}

impl Voxel {
    pub fn with_health(health: VoxelHealth) -> Self {
        Self {
            health,
            ..Default::default()
        }
    }

    fn observe(&mut self, q: Vector3<f32>) {
        self.num_pts += 1;
        self.sum += q;
        self.m2 += q * q.transpose();
    }

    /// Unit surface normal if the voxel holds enough confidently-planar points,
    /// else None (too sparse, or an edge/corner where the normal is ill-defined).
    fn planar_normal(&self) -> Option<Vector3<f32>> {
        if self.num_pts < NORMAL_MIN_POINTS {
            return None;
        }
        let n = self.num_pts as f32;
        let mean = self.sum / n;
        let cov = self.m2 / n - mean * mean.transpose();
        let eig = cov.symmetric_eigen();
        let mut idx = [0usize, 1, 2];
        idx.sort_by(|&a, &b| eig.eigenvalues[a].total_cmp(&eig.eigenvalues[b]));
        let e0 = eig.eigenvalues[idx[0]].max(0.0);
        let e1 = eig.eigenvalues[idx[1]].max(0.0);
        let e2 = eig.eigenvalues[idx[2]].max(0.0);
        if e2 < 1e-12 {
            return None;
        }
        // Reject a line: both in-plane directions must carry real spread, or the
        // normal is undefined (e.g. a single grazing scan-line across a floor).
        if e1 < NORMAL_LINE_RATIO * e2 {
            return None;
        }
        // Reject a patch that is not flat enough.
        if e0 > NORMAL_PLANAR_RATIO * e1 {
            return None;
        }
        Some(eig.eigenvectors.column(idx[0]).into_owned())
    }
}

/// Whether to spare an occupied voxel from a clearing miss: spare if a grazing
/// ray skims its surface, or if it is a confident edge/corner. Voxels with too
/// few points (no normal yet) are not spared, preserving the unguarded behavior.
fn should_spare(
    voxels: &AHashMap<VoxelKey, Voxel>,
    key: VoxelKey,
    ray_unit: Vector3<f32>,
    graze_cos: f32,
) -> bool {
    let Some(c) = voxels.get(&key) else {
        return false;
    };
    match c.planar_normal() {
        Some(n) => ray_unit.dot(&n).abs() < graze_cos,
        None => c.num_pts >= NORMAL_MIN_POINTS,
    }
}

pub struct LocalBounds {
    pub origin_x: f32,
    pub origin_y: f32,
    pub r_xy_max_sq: f32,
    pub z_min: f32,
    pub z_max: f32,
}

impl LocalBounds {
    pub fn contains(&self, x: f32, y: f32, z: f32) -> bool {
        if z < self.z_min || z > self.z_max {
            return false;
        }
        let dx = x - self.origin_x;
        let dy = y - self.origin_y;
        dx * dx + dy * dy <= self.r_xy_max_sq
    }
}

pub fn iter_global_points(
    map: &VoxelMap,
    voxel_size: f32,
) -> impl Iterator<Item = (f32, f32, f32)> + '_ {
    let half = voxel_size * 0.5;
    map.voxels
        .iter()
        .filter(|(_, c)| c.health > 0)
        .map(move |(&(kx, ky, kz), _)| {
            (
                kx as f32 * voxel_size + half,
                ky as f32 * voxel_size + half,
                kz as f32 * voxel_size + half,
            )
        })
}

/// Healthy voxel centers paired with their estimated surface normal. The normal
/// is the zero vector where the voxel has no confident planar normal.
pub fn iter_global_normals(
    map: &VoxelMap,
    voxel_size: f32,
) -> impl Iterator<Item = ((f32, f32, f32), [f32; 3])> + '_ {
    let half = voxel_size * 0.5;
    map.voxels
        .iter()
        .filter(|(_, c)| c.health > 0)
        .map(move |(&(kx, ky, kz), c)| {
            let pos = (
                kx as f32 * voxel_size + half,
                ky as f32 * voxel_size + half,
                kz as f32 * voxel_size + half,
            );
            let normal = c.planar_normal().map_or([0.0; 3], |n| [n[0], n[1], n[2]]);
            (pos, normal)
        })
}

fn live_voxels(points: &[(f32, f32, f32)], voxel_size: f32) -> AHashSet<VoxelKey> {
    let inv = 1.0_f32 / voxel_size;
    let mut out: AHashSet<VoxelKey> = AHashSet::with_capacity(points.len());
    for &(x, y, z) in points {
        out.insert(world_to_voxel(x, y, z, inv));
    }
    out
}

pub fn update_map(
    map: &mut VoxelMap,
    origin: (f32, f32, f32),
    points: &[(f32, f32, f32)],
    cfg: &Config,
) -> AHashSet<VoxelKey> {
    let inv = 1.0_f32 / cfg.voxel_size;
    let max_range_sq = if cfg.max_range > 0.0 {
        cfg.max_range * cfg.max_range
    } else {
        f32::INFINITY
    };

    let hits = live_voxels(points, cfg.voxel_size);

    let mut misses: AHashSet<VoxelKey> = AHashSet::new();
    let origin_voxel = world_to_voxel(origin.0, origin.1, origin.2, inv);
    let step = cfg.ray_subsample as usize;
    for (i, &p) in points.iter().enumerate() {
        if i % step != 0 {
            continue;
        }
        let dx = p.0 - origin.0;
        let dy = p.1 - origin.1;
        let dz = p.2 - origin.2;
        if dx * dx + dy * dy + dz * dz > max_range_sq {
            continue;
        }
        let endpoint = world_to_voxel(p.0, p.1, p.2, inv);
        find_misses_along_ray(
            &mut misses,
            &map.voxels,
            origin,
            p,
            cfg.voxel_size,
            cfg.shadow_depth,
            cfg.grace_depth,
            cfg.graze_cos,
            origin_voxel,
            endpoint,
        );
    }

    // add new hits
    for v in &hits {
        let c = map.voxels.entry(*v).or_insert_with(|| Voxel {
            health: cfg.min_health,
            ..Default::default()
        });
        c.health = (c.health + 1).min(cfg.max_health);
    }

    // accumulate each return into its voxel's covariance
    for &p in points {
        map.accumulate(p, cfg.voxel_size);
    }

    // each miss is only checked once; removal drops the covariance with it
    for v in misses.difference(&hits) {
        if let Some(c) = map.voxels.get_mut(v) {
            c.health -= 1;
            if c.health <= cfg.min_health {
                map.voxels.remove(v);
            }
        }
    }

    hits
}

#[inline]
fn world_to_voxel(x: f32, y: f32, z: f32, inv: f32) -> VoxelKey {
    (
        (x * inv).floor() as i32,
        (y * inv).floor() as i32,
        (z * inv).floor() as i32,
    )
}

/// Amanatides & Woo 3d DDA. Records voxels on ray in between the end of the shadow region
/// and origin if it is in the map. Voxels within grace region of the endpoint are spared from being marked as misses.
#[allow(clippy::too_many_arguments)]
fn find_misses_along_ray(
    misses: &mut AHashSet<VoxelKey>,
    map_voxels: &AHashMap<VoxelKey, Voxel>,
    origin: (f32, f32, f32),
    end: (f32, f32, f32),
    voxel_size: f32,
    shadow_depth: f32,
    grace_depth: f32,
    graze_cos: f32,
    origin_voxel: VoxelKey,
    endpoint: VoxelKey,
) {
    if origin_voxel == endpoint {
        return;
    }

    let (ox, oy, oz) = origin;
    let dx = end.0 - ox;
    let dy = end.1 - oy;
    let dz = end.2 - oz;

    let (mut x, mut y, mut z) = origin_voxel;

    let step_x = dx.signum() as i32;
    let step_y = dy.signum() as i32;
    let step_z = dz.signum() as i32;

    let t_max_init = |p: f32, d: f32, vox: i32, step: i32| -> f32 {
        if step == 0 {
            return f32::INFINITY;
        }
        let next_boundary = if step > 0 {
            (vox + 1) as f32 * voxel_size
        } else {
            vox as f32 * voxel_size
        };
        (next_boundary - p) / d
    };

    let mut tx = t_max_init(ox, dx, x, step_x);
    let mut ty = t_max_init(oy, dy, y, step_y);
    let mut tz = t_max_init(oz, dz, z, step_z);

    let dt_x = if step_x == 0 {
        f32::INFINITY
    } else {
        voxel_size / dx.abs()
    };
    let dt_y = if step_y == 0 {
        f32::INFINITY
    } else {
        voxel_size / dy.abs()
    };
    let dt_z = if step_z == 0 {
        f32::INFINITY
    } else {
        voxel_size / dz.abs()
    };

    let half = voxel_size * 0.5;
    let endpoint_center = (
        endpoint.0 as f32 * voxel_size + half,
        endpoint.1 as f32 * voxel_size + half,
        endpoint.2 as f32 * voxel_size + half,
    );
    let shadow_sq = shadow_depth.powi(2);
    let grace_sq = grace_depth.powi(2);

    let ray_len = (dx * dx + dy * dy + dz * dz).sqrt();
    let t_max = 1.0 + shadow_depth / ray_len.max(f32::EPSILON);
    let ray_unit = Vector3::new(dx, dy, dz) / ray_len.max(f32::EPSILON);

    let mut past_endpoint = false;
    loop {
        let t_enter = tx.min(ty).min(tz);
        if t_enter > t_max {
            return;
        }
        if t_enter >= 1.0 {
            past_endpoint = true;
        }

        if tx < ty {
            if tx < tz {
                x += step_x;
                tx += dt_x;
            } else {
                z += step_z;
                tz += dt_z;
            }
        } else if ty < tz {
            y += step_y;
            ty += dt_y;
        } else {
            z += step_z;
            tz += dt_z;
        }

        if (x, y, z) == endpoint {
            past_endpoint = true;
            continue;
        }

        // don't remove points in the same xy plane as the hit, unless the plane only walks that plane
        // we do this to preserve floors, which is more important than some missed points
        if origin_voxel.2 != endpoint.2 && z == endpoint.2 {
            continue;
        }

        let cx = x as f32 * voxel_size + half;
        let cy = y as f32 * voxel_size + half;
        let cz = z as f32 * voxel_size + half;
        let ddx = cx - endpoint_center.0;
        let ddy = cy - endpoint_center.1;
        let ddz = cz - endpoint_center.2;
        let dist_sq = ddx * ddx + ddy * ddy + ddz * ddz;

        if past_endpoint {
            // continue past the endpoint and in to the shadow realm
            if dist_sq > shadow_sq {
                return;
            }
        } else if dist_sq < grace_sq {
            // too close to the endpoint to safely mark as miss because we might be clipping other voxel's rays
            continue;
        }

        if map_voxels.contains_key(&(x, y, z))
            && !should_spare(map_voxels, (x, y, z), ray_unit, graze_cos)
        {
            misses.insert((x, y, z));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn basic_config() -> Config {
        Config {
            voxel_size: 1.0,
            max_range: 100.0,
            ray_subsample: 1,
            shadow_depth: 2.0,
            grace_depth: 0.0,
            min_health: 0,
            max_health: 1,
            graze_cos: 0.5,
        }
    }

    #[test]
    fn find_misses_along_ray_hits_correct_voxels_1() {
        let voxel_size = 1.0;
        let shadow_depth = 2.0;
        let origin = (0.5, 0.5, 0.5);
        let end = (5.5, 0.5, 0.5);
        let inv = 1.0 / voxel_size;
        let origin_voxel = world_to_voxel(origin.0, origin.1, origin.2, inv);
        let endpoint = world_to_voxel(end.0, end.1, end.2, inv);

        let expected: AHashSet<VoxelKey> = [
            (1, 0, 0),
            (2, 0, 0),
            (3, 0, 0),
            (4, 0, 0),
            (6, 0, 0),
            (7, 0, 0),
        ]
        .into_iter()
        .collect();
        let mut map_voxels: AHashMap<VoxelKey, Voxel> = AHashMap::new();
        for v in &expected {
            map_voxels.insert(*v, Voxel::with_health(1));
        }

        let mut misses: AHashSet<VoxelKey> = AHashSet::new();
        find_misses_along_ray(
            &mut misses,
            &map_voxels,
            origin,
            end,
            voxel_size,
            shadow_depth,
            0.0,
            0.5,
            origin_voxel,
            endpoint,
        );

        assert_eq!(misses, expected);
    }

    #[test]
    fn find_misses_along_ray_hits_correct_voxels_2() {
        let voxel_size = 1.0;
        let shadow_depth = 2.0;
        let origin = (0.5, 0.5, 0.5);
        let end = (3.5, 2.5, 1.5);
        let inv = 1.0 / voxel_size;
        let origin_voxel = world_to_voxel(origin.0, origin.1, origin.2, inv);
        let endpoint = world_to_voxel(end.0, end.1, end.2, inv);

        let walked: AHashSet<VoxelKey> = [
            (1, 0, 0),
            (1, 1, 0),
            (1, 1, 1),
            (2, 1, 1),
            (2, 2, 1),
            (4, 2, 1),
            (4, 3, 1),
            (4, 3, 2),
        ]
        .into_iter()
        .collect();
        let mut map_voxels: AHashMap<VoxelKey, Voxel> = AHashMap::new();
        for v in &walked {
            map_voxels.insert(*v, Voxel::with_health(1));
        }

        let mut misses: AHashSet<VoxelKey> = AHashSet::new();
        find_misses_along_ray(
            &mut misses,
            &map_voxels,
            origin,
            end,
            voxel_size,
            shadow_depth,
            0.0,
            0.5,
            origin_voxel,
            endpoint,
        );

        // z-slab protection skips voxels in the endpoint's z-slab when the
        // ray crosses z-slabs. Endpoint is at z=1 here.
        let expected: AHashSet<VoxelKey> = walked
            .iter()
            .filter(|v| v.2 != endpoint.2)
            .copied()
            .collect();
        assert_eq!(misses, expected);
    }

    #[test]
    fn hits_insert_voxels() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        update_map(
            &mut map,
            (0.0, 0.0, 0.0),
            &[(5.5, 0.5, 0.5), (0.5, 5.5, 0.5)],
            &cfg,
        );
        assert_eq!(map.health((5, 0, 0)), Some(1));
        assert_eq!(map.health((0, 5, 0)), Some(1));
        assert_eq!(map.voxels.len(), 2);
    }

    #[test]
    fn voxels_on_ray_are_removed() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        map.set((3, 0, 0), 1);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        // make sure the initial point got cleared by the new update
        assert!(!map.voxels.contains_key(&(3, 0, 0)));
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    #[test]
    fn voxels_not_on_ray_survive() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        map.set((3, 5, 0), 1);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((3, 5, 0)), Some(1));
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    #[test]
    fn voxels_within_shadow_region_are_removed() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        map.set((6, 0, 0), 1);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        // point within the shadow is no longer included, new point is included
        assert!(!map.voxels.contains_key(&(6, 0, 0)));
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    #[test]
    fn voxels_beyond_shadow_region_survive() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        map.set((8, 0, 0), 1);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((8, 0, 0)), Some(1));
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    #[test]
    fn hit_caught_by_other_ray_is_not_removed() {
        let cfg = basic_config();
        let mut map = VoxelMap::default();
        update_map(
            &mut map,
            (0.0, 0.0, 0.0),
            &[(3.5, 0.5, 0.5), (5.5, 0.5, 0.5)],
            &cfg,
        );
        assert_eq!(map.health((3, 0, 0)), Some(1));
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    #[test]
    fn point_beyond_max_range_does_not_clear() {
        let cfg = Config {
            max_range: 3.0,
            ..basic_config()
        };
        let mut map = VoxelMap::default();
        map.set((3, 0, 0), 1);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((3, 0, 0)), Some(1));
    }

    #[test]
    fn two_hits_needed_when_min_health_is_negative() {
        let cfg = Config {
            min_health: -1,
            ..basic_config()
        };
        let mut map = VoxelMap::default();
        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((5, 0, 0)), Some(0));

        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((5, 0, 0)), Some(1));
    }

    /// Test how bad the planar ray clipping is.
    /// For example, points on floors can be counted as misses because they are close to the same ray as the hit.
    #[test]
    fn ground_clipping_single_ray() {
        let voxel_size = 0.1_f32;
        let lidar_height = 1.0_f32;
        let cfg = Config {
            voxel_size,
            max_range: 50.0,
            ray_subsample: 1,
            shadow_depth: 0.2,
            grace_depth: 0.2,
            min_health: 0,
            max_health: 1,
            graze_cos: 0.5,
        };
        let inv = 1.0 / voxel_size;

        // Cover the full range we will probe, plus a little for shadow.
        let max_x = 25.0_f32;
        let n_ground = (max_x / voxel_size).ceil() as i32;

        let ranges: Vec<f32> = (1..=20).map(|i| i as f32).collect();
        let mut table = format!(
            "voxel_size={voxel_size} lidar_height={lidar_height} grace={} shadow={}\n\
             range_m  ground_voxels_in_row  clipped  clipped_pct\n",
            cfg.grace_depth, cfg.shadow_depth
        );
        let mut total_clipped = 0usize;
        for &range in &ranges {
            let mut map = VoxelMap::default();
            for i in 0..n_ground {
                let x = (i as f32) * voxel_size + voxel_size * 0.5;
                let key = world_to_voxel(x, 0.0, 0.0, inv);
                map.set(key, cfg.max_health);
            }
            let n_before = map.voxels.len();

            let origin = (0.0_f32, 0.0_f32, lidar_height);
            let points = vec![(range, 0.0_f32, 0.0_f32)];
            update_map(&mut map, origin, &points, &cfg);

            let n_after_ground: usize = (0..n_ground)
                .filter(|i| {
                    let x = (*i as f32) * voxel_size + voxel_size * 0.5;
                    let key = world_to_voxel(x, 0.0, 0.0, inv);
                    map.voxels.contains_key(&key)
                })
                .count();
            let clipped = n_before - n_after_ground;
            let pct = 100.0 * clipped as f32 / n_before as f32;
            table.push_str(&format!(
                "{range:>6.1}  {n_before:>20}  {clipped:>7}  {pct:>10.1}\n"
            ));
            total_clipped += clipped;
        }
        eprint!("{table}");
        assert!(
            total_clipped == 0,
            "planar grace regressed, ground voxels clipped:\n{table}"
        );
    }

    /// Dense surface samples for axis-aligned segments (vertical?, fixed, lo,
    /// hi), swept across a y band so the per-voxel covariance is a genuine 2d
    /// patch rather than a degenerate line in the x-z slice.
    fn sample_segments(
        segments: &[(bool, f32, f32, f32)],
        voxel_size: f32,
    ) -> Vec<(f32, f32, f32)> {
        let ds = voxel_size / 6.0;
        let ny = 5;
        let mut pts = Vec::new();
        for &(vertical, fixed, lo, hi) in segments {
            let n = ((hi - lo) / ds).round().max(1.0) as i32;
            for i in 0..=n {
                let t = lo + (hi - lo) * (i as f32 / n as f32);
                for j in 0..ny {
                    let yy = voxel_size * (0.15 + 0.7 * j as f32 / (ny - 1) as f32);
                    pts.push(if vertical {
                        (fixed, yy, t)
                    } else {
                        (t, yy, fixed)
                    });
                }
            }
        }
        pts
    }

    /// Build a map by accumulating sampled returns and marking each touched
    /// voxel occupied. Returns the map and the sorted unique voxel keys.
    fn build_surface(
        lidar: &[(f32, f32, f32)],
        voxel_size: f32,
        health: VoxelHealth,
    ) -> (VoxelMap, Vec<VoxelKey>) {
        let inv = 1.0 / voxel_size;
        let mut map = VoxelMap::default();
        for &p in lidar {
            map.accumulate(p, voxel_size);
        }
        let mut keys: Vec<VoxelKey> = lidar
            .iter()
            .map(|&(x, y, z)| world_to_voxel(x, y, z, inv))
            .collect();
        keys.sort();
        keys.dedup();
        for &k in &keys {
            map.voxels.get_mut(&k).unwrap().health = health;
        }
        (map, keys)
    }

    /// Nearest forward intersection (t > 0) of a ray with the segments, as an
    /// x-z point.
    fn nearest_hit(
        origin: (f32, f32, f32),
        d: (f32, f32),
        segments: &[(bool, f32, f32, f32)],
    ) -> Option<(f32, f32)> {
        let mut best: Option<(f32, (f32, f32))> = None;
        for &(vertical, fixed, lo, hi) in segments {
            let hit = if vertical {
                if d.0.abs() < 1e-9 {
                    continue;
                }
                let t = (fixed - origin.0) / d.0;
                let z = origin.2 + t * d.1;
                (t > 1e-4 && z >= lo && z <= hi).then_some((t, (fixed, z)))
            } else {
                if d.1.abs() < 1e-9 {
                    continue;
                }
                let t = (fixed - origin.2) / d.1;
                let x = origin.0 + t * d.0;
                (t > 1e-4 && x >= lo && x <= hi).then_some((t, (x, fixed)))
            };
            if let Some(cand) = hit {
                if best.is_none_or(|b| cand.0 < b.0) {
                    best = Some(cand);
                }
            }
        }
        best.map(|(_, p)| p)
    }

    /// Write an SVG of the x-z plane: kept voxels blue, cleared voxels red,
    /// ray-hit voxels green, the dense true-surface points, each ray from the
    /// sensor to its surface hit, and the sensor.
    #[allow(clippy::too_many_arguments)]
    fn write_stair_svg(
        path: &std::path::Path,
        stairs: &[VoxelKey],
        map: &VoxelMap,
        lidar_points: &[(f32, f32, f32)],
        origin: (f32, f32, f32),
        hits: &[(f32, f32, f32)],
        voxel_size: f32,
        shadow_depth: f32,
        grace_depth: f32,
    ) {
        use svg::node::element::{Circle, Definitions, Line, Marker, Path, Rectangle};
        use svg::Document;

        let inv = 1.0 / voxel_size;
        let origin_v = world_to_voxel(origin.0, origin.1, origin.2, inv);
        let hit_voxels: AHashSet<VoxelKey> = hits
            .iter()
            .map(|&(x, y, z)| world_to_voxel(x, y, z, inv))
            .collect();

        let mut keys: Vec<VoxelKey> = stairs.to_vec();
        keys.push(origin_v);
        keys.extend(hit_voxels.iter().copied());
        let xmin = keys.iter().map(|k| k.0).min().unwrap() - 2;
        let xmax = keys.iter().map(|k| k.0).max().unwrap() + 2;
        let zmin = keys.iter().map(|k| k.2).min().unwrap() - 2;
        let zmax = keys.iter().map(|k| k.2).max().unwrap() + 2;

        let s = 70.0_f32;
        let w = (xmax - xmin + 1) as f32 * s;
        let h = (zmax - zmin + 1) as f32 * s;
        let sx = |xi: f32| (xi - xmin as f32) * s;
        let sz = |zi: f32| (zmax as f32 + 1.0 - zi) * s;

        let mut doc = Document::new()
            .set("viewBox", (0.0, 0.0, w, h))
            .set("width", w)
            .set("height", h)
            .add(
                Rectangle::new()
                    .set("width", w)
                    .set("height", h)
                    .set("fill", "white"),
            )
            .add(
                Definitions::new().add(
                    Marker::new()
                        .set("id", "nrm")
                        .set("viewBox", "0 0 10 10")
                        .set("refX", 9)
                        .set("refY", 5)
                        .set("markerWidth", 5)
                        .set("markerHeight", 5)
                        .set("orient", "auto")
                        .add(
                            Path::new()
                                .set("d", "M0,0 L10,5 L0,10 z")
                                .set("fill", "#7b2cbf"),
                        ),
                ),
            );

        for xi in xmin..=xmax + 1 {
            let x = sx(xi as f32);
            doc = doc.add(
                Line::new()
                    .set("x1", x)
                    .set("y1", 0)
                    .set("x2", x)
                    .set("y2", h)
                    .set("stroke", "#eee"),
            );
        }
        for zi in zmin..=zmax + 1 {
            let y = sz(zi as f32);
            doc = doc.add(
                Line::new()
                    .set("x1", 0)
                    .set("y1", y)
                    .set("x2", w)
                    .set("y2", y)
                    .set("stroke", "#eee"),
            );
        }
        for &v in stairs {
            let fill = if hit_voxels.contains(&v) {
                "#2ca02c"
            } else if map.voxels.contains_key(&v) {
                "#4a78b0"
            } else {
                "#d62728"
            };
            doc = doc.add(
                Rectangle::new()
                    .set("x", sx(v.0 as f32))
                    .set("y", sz((v.2 + 1) as f32))
                    .set("width", s)
                    .set("height", s)
                    .set("fill", fill)
                    .set("stroke", "black"),
            );
        }

        // Per-voxel surface normal, projected into the x-z plane and oriented
        // toward the sensor. Voxels with no confident planar normal get none.
        for &v in stairs {
            let Some(normal) = map.voxels.get(&v).and_then(Voxel::planar_normal) else {
                continue;
            };
            let (mut nx, mut nz) = (normal[0], normal[2]);
            let mag = (nx * nx + nz * nz).sqrt();
            if mag < 1e-3 {
                continue;
            }
            nx /= mag;
            nz /= mag;
            let (cx, cz) = (v.0 as f32 + 0.5, v.2 as f32 + 0.5);
            if nx * (origin.0 * inv - cx) + nz * (origin.2 * inv - cz) < 0.0 {
                nx = -nx;
                nz = -nz;
            }
            let len = 0.6;
            doc = doc.add(
                Line::new()
                    .set("x1", sx(cx))
                    .set("y1", sz(cz))
                    .set("x2", sx(cx + nx * len))
                    .set("y2", sz(cz + nz * len))
                    .set("stroke", "#7b2cbf")
                    .set("stroke-width", 3)
                    .set("marker-end", "url(#nrm)"),
            );
        }

        for &(px, _, pz) in lidar_points {
            doc = doc.add(
                Circle::new()
                    .set("cx", sx(px * inv))
                    .set("cy", sz(pz * inv))
                    .set("r", 2.0)
                    .set("fill", "#111")
                    .set("fill-opacity", 0.85),
            );
        }

        let oc = (origin.0 * inv, origin.2 * inv);
        let shadow_idx = shadow_depth * inv;
        let grace_px = grace_depth * inv * s;
        for &(hx, _, hz) in hits {
            let hc = (hx * inv, hz * inv);
            let dir = (hc.0 - oc.0, hc.1 - oc.1);
            let dlen = (dir.0 * dir.0 + dir.1 * dir.1).sqrt().max(f32::EPSILON);
            let sh = (
                hc.0 + dir.0 / dlen * shadow_idx,
                hc.1 + dir.1 / dlen * shadow_idx,
            );
            doc = doc
                .add(
                    Line::new()
                        .set("x1", sx(oc.0))
                        .set("y1", sz(oc.1))
                        .set("x2", sx(hc.0))
                        .set("y2", sz(hc.1))
                        .set("stroke", "orange")
                        .set("stroke-width", 2),
                )
                .add(
                    Line::new()
                        .set("x1", sx(hc.0))
                        .set("y1", sz(hc.1))
                        .set("x2", sx(sh.0))
                        .set("y2", sz(sh.1))
                        .set("stroke", "purple")
                        .set("stroke-width", 2)
                        .set("stroke-dasharray", "5"),
                )
                .add(
                    Circle::new()
                        .set("cx", sx(hc.0))
                        .set("cy", sz(hc.1))
                        .set("r", grace_px)
                        .set("fill", "none")
                        .set("stroke", "green")
                        .set("stroke-dasharray", "4"),
                )
                .add(
                    Circle::new()
                        .set("cx", sx(hc.0))
                        .set("cy", sz(hc.1))
                        .set("r", 4)
                        .set("fill", "darkgreen"),
                );
        }
        doc = doc.add(
            Circle::new()
                .set("cx", sx(oc.0))
                .set("cy", sz(oc.1))
                .set("r", 6)
                .set("fill", "darkorange"),
        );

        svg::save(path, &doc).expect("write stair_clip.svg");
    }

    /// A fan of lidar rays from a sensor at the foot of a staircase. Each ray
    /// direction is intersected with the true continuous surface to find its
    /// hit point, then the whole frame is fed to the mapper. Rays that reach an
    /// upper step graze the voxels of the lower steps they pass over, and the
    /// thin-ray DDA clears that real geometry. A correct clearing pass must
    /// leave every stair voxel intact.
    ///
    /// Run it with `cargo test stair_clipping_ray_fan -- --nocapture`.
    #[test]
    fn stair_clipping_ray_fan() {
        let voxel_size = 0.1_f32;
        let half = voxel_size * 0.5;
        let cfg = Config {
            voxel_size,
            max_range: 50.0,
            ray_subsample: 1,
            shadow_depth: 0.2,
            grace_depth: 0.2,
            min_health: 0,
            max_health: 1,
            graze_cos: 0.5,
        };

        // True continuous staircase in the x-z plane (single y row): household
        // slope, run = 0.3 m, rise = 0.2 m. Each step is a vertical riser face
        // and a horizontal tread top, stored as axis-aligned segments
        // (vertical?, fixed, lo, hi) in world meters.
        const N: i32 = 5;
        let run = 3.0 * voxel_size;
        let rise = 2.0 * voxel_size;
        let first_riser_x = 3.0 * voxel_size + half;
        let base_z = half;
        let mut segments: Vec<(bool, f32, f32, f32)> = Vec::new();
        for k in 1..=N {
            let rx = first_riser_x + (k - 1) as f32 * run;
            let zb = base_z + (k - 1) as f32 * rise;
            let zt = base_z + k as f32 * rise;
            segments.push((true, rx, zb, zt));
            segments.push((false, zt, rx, rx + run));
        }

        let lidar = sample_segments(&segments, voxel_size);
        let (mut map, all_stairs) = build_surface(&lidar, voxel_size, cfg.max_health);

        // Sensor at the foot of the stairs, 0.23 m off the ground.
        let origin = (half, half, base_z + 0.23);

        // Six rays evenly spaced in elevation, sweeping the staircase. Each
        // ray's hit is the nearest forward intersection with a surface segment.
        const N_RAYS: usize = 6;
        let (lo_deg, hi_deg) = (0.0_f32, 27.0_f32);
        let mut hits: Vec<(f32, f32, f32)> = Vec::new();
        for i in 0..N_RAYS {
            let frac = i as f32 / (N_RAYS - 1) as f32;
            let theta = (lo_deg + (hi_deg - lo_deg) * frac).to_radians();
            if let Some((hx, hz)) = nearest_hit(origin, (theta.cos(), theta.sin()), &segments) {
                hits.push((hx, half, hz));
            }
        }

        update_map(&mut map, origin, &hits, &cfg);

        let svg_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("stair_clip.svg");
        write_stair_svg(
            &svg_path,
            &all_stairs,
            &map,
            &lidar,
            origin,
            &hits,
            voxel_size,
            cfg.shadow_depth,
            cfg.grace_depth,
        );
        eprintln!("wrote {}", svg_path.display());

        // No real stair voxel may be cleared: every ray that grazes a step's
        // voxels en route to its true hit must leave them intact.
        let cleared: Vec<VoxelKey> = all_stairs
            .iter()
            .copied()
            .filter(|v| !map.voxels.contains_key(v))
            .collect();
        eprintln!(
            "{} rays hit, cleared {} stair voxel(s): {cleared:?}",
            hits.len(),
            cleared.len()
        );
        assert!(
            cleared.is_empty(),
            "ray fan cleared {} real stair voxel(s): {cleared:?}",
            cleared.len()
        );
    }

    /// A flat landing floor with a wall at the far end, scanned by a fan of rays
    /// from a sensor above the floor. Reports which floor voxels get cleared and
    /// prints a sample of floor-voxel normals. Tune SENSOR_HEIGHT / shadow_depth
    /// / NORMAL_MIN_POINTS to probe what erodes the floor.
    ///
    /// Run it with `cargo test landing_floor_ray_fan -- --nocapture`.
    #[test]
    fn landing_floor_ray_fan() {
        let voxel_size = 0.1_f32;
        let half = voxel_size * 0.5;
        let cfg = Config {
            voxel_size,
            max_range: 50.0,
            ray_subsample: 1,
            shadow_depth: 0.2,
            grace_depth: 0.2,
            min_health: 0,
            max_health: 1,
            graze_cos: 0.5,
        };

        // Flat floor (horizontal, row 0) from the sensor out to a vertical wall.
        let floor_z = half;
        let x_wall = 25.0 * voxel_size + half;
        let segments = vec![
            (false, floor_z, half, x_wall),         // floor
            (true, x_wall, floor_z, floor_z + 1.0), // wall
        ];

        let lidar = sample_segments(&segments, voxel_size);
        let (mut map, all_surf) = build_surface(&lidar, voxel_size, cfg.max_health);

        // Sensor above the floor. Drop this toward 0 to disable the z-slab guard
        // (origin and floor in the same z-row) and stress the normal gate.
        const SENSOR_HEIGHT: f32 = 0.3;
        let origin = (half, half, floor_z + SENSOR_HEIGHT);

        // Floor voxels and their normals, sampled before any clearing.
        let floor: Vec<VoxelKey> = all_surf.iter().copied().filter(|k| k.2 == 0).collect();
        for &k in floor.iter().step_by(floor.len().max(6) / 6) {
            let normal = map.voxels.get(&k).and_then(Voxel::planar_normal);
            eprintln!(
                "  floor {k:?} normal {:?}",
                normal.map(|n| [n[0], n[1], n[2]])
            );
        }

        // Fan sweeping from steep-down at the near floor up to the wall.
        const N_RAYS: usize = 16;
        let (lo_deg, hi_deg) = (-35.0_f32, 18.0_f32);
        let mut hits: Vec<(f32, f32, f32)> = Vec::new();
        for i in 0..N_RAYS {
            let frac = i as f32 / (N_RAYS - 1) as f32;
            let theta = (lo_deg + (hi_deg - lo_deg) * frac).to_radians();
            if let Some((hx, hz)) = nearest_hit(origin, (theta.cos(), theta.sin()), &segments) {
                hits.push((hx, half, hz));
            }
        }

        update_map(&mut map, origin, &hits, &cfg);

        let svg_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("floor_clip.svg");
        write_stair_svg(
            &svg_path,
            &all_surf,
            &map,
            &lidar,
            origin,
            &hits,
            voxel_size,
            cfg.shadow_depth,
            cfg.grace_depth,
        );
        eprintln!("wrote {}", svg_path.display());

        let cleared: Vec<VoxelKey> = floor
            .iter()
            .copied()
            .filter(|v| !map.voxels.contains_key(v))
            .collect();
        eprintln!(
            "{} rays hit, {} floor voxels, cleared {}: {cleared:?}",
            hits.len(),
            floor.len(),
            cleared.len()
        );
        assert!(
            cleared.is_empty(),
            "ray fan cleared {} floor voxel(s): {cleared:?}",
            cleared.len()
        );
    }

    /// Robot on the step just below a landing, sensor at head height, so it can
    /// just see over the landing. A single frame does NOT erode it: the rays hit
    /// the surface directly and the grazed voxels share the hit's z-row, so the
    /// z-slab guard protects them. This regression guard documents that the
    /// realistic single-frame view is safe; real-data landing loss is a
    /// multi-frame occlusion effect, reproduced elsewhere.
    ///
    /// Run it with `cargo test landing_grazed_from_below -- --nocapture`.
    #[test]
    fn landing_grazed_from_below() {
        let voxel_size = 0.1_f32;
        let half = voxel_size * 0.5;
        let cfg = |graze_cos| Config {
            voxel_size,
            max_range: 50.0,
            ray_subsample: 1,
            shadow_depth: 0.2,
            grace_depth: 0.2,
            min_health: 0,
            max_health: 1,
            graze_cos,
        };

        // Staircase, then the top tread extended into a long flat landing and a
        // back wall for the grazing rays to terminate on.
        const N: i32 = 5;
        let run = 3.0 * voxel_size;
        let rise = 2.0 * voxel_size;
        let first_riser_x = 3.0 * voxel_size + half;
        let base_z = half;
        let mut segments: Vec<(bool, f32, f32, f32)> = Vec::new();
        for k in 1..=N {
            let rx = first_riser_x + (k - 1) as f32 * run;
            let zb = base_z + (k - 1) as f32 * rise;
            let zt = base_z + k as f32 * rise;
            segments.push((true, rx, zb, zt));
            if k < N {
                segments.push((false, zt, rx, rx + run));
            }
        }
        let z_top = base_z + N as f32 * rise;
        let landing_x0 = first_riser_x + (N - 1) as f32 * run;
        segments.push((false, z_top, landing_x0, landing_x0 + 1.0));
        segments.push((true, landing_x0 + 1.0, z_top, z_top + 1.0));

        let lidar = sample_segments(&segments, voxel_size);
        let landing_row = (z_top / voxel_size).floor() as i32;

        // Robot on the step just below the landing, sensor 0.3 m up: it can just
        // see over the landing edge, so its downward fan grazes that edge at the
        // slope angle and skims the surface beyond toward the back wall.
        let step_below_x = first_riser_x + (N - 2) as f32 * run + run * 0.5;
        let origin = (step_below_x, half, z_top - rise + 0.3);
        const N_RAYS: usize = 16;
        let (lo_deg, hi_deg) = (-38.0_f32, -2.0_f32);
        let mut hits: Vec<(f32, f32, f32)> = Vec::new();
        for i in 0..N_RAYS {
            let frac = i as f32 / (N_RAYS - 1) as f32;
            let theta = (lo_deg + (hi_deg - lo_deg) * frac).to_radians();
            if let Some((hx, hz)) = nearest_hit(origin, (theta.cos(), theta.sin()), &segments) {
                hits.push((hx, half, hz));
            }
        }

        let (mut map, surf) = build_surface(&lidar, voxel_size, 1);
        update_map(&mut map, origin, &hits, &cfg(0.7));
        let svg = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("landing_clip.svg");
        write_stair_svg(
            &svg, &surf, &map, &lidar, origin, &hits, voxel_size, 0.2, 0.2,
        );
        eprintln!("wrote {}", svg.display());

        // When the robot can see the landing, it hits the surface directly and
        // the grazed voxels share the hit's z-row, so the z-slab guard protects
        // them. The landing must survive this view. (Real-data landing loss is a
        // multi-frame occlusion effect, not a single grazing frame.)
        let cleared: Vec<VoxelKey> = surf
            .iter()
            .copied()
            .filter(|k| k.2 == landing_row && !map.voxels.contains_key(k))
            .collect();
        eprintln!("landing voxels cleared: {} {cleared:?}", cleared.len());
        assert!(
            cleared.is_empty(),
            "landing must survive when the robot can see over it; cleared {cleared:?}"
        );
    }

    #[test]
    fn two_misses_needed_when_max_health_is_two() {
        let cfg = Config {
            max_health: 2,
            ..basic_config()
        };
        let mut map = VoxelMap::default();
        update_map(&mut map, (0.0, 0.0, 0.0), &[(3.5, 0.5, 0.5)], &cfg);
        update_map(&mut map, (0.0, 0.0, 0.0), &[(3.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((3, 0, 0)), Some(2));

        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert_eq!(map.health((3, 0, 0)), Some(1));

        update_map(&mut map, (0.0, 0.0, 0.0), &[(5.5, 0.5, 0.5)], &cfg);
        assert!(!map.voxels.contains_key(&(3, 0, 0)));
    }

    #[test]
    fn planar_patch_yields_vertical_normal() {
        let mut v = Voxel::default();
        for i in 0..8 {
            for j in 0..8 {
                let x = 0.09 * (i as f32 / 7.0 - 0.5);
                let y = 0.09 * (j as f32 / 7.0 - 0.5);
                v.observe(Vector3::new(x, y, 0.0));
            }
        }
        let n = v.planar_normal().expect("a 2d patch has a normal");
        assert!(n[2].abs() > 0.99, "expected ~vertical normal, got {n:?}");
    }

    #[test]
    fn line_like_patch_has_no_normal() {
        // Wide in y, ~zero in x, tiny z noise: a grazing scan-line across a flat
        // floor. Its smallest eigenvector is horizontal, so trusting it would
        // clear the floor; the line guard must reject it.
        let mut v = Voxel::default();
        for j in 0..20 {
            let y = 0.08 * (j as f32 / 19.0 - 0.5);
            let z = 0.003 * ((j % 3) - 1) as f32;
            v.observe(Vector3::new(0.0, y, z));
        }
        assert!(
            v.planar_normal().is_none(),
            "a line-like patch must not yield a normal"
        );
    }

    #[test]
    fn validate_rejects_zero_voxel_size() {
        let cfg = Config {
            voxel_size: 0.0,
            ..basic_config()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn validate_rejects_min_health_geq_max_health() {
        let cfg = Config {
            min_health: 5,
            max_health: 1,
            ..basic_config()
        };
        assert!(cfg.validate().is_err());
    }

    #[test]
    fn validate_accepts_basic_config() {
        assert!(basic_config().validate().is_ok());
    }
}
