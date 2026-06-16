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

VirtualMid360 replays the pcap over the Livox wire protocol on a virtual NIC;
FastLio2 connects in live SDK mode, unaware the sensor is synthetic. They talk
over UDP on lidar_ip/host_ip, so the harness puts them in separate netns joined
by a veth — see fastlio2/tools/pcap_to_db.py.
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
