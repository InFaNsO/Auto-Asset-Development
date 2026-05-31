"""Stage 8 — UniRig API backend (stub — endpoint to be confirmed).

UniRig is an ML-based automatic rigging model that produces higher quality bone
placement than the heuristic RigifyBackend. It is not yet widely available via a
stable public API, so this backend is implemented as a wired stub:

  • is_available() returns False until a secret named 'unirig' is configured.
  • run_api() has the correct shape for when the endpoint stabilises.
  • The resolver will fall back to RigifyBackend automatically until this is available.

Candidate endpoints to watch:
  • Replicate:  https://replicate.com/models (search "UniRig")
  • fal.ai:     https://fal.ai/models (search "unirig")
  • HuggingFace Inference API (if weights are public)

When an endpoint is confirmed, update BASE_URL, _DONE, and the response parsing in
_poll_result() below, then set secret_name = 'unirig' in preferences.
"""
from __future__ import annotations

import os
from typing import Optional, Protocol

from assetforge.core.adapter import Backend, Capabilities, CostEstimate, RunContext, RunMode
from assetforge.core.asset_state import AssetState
from assetforge.core.secrets import get_api_key

BASE_URL = "https://api.unirig.example.com/v1"   # ← replace when confirmed
_DONE = "COMPLETED"


class UniRigHttpClient(Protocol):
    def submit(self, base_url: str, api_key: str, glb_path: str) -> dict: ...
    def get_result(self, base_url: str, api_key: str, task_id: str) -> dict: ...
    def download(self, url: str, dest: str) -> str: ...


class UniRigError(RuntimeError):
    pass


class UniRigBackend(Backend):
    name = "unirig"
    stage = "rig"
    secret_name = "unirig"

    def __init__(self, http_client: Optional[UniRigHttpClient] = None) -> None:
        self.http = http_client

    def supports_api(self) -> bool:
        return True

    def is_available(self, ctx: RunContext, mode: RunMode):
        key = get_api_key(ctx.secrets, self.secret_name)
        if not key:
            return False, "no UniRig API key — using auto_rig fallback"
        return True, "UniRig API key found"

    def capabilities(self) -> Capabilities:
        return Capabilities("rig", input_types=("mesh",), output_types=("skeleton",),
                            skeleton="mixamo")

    def cost_estimate(self, state: AssetState, params: dict) -> CostEstimate:
        return CostEstimate(seconds=90.0, credits=2.0)

    def run_api(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        api_key = get_api_key(ctx.secrets, self.secret_name)
        if not api_key or not self.http:
            raise UniRigError("UniRig API not configured")

        glb_path = state.artifacts.get("mesh", "")
        if not os.path.exists(str(glb_path)):
            raise UniRigError(f"mesh GLB not found at {glb_path}")

        submitted = self.http.submit(BASE_URL, api_key, str(glb_path))
        task_id = submitted.get("task_id") or submitted.get("request_id")
        if not task_id:
            raise UniRigError(f"no task_id in submit response: {submitted}")

        result = self._poll_result(api_key, task_id)
        rigged_url = result.get("rigged_glb_url") or result.get("model_url")
        if not rigged_url:
            raise UniRigError(f"no rigged GLB URL in result: {result}")

        dest = os.path.join(ctx.work_dir, f"{state.id}_unirig.glb")
        self.http.download(rigged_url, dest)

        state.artifacts["mesh"] = dest
        state.artifacts["skeleton"] = "mixamo"
        state.metadata.setdefault("rig", {}).update(
            {"backend": self.name, "task_id": task_id})
        return state

    def _poll_result(self, api_key: str, task_id: str) -> dict:
        # Placeholder polling — implement when endpoint is confirmed.
        raise UniRigError("UniRig polling not yet implemented (endpoint pending)")
