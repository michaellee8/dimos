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

"""PointLio fed by a VirtualMid360 replaying a recorded pcap (live SDK path).

Configured via env vars; the two ends must agree on the addresses:
VIRTUAL_MID360_PCAP, VIRTUAL_MID360_LIDAR_IP, VIRTUAL_MID360_HOST_IP,
VIRTUAL_MID360_NETNS.
"""

import os

from dimos.core.coordination.blueprints import autoconnect
from dimos.hardware.sensors.lidar.livox.virtual_mid360.module import VirtualMid360
from dimos.hardware.sensors.lidar.pointlio.module import PointLio
from dimos.visualization.vis_module import vis_module

_PCAP = os.environ.get("VIRTUAL_MID360_PCAP", "")
_LIDAR_IP = os.environ.get("VIRTUAL_MID360_LIDAR_IP", "")
_HOST_IP = os.environ.get("VIRTUAL_MID360_HOST_IP", "")
_NETNS = os.environ.get("VIRTUAL_MID360_NETNS", "lidar")

demo_virtual_mid360_pointlio = autoconnect(
    VirtualMid360.blueprint(pcap=_PCAP, lidar_ip=_LIDAR_IP, host_ip=_HOST_IP, lidar_netns=_NETNS),
    PointLio.blueprint(host_ip=_HOST_IP, lidar_ip=_LIDAR_IP),
    vis_module("rerun"),
).global_config(n_workers=3, robot_model="virtual_mid360_pointlio")
