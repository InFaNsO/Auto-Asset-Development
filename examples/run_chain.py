"""Run the AssetForge pipeline from plain Python (no Blender needed).

Examples
--------
# 1) Pure demo: stub backends, whole chain runs instantly
py -3.12 examples/run_chain.py

# 2) Real free generation via Copilot 3D (download a GLB first, see README)
py -3.12 examples/run_chain.py --image my.png --glb downloaded_model.glb

# 3) Real paid generation via Tripo (needs ASSETFORGE_TRIPO_API_KEY in env / .env)
py -3.12 examples/run_chain.py --image my.png --tripo
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assetforge.core.adapter import RunContext
from assetforge.core.asset_state import AssetState, SourceKind
from assetforge.core.backends.registry import build_default_registry
from assetforge.core.backends.stubs import build_stub_registry
from assetforge.core.pipeline import Mode, Pipeline
from assetforge.core.secrets import EnvSecretStore
from assetforge.core.stages import AssetType


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the AssetForge pipeline.")
    ap.add_argument("--image", help="input image path (for real generation)")
    ap.add_argument("--glb", help="a GLB you downloaded from Copilot 3D (manual free path)")
    ap.add_argument("--tripo", action="store_true", help="use the Tripo API backend")
    ap.add_argument("--type", default="static",
                    choices=[t.value for t in AssetType], help="asset type")
    args = ap.parse_args(argv)

    work = os.path.abspath("work")
    os.makedirs(work, exist_ok=True)
    ctx = RunContext(secrets=EnvSecretStore(), work_dir=work)
    params = {}

    if args.glb:
        registry = build_default_registry()
        ctx.user_choice["generate"] = "copilot3d"
        params["generate"] = {"downloaded_glb": os.path.abspath(args.glb)}
        source_ref = args.image or args.glb
        source_kind = SourceKind.IMAGE
    elif args.tripo:
        registry = build_default_registry()
        ctx.user_choice["generate"] = "tripo"
        source_ref = args.image or ""
        source_kind = SourceKind.IMAGE
        if not source_ref:
            ap.error("--tripo needs --image")
    else:
        # Pure demo: every stage stubbed, the chain just runs.
        registry = build_stub_registry()
        source_ref = args.image or "examples/input.png"
        source_kind = SourceKind.IMAGE

    state = AssetState(id="demo", source_kind=source_kind, source_ref=source_ref,
                       asset_type=AssetType(args.type))
    report = Pipeline(registry, mode=Mode.GUIDED).run(state, ctx, params=params)

    print("Run report:")
    print(report.summary())
    print(f"\nResult: {'OK' if report.ok else 'FAILED'}")
    print(f"Mesh artifact:     {state.artifacts.get('mesh')}")
    print(f"Exported artifact: {state.artifacts.get('exported')}")
    print(f"Provenance entries: {len(state.provenance)}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
