"""Extract texture images from a Blender material's shader node tree.

After a GLB is imported into Blender, its textures are embedded as
``bpy.data.images`` and wired into the material's Principled BSDF node.
We read the node tree to classify which image is base colour, normal map, etc.
"""
from __future__ import annotations

import os
from typing import Optional

import bpy

from assetforge.core.asset_state import AssetState


def _classify(node_label: str) -> Optional[str]:
    """Map a node label/name to a texture role."""
    lb = node_label.lower()
    if any(k in lb for k in ("color", "colour", "diffuse", "albedo", "base_col")):
        return "basecolor"
    if "normal" in lb:
        return "normal"
    if "rough" in lb:
        return "roughness"
    if "metal" in lb:
        return "metallic"
    if any(k in lb for k in ("height", "displace", "bump")):
        return "height"
    if any(k in lb for k in ("emission", "emissive")):
        return "emission"
    return None


def extract_material_textures(obj) -> dict:
    """Return {role: bpy.types.Image} for all classified image texture nodes."""
    textures: dict = {}
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type != "TEX_IMAGE" or not node.image:
                continue
            label = node.label or node.name
            role = _classify(label)
            if role and role not in textures:
                textures[role] = node.image
            elif not role and "basecolor" not in textures:
                # First unclassified texture → assume base colour
                textures["basecolor"] = node.image
    return textures


def save_textures_to_disk(textures: dict, work_dir: str, asset_id: str) -> dict:
    """Save each image to {work_dir}/{asset_id}_{role}.png and return {role: path}."""
    os.makedirs(work_dir, exist_ok=True)
    paths: dict = {}
    for role, img in textures.items():
        dest = os.path.join(work_dir, f"{asset_id}_{role}.png")
        try:
            img_copy = img.copy()
            img_copy.filepath_raw = dest
            img_copy.file_format = "PNG"
            img_copy.save()
            bpy.data.images.remove(img_copy)
            paths[role] = dest
        except Exception as exc:
            print(f"[AssetForge] texture extractor: could not save {role}: {exc}")
    return paths
