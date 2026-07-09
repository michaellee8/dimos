// Copyright 2026 Dimensional Inc.
// SPDX-License-Identifier: Apache-2.0
//
// Pong: echoes every Twist received on `data` back on `confirm`, stamping the
// echo's angular.z with the configured sample_config. C++ mirror of
// examples/native-modules/rust/src/pong.rs.

#include <cstdint>

#include "dimos/native.hpp"
#include "geometry_msgs/Twist.hpp"

using dimos::native::Builder;
using dimos::native::Config;
using dimos::native::lcm_decode;
using dimos::native::lcm_encode;
using dimos::native::Module;
using dimos::native::Output;
using geometry_msgs::Twist;

class Pong : public Module {
public:
    void build(Builder& builder, Config& config) override {
        sample_config_ = config.require_in_range<std::int64_t>("sample_config", 0, 1000);
        confirm_ = builder.output<Twist>("confirm", lcm_encode<Twist>);
        builder.input<Twist>("data", lcm_decode<Twist>, [this](Twist msg) { on_data(msg); });
    }

private:
    void on_data(const Twist& msg) {
        Twist reply;
        reply.linear = msg.linear;
        reply.angular.x = 0.0;
        reply.angular.y = 0.0;
        reply.angular.z = static_cast<double>(sample_config_);
        confirm_.publish(reply);
    }

    Output<Twist> confirm_;
    std::int64_t sample_config_ = 0;
};

int main() {
    dimos::native::run_with_transport<Pong>();
    return 0;
}
