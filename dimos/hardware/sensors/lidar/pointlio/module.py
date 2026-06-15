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

"""Python NativeModule wrapper for the topic-isolated Point-LIO binary.

Point-LIO runs the IESKF over Imu + PointCloud2 streams (e.g. from the Mid360
module) — no Livox SDK in this module, the sensor lives elsewhere. Publishes
odometry (with covariance + velocity) in the sensor frame.

The PointCloud2 must carry a per-point time field (`t`, uint32 ns offset from
the header stamp) for motion compensation; the Mid360 module publishes it.

Usage::

    from dimos.core.coordination.blueprints import autoconnect
    from dimos.hardware.sensors.lidar.livox.module import Mid360
    from dimos.hardware.sensors.lidar.pointlio.module import PointLio

    autoconnect(Mid360.blueprint(), PointLio.blueprint())  # imu/lidar auto-wire
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic.experimental.pipeline import validate_as
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.native_module import NativeModule, NativeModuleConfig
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.sensor_msgs.Imu import Imu
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.navigation.nav_stack.frames import FRAME_ODOM
from dimos.spec import perception

_CONFIG_DIR = Path(__file__).parent / "config"


class PointLioConfig(NativeModuleConfig):
    cwd: str | None = "cpp"
    executable: str = "result/bin/pointlio_native"
    build_command: str | None = "nix build .#pointlio_native"

    # Sensor frame for the odometry header.
    frame_id: str = "mid360_link"
    # Published TF: body_start_frame_id -> body_frame_id.
    body_start_frame_id: str = FRAME_ODOM
    body_frame_id: str = "base_link"

    # Point-LIO internal processing rates (Hz)
    msr_freq: float = 50.0
    main_freq: float = 5000.0
    odom_freq: float = 30.0

    # Point-LIO YAML config (relative to config/ dir, or absolute path).
    config: Annotated[
        Path,
        validate_as(...).transform(lambda path: path if path.is_absolute() else _CONFIG_DIR / path),
    ] = Path("default.yaml")

    debug: bool = False

    # Resolved in __post_init__, passed as --config_path to the binary.
    config_path: str | None = None

    cli_exclude: frozenset[str] = frozenset({"config", "body_start_frame_id"})

    def model_post_init(self, __context: object) -> None:
        """Resolve the Point-LIO YAML config to an absolute config_path."""
        super().model_post_init(__context)
        cfg = self.config
        if not cfg.is_absolute():
            cfg = _CONFIG_DIR / cfg
        self.config_path = str(cfg.resolve())


class PointLio(NativeModule, perception.Odometry):
    config: PointLioConfig

    # Inputs from the sensor module (e.g. Mid360): raw scan + IMU.
    lidar: In[PointCloud2]
    imu: In[Imu]
    odometry: Out[Odometry]

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(
            Disposable(self.odometry.transport.subscribe(self._on_odom_for_tf, self.odometry))
        )

    def _on_odom_for_tf(self, msg: Odometry) -> None:
        self.tf.publish(
            Transform(
                frame_id=self.config.body_start_frame_id,
                child_frame_id=self.config.body_frame_id,
                translation=Vector3(
                    msg.pose.position.x,
                    msg.pose.position.y,
                    msg.pose.position.z,
                ),
                rotation=Quaternion(
                    msg.pose.orientation.x,
                    msg.pose.orientation.y,
                    msg.pose.orientation.z,
                    msg.pose.orientation.w,
                ),
                # Match the odometry ts exactly; no `or time.time()` fallback (a
                # real ts of 0.0 must not become wall time).
                ts=msg.ts,
            )
        )

    @rpc
    def stop(self) -> None:
        super().stop()


# Verify protocol port compliance (mypy will flag missing ports)
if TYPE_CHECKING:
    PointLio()
