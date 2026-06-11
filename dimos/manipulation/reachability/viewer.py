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

"""One-shot viser viewer for capability maps.

Renders only the *reachable* cells as a score-colored point cloud around
the G1 (URDF shown for context, pelvis at the map height), with live
filters for approach angle, in-plane bin, and minimum score — much easier
to read than 2D slices where most of the grid is red.

Two view modes, both honest about the map's heading-free semantics:

- **canonical**: cells are placed at the TCP position of the ψ = 0 gauge
  representative — "where can the hand be when its approach azimuth
  points along +x (for some pelvis heading)". Shows per-θ structure.
- **position**: the orientation-marginal radial profile revolved around
  the pelvis axis — "positions reachable in *some* orientation". This one
  is rotationally symmetric by construction (the robot can turn in place).

CLI::

    python -m dimos.manipulation.reachability.viewer \\
        --map ~/Desktop/g1_reachability/g1_left_capability.npz
"""

from __future__ import annotations

import argparse
from pathlib import Path
import time

import numpy as np

from dimos.manipulation.reachability.capability_map import CapabilityMap
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

_REPO_ROOT = Path(__file__).parents[3]
_G1_URDF = _REPO_ROOT / "data" / "g1_urdf" / "g1.urdf"


def canonical_cloud(
    cap: CapabilityMap,
    theta_lo_deg: float,
    theta_hi_deg: float,
    gamma_bin: int | None,
    min_score: int,
) -> tuple[np.ndarray, np.ndarray]:
    """(points, scores) for the ψ=0 gauge representative of every marked cell.

    With ψ = 0 the canonical offset is (x*, y*) = (-p_x, -p_y), so the
    TCP position is (-x*, -y*, p_z) — pelvis at the origin.
    """
    params = cap.params
    t_lo = int(np.clip(theta_lo_deg / 180.0 * params.n_theta, 0, params.n_theta - 1))
    t_hi = int(np.clip(theta_hi_deg / 180.0 * params.n_theta + 1, t_lo + 1, params.n_theta))
    block = cap.counts[:, t_lo:t_hi]
    scores = (
        block[..., gamma_bin].max(axis=1) if gamma_bin is not None else block.max(axis=(1, 4))
    )  # (n_z, n_xy, n_xy)

    iz, ix, iy = np.nonzero(scores >= min_score)
    if len(iz) == 0:
        return np.empty((0, 3)), np.empty(0)
    centers = (np.arange(params.n_xy) + 0.5) * params.cell - params.r_xy
    z_centers = (np.arange(params.n_z) + 0.5) * params.cell + params.z_min
    points = np.stack([-centers[ix], -centers[iy], z_centers[iz]], axis=1)
    return points, scores[iz, ix, iy].astype(float)


def position_cloud(
    cap: CapabilityMap, min_score: int, ring_step: int = 12
) -> tuple[np.ndarray, np.ndarray]:
    """Orientation-marginal radial profile revolved into rings around the axis."""
    params = cap.params
    radial = cap.position_scores()  # (n_z, n_r)
    iz, ir = np.nonzero(radial >= min_score)
    if len(iz) == 0:
        return np.empty((0, 3)), np.empty(0)
    points, scores = [], []
    z_centers = (np.arange(params.n_z) + 0.5) * params.cell + params.z_min
    for z_idx, r_idx in zip(iz, ir, strict=True):
        radius = (r_idx + 0.5) * params.cell
        n_pts = max(int(2 * np.pi * radius / params.cell / 2), 1) if radius > 0 else 1
        n_pts = min(n_pts, ring_step * 8)
        angles = np.linspace(0, 2 * np.pi, n_pts, endpoint=False)
        ring = np.stack(
            [radius * np.cos(angles), radius * np.sin(angles), np.full(n_pts, z_centers[z_idx])],
            axis=1,
        )
        points.append(ring)
        scores.append(np.full(n_pts, float(radial[z_idx, r_idx])))
    return np.concatenate(points), np.concatenate(scores)


def score_colors(scores: np.ndarray, vmax: float | None = None) -> np.ndarray:
    """Score → RdYlGn uint8 colors (low = red/orange, high = green)."""
    import matplotlib
    import matplotlib.colors as mcolors

    vmax = vmax or max(float(scores.max(initial=1.0)), 1.0)
    norm = mcolors.Normalize(vmin=0.0, vmax=vmax)
    rgba = matplotlib.colormaps["RdYlGn"](norm(scores))
    return (rgba[:, :3] * 255).astype(np.uint8)


def _add_g1_context(server, pelvis_height: float) -> None:
    """Render the G1 URDF at the map's pelvis pose for spatial context."""
    try:
        from viser.extras import ViserUrdf
        import yourdfpy

        urdf = yourdfpy.URDF.load(str(_G1_URDF))
        viser_urdf = ViserUrdf(server, urdf, root_node_name="/g1")
        server.scene.add_frame("/g1", position=(0.0, 0.0, pelvis_height), show_axes=False)
        viser_urdf.update_cfg(np.zeros(len(viser_urdf.get_actuated_joint_names())))
    except Exception as e:  # context only — the cloud works without it
        logger.warning(f"G1 URDF context unavailable ({e}); showing frame axes only")
        server.scene.add_frame(
            "/g1", position=(0.0, 0.0, pelvis_height), show_axes=True, axes_length=0.25
        )


def serve(maps: dict[str, CapabilityMap], port: int = 8082) -> None:
    """Start the one-shot viewer (blocks until Ctrl-C)."""
    import viser

    server = viser.ViserServer(host="0.0.0.0", port=port)
    first = next(iter(maps.values()))
    server.scene.add_grid("/ground", width=4.0, height=4.0, cell_size=0.25)
    _add_g1_context(server, first.params.pelvis_height)

    side = server.gui.add_dropdown("arm", tuple(maps), initial_value=next(iter(maps)))
    mode = server.gui.add_dropdown(
        "mode", ("canonical (approach az = +x)", "position (any orientation)")
    )
    min_score = server.gui.add_slider("min score", min=1, max=60, step=1, initial_value=1)
    theta_lo = server.gui.add_slider("θ min [deg]", min=0, max=180, step=5, initial_value=0)
    theta_hi = server.gui.add_slider("θ max [deg]", min=0, max=180, step=5, initial_value=180)
    gamma_options = (
        "all",
        *(
            f"bin {i} ({int(-180 + (i + 0.5) * 360 / first.params.n_inplane)}°)"
            for i in range(first.params.n_inplane)
        ),
    )
    gamma = server.gui.add_dropdown("in-plane gamma", gamma_options, initial_value="all")
    point_size = server.gui.add_slider(
        "point size", min=0.005, max=0.05, step=0.005, initial_value=0.02
    )
    count_text = server.gui.add_text("cells shown", initial_value="", disabled=True)

    def refresh(_=None) -> None:
        cap = maps[side.value]
        if mode.value.startswith("position"):
            points, scores = position_cloud(cap, int(min_score.value))
        else:
            gamma_bin = None if gamma.value == "all" else int(gamma.value.split()[1])
            points, scores = canonical_cloud(
                cap, theta_lo.value, theta_hi.value, gamma_bin, int(min_score.value)
            )
        count_text.value = f"{len(points)}"
        if len(points) == 0:
            server.scene.add_point_cloud(
                "/reachability",
                points=np.zeros((1, 3)),
                colors=np.zeros((1, 3), dtype=np.uint8),
                point_size=0.001,
            )
            return
        server.scene.add_point_cloud(
            "/reachability",
            points=points.astype(np.float32),
            colors=score_colors(scores),
            point_size=float(point_size.value),
            point_shape="circle",
        )

    for control in (side, mode, min_score, theta_lo, theta_hi, gamma, point_size):
        control.on_update(refresh)
    refresh()

    logger.info(f"Reachability viewer: http://localhost:{port}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass


def cli_main() -> None:
    parser = argparse.ArgumentParser(description="Interactive capability-map viewer (viser).")
    parser.add_argument(
        "--map", type=Path, action="append", required=True, help="capability .npz (repeatable)"
    )
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()

    maps = {}
    for path in args.map:
        cap = CapabilityMap.load(path)
        maps[f"{cap.side} ({path.name})"] = cap
    serve(maps, port=args.port)


if __name__ == "__main__":
    cli_main()


__all__ = ["canonical_cloud", "position_cloud", "score_colors", "serve"]
