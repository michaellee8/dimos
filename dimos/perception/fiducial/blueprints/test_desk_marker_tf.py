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

from dimos.core.coordination.blueprints import Blueprint
from dimos.perception.fiducial.blueprints.desk_marker_tf import (
    DeskStaticTfModule,
    desk_marker_tf,
)


def test_desk_marker_tf_blueprint_declares_static_tf_module() -> None:
    assert isinstance(desk_marker_tf, Blueprint)
    assert desk_marker_tf.blueprints[0].module is DeskStaticTfModule


def test_desk_static_tf_module_publishes_world_to_camera_optical_chain() -> None:
    mod = DeskStaticTfModule(
        camera_translation_m=(0.3, 0.0, 0.2),
        camera_rotation_rpy_rad=(0.0, 0.0, 0.0),
    )
    try:
        mod.start()
        assert mod._last_publish_ts is not None

        world_camera = mod.tf.get("world", "camera_optical", mod._last_publish_ts, 1.0)
        assert world_camera is not None
        assert world_camera.frame_id == "world"
        assert world_camera.child_frame_id == "camera_optical"
        assert world_camera.translation.x == 0.3
        assert world_camera.translation.y == 0.0
        assert world_camera.translation.z == 0.2
    finally:
        mod.stop()
