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

"""CustomStaticTransforms — republish a fixed dict of TF transforms periodically.

TF buffers expect periodic refresh, so static (fixed) transforms still need to be
re-emitted on a timer. This module is the stand-alone publisher equivalent of the
``_static_publish`` thread pattern in the Go2 connection, lifted out so any
blueprint can drop it in without dragging a robot-connection module along.

Usage::

    from dimos.robot.custom_static_transforms import CustomStaticTransforms
    from dimos.msgs.geometry_msgs.Transform import Transform

    autoconnect(
        CustomStaticTransforms.blueprint(
            static_transforms={
                "mid360_link": Transform(
                    translation=Vector3(0, 0, 1.2),
                    rotation=Quaternion(0, 0, 0, 1),
                    frame_id="base_link",
                    child_frame_id="mid360_link",
                ),
            },
        ),
        ...,
    )
"""

from __future__ import annotations

import threading
import time
from typing import Any

from pydantic import Field

from dimos.constants import DEFAULT_THREAD_JOIN_TIMEOUT
from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.msgs.geometry_msgs.Transform import Transform
from dimos.utils.logging_config import setup_logger

logger = setup_logger()


class CustomStaticTransformsConfig(ModuleConfig):
    # Keyed by child frame for ergonomic overrides. The map's keys are
    # informational — each value carries its own ``frame_id`` / ``child_frame_id``.
    static_transforms: dict[str, Transform] = Field(default_factory=dict)

    # Hz at which to re-emit transforms. Set 0 to publish once and stop.
    publish_rate: float = 1.0

    # Optional rename pass applied to both ``frame_id`` and ``child_frame_id``
    # right before each publish. Lets a blueprint swap "base_link" -> "body"
    # (or similar) without rewriting the source dict.
    frame_mapping: dict[str, str] = Field(default_factory=dict)


class CustomStaticTransforms(Module):
    """Periodically publishes a fixed set of TF transforms with fresh timestamps."""

    config: CustomStaticTransformsConfig

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @rpc
    def start(self) -> None:
        super().start()
        if not self.config.static_transforms:
            logger.warning("CustomStaticTransforms started with empty static_transforms")
            return
        self._publish_once()
        if self.config.publish_rate > 0:
            self._thread = threading.Thread(target=self._publish_loop, daemon=True)
            self._thread.start()

    @rpc
    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=DEFAULT_THREAD_JOIN_TIMEOUT)
            self._thread = None
        super().stop()

    def _remapped(self, transform: Transform, ts: float) -> Transform:
        remap = self.config.frame_mapping
        return Transform(
            translation=transform.translation,
            rotation=transform.rotation,
            frame_id=remap.get(transform.frame_id, transform.frame_id),
            child_frame_id=remap.get(transform.child_frame_id, transform.child_frame_id),
            ts=ts,
        )

    def _publish_once(self) -> None:
        now = time.time()
        self.tf.publish(*(self._remapped(t, now) for t in self.config.static_transforms.values()))

    def _publish_loop(self) -> None:
        period = 1.0 / self.config.publish_rate
        while not self._stop_event.wait(period):
            self._publish_once()
