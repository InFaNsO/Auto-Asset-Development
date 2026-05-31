"""Assembles the backend registry for real runs.

Phase 1: generation has TWO real backends (Copilot 3D automation + Tripo API); every
downstream stage uses the algorithmic placeholder from ``stubs`` until its real algo lands
in Phase 2+. This is the single swap point as backends mature (also referenced by the
Blender operators).
"""
from __future__ import annotations

from typing import Optional

from ..adapter import BackendRegistry
from .generation.copilot3d import Copilot3DBackend
from .generation.drivers import BrowserDriver
from .generation.tripo import HttpClient, TripoBackend
from .stubs import (
    RetopoStub, UVStub, BakeStub, TextureStub, RigStub, AnimateStub,
    LodStub, CollisionStub, ExportStub, ValidateStub,
)

_DOWNSTREAM = (RetopoStub, UVStub, BakeStub, TextureStub, RigStub,
               AnimateStub, LodStub, CollisionStub, ExportStub, ValidateStub)


def build_default_registry(
    *,
    copilot_driver: Optional[BrowserDriver] = None,
    tripo_http: Optional[HttpClient] = None,
) -> BackendRegistry:
    reg = BackendRegistry()
    # Stage 3 — two real generation backends in parallel (DEVELOPMENT_PLAN.md §2.5).
    reg.register(Copilot3DBackend(driver=copilot_driver))
    reg.register(TripoBackend(http_client=tripo_http))
    # Stages 4-13 — algorithmic placeholders for the vertical slice.
    for cls in _DOWNSTREAM:
        reg.register(cls())
    return reg
