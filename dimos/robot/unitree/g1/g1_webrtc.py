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

"""G1 WebRTC connection — G1's own movement/posture commands.

Subclasses the generic UnitreeWebRTCConnection (connection only) and owns G1's
high-level commands. Twists go out as wireless-controller joystick axes (G1's
high-level FSM is joystick-driven). Postures are kept G1-local even where the SPORT
api ids currently match Go2's, since the FSMs may diverge.
"""

import asyncio
import threading
import time

from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD

from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.robot.unitree.unitree_webrtc import UnitreeWebRTCConnection
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class G1WebRTCConnection(UnitreeWebRTCConnection):
    """G1 high-level WebRTC connection — G1's own move + posture commands."""

    def __init__(self, ip: str, mode: str = "ai", aes_128_key: str | None = None) -> None:
        self.stop_timer: threading.Timer | None = None
        self.cmd_vel_timeout = 0.2
        super().__init__(ip, mode=mode, aes_128_key=aes_128_key)

    def _publish_joystick(self, x: float, y: float, yaw: float) -> None:
        """Wireless-controller joystick send. Axis mapping: lx = -vy, ly = vx, rx = -vyaw."""
        self.conn.datachannel.pub_sub.publish_without_callback(
            RTC_TOPIC["WIRELESS_CONTROLLER"],
            data={"lx": -y, "ly": x, "rx": -yaw, "ry": 0},
        )

    def move(self, twist: Twist, duration: float = 0.0) -> bool:
        """Send a movement command as wireless-controller joystick axes.

        Args:
            twist: linear & angular velocities
            duration: how long to move (seconds). If 0, a single continuous command.
        """
        x, y, yaw = twist.linear.x, twist.linear.y, twist.angular.z

        async def async_move() -> None:
            self._publish_joystick(x, y, yaw)

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

    def standup(self) -> bool:
        return bool(self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandUp"]}))

    def liedown(self) -> bool:
        return bool(
            self.publish_request(RTC_TOPIC["SPORT_MOD"], {"api_id": SPORT_CMD["StandDown"]})
        )
