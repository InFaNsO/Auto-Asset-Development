"""Tripo image-to-3D generation backend (paid REST API).

Flow (Tripo v2 OpenAPI, base https://api.tripo3d.ai/v2/openapi, Bearer auth):
    1. POST /upload (multipart 'file')      -> data.image_token
    2. POST /task   {type: image_to_model,  -> data.task_id
                     file:{type, file_token}}
    3. GET  /task/{task_id} (poll)          -> data.status in
                                               queued|running|success|failed
       on success: data.output.pbr_model (or .model) = GLB URL
    4. download the GLB

The HTTP layer is injected (:class:`HttpClient`) so the pipeline integration is unit-
tested with a fake, and the real network/endpoints live in one correctable place
(:class:`UrllibHttpClient`). Verify field names against https://platform.tripo3d.ai/docs
when you add a live key — Tripo has versioned the schema.
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

BASE_URL = "https://api.tripo3d.ai/v2/openapi"
_DONE = "success"
_FAILED = {"failed", "cancelled", "expired", "banned", "unknown"}


class HttpClient(Protocol):
    def upload_image(self, base_url: str, api_key: str, image_path: str) -> dict: ...
    def post_json(self, url: str, api_key: str, body: dict) -> dict: ...
    def get_json(self, url: str, api_key: str) -> dict: ...
    def download(self, url: str, dest: str) -> str: ...


class TripoError(RuntimeError):
    pass


class UrllibHttpClient:
    """Real HTTP via stdlib urllib (no third-party dependency)."""

    def _read(self, req: urllib.request.Request) -> dict:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("code", 0) != 0:
            raise TripoError(f"Tripo API error: {payload}")
        return payload.get("data", {})

    def upload_image(self, base_url: str, api_key: str, image_path: str) -> dict:
        # multipart/form-data with a single 'file' part, built by hand to avoid deps.
        boundary = "----assetforgeTripoBoundary"
        with open(image_path, "rb") as fh:
            content = fh.read()
        filename = os.path.basename(image_path)
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{base_url}/upload", data=body, method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        return self._read(req)

    def post_json(self, url: str, api_key: str, body: dict) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        return self._read(req)

    def get_json(self, url: str, api_key: str) -> dict:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        return self._read(req)

    def download(self, url: str, dest: str) -> str:
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        return dest


class TripoBackend(Backend):
    name = "tripo"
    stage = "generate"
    secret_name = "tripo"

    def __init__(self, http_client: Optional[HttpClient] = None,
                 poll_interval: float = 2.0, timeout_s: float = 300.0) -> None:
        self.http = http_client or UrllibHttpClient()
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s

    def supports_api(self) -> bool:
        return True

    def capabilities(self) -> Capabilities:
        return Capabilities("generate", input_types=("image", "text"),
                            output_types=("mesh",), emits_quads=True)

    def cost_estimate(self, state: AssetState, params: dict) -> CostEstimate:
        return CostEstimate(seconds=40.0, credits=5.0)

    def run_api(self, state: AssetState, params: dict, ctx: RunContext) -> AssetState:
        api_key = get_api_key(ctx.secrets, self.secret_name)
        if not api_key:
            raise TripoError("no Tripo API key configured")

        upload = self.http.upload_image(BASE_URL, api_key, state.source_ref)
        image_token = upload.get("image_token") or upload.get("file_token")
        if not image_token:
            raise TripoError(f"upload returned no token: {upload}")

        task_body = {
            "type": "image_to_model",
            "file": {"type": "png", "file_token": image_token},
        }
        task_body.update(params.get("tripo", {}))   # texture_quality, face_limit, etc.
        created = self.http.post_json(f"{BASE_URL}/task", api_key, task_body)
        task_id = created.get("task_id")
        if not task_id:
            raise TripoError(f"task creation returned no task_id: {created}")

        glb_url = self._poll_for_model(api_key, task_id)
        dest = os.path.join(ctx.work_dir, f"{state.id}_tripo.glb")
        self.http.download(glb_url, dest)

        state.artifacts["mesh"] = dest
        gen = state.metadata.setdefault("generation", {})
        gen["backend"] = self.name
        gen["task_id"] = task_id
        return state

    def _poll_for_model(self, api_key: str, task_id: str) -> str:
        deadline = time.monotonic() + self.timeout_s
        while True:
            data = self.http.get_json(f"{BASE_URL}/task/{task_id}", api_key)
            status = data.get("status")
            if status == _DONE:
                output = data.get("output", {})
                url = output.get("pbr_model") or output.get("model")
                if not url:
                    raise TripoError(f"task finished but no model URL: {output}")
                return url
            if status in _FAILED:
                raise TripoError(f"Tripo task {task_id} failed: status={status}")
            if time.monotonic() > deadline:
                raise TripoError(f"Tripo task {task_id} timed out (last status={status})")
            time.sleep(self.poll_interval)
