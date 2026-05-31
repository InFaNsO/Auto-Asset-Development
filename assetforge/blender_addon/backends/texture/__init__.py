"""Stage 7 — Texture enhancement pipeline (bpy-based).

Runs the four-step enhancement chain from PROJECT_SPEC.md §6:
  base color (w/ baked light)
    → Delight        strip baked lighting (algorithmic colour normalisation)
    → PBR decomp     derive roughness / metallic / height maps
    → Upscale        super-resolution on low-texel-density images
    → Seam repair    detect + fix UV seam colour discontinuities

Each step is a separate module so ML models can be swapped in independently.
The backend itself (backend.py) orchestrates the chain.
"""
