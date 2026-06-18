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

"""FlowBase instantiation of the trajectory-tracking config.

The robot-agnostic machinery lives in :mod:`.config`; this module pins the
FlowBase: it builds ``FLOWBASE_TRACKING`` from the vendored 2026-06-09 fit
plus the firmware command limits, and re-exports the individual gains/limits
as module-level names for convenience and provenance. A re-characterization
only has to update the fit in plant.py.
"""

from __future__ import annotations

from dimos.control.tasks.feedforward_gain_compensator import FeedforwardGainConfig
from dimos.control.tasks.trajectory_tracking_task.config import (
    FB_CLAMP_LINEAR,
    FB_CLAMP_YAW,
    LAT_ACCEL_FRACTION,
    PLANNING_MARGIN,
    ZETA_AGGRESSIVE,
    ZETA_DEFAULT,
    PerAxis,
    TrackingConfig,
    kp_for_zeta,
)
from dimos.utils.benchmarking.plant import (
    FLOWBASE_CMD_MAX_ACC,
    FLOWBASE_CMD_MAX_VEL,
    FLOWBASE_PLANT_FITTED,
)

# Provenance — embed in run metadata of every certification/benchmark run.
CHARACTERIZATION_DATE = "2026-06-09"
CHARACTERIZATION_ARTIFACT = (
    "data/characterization/flowbase/flowbase_config_hw_concrete_2026-06-09_704a591f5.json"
)

FLOWBASE_TRACKING = TrackingConfig.from_plant_fit(
    FLOWBASE_PLANT_FITTED,
    FLOWBASE_CMD_MAX_VEL,
    FLOWBASE_CMD_MAX_ACC,
    provenance=f"flowbase concrete {CHARACTERIZATION_DATE}",
)

# --- per-name re-exports (provenance + back-compat) ----------------------
K_HAT = FLOWBASE_TRACKING.k_hat
DEADTIME = FLOWBASE_TRACKING.deadtime
KP_DEFAULT = FLOWBASE_TRACKING.kp_default  # ~ (0.87, 0.94, 0.41)
KP_AGGRESSIVE = FLOWBASE_TRACKING.kp_aggressive  # ~ (1.77, 1.91, 0.84)
PLAN_MAX_VEL = FLOWBASE_TRACKING.plan_max_vel
PLAN_MAX_ACC = FLOWBASE_TRACKING.plan_max_acc
A_LAT_MAX = FLOWBASE_TRACKING.a_lat_max

# Physical limits = K x firmware command limits (the planning margins above
# are 85% of these). Kept as named values for traceability.
PHYSICAL_MAX_VEL = PerAxis(
    x=K_HAT.x * FLOWBASE_CMD_MAX_VEL[0],
    y=K_HAT.y * FLOWBASE_CMD_MAX_VEL[1],
    yaw=K_HAT.yaw * FLOWBASE_CMD_MAX_VEL[2],
)
PHYSICAL_MAX_ACC = PerAxis(
    x=K_HAT.x * FLOWBASE_CMD_MAX_ACC[0],
    y=K_HAT.y * FLOWBASE_CMD_MAX_ACC[1],
    yaw=K_HAT.yaw * FLOWBASE_CMD_MAX_ACC[2],
)


def flowbase_feedforward_config() -> FeedforwardGainConfig:
    """Gain-inversion config for the FlowBase (u_cmd = u_phys / K_hat)."""
    return FLOWBASE_TRACKING.feedforward_config()


__all__ = [
    "A_LAT_MAX",
    "CHARACTERIZATION_ARTIFACT",
    "CHARACTERIZATION_DATE",
    "DEADTIME",
    "FB_CLAMP_LINEAR",
    "FB_CLAMP_YAW",
    "FLOWBASE_TRACKING",
    "KP_AGGRESSIVE",
    "KP_DEFAULT",
    "K_HAT",
    "LAT_ACCEL_FRACTION",
    "PHYSICAL_MAX_ACC",
    "PHYSICAL_MAX_VEL",
    "PLANNING_MARGIN",
    "PLAN_MAX_ACC",
    "PLAN_MAX_VEL",
    "ZETA_AGGRESSIVE",
    "ZETA_DEFAULT",
    "PerAxis",
    "TrackingConfig",
    "flowbase_feedforward_config",
    "kp_for_zeta",
]
