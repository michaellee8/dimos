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

"""Compose scene-package entities into a MuJoCo model via ``MjSpec``.

The cook step removes entity prims (chairs, props) from the static
scene bake and writes their per-entity GLBs and metadata to the
package's ``entities/`` directory. At runtime, ``MujocoSimModule``
calls :func:`add_entities_to_spec` on its scene spec **before** the
robot attach, so the cooked entities become first-class bodies in the
composed model.

Entities with ``kind == "dynamic"`` and positive mass receive a
freejoint (robot can push/grasp them); anything else is welded static.
Collision: primitive shapes (box/sphere/cylinder) use the descriptor
extents; mesh entities use the convex hull of their cooked
``visual.glb`` (MuJoCo collides on the hull of mesh geoms anyway, so
this is exact for its collision model). Exact concave collision via
convex decomposition at cook time is a follow-up.

A spawn-contact audit can be run on the compiled model to weld
entities that start in deep penetration with the static scene; see
:func:`spawn_penetrators`. The runtime caller (``MujocoSimModule``)
chooses when to invoke it.

Body naming: ``entity:<entity_id>`` — consumers map MuJoCo bodies back
to entity ids through this prefix.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dimos.utils.logging_config import setup_logger

if TYPE_CHECKING:
    import mujoco

    from dimos.simulation.scene_assets.spec import ScenePackage

logger = setup_logger()

ENTITY_BODY_PREFIX = "entity:"

_MIN_HALF_EXTENT = 0.01
# Sliding friction 0.3 ≈ furniture that scoots when bumped. Entity geoms
# carry priority=1 so this wins the contact pair outright (MuJoCo's
# default combine rule is element-wise max, which would let the μ=1.0
# floor override it). Graspable props override via ``physics.friction``.
_DEFAULT_FRICTION = (0.3, 0.05, 0.001)
_DEFAULT_RGBA = (0.62, 0.62, 0.68, 1.0)
# Same geom group as the baked static scene so depth-based lidar renders
# (which hide robot groups 0/1) still see entities.
_ENTITY_GEOM_GROUP = 3
# Spawn-contact audit: deeper penetration than this at t=0 demotes the
# entity to static instead of letting MuJoCo eject it.
_SPAWN_PENETRATION_LIMIT_M = 0.02


def entity_body_name(entity_id: str) -> str:
    return f"{ENTITY_BODY_PREFIX}{entity_id}"


def _initial_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entities if e.get("spawn", "initial") == "initial"]


def _box_size_and_offset(entity: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    """Half-extents + geom offset (body frame) for an entity's collision box."""
    descriptor = entity.get("descriptor", {})
    shape = descriptor.get("shape_hint", "mesh")
    extents = [float(x) for x in descriptor.get("extents", [])]

    if shape == "box" and len(extents) == 3:
        half = [max(x / 2.0, _MIN_HALF_EXTENT) for x in extents]
        return half, [0.0, 0.0, 0.0]
    if shape == "sphere" and len(extents) == 1:
        r = max(extents[0], _MIN_HALF_EXTENT)
        return [r, r, r], [0.0, 0.0, 0.0]
    if shape == "cylinder" and len(extents) == 2:
        r = max(extents[0], _MIN_HALF_EXTENT)
        h = max(extents[1] / 2.0, _MIN_HALF_EXTENT)
        return [r, r, h], [0.0, 0.0, 0.0]

    # Mesh entities: box from the cooked world-frame AABB. Cook poses are
    # identity-rotation, so the AABB is axis-aligned in the body frame too.
    aabb = entity.get("aabb")
    pose = entity.get("initial_pose")
    if not aabb or not pose:
        return None
    lo = [float(x) for x in aabb["min"]]
    hi = [float(x) for x in aabb["max"]]
    half = [max((h - low) / 2.0, _MIN_HALF_EXTENT) for low, h in zip(lo, hi, strict=True)]
    center = [(h + low) / 2.0 for low, h in zip(lo, hi, strict=True)]
    origin = [float(pose.get(k, 0.0)) for k in ("x", "y", "z")]
    offset = [c - o for c, o in zip(center, origin, strict=True)]
    return half, offset


def _hull_obj_path(entity: dict[str, Any], cache_dir: Path | None) -> Path | None:
    """Convex hull of the entity's cooked GLB as a cached OBJ for MuJoCo.

    The cooked per-entity GLBs are entity-local (origin = initial_pose,
    world axes), so the hull drops in with zero geom offset.

    Hulls live in a per-user cache (``~/.cache/dimos/entity_hulls/`` by
    default; override via ``cache_dir``) keyed on the GLB's content
    signature, so multiple sim runs share them and recook isn't
    required when a robot path changes.
    """
    visual_path = entity.get("visual_path")
    if not isinstance(visual_path, str):
        return None
    glb = Path(visual_path)
    if not glb.exists():
        return None

    entity_id = str(entity.get("id", "unknown"))
    stat = glb.stat()
    key = hashlib.sha256(f"{glb}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:10]
    hulls_root = cache_dir or (Path.home() / ".cache" / "dimos" / "entity_hulls")
    hulls_root.mkdir(parents=True, exist_ok=True)
    obj_path = hulls_root / f"{entity_id}_{key}.obj"
    if obj_path.exists():
        return obj_path

    try:
        import open3d as o3d  # type: ignore[import-untyped]

        mesh = o3d.io.read_triangle_mesh(str(glb))
        if not mesh.has_vertices():
            return None
        hull, _ = mesh.compute_convex_hull()
        o3d.io.write_triangle_mesh(str(obj_path), hull, write_vertex_normals=False)
    except Exception as exc:
        logger.warning("entity %s: hull from %s failed (%s); using AABB box", entity_id, glb, exc)
        return None
    return obj_path


def _entity_friction(entity: dict[str, Any]) -> tuple[float, float, float]:
    """``physics.friction`` from entity metadata (scalar sliding or full
    [sliding, torsional, rolling] triple), else the scoot-able default."""
    raw = entity.get("physics", {}).get("friction")
    sliding, torsional, rolling = _DEFAULT_FRICTION
    if isinstance(raw, int | float):
        sliding = float(raw)
    elif isinstance(raw, list | tuple) and len(raw) == 3:
        sliding, torsional, rolling = (float(v) for v in raw)
    return sliding, torsional, rolling


def _entity_rgba(descriptor: dict[str, Any]) -> tuple[float, float, float, float]:
    raw = descriptor.get("rgba")
    if isinstance(raw, list | tuple) and len(raw) == 4:
        return tuple(float(v) for v in raw)  # type: ignore[return-value]
    return _DEFAULT_RGBA


def add_entities_to_spec(
    spec: mujoco.MjSpec,
    entities: list[dict[str, Any]],
    *,
    force_static: frozenset[str] = frozenset(),
    hull_cache_dir: Path | None = None,
) -> None:
    """Append scene-package entities as bodies on ``spec.worldbody``.

    Call before attaching the robot. Each ``spawn=="initial"`` entity
    becomes one body named ``entity:<id>`` with the descriptor's geom
    shape and friction; dynamic entities also receive a freejoint named
    ``entity:<id>:free``.

    ``force_static`` is a set of entity ids to demote to welded static
    regardless of their ``kind`` — used by the spawn-penetration audit
    when an entity boots in deep contact with the static scene.
    """
    import mujoco

    for entity in _initial_entities(entities):
        descriptor = entity.get("descriptor", {})
        entity_id = descriptor.get("entity_id") or entity.get("id")
        pose = entity.get("initial_pose")
        if not entity_id or not pose:
            continue
        entity_id = str(entity_id)

        kind = descriptor.get("kind", "kinematic")
        mass = float(descriptor.get("mass", 0.0))
        dynamic = kind == "dynamic" and mass > 0.0 and entity_id not in force_static

        body = spec.worldbody.add_body(
            name=entity_body_name(entity_id),
            pos=[
                float(pose.get("x", 0.0)),
                float(pose.get("y", 0.0)),
                float(pose.get("z", 0.0)),
            ],
            quat=[
                float(pose.get("qw", 1.0)),
                float(pose.get("qx", 0.0)),
                float(pose.get("qy", 0.0)),
                float(pose.get("qz", 0.0)),
            ],
        )
        if dynamic:
            body.add_freejoint(name=f"{entity_body_name(entity_id)}:free")

        rgba = _entity_rgba(descriptor)
        friction = _entity_friction(entity)
        geom_kwargs: dict[str, Any] = dict(
            name=f"{entity_body_name(entity_id)}:geom",
            rgba=list(rgba),
            friction=list(friction),
            group=_ENTITY_GEOM_GROUP,
            # priority=1: contact friction comes from the entity geom alone.
            # MuJoCo's default combine rule (element-wise max across the
            # pair) would otherwise let the μ=1.0 floor override every
            # entity's friction.
            priority=1,
        )
        if dynamic:
            geom_kwargs["mass"] = mass

        shape = descriptor.get("shape_hint", "mesh")
        hull_obj = _hull_obj_path(entity, hull_cache_dir) if shape == "mesh" else None
        if hull_obj is not None:
            mesh_name = f"{entity_body_name(entity_id)}:hull"
            spec.add_mesh(name=mesh_name, file=str(hull_obj))
            body.add_geom(
                type=mujoco.mjtGeom.mjGEOM_MESH,
                meshname=mesh_name,
                **geom_kwargs,
            )
            continue

        box = _box_size_and_offset(entity)
        if box is None:
            logger.warning("entity %s has no usable collision shape; skipping", entity_id)
            continue
        half, offset = box
        geom_kwargs["pos"] = offset
        if shape == "sphere":
            geom_type = mujoco.mjtGeom.mjGEOM_SPHERE
            size = [half[0], 0.0, 0.0]
        elif shape == "cylinder":
            geom_type = mujoco.mjtGeom.mjGEOM_CYLINDER
            size = [half[0], half[2], 0.0]
        else:
            geom_type = mujoco.mjtGeom.mjGEOM_BOX
            size = half
        body.add_geom(type=geom_type, size=size, **geom_kwargs)


def spawn_penetrators(model: mujoco.MjModel) -> frozenset[str]:
    """Entity ids whose geoms start in deep contact at the spawn pose.

    Run after ``spec.compile()`` and before stepping; pass the returned
    set as ``force_static`` to a second ``add_entities_to_spec`` call on
    a fresh spec if you want to weld penetrating entities and recompile.
    """
    import mujoco

    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    bad: set[str] = set()
    for c in range(data.ncon):
        contact = data.contact[c]
        if contact.dist >= -_SPAWN_PENETRATION_LIMIT_M:
            continue
        for geom_id in (contact.geom1, contact.geom2):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, int(geom_id)) or ""
            if name.startswith(ENTITY_BODY_PREFIX) and name.endswith(":geom"):
                bad.add(name[len(ENTITY_BODY_PREFIX) : -len(":geom")])
    return frozenset(bad)


def compose_entity_model(scene_package: ScenePackage) -> Path | None:
    """Legacy entry point — pre-compose a scene+entities ``.mjb`` from a
    package wrapper.

    The new runtime path (``MujocoSimModule._compose_model``) calls
    :func:`add_entities_to_spec` directly on the ``MjSpec`` and never
    materialises a separate ``.mjb``. This function is retained for the
    few callers that still want a precompiled binary; it returns ``None``
    when the package has no MuJoCo scene artifact.
    """
    if scene_package.mujoco_scene_path is None:
        return None
    wrapper = Path(scene_package.mujoco_scene_path)
    if not wrapper.exists():
        return None

    import mujoco

    entities = _initial_entities(scene_package.entities)
    if not entities:
        return wrapper

    spec = mujoco.MjSpec.from_file(str(wrapper))
    add_entities_to_spec(spec, entities)
    model = spec.compile()

    penetrators = spawn_penetrators(model)
    if penetrators:
        logger.warning(
            "%d entities spawn in deep contact and are welded static: %s",
            len(penetrators),
            ", ".join(sorted(penetrators)),
        )
        spec = mujoco.MjSpec.from_file(str(wrapper))
        add_entities_to_spec(spec, entities, force_static=penetrators)
        model = spec.compile()

    out_dir = wrapper.parent
    key = hashlib.sha256(repr(entities).encode()).hexdigest()[:12]
    mjb_path = out_dir / f"entities_{key}.mjb"
    mujoco.mj_saveModel(model, str(mjb_path))
    return mjb_path


__all__ = [
    "ENTITY_BODY_PREFIX",
    "add_entities_to_spec",
    "compose_entity_model",
    "entity_body_name",
    "spawn_penetrators",
]
