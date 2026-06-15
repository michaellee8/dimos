// Copyright 2026 Dimensional Inc.
// SPDX-License-Identifier: Apache-2.0
//
// Point-LIO native module (topic-isolated): consumes Imu + PointCloud2 LCM
// streams (e.g. published by the Mid360 module) and runs the Point-LIO IESKF,
// publishing odometry. No Livox SDK — the sensor lives in a separate module.
//
// Usage:
//   ./pointlio_native \
//       --imu '/imu#sensor_msgs.Imu' \
//       --lidar '/lidar#sensor_msgs.PointCloud2' \
//       --odometry '/odometry#nav_msgs.Odometry' \
//       --config_path /path/to/default.yaml

#include <lcm/lcm-cpp.hpp>

#include <atomic>
#include <boost/make_shared.hpp>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#include "dimos_native_module.hpp"

#include "nav_msgs/Odometry.hpp"
#include "sensor_msgs/Imu.hpp"
#include "sensor_msgs/PointCloud2.hpp"

// Point-LIO (header-only core, compiled sources linked via CMake)
#include "pointlio.hpp"
#include "pointlio_debug.hpp"

// The Mid360 module publishes IMU accel in m/s^2 (raw_g * GRAVITY_MS2); Point-LIO
// expects g (config acc_norm = 1.0), so divide it back out. Must match the
// publisher's constant (livox common GRAVITY_MS2).
static constexpr double GRAVITY_MS2 = 9.80665;

static std::atomic<bool> g_running{true};
static lcm::LCM* g_lcm = nullptr;
static PointLio* g_point_lio = nullptr;
static std::string g_odometry_topic;
static std::string g_frame_id;        // odometry header frame (sensor frame)
static std::string g_child_frame_id;  // odometry child frame
static bool g_warned_lidar_fields = false;

using dimos::make_header;

static double stamp_to_sec(const std_msgs::Time& t) {
    return static_cast<double>(t.sec) + static_cast<double>(t.nsec) / 1e9;
}

static void publish_odometry(const custom_messages::Odometry& odom, double timestamp) {
    if (!g_lcm || g_odometry_topic.empty()) { return; }

    nav_msgs::Odometry msg;
    msg.header = make_header(g_frame_id, timestamp);
    msg.child_frame_id = g_child_frame_id;

    msg.pose.pose.position.x = odom.pose.pose.position.x;
    msg.pose.pose.position.y = odom.pose.pose.position.y;
    msg.pose.pose.position.z = odom.pose.pose.position.z;
    msg.pose.pose.orientation.x = odom.pose.pose.orientation.x;
    msg.pose.pose.orientation.y = odom.pose.pose.orientation.y;
    msg.pose.pose.orientation.z = odom.pose.pose.orientation.z;
    msg.pose.pose.orientation.w = odom.pose.pose.orientation.w;
    for (int idx = 0; idx < 36; ++idx) {
        msg.pose.covariance[idx] = odom.pose.covariance[idx];
    }

    // Velocity from Point-LIO's IESKF state (its key output over FAST-LIO).
    msg.twist.twist.linear.x = odom.twist.twist.linear.x;
    msg.twist.twist.linear.y = odom.twist.twist.linear.y;
    msg.twist.twist.linear.z = odom.twist.twist.linear.z;
    msg.twist.twist.angular.x = odom.twist.twist.angular.x;
    msg.twist.twist.angular.y = odom.twist.twist.angular.y;
    msg.twist.twist.angular.z = odom.twist.twist.angular.z;
    std::memset(msg.twist.covariance, 0, sizeof(msg.twist.covariance));

    g_lcm->publish(g_odometry_topic, &msg);
}

// LCM input handlers feed Point-LIO directly. They run on the main thread (via
// lcm.handleTimeout below), so there's no race with process().
struct InputHandler {
    void on_imu(const lcm::ReceiveBuffer*, const std::string&, const sensor_msgs::Imu* msg) {
        if (!g_running.load() || g_point_lio == nullptr) { return; }
        auto imu = boost::make_shared<custom_messages::Imu>();
        imu->header.stamp = custom_messages::Time().fromSec(stamp_to_sec(msg->header.stamp));
        imu->header.seq = 0;
        imu->header.frame_id = "imu_link";
        imu->orientation.x = 0.0;
        imu->orientation.y = 0.0;
        imu->orientation.z = 0.0;
        imu->orientation.w = 1.0;
        imu->angular_velocity.x = msg->angular_velocity.x;
        imu->angular_velocity.y = msg->angular_velocity.y;
        imu->angular_velocity.z = msg->angular_velocity.z;
        // m/s^2 -> g (Point-LIO's acc_norm is 1.0; the Mid360 publishes m/s^2).
        imu->linear_acceleration.x = msg->linear_acceleration.x / GRAVITY_MS2;
        imu->linear_acceleration.y = msg->linear_acceleration.y / GRAVITY_MS2;
        imu->linear_acceleration.z = msg->linear_acceleration.z / GRAVITY_MS2;
        for (int i = 0; i < 9; ++i) {
            imu->orientation_covariance[i] = 0.0;
            imu->angular_velocity_covariance[i] = 0.0;
            imu->linear_acceleration_covariance[i] = 0.0;
        }
        g_point_lio->feed_imu(imu);
    }

    void on_lidar(const lcm::ReceiveBuffer*, const std::string&, const sensor_msgs::PointCloud2* msg) {
        if (!g_running.load() || g_point_lio == nullptr) { return; }
        const uint32_t num_points = msg->width * msg->height;
        if (num_points == 0) { return; }

        // Locate fields by name. Point-LIO is timestamp-sensitive, so the
        // per-point time field `t` (uint32 ns offset from the header stamp,
        // published by the Mid360 module) is required — without it there's no
        // motion compensation, so refuse the cloud rather than guess.
        int off_x = -1, off_y = -1, off_z = -1, off_intensity = -1, off_t = -1;
        for (size_t k = 0; k < msg->fields.size(); ++k) {
            const auto& field = msg->fields[k];
            if (field.name == "x" && field.datatype == sensor_msgs::PointField::FLOAT32) { off_x = field.offset; }
            else if (field.name == "y" && field.datatype == sensor_msgs::PointField::FLOAT32) { off_y = field.offset; }
            else if (field.name == "z" && field.datatype == sensor_msgs::PointField::FLOAT32) { off_z = field.offset; }
            else if (field.name == "intensity" && field.datatype == sensor_msgs::PointField::FLOAT32) { off_intensity = field.offset; }
            else if (field.name == "t" && field.datatype == sensor_msgs::PointField::UINT32) { off_t = field.offset; }
        }
        if (off_x < 0 || off_y < 0 || off_z < 0 || off_t < 0) {
            if (!g_warned_lidar_fields) {
                fprintf(stderr,
                        "[pointlio] ERROR: PointCloud2 missing required float32 x/y/z and uint32 `t` "
                        "(per-point time) fields; dropping clouds. Publish from the Mid360 module.\n");
                g_warned_lidar_fields = true;
            }
            return;
        }

        const double ts = stamp_to_sec(msg->header.stamp);
        auto lidar = boost::make_shared<custom_messages::CustomMsg>();
        lidar->header.stamp = custom_messages::Time().fromSec(ts);
        lidar->header.seq = 0;
        lidar->header.frame_id = "livox_frame";
        lidar->timebase = static_cast<uint64_t>(ts * 1e9);
        lidar->lidar_id = 0;
        for (int idx = 0; idx < 3; ++idx) { lidar->rsvd[idx] = 0; }
        lidar->point_num = num_points;
        lidar->points.resize(num_points);

        const uint8_t* base = msg->data.data();
        for (uint32_t i = 0; i < num_points; ++i) {
            const uint8_t* row = base + i * msg->point_step;
            auto& cp = lidar->points[i];
            cp.x = static_cast<double>(*reinterpret_cast<const float*>(row + off_x));
            cp.y = static_cast<double>(*reinterpret_cast<const float*>(row + off_y));
            cp.z = static_cast<double>(*reinterpret_cast<const float*>(row + off_z));
            cp.reflectivity = off_intensity < 0
                ? 0
                : static_cast<unsigned short>(*reinterpret_cast<const float*>(row + off_intensity));
            cp.tag = 0;
            cp.line = 0;
            uint32_t offset_ns = 0;
            std::memcpy(&offset_ns, row + off_t, sizeof(uint32_t));
            cp.offset_time = static_cast<uli>(offset_ns);
        }
        g_point_lio->feed_lidar(lidar);
        if (pointlio_debug) {
            fprintf(stderr, "[pointlio] feed_lidar: %u points\n", num_points);
        }
    }
};

static void signal_handler(int /*sig*/) {
    g_running.store(false);
}

int main(int argc, char** argv) {
    dimos::NativeModule mod(argc, argv);

    if (!mod.has("imu") || !mod.has("lidar")) {
        fprintf(stderr, "Error: --imu and --lidar input topics are required\n");
        return 1;
    }
    const std::string imu_topic = mod.topic("imu");
    const std::string lidar_topic = mod.topic("lidar");
    g_odometry_topic = mod.has("odometry") ? mod.topic("odometry") : "";

    const std::string config_path = mod.arg("config_path", "");
    if (config_path.empty()) {
        fprintf(stderr, "Error: --config_path <path> is required\n");
        return 1;
    }

    const double msr_freq = mod.arg_float("msr_freq", 50.0f);
    const double main_freq = mod.arg_float("main_freq", 5000.0f);
    g_frame_id = mod.arg_required("frame_id");
    g_child_frame_id = mod.arg_required("body_frame_id");
    const double odom_freq = mod.arg_float("odom_freq", 50.0f);
    pointlio_debug = mod.arg_bool("debug", false);

    if (pointlio_debug) {
        printf("[pointlio] Starting topic-isolated Point-LIO\n");
        printf("[pointlio] imu topic: %s\n", imu_topic.c_str());
        printf("[pointlio] lidar topic: %s\n", lidar_topic.c_str());
        printf("[pointlio] odometry topic: %s\n",
               g_odometry_topic.empty() ? "(disabled)" : g_odometry_topic.c_str());
        printf("[pointlio] config: %s\n", config_path.c_str());
    }

    signal(SIGTERM, signal_handler);
    signal(SIGINT, signal_handler);

    lcm::LCM lcm;
    if (!lcm.good()) {
        fprintf(stderr, "Error: LCM init failed\n");
        return 1;
    }
    g_lcm = &lcm;

    if (pointlio_debug) { printf("[pointlio] Initializing Point-LIO...\n"); }
    PointLio point_lio(config_path, msr_freq, main_freq);
    g_point_lio = &point_lio;
    if (pointlio_debug) { printf("[pointlio] Point-LIO initialized.\n"); }

    InputHandler handler;
    lcm.subscribe(imu_topic, &InputHandler::on_imu, &handler);
    lcm.subscribe(lidar_topic, &InputHandler::on_lidar, &handler);

    const auto odom_interval = std::chrono::microseconds(static_cast<int64_t>(1e6 / odom_freq));
    auto last_odom_publish = std::chrono::steady_clock::now();
    const double process_period_ms = 1000.0 / main_freq;

    while (g_running.load()) {
        const auto loop_start = std::chrono::high_resolution_clock::now();

        // Dispatch any queued imu/lidar messages (feeds Point-LIO), then step.
        lcm.handleTimeout(0);
        point_lio.process();

        auto pose = point_lio.get_pose();
        if (!pose.empty() && (pose[0] != 0.0 || pose[1] != 0.0 || pose[2] != 0.0)) {
            const auto now = std::chrono::steady_clock::now();
            if (!g_odometry_topic.empty() && now - last_odom_publish >= odom_interval) {
                const custom_messages::Odometry& odom = point_lio.get_odometry();
                publish_odometry(odom, odom.header.stamp.toSec());
                last_odom_publish = now;
                if (pointlio_debug) {
                    fprintf(stderr, "[pointlio] publish odom: pose=(%.3f, %.3f, %.3f)\n",
                            pose[0], pose[1], pose[2]);
                }
            }
        }

        const auto loop_end = std::chrono::high_resolution_clock::now();
        const auto elapsed_ms =
            std::chrono::duration<double, std::milli>(loop_end - loop_start).count();
        if (elapsed_ms < process_period_ms) {
            std::this_thread::sleep_for(
                std::chrono::microseconds(static_cast<int64_t>((process_period_ms - elapsed_ms) * 1000)));
        }
    }

    if (pointlio_debug) { printf("[pointlio] Shutting down...\n"); }
    g_point_lio = nullptr;
    g_lcm = nullptr;
    if (pointlio_debug) { printf("[pointlio] Done.\n"); }
    return 0;
}
