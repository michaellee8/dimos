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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

JsonObject: TypeAlias = Mapping[str, object]
BackendPayload: TypeAlias = Mapping[str, object]


@dataclass(frozen=True)
class BackendBatch:
    """Backend-ready policy inference batch produced by a robot contract."""

    payload: BackendPayload
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class BackendOutputEnvelope:
    """Backend-native policy output and inference metadata."""

    output: object
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyBackendDescription:
    """Serializable metadata describing a loaded policy backend."""

    backend_type: str
    checkpoint_id: str | None = None
    resolved_checkpoint_metadata: JsonObject = field(default_factory=dict)
    device: str | None = None
    policy_class: str | None = None
    supports_episode_reset: bool = True
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RobotPolicyContractDescription:
    """Serializable metadata describing a robot policy IO contract."""

    contract_type: str
    input_description: JsonObject = field(default_factory=dict)
    output_description: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeActionOutput:
    """Generic runtime action frame until the runtime protocol model lands."""

    space_id: str
    values: tuple[float, ...]
    sequence: int | None = None
    metadata: JsonObject = field(default_factory=dict)
    kind: str = "runtime_action"


@dataclass(frozen=True)
class RolloutEpisodeRecord:
    """Per-episode rollout record for benchmark artifacts."""

    episode_id: str
    task_id: str
    init_state_id: str
    success: bool
    steps: int
    reward_sum: float = 0.0
    done: bool = False
    failure_reason: str | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RolloutSummary:
    """Aggregate rollout summary for benchmark artifacts."""

    episodes: int
    successes: int
    success_rate: float
    metadata: JsonObject = field(default_factory=dict)
