"""Stage 4 — Retopology.

Strategy (in order of preference):
  1. QuadriFlow  — best quality: re-meshes to clean quads while following the
                   surface. Needs a VIEW_3D area for context (temp_override).
  2. Decimate COLLAPSE — shape-preserving fallback: collapses the least important
                   edges while following the original surface. The model keeps its
                   silhouette and proportions, just at a lower poly count.
                   Applied via the depsgraph method — no viewport context needed.

⚠ Voxel Remesh is intentionally NOT used as a fallback. It voxelises the volume
  and reconstructs the surface, which merges thin parts (fingers, clothing,
  accessories) and destroys proportions on character meshes.

Why depsgraph for modifier apply?
  ``bpy.ops.object.modifier_apply()`` needs a 3D-viewport operator context that
  is unavailable inside another operator. The depsgraph method
  (``obj.evaluated_get(depsgraph)`` → ``new_from_object``) works from any context
  and is the recommended approach in Blender 3.2+.
"""
from __future__ import annotations

import bpy

from assetforge.core.adapter import Backend, Capabilities, RunContext, RunMode
from assetforge.core.asset_state import AssetState

from .utils import apply_single_modifier, ensure_object, set_active


class RetopoBackend(Backend):
    name = "quadriflow"
    stage = "retopo"

    def supports_local(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("retopo", input_types=("mesh",), output_types=("mesh",),
                            emits_quads=True)

    def run_local(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        obj = ensure_object(state)
        if obj is None:
            raise RuntimeError("No mesh object in scene — generate stage must run first")

        target_faces = int(params.get("target_faces", 5_000))
        set_active(obj)

        faces_before = len(obj.data.polygons)
        print(f"[AssetForge] retopo: {faces_before} polys → target {target_faces}")

        used = _try_quadriflow(obj, target_faces)
        faces_after = len(obj.data.polygons)

        # If QuadriFlow didn't fire or left the mesh unchanged, fall back to
        # Decimate COLLAPSE — shape-preserving, works from any context.
        if used is None or faces_after == faces_before:
            print("[AssetForge] retopo: QuadriFlow unavailable — using Decimate (shape-preserving)")
            _apply_decimate(obj, faces_before, target_faces)
            used = "decimate_collapse"

        faces_final = len(obj.data.polygons)
        print(f"[AssetForge] retopo via {used}: {faces_before} → {faces_final} polys")

        state.artifacts["topology"] = "quad" if used == "quadriflow" else "tri"
        state.artifacts["blender_object"] = obj.name
        state.metadata.setdefault("retopo", {}).update(
            {"method": used, "faces_before": faces_before, "faces_after": faces_final})
        return state


def _try_quadriflow(obj, target_faces: int):
    """Try QuadriFlow with a VIEW_3D temp_override. Returns 'quadriflow' or None."""
    areas = [a for a in bpy.context.screen.areas if a.type == "VIEW_3D"]
    if not areas:
        return None
    try:
        with bpy.context.temp_override(area=areas[0], active_object=obj):
            result = bpy.ops.object.quadriflow_remesh(
                mode="FACES",
                target_faces=target_faces,
                use_preserve_sharp=True,
                use_preserve_boundary=True,
                smooth_normals=False,
            )
        return "quadriflow" if "FINISHED" in result else None
    except Exception as exc:
        print(f"[AssetForge] QuadriFlow failed ({exc})")
        return None


def _apply_decimate(obj, faces_before: int, target_faces: int) -> None:
    """Reduce poly count via Decimate COLLAPSE — shape-preserving, no context needed.

    Unlike Voxel Remesh this follows the original surface, so the model silhouette
    and proportions are maintained. The ratio is clamped so we never try to increase
    the poly count or decimate to essentially nothing.
    """
    ratio = max(0.01, min(0.99, target_faces / max(faces_before, 1)))

    mod = obj.modifiers.new("AF_Decimate", "DECIMATE")
    mod.decimate_type = "COLLAPSE"
    mod.ratio = ratio
    mod.use_collapse_triangulate = False  # keep n-gons / quads where possible

    apply_single_modifier(obj, mod)
