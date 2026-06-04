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

"""Fixed manipulation benchmark suite: objects, scenes, and per-episode trials.

Pure data — no imports beyond the standard library, so this is safe to load in
any context (report tooling, tests) without pulling in hardware dependencies.
"""

from __future__ import annotations

from typing import TypedDict

# Functional TypedDict syntax so the field can be named "class" (a Python keyword).
ObjectSpec = TypedDict("ObjectSpec", {"name": str, "class": str, "description": str})


class SceneConfig(TypedDict):
    scene_id: str
    description: str
    object_names: list[str]
    place_targets: dict[str, list[float]]
    clutter_level: str


class Trial(TypedDict):
    scene_id: str
    object_name: str
    target_position: list[float]


# Six common household items that perception models reliably detect. ``class`` is
# the grouping label used for per-class rollups; for this distinct set each
# object is its own class (e.g. cup -> "cup").
OBJECT_SET: list[ObjectSpec] = [
    {"name": "cup", "class": "cup", "description": "ceramic coffee mug"},
    {"name": "bottle", "class": "bottle", "description": "plastic water bottle"},
    {"name": "can", "class": "can", "description": "aluminum soda can"},
    {"name": "box", "class": "box", "description": "small cardboard box"},
    {"name": "marker", "class": "marker", "description": "whiteboard marker"},
    {"name": "tape", "class": "tape", "description": "roll of masking tape"},
]

# object name -> grouping class, derived from OBJECT_SET.
OBJECT_CLASS_BY_NAME: dict[str, str] = {obj["name"]: obj["class"] for obj in OBJECT_SET}


# Three scenes spanning clutter levels. ``place_targets`` give a per-object drop
# location in the xArm7 workspace (metres, base frame; z is the table-plus-margin
# height). Targets are spaced so placed objects do not collide.
SCENE_CONFIGS: list[SceneConfig] = [
    {
        "scene_id": "sparse_3obj",
        "description": "3 well-separated objects, place targets ~10cm apart",
        "object_names": ["cup", "bottle", "can"],
        "place_targets": {
            "cup": [0.45, 0.10, 0.05],
            "bottle": [0.40, -0.10, 0.05],
            "can": [0.50, 0.00, 0.05],
        },
        "clutter_level": "sparse",
    },
    {
        "scene_id": "medium_5obj",
        "description": "5 objects, moderate spacing (~7cm)",
        "object_names": ["cup", "bottle", "can", "box", "marker"],
        "place_targets": {
            "cup": [0.45, 0.12, 0.05],
            "bottle": [0.42, -0.02, 0.05],
            "can": [0.50, 0.06, 0.05],
            "box": [0.38, 0.05, 0.05],
            "marker": [0.52, -0.10, 0.05],
        },
        "clutter_level": "medium",
    },
    {
        "scene_id": "cluttered_6obj",
        "description": "all 6 objects, tight spacing (~4cm)",
        "object_names": ["cup", "bottle", "can", "box", "marker", "tape"],
        "place_targets": {
            "cup": [0.44, 0.08, 0.05],
            "bottle": [0.41, -0.06, 0.05],
            "can": [0.48, 0.02, 0.05],
            "box": [0.38, 0.01, 0.05],
            "marker": [0.51, -0.09, 0.05],
            "tape": [0.46, -0.12, 0.05],
        },
        "clutter_level": "cluttered",
    },
]


def build_trials(scenes: list[SceneConfig]) -> list[Trial]:
    """Flatten scenes into one trial per (scene, object) pair."""
    trials: list[Trial] = []
    for scene in scenes:
        for object_name in scene["object_names"]:
            trials.append(
                {
                    "scene_id": scene["scene_id"],
                    "object_name": object_name,
                    "target_position": list(scene["place_targets"][object_name]),
                }
            )
    return trials


# One episode per (scene, object): 3 + 5 + 6 = 14 trials. A full ~50-episode
# benchmark is reached by running these with n_repeats=3-4.
BENCHMARK_TRIALS: list[Trial] = build_trials(SCENE_CONFIGS)
