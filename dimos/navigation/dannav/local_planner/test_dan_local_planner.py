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

"""Tests for ``DanLocalPlanner`` module wiring and ``_ReplanGate`` behavior."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import math
from typing import Any

from dimos.core.stream import Stream, Transport
from dimos.msgs.geometry_msgs.PointStamped import PointStamped
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.nav_msgs.Odometry import Odometry
from dimos.msgs.nav_msgs.Path import Path
from dimos.navigation.dannav.local_planner.module import (
    DanLocalPlanner,
    DanLocalPlannerConfig,
    _ReplanGate,
)


class _DirectTransport(Transport):  # type: ignore[type-arg]
    """Synchronous in-process transport so ``start()`` can wire the inputs.

    Delivers each broadcast straight to the subscribed handlers on the calling
    thread, which keeps the wiring assertions deterministic.
    """

    def __init__(self) -> None:
        self._subscribers: list[Callable[[Any], Any]] = []

    def broadcast(self, _selfstream: Any, value: Any) -> None:
        for callback in list(self._subscribers):
            callback(value)

    def subscribe(
        self, callback: Callable[[Any], Any], _selfstream: Stream[Any] | None = None
    ) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    def start(self) -> None: ...

    def stop(self) -> None:
        self._subscribers.clear()


def _path_from_points(points: list[tuple[float, float]]) -> Path:
    poses = [
        PoseStamped(ts=1.0, frame_id="world", position=[x, y, 0.0], orientation=[0.0, 0.0, 0.0, 1.0])
        for x, y in points
    ]
    return Path(frame_id="world", poses=poses)


def _odometry(x: float, y: float, *, ts: float = 1.0) -> Odometry:
    return Odometry(
        ts=ts,
        frame_id="world",
        pose=PoseStamped(position=[x, y, 0.0], orientation=[0.0, 0.0, 0.0, 1.0]),
    )


def _point(x: float, y: float) -> PointStamped:
    return PointStamped(x=x, y=y, z=0.0, frame_id="world")


class _ModuleHarness:
    def __init__(self, module: DanLocalPlanner, forwarded: list[Path]) -> None:
        self.module = module
        self.forwarded = forwarded

    @property
    def gate(self) -> _ReplanGate:
        return self.module._gate

    def feed_odom(self, x: float, y: float, *, ts: float = 1.0) -> None:
        self.module.odometry.transport.broadcast(None, _odometry(x, y, ts=ts))

    def feed_goal(self, x: float, y: float) -> None:
        self.module.goal.transport.broadcast(None, _point(x, y))

    def feed_planner_path(self, path: Path) -> None:
        self.module.planner_path.transport.broadcast(None, path)

    def close(self) -> None:
        self.module.stop()


@contextmanager
def _running_module(**config: Any) -> Iterator[_ModuleHarness]:
    module = DanLocalPlanner(**config)
    module.planner_path.transport = _DirectTransport()
    module.odometry.transport = _DirectTransport()
    module.goal.transport = _DirectTransport()
    forwarded: list[Path] = []
    module.path.subscribe(forwarded.append)
    module.start()
    harness = _ModuleHarness(module, forwarded)
    try:
        yield harness
    finally:
        harness.close()


# ---- gate core (transport-free) ----------------------------------------------


def test_gate_forwards_non_empty_path() -> None:
    gate = _ReplanGate(DanLocalPlannerConfig())
    path = _path_from_points([(0.0, 0.0), (1.0, 0.0)])
    assert gate.on_planner_path(path) is path


def test_gate_forwards_empty_path_as_stop() -> None:
    gate = _ReplanGate(DanLocalPlannerConfig())
    empty = Path(frame_id="world", poses=[])
    assert gate.on_planner_path(empty) is empty


def test_gate_on_odom_records_robot_xy() -> None:
    gate = _ReplanGate(DanLocalPlannerConfig())
    assert gate._robot_xy is None
    gate.on_odom(_odometry(1.5, -2.0))
    assert gate._robot_xy is not None
    assert list(gate._robot_xy) == [1.5, -2.0]


def test_gate_on_goal_finite_arms_and_nan_disarms() -> None:
    gate = _ReplanGate(DanLocalPlannerConfig())
    gate.on_goal(_point(3.0, 4.0))
    assert gate._armed_goal is not None
    assert list(gate._armed_goal) == [3.0, 4.0]

    # A NaN PointStamped is MovementManager's cancel: it disarms the gate.
    gate.on_goal(_point(math.nan, math.nan))
    assert gate._armed_goal is None


# ---- module wiring -----------------------------------------------------------


def test_planner_path_is_forwarded_to_path_output() -> None:
    with _running_module() as h:
        path = _path_from_points([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
        h.feed_planner_path(path)

        assert h.forwarded == [path]


def test_empty_planner_path_is_forwarded() -> None:
    with _running_module() as h:
        empty = Path(frame_id="world", poses=[])
        h.feed_planner_path(empty)

        assert h.forwarded == [empty]


def test_passthrough_forwards_every_path() -> None:
    # Default config (lock_replan=0) is a pass-through: each planner path
    # produces exactly one forwarded path.
    with _running_module() as h:
        paths = [
            _path_from_points([(0.0, 0.0), (1.0, 0.0)]),
            _path_from_points([(0.0, 0.0), (0.0, 1.0)]),
            _path_from_points([(0.0, 0.0), (1.0, 1.0)]),
        ]
        for path in paths:
            h.feed_planner_path(path)

        assert h.forwarded == paths


def test_odom_and_goal_do_not_publish_a_path() -> None:
    with _running_module() as h:
        h.feed_odom(0.0, 0.0)
        h.feed_goal(2.0, 0.0)

        # Only planner paths flow to the path output; odom/goal update gate state.
        assert h.forwarded == []
        assert h.gate._robot_xy is not None
        assert h.gate._armed_goal is not None


# ---- commit window (gate core) -------------------------------------------------


def _gate(**config: Any) -> _ReplanGate:
    return _ReplanGate(DanLocalPlannerConfig(**config))


def test_replan_within_lock_is_suppressed() -> None:
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    first = _path_from_points([(0.0, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(first) is first  # cold-start commit

    # MLS re-roots and re-emits, but the robot has only advanced 0.2 m (< L), so
    # the replan is held and DanHolonomicTC keeps following the committed path.
    gate.on_odom(_odometry(0.2, 0.0))
    replan = _path_from_points([(0.2, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(replan) is None


def test_replan_after_advancing_lock_is_published() -> None:
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    gate.on_planner_path(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))

    # A replan within the window is held...
    gate.on_odom(_odometry(0.3, 0.0))
    assert gate.on_planner_path(_path_from_points([(0.3, 0.0), (5.0, 0.0)])) is None

    # ...then once the robot has advanced >= L the next replan commits and
    # re-anchors, so a subsequent replan is held again until the new window.
    gate.on_odom(_odometry(0.6, 0.0))
    committed = _path_from_points([(0.6, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(committed) is committed
    gate.on_odom(_odometry(0.7, 0.0))
    assert gate.on_planner_path(_path_from_points([(0.7, 0.0), (5.0, 0.0)])) is None


def test_fresh_click_commits_within_lock() -> None:
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    gate.on_planner_path(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))

    # The robot has only crept forward (< L), so the window has not released...
    gate.on_odom(_odometry(0.1, 0.0))
    # ...but a fresh click whose path actually reaches the goal commits anyway
    # ("the dog agrees when clicked"), and the arm is consumed.
    gate.on_goal(_point(5.0, 0.0))
    clicked = _path_from_points([(0.1, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(clicked) is clicked
    assert gate._armed_goal is None


def test_fresh_click_does_not_commit_a_stale_replan() -> None:
    # The click arms a commit, but a path that does NOT end at the clicked goal
    # (a stale in-flight replan for the previous goal) is still held within L,
    # and the arm stays set until a path that reaches the goal arrives.
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    gate.on_planner_path(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))
    gate.on_odom(_odometry(0.1, 0.0))
    gate.on_goal(_point(9.0, 0.0))
    stale = _path_from_points([(0.1, 0.0), (5.0, 0.0)])  # ends at the OLD goal
    assert gate.on_planner_path(stale) is None
    assert gate._armed_goal is not None


def test_empty_path_published_and_resets_gate() -> None:
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    gate.on_planner_path(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))

    # An empty path (nothing safe ahead) forwards immediately as a stop and
    # drops the committed path.
    empty = Path(frame_id="world", poses=[])
    assert gate.on_planner_path(empty) is empty
    assert gate._committed is None

    # The reset means the next path cold-starts a commit even though the robot
    # has not advanced a window's worth.
    gate.on_odom(_odometry(0.1, 0.0))
    restart = _path_from_points([(0.1, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(restart) is restart


def test_cancel_resets_committed_path() -> None:
    # A NaN goal is MovementManager's cancel: it disarms AND drops the committed
    # path, so the next planner path cold-starts a fresh commit within L.
    gate = _gate(lock_replan=0.5)
    gate.on_odom(_odometry(0.0, 0.0))
    gate.on_planner_path(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))
    gate.on_goal(_point(math.nan, math.nan))
    assert gate._committed is None

    gate.on_odom(_odometry(0.1, 0.0))
    restart = _path_from_points([(0.1, 0.0), (5.0, 0.0)])
    assert gate.on_planner_path(restart) is restart


def test_lock_replan_zero_commits_every_non_empty_path() -> None:
    # L = 0 disables gating: every non-empty path commits, even with no advance.
    gate = _gate(lock_replan=0.0)
    gate.on_odom(_odometry(0.0, 0.0))
    for path in (
        _path_from_points([(0.0, 0.0), (1.0, 0.0)]),
        _path_from_points([(0.0, 0.0), (0.0, 1.0)]),
        _path_from_points([(0.0, 0.0), (1.0, 1.0)]),
    ):
        assert gate.on_planner_path(path) is path


# ---- commit window (module wiring) ---------------------------------------------


def test_module_suppresses_replan_within_lock_then_publishes_after_advance() -> None:
    with _running_module(lock_replan=0.5) as h:
        h.feed_odom(0.0, 0.0)
        first = _path_from_points([(0.0, 0.0), (5.0, 0.0)])
        h.feed_planner_path(first)
        assert h.forwarded == [first]  # cold-start commit

        # Replans arriving while the robot is still within the window publish
        # nothing.
        h.feed_odom(0.2, 0.0)
        h.feed_planner_path(_path_from_points([(0.2, 0.0), (5.0, 0.0)]))
        h.feed_odom(0.4, 0.0)
        h.feed_planner_path(_path_from_points([(0.4, 0.0), (5.0, 0.0)]))
        assert h.forwarded == [first]

        # Once the robot has advanced >= L, the next replan is published.
        h.feed_odom(0.6, 0.0)
        committed = _path_from_points([(0.6, 0.0), (5.0, 0.0)])
        h.feed_planner_path(committed)
        assert h.forwarded == [first, committed]


def test_module_fresh_click_commits_within_lock() -> None:
    with _running_module(lock_replan=0.5) as h:
        h.feed_odom(0.0, 0.0)
        first = _path_from_points([(0.0, 0.0), (5.0, 0.0)])
        h.feed_planner_path(first)

        h.feed_odom(0.1, 0.0)
        h.feed_goal(5.0, 0.0)
        clicked = _path_from_points([(0.1, 0.0), (5.0, 0.0)])
        h.feed_planner_path(clicked)
        assert h.forwarded == [first, clicked]


def test_module_empty_path_publishes_and_resets() -> None:
    with _running_module(lock_replan=0.5) as h:
        h.feed_odom(0.0, 0.0)
        first = _path_from_points([(0.0, 0.0), (5.0, 0.0)])
        h.feed_planner_path(first)

        empty = Path(frame_id="world", poses=[])
        h.feed_planner_path(empty)
        h.feed_odom(0.1, 0.0)
        restart = _path_from_points([(0.1, 0.0), (5.0, 0.0)])
        h.feed_planner_path(restart)
        assert h.forwarded == [first, empty, restart]


# ---- smoothing + uniform resampling --------------------------------------------


def _spacings(path: Path) -> list[float]:
    return [
        math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(path.poses, path.poses[1:], strict=False)
    ]


def test_smooth_resamples_straight_path_to_uniform_spacing() -> None:
    # A 2-point straight MLS path is densified to points ~resample_spacing_m
    # apart, with the endpoints left exactly where MLS put them.
    gate = _gate(resample_spacing_m=0.1)
    out = gate._smooth(_path_from_points([(0.0, 0.0), (5.0, 0.0)]))

    assert len(out.poses) > 2
    assert (out.poses[0].x, out.poses[0].y) == (0.0, 0.0)
    assert (out.poses[-1].x, out.poses[-1].y) == (5.0, 0.0)
    assert all(abs(d - 0.1) < 1e-6 for d in _spacings(out))


def test_smooth_rounds_a_corner() -> None:
    # A right-angle corner is rounded: no waypoint sits on the exact corner, and
    # cutting the corner makes the smoothed path shorter than the raw chords.
    gate = _gate(resample_spacing_m=0.1)
    out = gate._smooth(_path_from_points([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]))

    assert min(math.hypot(p.x - 1.0, p.y - 0.0) for p in out.poses) > 0.05
    assert sum(_spacings(out)) < 2.0  # 1.0 + 1.0 raw cornered length


def test_smooth_returns_empty_path_unchanged() -> None:
    gate = _gate(resample_spacing_m=0.1)
    empty = Path(frame_id="world", poses=[])
    assert gate._smooth(empty) is empty


def test_smooth_disabled_returns_path_unchanged() -> None:
    # resample_spacing_m == 0 forwards the raw path (same object), no reshaping.
    gate = _gate(resample_spacing_m=0.0)
    path = _path_from_points([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    assert gate._smooth(path) is path


def test_commit_forwards_and_tracks_the_smoothed_path() -> None:
    # The path the gate commits and tracks is the smoothed one, not the raw
    # planner chords.
    gate = _gate(resample_spacing_m=0.1)
    gate.on_odom(_odometry(0.0, 0.0))
    raw = _path_from_points([(0.0, 0.0), (5.0, 0.0)])
    forwarded = gate.on_planner_path(raw)

    assert forwarded is not raw
    assert len(forwarded.poses) > 2
    assert all(abs(d - 0.1) < 1e-6 for d in _spacings(forwarded))
