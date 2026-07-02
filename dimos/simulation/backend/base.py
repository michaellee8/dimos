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

"""The in-process physics-engine seam of the simulation standard.

``PhysicsEngine`` is the ONLY surface a new in-process engine (Isaac,
Genesis, MJX, ...) must implement: dynamics stepping, joint state and
actuation, reset/respawn, root pose, and a set of optional fast-paths
(raycast ground queries, native cameras) that default to "unsupported"
— when absent, the backend-agnostic sensor layer produces the streams
instead.

The layer above (the sim module) drives exactly one ``PhysicsEngine``
and presents it to dimos as topics; out-of-process authorities (the
Babylon viewer, DimSim, Unity bridges) skip this seam entirely and
implement ``dimos.simulation.spec.PhysicsAuthority`` directly.

Engine-native handles (e.g. MuJoCo's ``MjModel``/``MjData``) must NOT
appear on this surface — that leak is precisely what couples consumers
to one engine. MuJoCo-specific accessors live on ``MujocoEngine`` and
are documented as private to ``dimos/simulation/backend/mujoco/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    from numpy.typing import NDArray

    from dimos.msgs.sensor_msgs.JointState import JointState

# Step hook signature: called with the engine instance inside the sim thread.
StepHook = Callable[["PhysicsEngine"], None]

_RESET_WAIT_TIMEOUT_S = 5.0


@dataclass
class CameraFrame:
    """One rendered frame from an engine-native camera (optional fast-path)."""

    rgb: NDArray[np.uint8] | None
    depth: NDArray[np.float32] | None
    cam_pos: NDArray[np.float64]
    cam_mat: NDArray[np.float64]
    fovy: float
    timestamp: float


class PhysicsEngine(ABC):
    """Abstract base class for an in-process physics engine."""

    def __init__(self, config_path: Path | None = None, headless: bool = True) -> None:
        self._config_path = config_path
        self._headless = headless

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def headless(self) -> bool:
        return self._headless

    # ── lifecycle / clock ────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> bool:
        """Connect to simulation and start the engine."""

    @abstractmethod
    def disconnect(self) -> bool:
        """Disconnect from simulation and stop the engine."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether the engine is connected."""

    @property
    @abstractmethod
    def control_frequency(self) -> float:
        """Native step rate in Hz (the engine owns the clock in live mode)."""

    def set_step_hooks(  # noqa: B027 — optional capability, deliberate no-op default
        self,
        before: StepHook | None = None,
        after: StepHook | None = None,
    ) -> None:
        """Install pre/post step hooks (WBC bridges, scenario drivers).

        Optional: engines without an owned step loop may ignore hooks.
        """

    def run_blocking(self, on_started: Callable[[], None] | None = None) -> None:
        """Run the sim loop on the calling thread (interactive viewers)."""
        raise NotImplementedError(f"{type(self).__name__} does not support run_blocking")

    def request_stop(self) -> None:  # noqa: B027 — optional capability, deliberate no-op default
        """Ask a blocking run to exit. No-op when unsupported."""

    # ── embodiment topology ──────────────────────────────────────────────

    @property
    @abstractmethod
    def num_joints(self) -> int:
        """Number of joints for the loaded robot."""

    @property
    @abstractmethod
    def joint_names(self) -> list[str]:
        """Joint names for the loaded robot."""

    @property
    def has_root_freejoint(self) -> bool:
        """Whether the embodiment has a floating base (mobile) or is fixed."""
        return False

    def get_actuator_ctrl_range(self, actuator_idx: int) -> tuple[float, float] | None:
        """Get (min, max) ctrl range for an actuator. None if not available."""
        return None

    def get_joint_range(self, joint_idx: int) -> tuple[float, float] | None:
        """Get (min, max) position range for a joint. None if not available."""
        return None

    # ── state read ───────────────────────────────────────────────────────

    @abstractmethod
    def read_joint_positions(self) -> list[float]:
        """Read joint positions in radians."""

    @abstractmethod
    def read_joint_velocities(self) -> list[float]:
        """Read joint velocities in rad/s."""

    @abstractmethod
    def read_joint_efforts(self) -> list[float]:
        """Read joint efforts in Nm."""

    @abstractmethod
    def get_root_pose(self) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        """Floating-base world pose as (position xyz, quaternion xyzw), or None."""

    def get_body_world_poses(
        self, body_ids: list[int]
    ) -> list[tuple[NDArray[np.float64], NDArray[np.float64]]]:
        """World (position, quaternion_wxyz) per body id, from latest stepped data."""
        return []

    def body_id(self, name: str) -> int | None:
        """Resolve a body name to the engine's body id, or None if absent."""
        return None

    # ── actuation ────────────────────────────────────────────────────────

    @abstractmethod
    def write_joint_command(self, command: JointState) -> None:
        """Command joints using a JointState message (position/velocity/effort)."""

    @abstractmethod
    def hold_current_position(self) -> None:
        """Hold current joint positions."""

    @abstractmethod
    def set_position_target(self, joint_idx: int, value: float) -> None:
        """Set position target for a single joint/actuator by index."""

    @abstractmethod
    def get_position_target(self, joint_idx: int) -> float:
        """Get current position target for a single joint/actuator by index."""

    def apply_root_twist(
        self,
        linear_x: float,
        linear_y: float,
        angular_z: float,
        *,
        fixed_z: float | None = None,
    ) -> bool:
        """Integrate a planar base twist onto a floating root (mobile bases).

        Returns False when the embodiment has no controllable floating base.
        """
        return False

    # ── world authoring ──────────────────────────────────────────────────

    @abstractmethod
    def reset(self) -> None:
        """Reset the world to its configured spawn state (synchronous)."""

    @abstractmethod
    def request_reset(
        self,
        *,
        wait: bool = False,
        timeout: float = _RESET_WAIT_TIMEOUT_S,
    ) -> bool:
        """Queue a reset on the sim thread; optionally wait for completion."""

    @abstractmethod
    def request_reset_to(
        self,
        *,
        spawn_xy: tuple[float, float],
        spawn_z: float | None = None,
        spawn_yaw: float | None = None,
        wait: bool = False,
        timeout: float = _RESET_WAIT_TIMEOUT_S,
    ) -> bool:
        """Queue a reset with a respawn pose; optionally wait for completion."""

    # ── optional fast-paths (backend-agnostic sensors cover the absence) ─

    def ground_height_at(
        self,
        x: float,
        y: float,
        *,
        ray_start_z: float = 10.0,
    ) -> float | None:
        """Raycast the static scene for ground height. None when unsupported."""
        return None

    def read_camera(self, camera_name: str) -> CameraFrame | None:
        """Latest engine-native rendered frame. None when unsupported."""
        return None

    def get_camera_fovy(self, camera_name: str) -> float | None:
        return None

    def get_camera_pose(
        self, camera_name: str
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        return None
