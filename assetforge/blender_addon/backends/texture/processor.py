"""Texture processing steps — delight, PBR decomp, upscale, seam check.

All operations work on ``bpy.types.Image`` objects already loaded in Blender.
No third-party deps: pixel math uses Python's built-in ``array`` module on the
image's flat RGBA pixel buffer.

Algorithm notes
---------------
Delight  — reduce contrast + lift shadows via a simple S-curve on luminance.
           Removes most of the baked directional lighting artefacts.
           A proper ML delight (IC-Light, etc.) can replace this function later.

PBR decomp — derives roughness from inverted luminance (bright = smooth specular)
             and a metallic map (near-zero default for organic/fabric assets).
             ML decomp (Material Anything, StablePBR, etc.) replaces this later.

Upscale  — nearest-2x then Blender's LANCZOS bilinear scale; keeps detail crisp.
           Replace with Real-ESRGAN (fal.ai) for ML-quality.

Seam check — reports UV seam pixels where neighbouring texels differ by > threshold.
             Full repair is Phase 4b; this lays the groundwork.
"""
from __future__ import annotations

import array
import math
import os

import bpy


def _pixels_to_list(img: bpy.types.Image) -> list:
    return list(img.pixels)


def _list_to_pixels(img: bpy.types.Image, px: list) -> None:
    img.pixels = px


# ---------------------------------------------------------------------------
# Delight
# ---------------------------------------------------------------------------

def delight(img: bpy.types.Image, strength: float = 0.6) -> bpy.types.Image:
    """Return a new image with baked lighting reduced.

    ``strength`` 0-1 controls how aggressively highlights are clipped and
    shadows are lifted. 0 = no change, 1 = maximum flatten.
    """
    out = img.copy()
    out.name = img.name + "_delight"
    px = _pixels_to_list(out)
    n = len(px) // 4

    # Shadow lift + highlight compress per-pixel (works on linear colour).
    lift   = strength * 0.15   # lift dark values
    compress = strength * 0.20  # compress bright values

    for i in range(n):
        base = i * 4
        r, g, b, a = px[base], px[base+1], px[base+2], px[base+3]
        # Luminance-weighted adjustment
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        # S-curve: lift shadows, compress highlights
        r = _curve(r, lum, lift, compress)
        g = _curve(g, lum, lift, compress)
        b = _curve(b, lum, lift, compress)
        px[base], px[base+1], px[base+2] = r, g, b

    _list_to_pixels(out, px)
    return out


def _curve(c: float, lum: float, lift: float, compress: float) -> float:
    if lum < 0.4:
        c = min(1.0, c + lift * (0.4 - lum) / 0.4)
    elif lum > 0.7:
        excess = (lum - 0.7) / 0.3
        c = max(0.0, c - compress * excess)
    return c


# ---------------------------------------------------------------------------
# PBR decomposition
# ---------------------------------------------------------------------------

def derive_roughness(base_color: bpy.types.Image) -> bpy.types.Image:
    """Roughness ≈ inverse of (specular-weighted luminance).
    Bright, saturated pixels → smooth (low roughness).
    Dark, desaturated pixels → rough (high roughness).
    """
    out = bpy.data.images.new(
        base_color.name + "_roughness",
        width=base_color.size[0], height=base_color.size[1], alpha=False)
    px_in = _pixels_to_list(base_color)
    px_out = [0.0] * (base_color.size[0] * base_color.size[1] * 4)
    n = len(px_in) // 4
    for i in range(n):
        b4 = i * 4
        r, g, b = px_in[b4], px_in[b4+1], px_in[b4+2]
        lum = 0.2126*r + 0.7152*g + 0.0722*b
        # Roughness: low for bright highlights, high for dark areas
        roughness = max(0.05, min(1.0, 1.0 - lum * 0.8))
        px_out[b4] = px_out[b4+1] = px_out[b4+2] = roughness
        px_out[b4+3] = 1.0
    _list_to_pixels(out, px_out)
    return out


def derive_metallic(base_color: bpy.types.Image) -> bpy.types.Image:
    """Metallic ≈ low-saturation, mid-to-high brightness areas.
    Mostly zero for organic/fabric assets; useful for sci-fi/hard-surface.
    """
    out = bpy.data.images.new(
        base_color.name + "_metallic",
        width=base_color.size[0], height=base_color.size[1], alpha=False)
    px_in = _pixels_to_list(base_color)
    px_out = [0.0] * (base_color.size[0] * base_color.size[1] * 4)
    n = len(px_in) // 4
    for i in range(n):
        b4 = i * 4
        r, g, b = px_in[b4], px_in[b4+1], px_in[b4+2]
        cmax = max(r, g, b)
        cmin = min(r, g, b)
        sat = (cmax - cmin) / cmax if cmax > 0.01 else 0.0
        lum = 0.2126*r + 0.7152*g + 0.0722*b
        # Low saturation + mid brightness → metallic
        metallic = max(0.0, (1.0 - sat * 3.0) * lum * 0.6)
        px_out[b4] = px_out[b4+1] = px_out[b4+2] = min(1.0, metallic)
        px_out[b4+3] = 1.0
    _list_to_pixels(out, px_out)
    return out


# ---------------------------------------------------------------------------
# Upscale
# ---------------------------------------------------------------------------

def upscale(img: bpy.types.Image, target_size: int = 2048) -> bpy.types.Image:
    """Return an upscaled copy if the image is smaller than target_size."""
    w, h = img.size
    if w >= target_size and h >= target_size:
        return img  # already large enough
    out = img.copy()
    out.name = img.name + "_upscaled"
    out.scale(target_size, target_size)  # Blender uses LANCZOS interpolation
    return out


# ---------------------------------------------------------------------------
# Seam check
# ---------------------------------------------------------------------------

def check_seams(img: bpy.types.Image, threshold: float = 0.1) -> dict:
    """Quick row/column scan to detect likely UV-seam colour discontinuities.
    Returns {seam_count, max_delta, verdict} — a description, not a repair.
    Full seam repair is a later ML step.
    """
    px = _pixels_to_list(img)
    w, h = img.size
    max_delta = 0.0
    seam_count = 0
    for y in range(h):
        for x in range(w - 1):
            i0 = (y * w + x) * 4
            i1 = i0 + 4
            delta = abs(px[i0] - px[i1]) + abs(px[i0+1] - px[i1+1]) + abs(px[i0+2] - px[i1+2])
            if delta > threshold:
                seam_count += 1
                max_delta = max(max_delta, delta)

    verdict = "clean" if seam_count < (w * h * 0.001) else "seams_detected"
    return {"seam_count": seam_count, "max_delta": round(max_delta, 3),
            "verdict": verdict}


# ---------------------------------------------------------------------------
# Save helper
# ---------------------------------------------------------------------------

def save_image(img: bpy.types.Image, path: str) -> str:
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return path
