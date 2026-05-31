"""Stage 7 — TextureEnhanceBackend: orchestrates the full enhancement pipeline."""
from __future__ import annotations

import os

import bpy

from assetforge.core.adapter import Backend, Capabilities, RunContext, RunMode
from assetforge.core.asset_state import AssetState

from ..geometry.utils import ensure_object
from .extractor import extract_material_textures, save_textures_to_disk
from .processor import (
    check_seams, delight, derive_metallic, derive_roughness, save_image, upscale,
)


class TextureEnhanceBackend(Backend):
    name = "texture_enhance"
    stage = "texture"

    def supports_local(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("texture", input_types=("mesh",), output_types=("textures",))

    def run_local(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        obj = ensure_object(state)
        if obj is None:
            print("[AssetForge] texture: no mesh — skipping")
            state.artifacts["textures"] = {}
            return state

        raw_textures = extract_material_textures(obj)
        if not raw_textures:
            print("[AssetForge] texture: no textures in material — skipping")
            state.artifacts["textures"] = {}
            return state

        enhanced: dict = {}
        os.makedirs(ctx.work_dir, exist_ok=True)

        base_img = raw_textures.get("basecolor")
        if base_img:
            # 1. Delight
            strength = float(params.get("delight_strength", 0.6))
            delighted = delight(base_img, strength=strength)
            print(f"[AssetForge] texture: delight strength={strength}")

            # 2. Upscale
            target_size = int(params.get("upscale_size", 2048))
            upscaled = upscale(delighted, target_size=target_size)
            if upscaled is not delighted:
                bpy.data.images.remove(delighted)
                delighted = upscaled
            print(f"[AssetForge] texture: upscaled to {target_size}px")

            # 3. PBR decomp
            roughness_img = derive_roughness(delighted)
            metallic_img = derive_metallic(delighted)
            print("[AssetForge] texture: PBR decomp done")

            # 4. Seam check
            seam_info = check_seams(delighted)
            state.metadata.setdefault("texture", {})["seam_check"] = seam_info
            print(f"[AssetForge] texture: seam check → {seam_info['verdict']}")

            # Save all maps
            for role, img in [("basecolor", delighted), ("roughness", roughness_img),
                               ("metallic", metallic_img)]:
                path = os.path.join(ctx.work_dir, f"{state.id}_{role}_enhanced.png")
                save_image(img, path)
                enhanced[role] = path

            # Reuse baked normal if available
            if state.artifacts.get("bakes", {}).get("normal"):
                enhanced["normal"] = state.artifacts["bakes"]["normal"]

            # Clean up intermediate Blender images
            for img in [delighted, roughness_img, metallic_img]:
                if img.name in bpy.data.images:
                    bpy.data.images.remove(img)

            # Update the material with the enhanced base colour
            _apply_enhanced_texture(obj, enhanced.get("basecolor"),
                                    enhanced.get("roughness"),
                                    enhanced.get("metallic"))

        state.artifacts["textures"] = enhanced
        state.artifacts["blender_object"] = obj.name
        return state


def _apply_enhanced_texture(obj, basecolor_path, roughness_path, metallic_path) -> None:
    """Hot-swap material textures with the enhanced versions."""
    for slot in obj.material_slots:
        mat = slot.material
        if not mat or not mat.use_nodes:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            continue

        def _load_and_wire(path, socket_name, colorspace="Non-Color"):
            if not path or not os.path.exists(path):
                return
            img = bpy.data.images.load(path, check_existing=False)
            img.colorspace_settings.name = colorspace
            node = mat.node_tree.nodes.new("ShaderNodeTexImage")
            node.image = img
            node.label = socket_name
            mat.node_tree.links.new(node.outputs["Color"],
                                     bsdf.inputs[socket_name])

        if basecolor_path:
            _load_and_wire(basecolor_path, "Base Color", colorspace="sRGB")
        if roughness_path:
            _load_and_wire(roughness_path, "Roughness")
        if metallic_path:
            _load_and_wire(metallic_path, "Metallic")
