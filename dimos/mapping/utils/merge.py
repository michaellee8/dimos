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

from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2


def merge_pc(pc1: PointCloud2, pc2: PointCloud2, transform: Transform) -> PointCloud2:
    assert transform.frame_id == pc1.frame_id and transform.child_frame_id == pc2.frame_id, (
        f"wrong transform {pc1.frame_id!r} <- {pc2.frame_id!r}, "
        f"required: {transform.frame_id!r} <- {transform.child_frame_id!r}"
    )
    return pc1 + pc2.transform(transform)
