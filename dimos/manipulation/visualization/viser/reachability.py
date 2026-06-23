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

"""Reachability-map scene layer for the Viser manipulation visualizer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from dimos.manipulation.visualization.viser.scene import ViserManipulationScene

logger = setup_logger()


class ReachabilityMapLayer:
    """Layer object for reachability volumes and slices in a Viser scene."""

    def __init__(self, scene: ViserManipulationScene, root: str = "/reachability") -> None:
        self._scene = scene
        self._root = root.rstrip("/") or "/reachability"
        self._handles: dict[str, Any] = {}

    def show_points(
        self,
        points: NDArray[np.float64],
        colors: NDArray[np.uint8],
        *,
        point_size: float,
    ) -> None:
        """Show a reachability point cloud."""
        self.clear_volume()
        if len(points) == 0 or point_size <= 0.0:
            return
        self._handles["points"] = self._scene.server.scene.add_point_cloud(
            f"{self._root}/points",
            points=points.astype(np.float32),
            colors=colors,
            point_size=point_size,
            point_shape="circle",
        )

    def show_voxel_mesh(self, mesh: Any | None) -> None:
        """Show a reachability voxel mesh."""
        self.clear_volume()
        if mesh is None:
            return
        self._handles["voxels"] = self._scene.server.scene.add_mesh_trimesh(
            f"{self._root}/core", mesh
        )

    def clear_volume(self) -> None:
        """Remove volume handles."""
        self._remove("points")
        self._remove("voxels")

    def show_vertical_slice(
        self,
        image: NDArray[np.uint8],
        *,
        width: float,
        height: float,
        center_z: float,
        wxyz: tuple[float, float, float, float],
    ) -> None:
        """Show a vertical reachability slice."""
        self._remove("vertical_slice")
        self._handles["vertical_slice"] = self._scene.server.scene.add_image(
            f"{self._root}/slices/vertical",
            np.ascontiguousarray(image[::-1]),
            render_width=width,
            render_height=height,
            position=(0.0, 0.0, center_z),
            wxyz=wxyz,
        )

    def show_horizontal_slice(
        self,
        image: NDArray[np.uint8],
        *,
        width: float,
        height: float,
        z: float,
    ) -> None:
        """Show a horizontal reachability slice."""
        self._remove("horizontal_slice")
        self._handles["horizontal_slice"] = self._scene.server.scene.add_image(
            f"{self._root}/slices/horizontal",
            np.ascontiguousarray(image[::-1]),
            render_width=width,
            render_height=height,
            position=(0.0, 0.0, z),
            wxyz=(1.0, 0.0, 0.0, 0.0),
        )

    def clear_vertical_slice(self) -> None:
        """Remove the vertical slice."""
        self._remove("vertical_slice")

    def clear_horizontal_slice(self) -> None:
        """Remove the horizontal slice."""
        self._remove("horizontal_slice")

    def clear_slices(self) -> None:
        """Remove all slice handles."""
        self.clear_vertical_slice()
        self.clear_horizontal_slice()

    def close(self) -> None:
        """Remove all reachability handles."""
        self.clear_volume()
        self.clear_slices()

    def _remove(self, key: str) -> None:
        handle = self._handles.pop(key, None)
        if handle is None:
            return
        remove = getattr(handle, "remove", None)
        if callable(remove):
            try:
                remove()
            except Exception:
                logger.warning("Could not remove reachability layer handle %s", key, exc_info=True)


__all__ = ["ReachabilityMapLayer"]
