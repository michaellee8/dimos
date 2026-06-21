#!/usr/bin/env python
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

"""Post-process a Go2 + Mid-360 recording into a ground-truth map.

Thin Go2 wrapper around the refined PGO pipeline in
``dimos/navigation/nav_stack/modules/pgo/scripts``:

  1. write ``camera_intrinsics.json`` from the Go2 front-camera calibration
  2. ``detect_tags.py``  -> ``raw_april_tags`` stream (every AprilTag detection)
  3. ``post_process.py`` -> AprilTag PGO + ICP loop closures, writing
     ``gt_pointlio_{odometry,lidar}`` back into the db plus an aggregated
     ``gt_pointlio_lidar.pc2.lcm``.

That ``.pc2.lcm`` is a relocalization premap — point
``relocalizationmodule.map_file`` at it (see
docs/capabilities/mapping/relocalization.md).

    uv run python dimos/mapping/recording/go2_mid360/post_process.py [REC] [extra flags]

REC is a recording dir (or its ``mem2.db``); omit it to use the newest recording
under ``./recordings``. Any extra flags (e.g. ``--no-icp``, ``--no-lcm``,
``--no-rrd``, ``--out=...``) pass through to ``post_process.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from dimos.robot.unitree.go2.config import (
    GO2_FRONT_CAMERA_DISTORTION,
    GO2_FRONT_CAMERA_INTRINSICS,
    GO2_FRONT_CAMERA_OPTICAL_IN_BASE,
)

_PGO_SCRIPTS = "dimos.navigation.nav_stack.modules.pgo.scripts"
_RECORDINGS_DIR = Path("recordings")
_CAMERA_STREAM = "color_image"  # GO2Connection's front camera (matches the calibration below)


def _resolve_recording(argv: list[str]) -> tuple[Path, list[str]]:
    """Split argv into (recording dir, passthrough flags).

    The first non-flag token is the target (a recording dir or its mem2.db);
    with none, fall back to the newest recording under ./recordings.
    """
    targets = [a for a in argv if not a.startswith("-")]
    passthrough = [a for a in argv if a.startswith("-")]
    if targets:
        target = Path(targets[0]).expanduser()
        rec = target.parent if target.name == "mem2.db" else target
    else:
        candidates = sorted(
            (p for p in _RECORDINGS_DIR.glob("2*") if (p / "mem2.db").exists()),
            key=lambda p: p.stat().st_mtime,
        )
        if not candidates:
            sys.exit(f"no recordings with a mem2.db under {_RECORDINGS_DIR}/ — pass one explicitly")
        rec = candidates[-1]
    if not (rec / "mem2.db").exists():
        sys.exit(f"no mem2.db in {rec}")
    return rec, passthrough


def _write_camera_intrinsics(rec: Path) -> None:
    """The PGO scripts read intrinsics from the recording dir, not the code."""
    (rec / "camera_intrinsics.json").write_text(
        json.dumps(
            {
                "intrinsics": GO2_FRONT_CAMERA_INTRINSICS.flatten().tolist(),
                "distortion": GO2_FRONT_CAMERA_DISTORTION.tolist(),
                "optical_in_base": list(GO2_FRONT_CAMERA_OPTICAL_IN_BASE),
            },
            indent=2,
        )
    )


def _run(module: str, *flags: str) -> None:
    cmd = [sys.executable, "-m", module, *flags]
    print(f"\n$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def main(argv: list[str]) -> None:
    rec, passthrough = _resolve_recording(argv)
    print(f"post-processing {rec}", flush=True)
    _write_camera_intrinsics(rec)
    _run(f"{_PGO_SCRIPTS}.detect_tags", f"--rec={rec}", f"--camera={_CAMERA_STREAM}")
    _run(
        f"{_PGO_SCRIPTS}.post_process",
        f"--rec={rec}",
        "--lidar=pointlio_lidar",
        "--odom=pointlio_odometry",
        "--tags=raw_april_tags",
        *passthrough,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
