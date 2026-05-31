"""Stage 8 — Rigging backends (bpy-based).

Phase 5 implements:
  • RigifyBackend  — places a Mixamo-named humanoid metarig via bounding-box
                    heuristics, generates the rig, then auto-weights the mesh.
  • UniRigBackend  — calls the UniRig API (stub; endpoint verified when key added).

Canonical skeleton (PROJECT_SPEC.md §5): Mixamo bone-naming convention,
SMPL-X-compatible hierarchy, defined in skeleton.py.
"""
