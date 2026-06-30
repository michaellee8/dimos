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

from typing import Generic

from dimos.robot_learning.policy_rollout.backend import PolicyBackend
from dimos.robot_learning.policy_rollout.contract import RobotPolicyContract, SampleT
from dimos.robot_learning.policy_rollout.models import (
    PolicyBackendDescription,
    RobotPolicyContractDescription,
    RuntimeActionOutput,
)


class RobotPolicyModule(Generic[SampleT]):
    """Policy inference seam for robot-learning rollouts.

    The module owns backend lifecycle, episode reset, contract conversion,
    backend inference, and action emission. Benchmark/runtime lifecycle,
    sidecar reset/step, scoring, success gates, and artifact writing remain
    outside this class.
    """

    def __init__(self, backend: PolicyBackend, contract: RobotPolicyContract[SampleT]) -> None:
        self._backend = backend
        self._contract = contract
        self._initialized = False
        self._last_action: RuntimeActionOutput | None = None

    @property
    def last_action(self) -> RuntimeActionOutput | None:
        return self._last_action

    def initialize(self) -> None:
        if self._initialized:
            return
        self._backend.initialize()
        self._initialized = True

    def reset(self, episode_id: str | None = None) -> None:
        del episode_id
        self.initialize()
        self._backend.reset_episode()
        self._last_action = None

    def infer_action(self, sample: SampleT) -> RuntimeActionOutput:
        self.initialize()
        batch = self._contract.to_backend_batch(sample)
        backend_output = self._backend.infer_batch(batch)
        action = self._contract.from_backend_output(backend_output)
        return self.emit_action(action)

    def emit_action(self, action: RuntimeActionOutput) -> RuntimeActionOutput:
        self._last_action = action
        return action

    def close(self) -> None:
        self._backend.close()
        self._initialized = False

    def describe_backend(self) -> PolicyBackendDescription:
        return self._backend.describe()

    def describe_contract(self) -> RobotPolicyContractDescription:
        return self._contract.describe()
