# Copyright 2025-2026 Dimensional Inc.
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

"""Subprocess entry point for MujocoEngine (``engine_mode="subprocess"``).

Runs one engine in its own process: joint plane over SHM, odom/IMU over
LCM. ``MujocoSimModule`` launches it via ``python -m
dimos.simulation.backend.mujoco.engine_proc`` when process isolation is
requested; everything here is plumbing around the same MujocoEngine the
in-process mode uses.
"""

from __future__ import annotations

from pathlib import Path
import signal
import time

from dimos.core.transport import LCMTransport
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.sensor_msgs.Imu import Imu
from dimos.simulation.backend.mujoco.engine import MujocoEngine
from dimos.simulation.backend.mujoco.shm import ManipShmWriter
from dimos.simulation.backend.mujoco.wholebody_sim_hooks import WholeBodySimHooks
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


def engine_main(
    mjcf_path: str,
    shm_key: str,
    dof: int,
    *,
    headless: bool = True,
    inject_legacy_assets: bool = True,
    odom_topic: str = "/odom",
    imu_topic: str = "/imu",
    imu_gyro_sensor_names: tuple[str, ...] = (
        "imu-pelvis-angular-velocity",
        "imu-torso-angular-velocity",
        "gyro_pelvis",
        "imu_gyro",
    ),
    imu_accel_sensor_names: tuple[str, ...] = (
        "imu-pelvis-linear-acceleration",
        "imu-torso-linear-acceleration",
        "accelerometer_pelvis",
        "imu_accel",
    ),
) -> None:
    shm = ManipShmWriter(shm_key)

    assets: dict[str, bytes] | None = None
    if inject_legacy_assets:
        try:
            from dimos.simulation.backend.mujoco.assets import get_assets

            assets = get_assets()
        except Exception as exc:  # pragma: no cover - bare MJCFs do not need this
            logger.warning(f"engine_main: asset injection skipped: {exc}")

    engine = MujocoEngine(
        config_path=Path(mjcf_path),
        headless=headless,
        cameras=[],
        assets=assets,
    )

    imu_gyro_slice = engine.find_sensor_slice(*imu_gyro_sensor_names)
    imu_accel_slice = engine.find_sensor_slice(*imu_accel_sensor_names)
    has_freejoint = engine.has_root_freejoint
    hooks = WholeBodySimHooks(shm, dof=dof)

    odom_tx: LCMTransport[PoseStamped] = LCMTransport(odom_topic, PoseStamped)
    odom_tx.start()
    imu_tx: LCMTransport[Imu] = LCMTransport(imu_topic, Imu)
    imu_tx.start()

    def _on_after_step(step_engine: MujocoEngine) -> None:
        hooks.post_step(step_engine)

        data = step_engine.data
        ts = time.time()
        if has_freejoint:
            pos = data.qpos[0:3]
            quat = data.qpos[3:7]
            odom_tx.publish(
                PoseStamped(
                    ts=ts,
                    frame_id="world",
                    position=Vector3(float(pos[0]), float(pos[1]), float(pos[2])),
                    orientation=Quaternion(
                        float(quat[1]), float(quat[2]), float(quat[3]), float(quat[0])
                    ),
                )
            )

        if imu_gyro_slice is None and imu_accel_slice is None and not has_freejoint:
            return
        quat_tup = (
            (
                float(data.qpos[3]),
                float(data.qpos[4]),
                float(data.qpos[5]),
                float(data.qpos[6]),
            )
            if has_freejoint
            else (1.0, 0.0, 0.0, 0.0)
        )
        if imu_gyro_slice is not None:
            gyro_vals = data.sensordata[imu_gyro_slice]
            gyro_tup = (float(gyro_vals[0]), float(gyro_vals[1]), float(gyro_vals[2]))
        else:
            gyro_tup = (0.0, 0.0, 0.0)
        if imu_accel_slice is not None:
            accel_vals = data.sensordata[imu_accel_slice]
            accel_tup = (float(accel_vals[0]), float(accel_vals[1]), float(accel_vals[2]))
        else:
            accel_tup = (0.0, 0.0, 0.0)
        shm.write_imu(quaternion=quat_tup, gyroscope=gyro_tup, accelerometer=accel_tup)
        imu_tx.publish(
            Imu(
                ts=ts,
                frame_id="pelvis",
                orientation=Quaternion(quat_tup[1], quat_tup[2], quat_tup[3], quat_tup[0]),
                angular_velocity=Vector3(*gyro_tup),
                linear_acceleration=Vector3(*accel_tup),
            )
        )

    engine.set_step_hooks(before=hooks.pre_step, after=_on_after_step)

    def _handle_sig(signum: int, frame: object) -> None:
        logger.info(f"engine_main: signal {signum} received, stopping")
        engine.request_stop()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    def _mark_ready() -> None:
        shm.signal_ready(num_joints=engine.num_joints)
        logger.info(
            "engine_main: ready",
            mjcf=mjcf_path,
            shm_key=shm_key,
            dof=dof,
            headless=headless,
        )

    try:
        engine.run_blocking(on_started=_mark_ready)
    finally:
        engine.request_stop()
        try:
            shm.signal_stop()
            shm.cleanup()
        except Exception as exc:
            logger.warning(f"engine_main: shm cleanup raised: {exc}")
        odom_tx.stop()
        imu_tx.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Standalone MuJoCo whole-body sim subprocess.",
        prog="python -m dimos.simulation.backend.mujoco.engine_proc",
    )
    parser.add_argument("mjcf", help="Path to MJCF XML")
    parser.add_argument("shm_key", help="SHM key matching the dimos-side adapter")
    parser.add_argument("dof", type=int, help="Number of motor DOFs")
    parser.add_argument("--view", action="store_true", help="Launch passive viewer")
    parser.add_argument("--no-asset-inject", action="store_true", help="Skip asset injection")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--imu-topic", default="/imu")
    args = parser.parse_args()

    engine_main(
        mjcf_path=args.mjcf,
        shm_key=args.shm_key,
        dof=args.dof,
        headless=not args.view,
        inject_legacy_assets=not args.no_asset_inject,
        odom_topic=args.odom_topic,
        imu_topic=args.imu_topic,
    )
