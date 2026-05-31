"""Assembles the backend registry for real runs (CLI + tests, no bpy).

Phase 3: generation now has FOUR backends — Copilot 3D (free automation), Tripo, Meshy,
and Hunyuan3D (via fal.ai). Downstream stages remain algorithmic stubs until Phase 2+
bpy backends are wired in the Blender-specific registry (blender_addon/backends/registry).
"""
from __future__ import annotations

from typing import Optional

from ..adapter import BackendRegistry
from .generation.copilot3d import Copilot3DBackend
from .generation.drivers import BrowserDriver
from .generation.hunyuan import FalHttpClient, HunyuanBackend
from .generation.meshy import MeshyBackend, MeshyHttpClient
from .generation.tripo import HttpClient, TripoBackend
from .stubs import (
    AnimateStub, BakeStub, CollisionStub, ExportStub, LodStub,
    RetopoStub, RigStub, TextureStub, UVStub, ValidateStub,
)

_DOWNSTREAM = (RetopoStub, UVStub, BakeStub, TextureStub, RigStub,
               AnimateStub, LodStub, CollisionStub, ExportStub, ValidateStub)


def build_default_registry(
    *,
    copilot_driver: Optional[BrowserDriver] = None,
    tripo_http: Optional[HttpClient] = None,
    meshy_http: Optional[MeshyHttpClient] = None,
    fal_http: Optional[FalHttpClient] = None,
) -> BackendRegistry:
    reg = BackendRegistry()
    # Stage 3 — four generation backends; resolver picks by key availability + cost.
    reg.register(Copilot3DBackend(driver=copilot_driver))   # free automation
    reg.register(TripoBackend(http_client=tripo_http))       # paid, emits quads
    reg.register(MeshyBackend(http_client=meshy_http))       # paid, PBR textures
    reg.register(HunyuanBackend(http_client=fal_http))       # paid, high quality
    # Stages 4-13 — stubs; bpy geometry backends in blender_addon/backends/registry.
    for cls in _DOWNSTREAM:
        reg.register(cls())
    return reg
