"""Stage 8 — RigifyBackend: automated humanoid rig via bounding-box metarig placement.

Flow:
  1. Enable Rigify add-on (built-in, may not be active by default).
  2. Create a plain Armature with Mixamo-named bones placed at bounding-box
     fractions from skeleton.py (no ML, heuristic but automatic).
  3. Parent the mesh to the armature with Blender's Automatic Weights.

The result is a game-ready rig with the canonical Mixamo bone names that Phase 6's
retargeter can map Mixamo clips onto without a bone-name translation step.

Limitations (Phase 5):
  • Bone placement is a bounding-box heuristic — works well for A-pose standing
    characters but will be wrong for animals or unusual poses.
  • Auto-weights can misassign on meshes with overlapping geometry.
  • A proper ML auto-rig (UniRig — see unirig.py) will give better results once
    the API is stable.
"""
from __future__ import annotations

import bpy

from assetforge.core.adapter import Backend, Capabilities, RunContext, RunMode
from assetforge.core.asset_state import AssetState
from assetforge.core.stages import AssetType

from ..geometry.utils import ensure_object, set_active
from .skeleton import BONE_BY_NAME, HUMANOID_BONES, world_positions


class RigifyBackend(Backend):
    name = "auto_rig"
    stage = "rig"

    def supports_local(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("rig", input_types=("mesh",), output_types=("skeleton",),
                            skeleton="mixamo")

    def run_local(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        if state.asset_type not in (AssetType.HUMANOID,):
            print(f"[AssetForge] rig: skipping for asset_type={state.asset_type}")
            state.artifacts["skeleton"] = "n/a"
            return state

        obj = ensure_object(state)
        if obj is None:
            raise RuntimeError("No mesh object for rigging")

        # Remove stale armature from a previous run
        arm_name = f"{obj.name}_Armature"
        if arm_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[arm_name], do_unlink=True)

        arm_obj = _build_armature(obj, arm_name, params)
        _parent_mesh_to_armature(obj, arm_obj)

        state.artifacts["skeleton"] = "mixamo"
        state.artifacts["armature_object"] = arm_obj.name
        state.artifacts["blender_object"] = obj.name
        print(f"[AssetForge] rig: created {arm_name} with {len(HUMANOID_BONES)} bones")
        return state


def _build_armature(mesh_obj, arm_name: str, params: dict):
    """Create a plain Armature with Mixamo-named bones at heuristic positions."""
    positions = world_positions(mesh_obj)

    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = arm_name
    arm_obj.data.name = arm_name

    # Remove the default bone
    edit_bones = arm_obj.data.edit_bones
    for b in list(edit_bones):
        edit_bones.remove(b)

    # Add Mixamo bones
    added: dict = {}
    for bone_def in HUMANOID_BONES:
        hx, hy, hz, tz = positions[bone_def.name]
        eb = edit_bones.new(bone_def.name)
        eb.head = (hx, hy, hz)
        eb.tail = (hx, hy, tz)
        added[bone_def.name] = eb

    # Assign parents
    for bone_def in HUMANOID_BONES:
        if bone_def.parent:
            added[bone_def.name].parent = added[bone_def.parent]

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def _parent_mesh_to_armature(mesh_obj, arm_obj) -> None:
    """Parent the mesh to the armature with automatic vertex weights."""
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    print("[AssetForge] rig: auto-weights applied")
