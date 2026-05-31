"""Phase 1 generation-backend tests: real adapters, no network/GPU.

Copilot 3D is tested through ManualDriver; Tripo through a fake HTTP client. The full-chain
slice test then runs the WHOLE pipeline with a real generation backend + algorithmic
downstream placeholders (DEVELOPMENT_PLAN.md §8.2: thin end-to-end thread).
"""
import os
import tempfile
import unittest

from assetforge.core.adapter import RunContext, RunMode
from assetforge.core.asset_state import AssetState, SourceKind, StageStatus
from assetforge.core.backends.generation.copilot3d import Copilot3DBackend
from assetforge.core.backends.generation.drivers import GenerationPending, ManualDriver
from assetforge.core.backends.generation.tripo import TripoBackend, TripoError
from assetforge.core.backends.registry import build_default_registry
from assetforge.core.pipeline import Mode, Pipeline
from assetforge.core.resolver import resolve
from assetforge.core.secrets import DictSecretStore
from assetforge.core.stages import AssetType

GOLDEN_GLB = os.path.join(os.path.dirname(__file__), "golden", "sample_input.glb")


class _FakeTripoHttp:
    """Simulates upload -> task -> poll(success) -> download without network."""

    def __init__(self):
        self.calls = []

    def upload_image(self, base_url, api_key, image_path):
        self.calls.append("upload")
        return {"image_token": "tok-123"}

    def post_json(self, url, api_key, body):
        self.calls.append("create")
        assert body["type"] == "image_to_model"
        assert body["file"]["file_token"] == "tok-123"
        return {"task_id": "task-abc"}

    def get_json(self, url, api_key):
        self.calls.append("poll")
        return {"status": "success", "output": {"pbr_model": "https://x/model.glb"}}

    def download(self, url, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(b"glb")
        return dest


def _img_state(work):
    img = os.path.join(work, "in.png")
    with open(img, "wb") as fh:
        fh.write(b"png")
    return AssetState(id="g", source_kind=SourceKind.IMAGE, source_ref=img,
                      asset_type=AssetType.STATIC)


class TestCopilot3D(unittest.TestCase):
    def test_manual_driver_with_supplied_glb(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            backend = Copilot3DBackend(driver=ManualDriver())
            backend.run_automation(state, {"downloaded_glb": GOLDEN_GLB}, ctx)
            self.assertTrue(state.artifacts["mesh"].endswith("_copilot3d.glb"))
            self.assertTrue(os.path.exists(state.artifacts["mesh"]))

    def test_manual_driver_without_glb_raises_pending(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            backend = Copilot3DBackend(driver=ManualDriver())
            with self.assertRaises(GenerationPending):
                backend.run_automation(state, {}, ctx)

    def test_manual_driver_opens_url_when_requested(self):
        opened = []
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            backend = Copilot3DBackend(driver=ManualDriver(opener=opened.append))
            with self.assertRaises(GenerationPending):
                backend.run_automation(state, {"open": True}, ctx)
            self.assertEqual(len(opened), 1)
            self.assertIn("copilot", opened[0])


class TestTripo(unittest.TestCase):
    def test_run_api_full_flow_with_fake_http(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"tripo": "sk-test"}), work_dir=work)
            http = _FakeTripoHttp()
            backend = TripoBackend(http_client=http, poll_interval=0)
            backend.run_api(state, {}, ctx)
            self.assertTrue(os.path.exists(state.artifacts["mesh"]))
            self.assertEqual(state.metadata["generation"]["task_id"], "task-abc")
            self.assertEqual(http.calls, ["upload", "create", "poll"])

    def test_run_api_without_key_errors(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            with self.assertRaises(TripoError):
                TripoBackend(http_client=_FakeTripoHttp()).run_api(state, {}, ctx)

    def test_failed_status_raises(self):
        class _Fail(_FakeTripoHttp):
            def get_json(self, url, api_key):
                return {"status": "failed"}
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"tripo": "sk"}), work_dir=work)
            with self.assertRaises(TripoError):
                TripoBackend(http_client=_Fail(), poll_interval=0).run_api(state, {}, ctx)


class TestResolverWithRealBackends(unittest.TestCase):
    def test_no_key_picks_copilot_automation(self):
        reg = build_default_registry()
        ctx = RunContext(secrets=DictSecretStore())
        res = resolve("generate", reg, ctx, AssetState(id="x", asset_type=AssetType.STATIC))
        self.assertEqual(res.backend.name, "copilot3d")
        self.assertEqual(res.mode, RunMode.AUTOMATION)

    def test_user_can_choose_tripo_with_key(self):
        reg = build_default_registry(tripo_http=_FakeTripoHttp())
        ctx = RunContext(secrets=DictSecretStore({"tripo": "sk"}),
                         user_choice={"generate": "tripo"})
        res = resolve("generate", reg, ctx, AssetState(id="x", asset_type=AssetType.STATIC))
        self.assertEqual(res.backend.name, "tripo")
        self.assertEqual(res.mode, RunMode.API)


class TestVerticalSlice(unittest.TestCase):
    """The whole chain with a REAL generation backend + algo downstream placeholders."""

    def test_chain_with_copilot_manual_generation(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(
                secrets=DictSecretStore(),
                work_dir=work,
                user_choice={"generate": "copilot3d"},
            )
            reg = build_default_registry()
            report = Pipeline(reg, mode=Mode.GUIDED).run(
                state, ctx, params={"generate": {"downloaded_glb": GOLDEN_GLB}})
            self.assertTrue(report.ok, "\n" + report.summary())
            self.assertEqual(state.status("export"), StageStatus.DONE)
            self.assertTrue(os.path.exists(state.artifacts["mesh"]))

    def test_chain_with_tripo_generation(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(
                secrets=DictSecretStore({"tripo": "sk"}),
                work_dir=work,
                user_choice={"generate": "tripo"},
            )
            reg = build_default_registry(tripo_http=_FakeTripoHttp())
            report = Pipeline(reg, mode=Mode.GUIDED).run(state, ctx)
            self.assertTrue(report.ok, "\n" + report.summary())
            self.assertEqual(state.status("export"), StageStatus.DONE)


if __name__ == "__main__":
    unittest.main()
