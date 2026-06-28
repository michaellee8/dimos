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

"""Go2 WebRTC connection — Go2's own movement/mode commands and sensor decoding.

Subclasses the generic UnitreeWebRTCConnection (which handles connection only) and
owns everything Go2-specific: how it moves (SPORT Move velocity / joystick / rage),
its postures and modes, and how it decodes the Go2 sensor streams. The G1 equivalent
lives in dimos/robot/unitree/g1/g1_webrtc.py.
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
import functools
import json
import threading
import time
from typing import TypeAlias, TypeVar

import numpy as np
from numpy.typing import NDArray
from reactivex import operators as ops
from reactivex.observable import Observable
from reactivex.subject import Subject
from unitree_webrtc_connect.constants import (
    DATA_CHANNEL_TYPE,
    RTC_TOPIC,
    SPORT_CMD,
    VUI_COLOR,
)

from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.robot.unitree.type.lidar import RawLidarMsg, pointcloud2_from_webrtc_lidar
from dimos.robot.unitree.type.lowstate import LowStateMsg
from dimos.robot.unitree.type.odometry import Odometry
from dimos.robot.unitree.unitree_webrtc import UnitreeWebRTCConnection
from dimos.types.timestamped import Timestamped
from dimos.utils.decorators.decorators import simple_mcache
from dimos.utils.logging_config import setup_logger
from dimos.utils.reactive import backpressure

logger = setup_logger()

VideoMessage: TypeAlias = NDArray[np.uint8]  # Shape: (height, width, 3)

_T = TypeVar("_T", bound=Timestamped)


def time_is_now(x: _T) -> _T:
    x.ts = time.time()
    return x


@dataclass
class SerializableVideoFrame:
    """Pickleable wrapper for av.VideoFrame with all metadata"""

    data: np.ndarray
    pts: int | None = None
    time: float | None = None
    dts: int | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None

    @classmethod
    def from_av_frame(cls, frame):  # type: ignore[no-untyped-def]
        return cls(
            data=frame.to_ndarray(format="rgb24"),
            pts=frame.pts,
            time=frame.time,
            dts=frame.dts,
            width=frame.width,
            height=frame.height,
            format=frame.format.name if hasattr(frame, "format") and frame.format else None,
        )

    def to_ndarray(self, format=None):  # type: ignore[no-untyped-def]
        return self.data


class TwistMode(str, Enum):
    """How a Go2 Twist is sent over WebRTC.

    VELOCITY — SPORT ``Move`` (api 1008): true m/s & rad/s. Correct, calibrated.
    JOYSTICK — legacy wireless-controller axes ([-1, 1], uncalibrated yaw). Kept for
               backwards compatibility, and required by Rage Mode (its FSM is
               joystick-driven and ignores SPORT ``Move``).
    """

    VELOCITY = "velocity"
    JOYSTICK = "joystick"


class Go2WebRTCConnection(UnitreeWebRTCConnection):
    """Go2 WebRTC connection: Go2's own move/postures/modes + sensor streams.

    Sends twists as calibrated SPORT ``Move`` velocities (true m/s & rad/s), falling
    back to the joystick primitive for JOYSTICK mode or while Rage Mode is active
    (whose FSM is joystick-driven and ignores SPORT ``Move``).
    """

    _SPORT_API_ID_RAGEMODE: int = 2059

    def __init__(
        self,
        ip: str,
        mode: str = "ai",
        aes_128_key: str | None = None,
        twist_mode: TwistMode = TwistMode.VELOCITY,
    ) -> None:
        self.twist_mode = TwistMode(twist_mode)
        self._move_seq = 0  # monotonic request id for SPORT Move commands
        self._rage_active = False
        self.stop_timer: threading.Timer | None = None
        self.cmd_vel_timeout = 0.2
        super().__init__(ip, mode=mode, aes_128_key=aes_128_key)

    # --- movement ---------------------------------------------------------------

    def _publish_velocity(self, vx: float, vy: float, vyaw: float) -> None:
        """Publish one SPORT ``Move`` (api 1008) velocity command: true m/s & rad/s.

        Body frame: vx forward, vy left, vyaw CCW. Must be called on the event-loop
        thread (publish_without_callback talks to the datachannel directly).
        """
        self._move_seq += 1
        self.conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["SPORT_MOD"],  # "rt/api/sport/request"
            data={
                "header": {"identity": {"id": self._move_seq, "api_id": SPORT_CMD["Move"]}},
                # parameter is a JSON STRING (firmware contract); publish_without_callback
                # sends ``data`` verbatim and does not stringify it.
                "parameter": json.dumps({"x": vx, "y": vy, "z": vyaw}),
            },
            msg_type=DATA_CHANNEL_TYPE["REQUEST"],  # "req"
        )

    def _publish_joystick(self, x: float, y: float, yaw: float) -> None:
        """Wireless-controller joystick send. ``yaw`` is a normalized joystick axis,
        NOT rad/s. Axis mapping: lx = -vy, ly = vx, rx = -vyaw."""
        self.conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["WIRELESS_CONTROLLER"],
            data={"lx": -y, "ly": x, "rx": -yaw, "ry": 0},
        )

    @property
    def _effective_twist_mode(self) -> TwistMode:
        """The mode actually used on the wire. Rage Mode's FSM only accepts joystick
        axes (it ignores SPORT Move), so it overrides twist_mode."""
        if self._rage_active:
            return TwistMode.JOYSTICK
        return self.twist_mode

    def _send_twist(self, x: float, y: float, yaw: float) -> None:
        """Dispatch a twist per ``_effective_twist_mode`` (velocity vs joystick)."""
        if self._effective_twist_mode is TwistMode.VELOCITY:
            self._publish_velocity(x, y, yaw)
        else:
            self._publish_joystick(x, y, yaw)

    def move(self, twist: Twist, duration: float = 0.0) -> bool:
        """Send a movement command.

        Args:
            twist: linear & angular velocities (m/s & rad/s)
            duration: how long to move (seconds). If 0, a single continuous command.

        Returns True if the command was sent.
        """
        x, y, yaw = twist.linear.x, twist.linear.y, twist.angular.z

        async def async_move() -> None:
            self._send_twist(x, y, yaw)

        async def async_move_duration() -> None:
            start_time = time.time()
            sleep_time = 0.01
            while time.time() - start_time < duration:
                await async_move()
                await asyncio.sleep(sleep_time)

        if self.stop_timer:
            self.stop_timer.cancel()

        # Auto-stop if no new command arrives within cmd_vel_timeout.
        self.stop_timer = threading.Timer(self.cmd_vel_timeout, self.stop_movement)
        self.stop_timer.daemon = True
        self.stop_timer.start()

        try:
            if duration > 0:
                future = asyncio.run_coroutine_threadsafe(async_move_duration(), self.loop)
                future.result()
                self.stop_movement()
            else:
                future = asyncio.run_coroutine_threadsafe(async_move(), self.loop)
                future.result()
            return True
        except Exception as e:
            logger.warning("Failed to send movement command: %s", e)
            return False

    def stop_movement(self) -> None:
        """Cancel the auto-stop timer (used by move() for continuous commands)."""
        if self.stop_timer:
            self.stop_timer.cancel()
            self.stop_timer = None

    # --- postures / modes -------------------------------------------------------

    def standup(self) -> bool:
        return bool(self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandUp"]}))

    def liedown(self) -> bool:
        return bool(
            self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandDown"]})
        )

    def balance_stand(self) -> bool:
        """Activate BalanceStand mode — enables WIRELESS_CONTROLLER joystick commands."""
        return bool(
            self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["BalanceStand"]})
        )

    def free_walk(self) -> bool:
        """Activate FreeWalk locomotion mode — enables walking and velocity commands."""
        return bool(self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["FreeWalk"]}))

    def set_obstacle_avoidance(self, enabled: bool = True) -> None:
        self.publish_request(
            RTC_TOPIC["OBSTACLES_AVOID"],
            {"api_id": 1001, "parameter": {"enable": int(enabled)}},
        )

    def set_motion_mode(self, name: str) -> None:
        """Select the top-level motion controller via the motion switcher.

        mcf is the AI/sport controller that traverses stairs. normal is basic.
        """
        # api_id 1001 = CheckMode, 1002 = SelectMode, param {"name": <mode>}.
        current = None
        try:
            resp = self.publish_request(RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001})
            current = json.loads(resp["data"]["data"]).get("name")
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Motion mode check failed: %s", e)
        if current == name:
            return
        self.publish_request(
            RTC_TOPIC["MOTION_SWITCHER"],
            {"api_id": 1002, "parameter": {"name": name}},
        )
        time.sleep(5)

    def set_rage_mode(self, enable: bool) -> bool:
        """Toggle Rage Mode (api 2059) over WebRTC, both directions.

        BalanceStand → 2059 {data:enable} → SwitchJoystick(enable). When on, the
        robot runs a joystick-driven FSM that ignores SPORT Move, so move() falls
        back to the joystick path (see _effective_twist_mode) at the rage envelope.
        """
        # Re-establish BalanceStand before toggling (notes: always BalanceStand
        # before flipping Rage).
        if not self.balance_stand():
            logger.warning("balance_stand() failed before rage toggle — proceeding")
        time.sleep(0.3)

        rage_ok = bool(
            self.publish_request(
                RTC_TOPIC["SPORT_MOD"],
                {"api_id": self._SPORT_API_ID_RAGEMODE, "parameter": {"data": enable}},
            )
        )
        if not rage_ok:
            return False

        # FsmRageMode is (de)active now; route move() to the joystick path accordingly.
        self._rage_active = enable

        if enable:
            time.sleep(2.0)  # let FsmRageMode transition settle
        joystick_ok = bool(
            self.publish_request(
                RTC_TOPIC["SPORT_MOD"],
                {"api_id": SPORT_CMD["SwitchJoystick"], "parameter": {"data": enable}},
            )
        )
        if not joystick_ok:
            logger.warning("SwitchJoystick failed after rage toggle", enabled=enable)
        return joystick_ok

    async def handstand(self):  # type: ignore[no-untyped-def]
        return self.publish_request(
            RTC_TOPIC["SPORT_MOD"],
            {"api_id": SPORT_CMD["Standup"], "parameter": {"data": True}},
        )

    def color(self, color: VUI_COLOR = VUI_COLOR.RED, colortime: int = 60) -> bool:
        return self.publish_request(  # type: ignore[no-any-return]
            RTC_TOPIC["VUI"],
            {"api_id": 1001, "parameter": {"color": color, "time": colortime}},
        )

    # --- sensor streams (Go2 decoding) ------------------------------------------

    @simple_mcache
    def raw_lidar_stream(self) -> Observable[RawLidarMsg]:
        return backpressure(self.subscribe(RTC_TOPIC["ULIDAR_ARRAY"]))

    @simple_mcache
    def raw_odom_stream(self) -> Observable[Pose]:
        return backpressure(self.subscribe(RTC_TOPIC["ROBOTODOM"]))

    @simple_mcache
    def lidar_stream(self) -> Observable[PointCloud2]:
        return backpressure(
            self.raw_lidar_stream().pipe(
                ops.map(pointcloud2_from_webrtc_lidar),
                ops.map(time_is_now),
            )
        )

    @simple_mcache
    def tf_stream(self) -> Observable[Transform]:
        base_link = functools.partial(Transform.from_pose, "base_link")
        return backpressure(self.odom_stream().pipe(ops.map(base_link)))

    @simple_mcache
    def odom_stream(self) -> Observable[Pose]:
        return backpressure(
            self.raw_odom_stream().pipe(
                ops.map(Odometry.from_msg),
                ops.map(time_is_now),
            )
        )

    @simple_mcache
    def video_stream(self) -> Observable[Image]:
        return backpressure(
            self.raw_video_stream().pipe(
                ops.filter(lambda frame: frame is not None),
                ops.map(
                    lambda frame: Image.from_numpy(
                        frame.to_ndarray(format="rgb24"),  # type: ignore[attr-defined]
                        format=ImageFormat.RGB,  # Frame is RGB24, not BGR
                        frame_id="camera_optical",
                    ),
                ),
                ops.map(time_is_now),
            )
        )

    @simple_mcache
    def lowstate_stream(self) -> Observable[LowStateMsg]:
        return backpressure(self.subscribe(RTC_TOPIC["LOW_STATE"]))

    @simple_mcache
    def raw_video_stream(self) -> Observable[VideoMessage]:
        subject: Subject[VideoMessage] = Subject()
        stop_event = threading.Event()

        from aiortc import MediaStreamTrack

        async def accept_track(track: MediaStreamTrack) -> None:
            while True:
                if stop_event.is_set():
                    return
                frame = await track.recv()
                serializable_frame = SerializableVideoFrame.from_av_frame(frame)  # type: ignore[no-untyped-call]
                subject.on_next(serializable_frame)

        self.conn.video.add_track_callback(accept_track)

        def switch_video_channel() -> None:
            self.conn.video.switchVideoChannel(True)

        self.loop.call_soon_threadsafe(switch_video_channel)

        def stop() -> None:
            stop_event.set()
            self.conn.video.track_callbacks.remove(accept_track)

            def switch_video_channel_off() -> None:
                self.conn.video.switchVideoChannel(False)

            self.loop.call_soon_threadsafe(switch_video_channel_off)

        return subject.pipe(ops.finally_action(stop))

    def get_video_stream(self, fps: int = 30) -> Observable[Image]:
        """Get the video stream from the robot's camera.

        Args:
            fps: included for API compatibility; the real rate is camera-determined.
        """
        return self.video_stream()
