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

"""Run N stochastic replays of the [rec_t=1330, 1390] segment back to back.

Thin wrapper around ``replay_segment_1330_1390``. Each iteration calls
that module's orchestrator, which auto-increments a fresh
``attempt_NNN/`` dir under the shared runs root, spawns the binary as a
subprocess with stdout/stderr captured, and writes a ``meta.json`` with
the dimos commit hash. So this script just lays out N attempts under
the same root for ``plot_segment_1330_1390`` to render together.

With the 2026-05-29 two-thread replay refactor (commit ``32d7914f8``),
replay now runs at live wall throughput — each attempt costs ~40 s
(~30 s actual processing + ~10 s dimos startup/shutdown), so 5 runs is
~3.5 minutes total.

Run from the dimos venv:

    cd ~/repos/dimos
    source .venv/bin/activate
    python -m dimos.hardware.sensors.lidar.fastlio2.tools.replay_segment_1330_1390_x5
"""

from __future__ import annotations

from dimos.hardware.sensors.lidar.fastlio2.tools.replay_segment_1330_1390 import (
    main as one_attempt,
)

# ---------------- Configuration (hardcoded; bump and recommit to change) -----

N_RUNS = 5


def main() -> int:
    for i in range(N_RUNS):
        print(f"\n=== replay_segment_1330_1390 run {i + 1}/{N_RUNS} ===", flush=True)
        rc = one_attempt(["replay_segment_1330_1390_x5"])
        if rc != 0:
            print(f"[x5] run {i + 1} failed rc={rc}; aborting", flush=True)
            return rc
    print(f"\n=== {N_RUNS} runs complete ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
