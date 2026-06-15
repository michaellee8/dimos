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

"""Drive a running ``r1pro-perception-sim``: go_home -> scan -> pick.

Run the sim in one terminal::

    direnv exec . dimos run r1pro-perception-sim

then, in a second terminal, drive a pick (default object = ``cup``)::

    direnv exec . python examples/r1pro_pickplace/drive_pick.py cup

Watch it in viser at http://127.0.0.1:8095. The arm scans the desk, picks the
requested object with the nearer hand, and holds it up so you can eyeball the
grasp.

Note: this is a GROUND-TRUTH scan (the sim knows the object poses). The detections
live in the module's ``_detection_snapshot`` and ``pick()`` matches by name, so we
pick the requested name directly rather than gating on the perception cache.
"""

import sys
import time

from dimos.core.rpc_client import RPCClient
from dimos.manipulation.eval.runner import normalize_skill_result as nsr
from dimos.manipulation.pick_and_place_module import PickAndPlaceModule

target = sys.argv[1] if len(sys.argv) > 1 else "cup"
arm = RPCClient(None, PickAndPlaceModule)

# Clean slate: clear any prior fault, then home the arm.
if arm.get_state() in ("FAULT", "COMPLETED", "ABORTED"):
    arm.reset()
for _ in range(5):
    if nsr(arm.go_home())["success"]:
        break
arm.set_init_joints_to_current()
time.sleep(2.0)

# Ground-truth "scan" -- populates _detection_snapshot; the message lists the objects.
scan = nsr(arm.scan_objects())
print(f"[scan] success={scan['success']} :: {scan['message'][:240]}")
if not scan["success"]:
    sys.exit(1)

# Pick the requested object by NAME (pick() resolves it from _detection_snapshot).
ee0 = arm.get_ee_pose()
print(f"[pick] pick('{target}') ...")
result = nsr(arm.pick(target))
time.sleep(1.0)
ee1 = arm.get_ee_pose()
print(f"   -> success={result['success']} msg={result['message'][:160]}")
print(
    f"   -> ee_z {ee0.position.z:.3f} -> {ee1.position.z:.3f} "
    f"(delta={ee1.position.z - ee0.position.z:+.3f}m) state={arm.get_state()}"
)
print("[PICK OK] holding for visual check" if result["success"] else "[PICK FAILED]")
