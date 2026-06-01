// LCM-driven FAST-LIO2 native module.
//
// Consumes a livox lidar PointCloud2 + Imu stream, runs the FAST-LIO2 pipeline,
// and publishes Odometry plus the registered (world-frame) scan.

use std::time::Duration;

use dimos_module::{error_throttled, run, warn_throttled, Input, LcmTransport, Module, Output};
use lcm_msgs::geometry_msgs::{
    Point as GeomPoint, Pose, PoseWithCovariance, Quaternion, Twist, TwistWithCovariance, Vector3,
};
use lcm_msgs::nav_msgs::Odometry;
use lcm_msgs::sensor_msgs::{Imu, PointCloud2, PointField};
use lcm_msgs::std_msgs::{Header, Time};
use nalgebra::UnitQuaternion;
use serde::Deserialize;

use fastlio2::commons::{Config as PipelineConfig, IMUData, Point, PointCloud, SyncPackage, V3D};
use fastlio2::lidar_processor::LidarProcessor;
use fastlio2::map_builder::{BuilderStatus, MapBuilder};

const POINT_STEP: i32 = 16;
const FLOAT32: u8 = PointField::FLOAT32 as u8;

#[derive(Debug, Deserialize)]
struct ModuleConfig {
    #[serde(default = "default_frame_id")]
    frame_id: String,
    #[serde(default = "default_child_frame_id")]
    child_frame_id: String,
    #[serde(flatten)]
    pipeline: PipelineConfig,
}

fn default_frame_id() -> String {
    "odom".to_string()
}

fn default_child_frame_id() -> String {
    "base_link".to_string()
}

#[derive(Module)]
#[module(setup = on_start)]
struct FastLio2Rust {
    #[input(decode = PointCloud2::decode, handler = on_lidar)]
    lidar: Input<PointCloud2>,

    #[input(decode = Imu::decode, handler = on_imu)]
    imu: Input<Imu>,

    #[output(encode = Odometry::encode)]
    odometry: Output<Odometry>,

    #[output(encode = PointCloud2::encode)]
    world_cloud: Output<PointCloud2>,

    #[config]
    config: ModuleConfig,

    builder: Option<MapBuilder>,
    imu_buffer: Vec<IMUData>,
}

impl FastLio2Rust {
    async fn on_start(&mut self) {
        self.builder = Some(MapBuilder::new(self.config.pipeline.clone()));
        tracing::info!(
            frame_id = %self.config.frame_id,
            child_frame_id = %self.config.child_frame_id,
            "fastlio2_rust initialized"
        );
    }

    async fn on_imu(&mut self, msg: Imu) {
        self.imu_buffer.push(IMUData {
            acc: V3D::new(
                msg.linear_acceleration.x,
                msg.linear_acceleration.y,
                msg.linear_acceleration.z,
            ),
            gyro: V3D::new(
                msg.angular_velocity.x,
                msg.angular_velocity.y,
                msg.angular_velocity.z,
            ),
            time: stamp_to_sec(&msg.header.stamp),
        });
    }

    async fn on_lidar(&mut self, msg: PointCloud2) {
        // The pipeline needs imu samples spanning the scan before it can start.
        if self.imu_buffer.is_empty() {
            return;
        }

        let cloud = match extract_cloud(&msg) {
            Ok(cloud) => cloud,
            Err(error) => {
                warn_throttled!(Duration::from_secs(1), error = %error, "dropped a lidar scan");
                return;
            }
        };
        if cloud.is_empty() {
            return;
        }

        // Per-point curvature holds the ms offset from the scan start (the "time"
        // field). The largest offset is the scan end; it collapses to the start
        // when the source carries no per-point time, disabling undistortion.
        let stamp_sec = stamp_to_sec(&msg.header.stamp);
        let max_offset_sec = cloud
            .iter()
            .fold(0.0f32, |acc, point| acc.max(point.curvature))
            as f64
            / 1000.0;
        let mut package = SyncPackage {
            imus: std::mem::take(&mut self.imu_buffer),
            cloud,
            cloud_start_time: stamp_sec,
            cloud_end_time: stamp_sec + max_offset_sec,
        };

        let builder = self.builder.as_mut().expect("builder set in on_start");
        builder.process(&mut package);

        if builder.status() != BuilderStatus::Mapping {
            return;
        }

        let odometry = build_odometry(builder, &self.config, msg.header.stamp.clone());
        if let Err(error) = self.odometry.publish(&odometry).await {
            error_throttled!(Duration::from_secs(1), error = %error, "odometry publish failed");
        }

        let world = register_cloud(builder, &package.cloud);
        let world_msg = build_pointcloud(&world, &self.config.frame_id, msg.header.stamp);
        if let Err(error) = self.world_cloud.publish(&world_msg).await {
            error_throttled!(Duration::from_secs(1), error = %error, "world_cloud publish failed");
        }
    }
}

fn stamp_to_sec(stamp: &Time) -> f64 {
    stamp.sec as f64 + stamp.nsec as f64 * 1e-9
}

fn build_odometry(builder: &MapBuilder, config: &ModuleConfig, stamp: Time) -> Odometry {
    let state = &builder.kf.x;
    let translation = state.t_wi;
    let quaternion = UnitQuaternion::from_matrix(&state.r_wi);
    let velocity = state.v;
    Odometry {
        header: Header {
            seq: 0,
            stamp,
            frame_id: config.frame_id.clone(),
        },
        child_frame_id: config.child_frame_id.clone(),
        pose: PoseWithCovariance {
            pose: Pose {
                position: GeomPoint {
                    x: translation.x,
                    y: translation.y,
                    z: translation.z,
                },
                orientation: Quaternion {
                    x: quaternion.i,
                    y: quaternion.j,
                    z: quaternion.k,
                    w: quaternion.w,
                },
            },
            covariance: [0.0; 36],
        },
        twist: TwistWithCovariance {
            twist: Twist {
                linear: Vector3 {
                    x: velocity.x,
                    y: velocity.y,
                    z: velocity.z,
                },
                angular: Vector3 {
                    x: 0.0,
                    y: 0.0,
                    z: 0.0,
                },
            },
            covariance: [0.0; 36],
        },
    }
}

fn register_cloud(builder: &MapBuilder, body_cloud: &PointCloud) -> PointCloud {
    let r_wl = builder.lidar_processor.r_wl(&builder.kf);
    let t_wl = builder.lidar_processor.t_wl(&builder.kf);
    LidarProcessor::transform_cloud(body_cloud, &r_wl, &t_wl)
}

#[derive(Debug)]
struct ExtractError(&'static str);

impl std::fmt::Display for ExtractError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.0)
    }
}

fn extract_cloud(msg: &PointCloud2) -> Result<PointCloud, ExtractError> {
    if msg.is_bigendian {
        return Err(ExtractError("big-endian point data not supported"));
    }
    let mut x_offset: Option<usize> = None;
    let mut y_offset: Option<usize> = None;
    let mut z_offset: Option<usize> = None;
    let mut intensity_offset: Option<usize> = None;
    let mut time_offset: Option<usize> = None;
    for field in &msg.fields {
        if field.datatype != FLOAT32 {
            continue;
        }
        match field.name.as_str() {
            "x" => x_offset = Some(field.offset as usize),
            "y" => y_offset = Some(field.offset as usize),
            "z" => z_offset = Some(field.offset as usize),
            "intensity" => intensity_offset = Some(field.offset as usize),
            "time" | "t" | "timestamp" | "curvature" => time_offset = Some(field.offset as usize),
            _ => {}
        }
    }
    let x_offset = x_offset.ok_or(ExtractError("missing float32 x field"))?;
    let y_offset = y_offset.ok_or(ExtractError("missing float32 y field"))?;
    let z_offset = z_offset.ok_or(ExtractError("missing float32 z field"))?;

    let count = (msg.width as usize) * (msg.height as usize);
    let step = msg.point_step as usize;
    if step == 0 {
        return Err(ExtractError("point_step is 0"));
    }
    if msg.data.len() < count * step {
        return Err(ExtractError("data shorter than width*height*point_step"));
    }
    let max_offset = x_offset.max(y_offset).max(z_offset);
    if max_offset + 4 > step {
        return Err(ExtractError("xyz offsets do not fit within point_step"));
    }

    let mut cloud = Vec::with_capacity(count);
    for index in 0..count {
        let base = index * step;
        let x = read_f32(&msg.data, base + x_offset);
        let y = read_f32(&msg.data, base + y_offset);
        let z = read_f32(&msg.data, base + z_offset);
        if !(x.is_finite() && y.is_finite() && z.is_finite()) {
            continue;
        }
        let intensity = match intensity_offset {
            Some(offset) if offset + 4 <= step => read_f32(&msg.data, base + offset),
            _ => 0.0,
        };
        // Pipeline expects curvature as the ms offset from scan start.
        let curvature = match time_offset {
            Some(offset) if offset + 4 <= step => read_f32(&msg.data, base + offset) * 1000.0,
            _ => 0.0,
        };
        cloud.push(Point {
            x,
            y,
            z,
            intensity,
            curvature,
        });
    }
    Ok(cloud)
}

fn build_pointcloud(cloud: &PointCloud, frame_id: &str, stamp: Time) -> PointCloud2 {
    let mut data = Vec::with_capacity(cloud.len() * POINT_STEP as usize);
    for point in cloud {
        data.extend_from_slice(&point.x.to_le_bytes());
        data.extend_from_slice(&point.y.to_le_bytes());
        data.extend_from_slice(&point.z.to_le_bytes());
        data.extend_from_slice(&point.intensity.to_le_bytes());
    }
    let make_field = |name: &str, offset: i32| PointField {
        name: name.into(),
        offset,
        datatype: FLOAT32,
        count: 1,
    };
    let width = cloud.len() as i32;
    PointCloud2 {
        header: Header {
            seq: 0,
            stamp,
            frame_id: frame_id.into(),
        },
        height: 1,
        width,
        fields: vec![
            make_field("x", 0),
            make_field("y", 4),
            make_field("z", 8),
            make_field("intensity", 12),
        ],
        is_bigendian: false,
        point_step: POINT_STEP,
        row_step: POINT_STEP * width,
        data,
        is_dense: true,
    }
}

fn read_f32(buffer: &[u8], offset: usize) -> f32 {
    let bytes: [u8; 4] = buffer[offset..offset + 4]
        .try_into()
        .expect("bounds checked by caller");
    f32::from_le_bytes(bytes)
}

#[tokio::main]
async fn main() {
    let transport = LcmTransport::new()
        .await
        .expect("failed to create LCM transport");
    run::<FastLio2Rust, _>(transport)
        .await
        .expect("fastlio2_rust run failed");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn module_config_parses_with_defaults() {
        let config: ModuleConfig = serde_json::from_str("{}").unwrap();
        assert_eq!(config.frame_id, "odom");
        assert_eq!(config.child_frame_id, "base_link");
        assert_eq!(config.pipeline.imu_init_num, 20);
    }

    #[test]
    fn module_config_overrides_pipeline_fields() {
        let json = r#"{
            "frame_id": "map",
            "child_frame_id": "imu_link",
            "scan_resolution": 0.05,
            "lidar_max_range": 30.0,
            "gravity_align": false
        }"#;
        let config: ModuleConfig = serde_json::from_str(json).unwrap();
        assert_eq!(config.frame_id, "map");
        assert_eq!(config.child_frame_id, "imu_link");
        assert_eq!(config.pipeline.scan_resolution, 0.05);
        assert_eq!(config.pipeline.lidar_max_range, 30.0);
        assert!(!config.pipeline.gravity_align);
    }

    #[test]
    fn extract_cloud_reads_xyz_intensity() {
        let msg = build_pointcloud(
            &vec![
                Point {
                    x: 1.0,
                    y: 2.0,
                    z: 3.0,
                    intensity: 9.0,
                    curvature: 0.0,
                },
                Point {
                    x: 4.0,
                    y: 5.0,
                    z: 6.0,
                    intensity: 8.0,
                    curvature: 0.0,
                },
            ],
            "lidar",
            Time::default(),
        );
        let cloud = extract_cloud(&msg).unwrap();
        assert_eq!(cloud.len(), 2);
        assert_eq!(cloud[0].x, 1.0);
        assert_eq!(cloud[1].intensity, 8.0);
    }

    #[test]
    fn extract_cloud_reads_time_into_curvature_ms() {
        // x, y, z, intensity, time (float32) => point_step 20. time is seconds
        // from scan start; curvature must come back in milliseconds.
        let points: [(f32, f32, f32, f32, f32); 2] =
            [(1.0, 2.0, 3.0, 0.0, 0.0), (4.0, 5.0, 6.0, 0.0, 0.005)];
        let mut data = Vec::new();
        for (x, y, z, intensity, time) in points {
            for value in [x, y, z, intensity, time] {
                data.extend_from_slice(&value.to_le_bytes());
            }
        }
        let make_field = |name: &str, offset: i32| PointField {
            name: name.into(),
            offset,
            datatype: FLOAT32,
            count: 1,
        };
        let msg = PointCloud2 {
            header: Header {
                seq: 0,
                stamp: Time::default(),
                frame_id: "lidar".into(),
            },
            height: 1,
            width: 2,
            fields: vec![
                make_field("x", 0),
                make_field("y", 4),
                make_field("z", 8),
                make_field("intensity", 12),
                make_field("time", 16),
            ],
            is_bigendian: false,
            point_step: 20,
            row_step: 40,
            data,
            is_dense: true,
        };
        let cloud = extract_cloud(&msg).unwrap();
        assert_eq!(cloud.len(), 2);
        assert_eq!(cloud[0].curvature, 0.0);
        assert!((cloud[1].curvature - 5.0).abs() < 1e-4);
    }
}
