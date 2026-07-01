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

"""Agentic G1 on the GR00T whole-body scene stack.

``dimos --simulation mujoco --scene office run g1-groot-agentic`` spawns
the G1 in a cooked scene package with the full nav pipeline (Rust scene
lidar → raytrace voxel map → costmap → replanning A* → frontier
explorer), the textured mesh camera, and an MCP agent on top. Say
"explore the space" (``humancli`` / ``dimos agent-send`` / the web
input) and the agent calls ``begin_exploration``.

This is the union of the two previously-disjoint G1 stacks: the
groot-wbc scene stack (which had no agent) and the agentic-sim stack
(which ran on the legacy kinematic sim). ``UnitreeG1SkillContainer`` is
deliberately absent — it requires a ``G1ConnectionSpec`` the whole-body
stack doesn't provide; locomotion skills come from ``G1SimLocomotion``
(publishes ``cmd_vel``, same channel the nav planner uses).
"""

from dimos.agents.mcp.mcp_client import McpClient
from dimos.agents.mcp.mcp_server import McpServer
from dimos.agents.skills.navigation import NavigationSkillContainer
from dimos.agents.skills.sim_g1_locomotion import G1SimLocomotion
from dimos.agents.skills.speak_skill import SpeakSkill
from dimos.agents.web_human_input import WebInput
from dimos.core.coordination.blueprints import autoconnect
from dimos.perception.spatial_perception import SpatialMemory
from dimos.robot.unitree.g1.blueprints.basic.g1_groot_wbc import g1_groot_wbc
from dimos.robot.unitree.g1.system_prompt import G1_SYSTEM_PROMPT

# Top-level assignment so the all_blueprints AST scanner registers it
# as "g1-groot-agentic".
g1_groot_agentic = autoconnect(
    g1_groot_wbc,
    McpServer.blueprint(),
    McpClient.blueprint(system_prompt=G1_SYSTEM_PROMPT),
    SpeakSkill.blueprint(),
    G1SimLocomotion.blueprint(),
    WebInput.blueprint(),
    # Required by NavigationSkillContainer's SpatialMemorySpec module ref;
    # tests may `--disable spatial-memory` (resolves to a disabled proxy).
    SpatialMemory.blueprint(),
    NavigationSkillContainer.blueprint(),
)

__all__ = ["g1_groot_agentic"]
