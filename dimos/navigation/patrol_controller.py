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

"""PatrolController — back-and-forth patrol between two clicked points.

Behaviour
---------
- Click ONE point  -> stored as waypoint A.
- Click a SECOND point -> stored as waypoint B; patrol arms and the robot heads to A.
- Each time the planner reports `goal_reached`, the controller sends the *other*
  waypoint, so the robot ping-pongs A -> B -> A -> ... forever.
- The moment any teleop command (`tele_cmd_vel`) arrives, patrol HALTS. The
  MovementManager already cancels the active nav goal on teleop, so we just stop
  re-issuing goals. Patrol stays off until you re-arm by clicking two new points.

Wiring (see the patrol blueprint)
---------------------------------
This module is a filter inserted on the click line. It consumes the viewer's
raw `clicked_point` and re-emits the chosen goal on `patrol_goal`. In the
blueprint, the planner's and movement-manager's `clicked_point` *inputs* are
remapped to `patrol_goal`, so they receive the patrol's chosen goal instead of
the raw clicks:

    dimos-viewer.clicked_point  ----------->  PatrolController.clicked_point (raw clicks)
    PatrolController.patrol_goal --(remap)-->  ReplanningAStarPlanner.clicked_point
                                               MovementManager.clicked_point

Without the remap, raw clicks would reach the planner directly and it would
drive to each click instead of patrolling.
"""

from __future__ import annotations

import math
import time
from typing import Any

from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos_lcm.std_msgs import Bool  # type: ignore[import-untyped]

from dimos.msgs.geometry_msgs.PointStamped import PointStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class PatrolControllerConfig(ModuleConfig):
    # Minimum seconds between accepting consecutive `goal_reached` events. Guards
    # against the planner re-emitting "reached" before the robot has departed,
    # which would otherwise ping-pong the target without moving.
    min_leg_time: float = 2.0


class PatrolController(Module):
    clicked_point: In[PointStamped]      # raw clicks from the dimos-viewer
    goal_reached: In[Bool]               # from ReplanningAStarPlanner
    tele_cmd_vel: In[Twist]              # any teleop -> halt patrol

    patrol_goal: Out[PointStamped]       # remap planner + MM clicked_point inputs to this

    config: PatrolControllerConfig

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._a: PointStamped | None = None
        self._b: PointStamped | None = None
        self._going_to_b: bool = False  # which leg we're currently driving
        self._patrolling: bool = False
        self._last_goal_ts: float = 0.0

    @rpc
    def start(self) -> None:
        super().start()
        self.register_disposable(
            Disposable(self.clicked_point.subscribe(self._on_click))
        )
        self.register_disposable(
            Disposable(self.goal_reached.subscribe(self._on_reached))
        )
        self.register_disposable(
            Disposable(self.tele_cmd_vel.subscribe(self._on_teleop))
        )

    @rpc
    def stop(self) -> None:
        self._patrolling = False
        super().stop()

    # -- handlers -----------------------------------------------------------
    def _on_click(self, pt: PointStamped) -> None:
        # Ignore the NaN "cancel" clicks the MovementManager uses internally.
        if not all(math.isfinite(v) for v in (pt.x, pt.y, pt.z)):
            return

        if self._a is None or self._patrolling:
            # First click of a (new) pair -> waypoint A; also re-arms mid-patrol.
            self._a = pt
            self._b = None
            self._patrolling = False
            logger.info("Patrol: waypoint A set; click a second point for B")
            return

        # Second click -> waypoint B; arm patrol and head to A first.
        self._b = pt
        self._patrolling = True
        self._going_to_b = False
        self._publish_goal(self._a)
        logger.info("Patrol: armed A<->B, heading to A")

    def _on_reached(self, msg: Bool) -> None:
        if not msg.data or not self._patrolling:
            return
        if time.monotonic() - self._last_goal_ts < self.config.min_leg_time:
            return  # debounce stale/repeated "reached" before we've left
        self._going_to_b = not self._going_to_b
        nxt = self._b if self._going_to_b else self._a
        if nxt is not None:
            self._publish_goal(nxt)
            logger.info("Patrol: reached leg; heading to %s", "B" if self._going_to_b else "A")

    def _on_teleop(self, _msg: Twist) -> None:
        # Any teleop touch halts patrol. The MovementManager already cancels the
        # active goal, so we only need to stop re-issuing. Re-arm with two clicks.
        if self._patrolling:
            self._patrolling = False
            logger.info("Patrol: teleop detected -> halted (click two points to re-arm)")

    def _publish_goal(self, pt: PointStamped) -> None:
        self._last_goal_ts = time.monotonic()
        self.patrol_goal.publish(pt)
