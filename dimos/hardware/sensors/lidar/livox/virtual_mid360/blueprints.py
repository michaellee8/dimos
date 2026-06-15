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

"""Blueprint: FastLio2 fed by a VirtualMid360 replaying a recorded pcap.

VirtualMid360 stands up a fake Mid-360 on a virtual NIC and replays the pcap
over the Livox wire protocol; FastLio2 connects to it exactly as it would to
real hardware (no replay_pcap — it runs in live SDK mode and never knows the
sensor is synthetic). Use this to re-run a recorded session through the live
SLAM path, e.g. to reproduce (or rule out) the velocity-spike divergence.

The two talk over UDP on lidar_ip/host_ip, so they need a network where those
IPs are reachable: the e2e harness runs VirtualMid360 in a `lidar` netns and
FastLio2 in a `drv` netns joined by a veth carrying lidar_ip. See
tools/replay_via_virtual_mid360.sh for the full netns setup + a db recording.
"""

from dimos.core.coordination.blueprints import autoconnect
from dimos.hardware.sensors.lidar.fastlio2.module import FastLio2
from dimos.hardware.sensors.lidar.livox.virtual_mid360.module import VirtualMid360
from dimos.visualization.vis_module import vis_module

# Set pcap to a recorded Mid-360 capture before running, e.g.:
#   dimos run virtual-mid360-fastlio --VirtualMid360.pcap /path/to/capture.pcap
demo_virtual_mid360_fastlio = autoconnect(
    VirtualMid360.blueprint(
        pcap="", lidar_ip="192.168.1.155", host_ip="192.168.1.5", lidar_netns="fl_lidar"
    ),
    FastLio2.blueprint(),
    vis_module("rerun"),
).global_config(n_workers=3, robot_model="virtual_mid360_fastlio")
