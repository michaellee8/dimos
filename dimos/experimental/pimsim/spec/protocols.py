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

"""Protocol definitions for PimSim — the pluggable-physics simulation layer.

PimSim's thesis (see ``../DESIGN.md``): make *physics authority* a pluggable
role and decouple every other concern from it through three shared contracts,
so any authority can drive any consumer:

    1. SCENE PACKAGE   what geometry exists      -> ScenePackage (concrete,
                       (cooked offline, portable)   simulation/scene_assets/spec.py)
    2. ENTITY STREAM   where everything is now    -> EntityDescriptor /
                       (versioned JSON over LCM)     EntityStateBatch (../entity.py)
    3. LCM BUS         the transport              -> dimos LCM (+ an LCM-over-
                                                      WebSocket bridge for browsers)

Those three are already concrete types. What was only *implicit* in the
sprawling modules — and is named here — are the two roles they play.

Two interface styles appear below, each used where it is faithful:

* **Pub/sub port contracts** (``EntityAuthority``, ``EntityConsumer``). PimSim's
  entity flow is streaming: an authority *publishes* an ``EntityStateBatch``
  every tick on its own clock; no one calls it. So the contract IS the dimos
  port (``Out[...]`` / ``In[...]``), declared as a Protocol attribute, not a
  method you invoke.
* **Method stubs** (``SceneObjectWorld``, and the ``@rpc`` ``spawn_entity``).
  Used for surfaces that are genuinely *called* synchronously — a planner asks
  a world ``add_object(...)``; an operator RPCs ``spawn_entity(...)``. This is
  the ``dimos/manipulation/planning/spec`` ``WorldSpec`` style.

Read the concrete modules *through* these protocols:
    authority producers : BabylonSceneViewerModule (Havok, interactive)
                          MujocoSimModule          (headless, deterministic)
    consumers           : SceneLidarModule, SplatCameraModule,
                          MujocoWorld.sync_entity_poses, the reachability builder
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from dimos.experimental.pimsim.entity import EntityDescriptor, EntityStateBatch
from dimos.experimental.pimsim.spec.enums import AuthorityMode

if TYPE_CHECKING:
    # Typing-only: keep the spec import-light. ``In``/``Out`` are dimos stream
    # ports; ``ScenePackage`` is the concrete cooked-geometry dataclass;
    # ``SceneObject`` is the proposed unified noun (see models.py / §7-A).
    from dimos.core.stream import In, Out
    from dimos.experimental.pimsim.spec.models import SceneObject
    from dimos.msgs.geometry_msgs.Pose import Pose


# ─────────────────────────────────────────────────────────────────────────
# The two roles that exist today (streaming — expressed as port contracts)
# ─────────────────────────────────────────────────────────────────────────


@runtime_checkable
class EntityAuthority(Protocol):
    """The producer role: owns a scene's physics and broadcasts entity state.

    An authority ingests a cooked ``ScenePackage`` once (at construction, from
    config — not via a call), then **publishes an ``EntityStateBatch`` every
    tick** onto the LCM bus: a snapshot of every entity's descriptor + world
    pose. Consumers subscribe and never learn which authority is upstream;
    swapping authorities is a blueprint flag and nothing downstream changes.

    Authority is a *role*, not a kind of module — and it is **not exclusive
    with consuming**. ``BabylonSceneViewerModule`` implements both this and
    ``EntityConsumer``: it OWNS physics (Havok) in ``entity_authority="browser"``
    mode, and in ``"external"`` mode it MIRRORS another authority's stream as a
    viewer (i.e. behaves as a consumer). ``MujocoSimModule`` is authority-only,
    headless and deterministic. ``authority_mode`` says which way an instance is
    currently pointed.

    The contract is the **output port** below — not a method you call; the
    authority drives it from its own physics loop. (Robot base pose / ``odom``
    is a separate concern and deliberately *not* part of this contract — that
    is why the two authorities legitimately differ on how they handle it.)
    """

    entity_state_batch: Out[EntityStateBatch]
    """THE contract every consumer depends on: a fresh snapshot of every entity
    (descriptor + world pose) published each tick. Live when
    ``authority_mode == OWNS``; a MIRROR instance consumes instead (see
    ``EntityConsumer``)."""

    @property
    def authority_mode(self) -> AuthorityMode:
        """``OWNS`` — this instance simulates physics and produces the stream.
        ``MIRROR`` — it consumes another authority's stream and renders it as
        kinematic bodies (a viewer, not a simulator). For the Babylon viewer
        this is ``entity_authority`` ``"browser"`` vs ``"external"``."""
        ...

    def spawn_entity(self, descriptor: EntityDescriptor, pose: Pose) -> bool:
        """Add one body at runtime, beyond the cooked package, that the scene
        has assets for. Returns ``False`` if rejected — e.g. a ``MIRROR``
        instance, which only echoes the upstream stream.

        Both authorities should support this in principle. Babylon does today
        (``@rpc``); MuJoCo currently only seeds entities from its
        ``scene_entities`` config and does not yet expose runtime spawn — a
        known gap to close, not a reason to weaken the contract."""
        ...


@runtime_checkable
class EntityConsumer(Protocol):
    """The consumer role: reads the entity stream, blind to the authority.

    Subscribes to ``EntityStateBatch`` and reacts; never references a physics
    engine, so it behaves identically no matter which authority is upstream —
    including when the upstream is a MIRROR-mode authority. Adding a consumer is
    "subscribe to the stream," not "integrate with the simulator." Consumers:

    * ``SceneLidarModule`` — BVH raycast vs the cooked collision GLB + the
      dynamic entities from the stream (same scene the sim simulates).
    * ``SplatCameraModule`` — composite live entity poses + arm hulls onto a
      Gaussian-splat render.
    * the planning world — ``MujocoWorld.sync_entity_poses`` writes streamed
      poses into the collision world. (Here the ``world_monitor`` module owns
      the port and *calls* the world, so the world consumes the data
      indirectly — a second consumer shape, not a subscribing module.)
    * the reachability map builder — samples arm FK against that world.
    * ``BabylonSceneViewerModule`` in ``external`` mode — the same module that
      is an authority in ``browser`` mode, here acting as a viewer.

    The contract is the **input port** below. dimos binds it by topic
    (``/entity_state_batch``), so the local attribute name is each module's
    choice — consumers today name it ``entity_states``.
    """

    entity_states: In[EntityStateBatch]
    """The subscribed stream (topic ``/entity_state_batch``). The consumer keys
    on ``descriptor.entity_id`` for identity across ticks, and uses
    ``mesh_ref`` / ``shape_hint`` / ``extents`` to instantiate geometry the
    first time it sees an id; pose updates thereafter are just the ``Pose``
    half of each entry."""


# ─────────────────────────────────────────────────────────────────────────
# PROPOSED (DESIGN.md §7-A, Decision A) — NOT implemented yet.
# One scene-object noun, two verbs. Method-style because a planner calls it.
# ─────────────────────────────────────────────────────────────────────────


@runtime_checkable
class SceneObjectWorld(Protocol):
    """PROPOSED. Three types describe "a shaped thing at a pose" today:
    ``Obstacle`` (planning collision input), ``EntityDescriptor`` (PimSim scene
    state), and the perception ``Object`` (``Detection3D``: pointcloud + mask).
    Decision A merges the first two into one ``SceneObject`` noun and gives the
    world **two verbs**; perception ``Object`` stays separate (it pulls
    open3d + cv2 and is detector *output*, not spawnable geometry) and is
    *converted into* a ``SceneObject`` by the obstacle monitor.

    This is the planning ``WorldSpec``'s obstacle verbs renamed onto the
    unified noun. The payoff: ``EntityStateBatch`` becomes the *streaming form*
    of ``(SceneObject, pose)``, so the entity stream and the planning world
    speak one vocabulary. Two verbs, not one pipeline, because "inject new
    geometry" and "move known geometry" are genuinely different operations
    (one mutates the body set; one writes a pose).
    """

    def add_object(self, obj: SceneObject, pose: Pose) -> str:
        """Inject NEW geometry — what ``add_obstacle`` does, and what a
        perception detection becomes. Mutates the body set. Returns the id."""
        ...

    def update_object_pose(self, object_id: str, pose: Pose) -> bool:
        """Reposition KNOWN geometry — what ``sync_entity_poses`` does every
        tick from the entity stream. Writes a pose; never adds a body."""
        ...

    def remove_object(self, object_id: str) -> bool:
        """Remove a previously added object. Returns ``True`` if removed."""
        ...

    def get_objects(self) -> list[SceneObject]:
        """All objects currently in the world."""
        ...


__all__ = ["EntityAuthority", "EntityConsumer", "SceneObjectWorld"]
