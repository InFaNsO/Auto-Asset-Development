"""Stage 3 — Hunyuan3D via fal.ai (image-to-3D, API-only on Windows).

Hunyuan3D needs 24 GB VRAM + Linux for local inference, so on this machine (RTX 4080,
Windows) we run it through fal.ai which hosts the model.

fal.ai queue flow  (base https://queue.fal.run, Key auth):
    POST /{model}                 {image_url}          -> {request_id}
    GET  /{model}/requests/{id}/status                 -> {status}
    GET  /{model}/requests/{id}                        -> result
    result.glb.url  (or result[0].glb.url)             -> download

Verify the exact model slug and output schema at https://fal.ai/models when
you add a live fal key — fal model slugs can change between versions.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Optional, Protocol

from ...adapter import Backend, Capabilities, CostEstimate, RunContext, RunMode
from ...asset_state import AssetState
from ...secrets import get_api_key

_FAL_BASE = "https://queue.fal.run"
_MODEL = "fal-ai/hunyuan3d-2"     # verify at fal.ai/models
_DONE = "COMPLETED"
_FAILED = {"FAILED", "CANCELLED"}


class FalHttpClient(Protocol):
    def submit(self, base_url: str, model: str, api_key: str, body: dict) -> dict: ...
    def get_status(self, base_url: str, model: str, api_key: str, req_id: str) -> dict: ...
    def get_result(self, base_url: str, model: str, api_key: str, req_id: str) -> dict: ...
    def download(self, url: str, dest: str) -> str: ...


class FalError(RuntimeError):
    pass


class UrllibFalClient:
    """stdlib-only fal.ai client — no extra dependencies."""

    def _req(self, url: str, api_key: str, body: Optional[dict] = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data,
                                     method="POST" if data else "GET")
        req.add_header("Authorization", f"Key {api_key}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def submit(self, base_url, model, api_key, body):
        return self._req(f"{base_url}/{model}", api_key, body)

    def get_status(self, base_url, model, api_key, req_id):
        return self._req(f"{base_url}/{model}/requests/{req_id}/status", api_key)

    def get_result(self, base_url, model, api_key, req_id):
        return self._req(f"{base_url}/{model}/requests/{req_id}", api_key)

    def download(self, url, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        return dest


def _glb_url_from_result(result: dict) -> Optional[str]:
    """fal result schemas vary; try common paths."""
    # Direct: {"glb": {"url": "..."}}
    glb = result.get("glb")
    if isinstance(glb, dict):
        return glb.get("url")
    # List: [{"glb": {"url": "..."}}]
    if isinstance(result, list) and result:
        return _glb_url_from_result(result[0])
    # Flat: {"glb_url": "..."}
    return result.get("glb_url") or result.get("model_url")


class HunyuanBackend(Backend):
    name = "hunyuan3d"
    stage = "generate"
    secret_name = "fal"

    def __init__(self, http_client: Optional[FalHttpClient] = None,
                 poll_interval: float = 5.0, timeout_s: float = 600.0) -> None:
        self.http = http_client or UrllibFalClient()
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    def supports_api(self) -> bool:
        return True

    def supports_local(self) -> bool:
        return False  # needs 24 GB VRAM + Linux

    def capabilities(self) -> Capabilities:
        return Capabilities("generate", input_types=("image",),
                            output_types=("mesh",), emits_quads=False)

    def cost_estimate(self, state: AssetState, params: dict) -> CostEstimate:
        return CostEstimate(seconds=120.0, credits=3.0)

    def run_api(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        api_key = get_api_key(ctx.secrets, self.secret_name)
        if not api_key:
            raise FalError("no fal.ai API key configured")

        body = {"image_url": state.source_ref}
        body.update(params.get("hunyuan3d", {}))

        submitted = self.http.submit(_FAL_BASE, _MODEL, api_key, body)
        req_id = submitted.get("request_id")
        if not req_id:
            raise FalError(f"fal submit returned no request_id: {submitted}")

        glb_url = self._poll(api_key, req_id)
        dest = os.path.join(ctx.work_dir, f"{state.id}_hunyuan.glb")
        self.http.download(glb_url, dest)

        state.artifacts["mesh"] = dest
        state.metadata.setdefault("generation", {}).update(
            {"backend": self.name, "request_id": req_id})
        return state

    def _poll(self, api_key: str, req_id: str) -> str:
        deadline = time.monotonic() + self.timeout_s
        while True:
            status_data = self.http.get_status(_FAL_BASE, _MODEL, api_key, req_id)
            status = status_data.get("status", "")
            if status == _DONE:
                result = self.http.get_result(_FAL_BASE, _MODEL, api_key, req_id)
                url = _glb_url_from_result(result)
                if not url:
                    raise FalError(f"COMPLETED but no GLB URL in result: {result}")
                return url
            if status in _FAILED:
                raise FalError(f"fal request {req_id} {status}")
            if time.monotonic() > deadline:
                raise FalError(f"fal request {req_id} timed out (status={status})")
            time.sleep(self.poll_interval)
