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

"""Unit tests for the episode recorder and stage inference (no hardware)."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from dimos.manipulation.eval.recorder import EpisodeRecorder, infer_stages

FIXED_TS = datetime(2026, 1, 1, 0, 0, 0)


def _episode(object_name: str = "cup", task_success: bool = True) -> dict:
    return {
        "timestamp_iso": "2026-01-01T00:00:00.000Z",
        "hardware": "sim",
        "mode": "skill",
        "scene_id": "sparse_3obj",
        "object_name": object_name,
        "object_class": object_name,
        "target_position": [0.45, 0.10, 0.05],
        "stages": {
            k: True
            for k in (
                "scan",
                "grasp_gen",
                "plan_approach",
                "plan_grasp",
                "execute_pick",
                "execute_place",
            )
        },
        "pick_result": {"success": True, "error_code": None, "message": "ok", "duration_ms": 1.0},
        "place_result": {"success": True, "error_code": None, "message": "ok", "duration_ms": 1.0},
        "task_success": task_success,
        "cycle_time_ms": 1234.5,
        "placement_error_m": None,
        "agent_calls": None,
        "agent_retries": None,
        "agent_first_skill_correct": None,
    }


def test_records_episode_as_valid_json(tmp_path: Path) -> None:
    with EpisodeRecorder(output_dir=tmp_path, hardware="sim", timestamp=FIXED_TS) as rec:
        written = rec.record(_episode())

    # Filename is deterministic given the injected timestamp.
    assert rec.path.name == "eval_sim_20260101_000000.jsonl"

    lines = rec.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])

    # episode_id is injected and first; all schema keys are present.
    assert loaded["episode_id"] == "ep_0001"
    assert written == loaded
    expected_keys = {
        "episode_id",
        "timestamp_iso",
        "hardware",
        "mode",
        "scene_id",
        "object_name",
        "object_class",
        "target_position",
        "stages",
        "pick_result",
        "place_result",
        "task_success",
        "cycle_time_ms",
        "placement_error_m",
        "agent_calls",
        "agent_retries",
        "agent_first_skill_correct",
    }
    assert set(loaded.keys()) == expected_keys


def test_infer_stages_planning_failed() -> None:
    pick = {"success": False, "error_code": "PLANNING_FAILED", "message": "", "duration_ms": 0.0}
    stages = infer_stages(pick, None)
    assert stages["scan"] is True
    assert stages["grasp_gen"] is True
    assert stages["plan_approach"] is False
    assert stages["plan_grasp"] is None
    assert stages["execute_pick"] is None
    assert stages["execute_place"] is None


def test_infer_stages_success() -> None:
    pick = {"success": True, "error_code": None, "message": "", "duration_ms": 0.0}
    place = {"success": True, "error_code": None, "message": "", "duration_ms": 0.0}
    stages = infer_stages(pick, place)
    assert all(stages[k] is True for k in stages)


def test_infer_stages_grasp_failed() -> None:
    pick = {
        "success": False,
        "error_code": "GRASP_GENERATION_FAILED",
        "message": "",
        "duration_ms": 0.0,
    }
    stages = infer_stages(pick, None)
    assert stages["grasp_gen"] is False
    # All stages after grasp_gen were never attempted.
    assert stages["plan_approach"] is None
    assert stages["plan_grasp"] is None
    assert stages["execute_pick"] is None
    assert stages["execute_place"] is None


def test_infer_stages_scan_failed() -> None:
    scan = {
        "success": False,
        "error_code": "OBJECT_NOT_DETECTED",
        "message": "",
        "duration_ms": 0.0,
    }
    stages = infer_stages(None, None, scan)
    assert stages["scan"] is False
    assert all(stages[k] is None for k in stages if k != "scan")


def test_context_manager(tmp_path: Path) -> None:
    rec = EpisodeRecorder(output_dir=tmp_path, hardware="sim", timestamp=FIXED_TS)
    with rec:
        rec.record(_episode())
    assert rec._fh.closed  # file handle closed after the with-block


def test_multiple_episodes(tmp_path: Path) -> None:
    with EpisodeRecorder(output_dir=tmp_path, hardware="real", timestamp=FIXED_TS) as rec:
        ids = [rec.record(_episode(object_name=n))["episode_id"] for n in ("cup", "bottle", "can")]

    assert ids == ["ep_0001", "ep_0002", "ep_0003"]
    lines = rec.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["object_name"] for line in lines] == ["cup", "bottle", "can"]
