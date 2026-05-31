"""Canonical humanoid skeleton — Mixamo bone naming + SMPL-X-compatible hierarchy.

Used by RigifyBackend to name rig bones and by the retargeter (Phase 6) to map any
source skeleton onto this canonical target (PROJECT_SPEC.md §5).

Bone placement is expressed as fractions of the mesh bounding box so
``place_for_mesh(obj)`` returns world-space positions without needing ML.
The fractions below are calibrated for a standing, arms-down humanoid figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BoneDef:
    name: str           # Mixamo name
    parent: Optional[str]
    # Position as (x, y, z) fraction of bounding box, origin = (0.5, 0.5, 0.0)
    # x: 0=left side, 0.5=centre, 1=right side
    # y: 0=front, 0.5=centre, 1=back
    # z: 0=feet, 1=top of head
    pos: tuple          # (x_frac, y_frac, z_frac)
    tail_z_offset: float = 0.06  # tail length as fraction of total height


# fmt: off
HUMANOID_BONES: tuple[BoneDef, ...] = (
    BoneDef("Hips",           None,          (0.50, 0.50, 0.52)),
    BoneDef("Spine",          "Hips",        (0.50, 0.50, 0.57)),
    BoneDef("Spine1",         "Spine",       (0.50, 0.50, 0.63)),
    BoneDef("Spine2",         "Spine1",      (0.50, 0.50, 0.68)),
    BoneDef("Neck",           "Spine2",      (0.50, 0.50, 0.80)),
    BoneDef("Head",           "Neck",        (0.50, 0.50, 0.88), tail_z_offset=0.10),
    # Left arm
    BoneDef("LeftShoulder",   "Spine2",      (0.62, 0.50, 0.74)),
    BoneDef("LeftArm",        "LeftShoulder",(0.70, 0.50, 0.72)),
    BoneDef("LeftForeArm",    "LeftArm",     (0.79, 0.50, 0.62)),
    BoneDef("LeftHand",       "LeftForeArm", (0.86, 0.50, 0.53), tail_z_offset=0.05),
    # Right arm (mirrored)
    BoneDef("RightShoulder",  "Spine2",      (0.38, 0.50, 0.74)),
    BoneDef("RightArm",       "RightShoulder",(0.30, 0.50, 0.72)),
    BoneDef("RightForeArm",   "RightArm",    (0.21, 0.50, 0.62)),
    BoneDef("RightHand",      "RightForeArm",(0.14, 0.50, 0.53), tail_z_offset=0.05),
    # Left leg
    BoneDef("LeftUpLeg",      "Hips",        (0.57, 0.50, 0.50)),
    BoneDef("LeftLeg",        "LeftUpLeg",   (0.57, 0.50, 0.27)),
    BoneDef("LeftFoot",       "LeftLeg",     (0.57, 0.50, 0.07)),
    BoneDef("LeftToeBase",    "LeftFoot",    (0.57, 0.35, 0.02), tail_z_offset=0.03),
    # Right leg (mirrored)
    BoneDef("RightUpLeg",     "Hips",        (0.43, 0.50, 0.50)),
    BoneDef("RightLeg",       "RightUpLeg",  (0.43, 0.50, 0.27)),
    BoneDef("RightFoot",      "RightLeg",    (0.43, 0.50, 0.07)),
    BoneDef("RightToeBase",   "RightFoot",   (0.43, 0.35, 0.02), tail_z_offset=0.03),
)
# fmt: on

BONE_BY_NAME: dict[str, BoneDef] = {b.name: b for b in HUMANOID_BONES}


def world_positions(obj) -> dict:
    """Return {bone_name: (head_x, head_y, head_z, tail_z)} in world space."""
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [v.x for v in bbox]; ys = [v.y for v in bbox]; zs = [v.z for v in bbox]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    dx = max_x - min_x or 1.0
    dy = max_y - min_y or 1.0
    dz = max_z - min_z or 1.0

    result = {}
    for bone in HUMANOID_BONES:
        fx, fy, fz = bone.pos
        hx = min_x + fx * dx
        hy = min_y + fy * dy
        hz = min_z + fz * dz
        tz = hz + bone.tail_z_offset * dz
        result[bone.name] = (hx, hy, hz, tz)
    return result
