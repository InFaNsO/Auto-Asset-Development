"""AssetForge — AI game-asset pipeline.

This package doubles as the Blender addon: ``bl_info`` lives here and ``register()`` lazily
imports the ``bpy`` layer, so installing the ``assetforge`` folder into Blender's addons
directory "just works" and ``assetforge`` is importable as a top-level package.

Crucially, importing this module does NOT import ``bpy`` — only calling :func:`register`
(which Blender does) does. That keeps :mod:`assetforge.core` runnable headless in CI.
"""

__version__ = "0.1.0"

bl_info = {
    "name": "AssetForge",
    "author": "AssetForge",
    "version": (0, 1, 0),
    "blender": (4, 1, 0),
    "location": "View3D > N-panel > AssetForge",
    "description": "AI game-asset pipeline: image/text/mesh -> game-ready export.",
    "category": "Pipeline",
}


def register() -> None:
    from .blender_addon import register as _register
    _register()


def unregister() -> None:
    from .blender_addon import unregister as _unregister
    _unregister()
