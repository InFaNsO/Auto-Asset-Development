"""Phase 3-5 core tests: Meshy + Hunyuan backends, resolver with 4 backends."""
import os
import tempfile
import unittest

from assetforge.core.adapter import RunContext, RunMode
from assetforge.core.asset_state import AssetState, SourceKind, StageStatus
from assetforge.core.backends.generation.hunyuan import HunyuanBackend, FalError
from assetforge.core.backends.generation.meshy import MeshyBackend, MeshyError
from assetforge.core.backends.registry import build_default_registry
from assetforge.core.resolver import resolve
from assetforge.core.secrets import DictSecretStore
from assetforge.core.stages import AssetType

GOLDEN_GLB = os.path.join(os.path.dirname(__file__), "golden", "sample_input.glb")


def _img_state(work):
    img = os.path.join(work, "in.png")
    with open(img, "wb") as fh:
        fh.write(b"png")
    return AssetState(id="p3", source_kind=SourceKind.IMAGE, source_ref=img,
                      asset_type=AssetType.STATIC)


# --- Meshy fake HTTP ---

class _FakeMeshyHttp:
    def create_task(self, base_url, api_key, image_path, params):
        return {"result": "meshy-task-1"}

    def get_task(self, base_url, api_key, task_id):
        return {"status": "SUCCEEDED", "model_urls": {"glb": "https://x/m.glb"}}

    def download(self, url, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(b"glb")
        return dest


class TestMeshy(unittest.TestCase):
    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"meshy": "sk-m"}), work_dir=work)
            MeshyBackend(http_client=_FakeMeshyHttp(), poll_interval=0).run_api(state, {}, ctx)
            self.assertTrue(os.path.exists(state.artifacts["mesh"]))
            self.assertEqual(state.metadata["generation"]["backend"], "meshy")

    def test_no_key_raises(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            with self.assertRaises(MeshyError):
                MeshyBackend(http_client=_FakeMeshyHttp()).run_api(state, {}, ctx)

    def test_failed_status_raises(self):
        class _Fail(_FakeMeshyHttp):
            def get_task(self, *a, **k):
                return {"status": "FAILED"}
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"meshy": "sk"}), work_dir=work)
            with self.assertRaises(MeshyError):
                MeshyBackend(http_client=_Fail(), poll_interval=0).run_api(state, {}, ctx)


# --- Hunyuan / fal fake HTTP ---

class _FakeFalHttp:
    def submit(self, base_url, model, api_key, body):
        return {"request_id": "fal-req-1"}

    def get_status(self, base_url, model, api_key, req_id):
        return {"status": "COMPLETED"}

    def get_result(self, base_url, model, api_key, req_id):
        return {"glb": {"url": "https://x/h.glb"}}

    def download(self, url, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(b"glb")
        return dest


class TestHunyuan(unittest.TestCase):
    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"fal": "key-f"}), work_dir=work)
            HunyuanBackend(http_client=_FakeFalHttp(), poll_interval=0).run_api(state, {}, ctx)
            self.assertTrue(os.path.exists(state.artifacts["mesh"]))
            self.assertEqual(state.metadata["generation"]["backend"], "hunyuan3d")

    def test_no_key_raises(self):
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore(), work_dir=work)
            with self.assertRaises(FalError):
                HunyuanBackend(http_client=_FakeFalHttp()).run_api(state, {}, ctx)

    def test_alternate_result_schema(self):
        """fal result schemas vary; test the fallback paths."""
        class _AltResult(_FakeFalHttp):
            def get_result(self, *a, **k):
                return {"glb_url": "https://x/alt.glb"}
        with tempfile.TemporaryDirectory() as work:
            state = _img_state(work)
            ctx = RunContext(secrets=DictSecretStore({"fal": "k"}), work_dir=work)
            HunyuanBackend(http_client=_AltResult(), poll_interval=0).run_api(state, {}, ctx)
            self.assertIn("mesh", state.artifacts)


# --- Resolver with 4 generation backends ---

class TestResolverFourBackends(unittest.TestCase):
    def _reg(self, meshy_http=None, fal_http=None):
        return build_default_registry(
            meshy_http=meshy_http or _FakeMeshyHttp(),
            fal_http=fal_http or _FakeFalHttp(),
        )

    def test_no_keys_picks_copilot(self):
        ctx = RunContext(secrets=DictSecretStore())
        res = resolve("generate", self._reg(), ctx,
                      AssetState(id="x", asset_type=AssetType.STATIC))
        self.assertEqual(res.backend.name, "copilot3d")
        self.assertEqual(res.mode, RunMode.AUTOMATION)

    def test_user_picks_meshy(self):
        ctx = RunContext(secrets=DictSecretStore({"meshy": "sk"}),
                         user_choice={"generate": "meshy"})
        res = resolve("generate", self._reg(), ctx,
                      AssetState(id="x", asset_type=AssetType.STATIC))
        self.assertEqual(res.backend.name, "meshy")

    def test_user_picks_hunyuan(self):
        ctx = RunContext(secrets=DictSecretStore({"fal": "k"}),
                         user_choice={"generate": "hunyuan3d"})
        res = resolve("generate", self._reg(), ctx,
                      AssetState(id="x", asset_type=AssetType.STATIC))
        self.assertEqual(res.backend.name, "hunyuan3d")

    def test_four_backends_all_registered(self):
        reg = self._reg()
        names = {b.name for b in reg.for_stage("generate")}
        self.assertEqual(names, {"copilot3d", "tripo", "meshy", "hunyuan3d"})


if __name__ == "__main__":
    unittest.main()
