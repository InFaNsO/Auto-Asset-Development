"""Browser drivers for the Copilot 3D generation backend.

Copilot 3D has no API — it's a web app. Rather than hardcode one automation method, the
backend takes a *driver*, so the same adapter works three ways (the user wants all of them
eventually):

  ManualDriver     — semi-automated: open the page, the human (or Claude) generates +
                     downloads the GLB, points us at it. Zero dependencies; works today.
                     This is "human handoff is a feature" (PROJECT_SPEC.md design #5).
  PlaywrightDriver — full automation: the addon scripts the browser itself. Unattended /
                     batch. Optional dependency (`pip install playwright`).
  McpAgentDriver   — Phase 7: Claude drives the browser via its own Chrome/computer-use
                     tools and hands back the GLB. Stubbed here as the interface.

All drivers implement :class:`BrowserDriver.generate(image_path, out_dir, params) -> glb`.
"""
from __future__ import annotations

import os
import shutil
from typing import Optional, Protocol

COPILOT_3D_URL = "https://copilot.microsoft.com/labs/experiments/copilot-3d"


class GenerationPending(Exception):
    """Raised when a manual step is required before generation can complete.

    The pipeline surfaces this as a normal stage failure with a clear instruction,
    rather than crashing the chain (DEVELOPMENT_PLAN.md §2.4).
    """


class BrowserDriver(Protocol):
    def generate(self, image_path: str, out_dir: str, params: dict) -> str:
        """Return the path to a downloaded .glb. May raise GenerationPending."""
        ...


def _copy_into(out_dir: str, glb_path: str, asset_id: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"{asset_id}_copilot3d.glb")
    shutil.copyfile(glb_path, dest)
    return dest


class ManualDriver:
    """Semi-automated. Two ways to supply the result:

    1. Pass ``params['downloaded_glb']`` = path to a GLB you already downloaded.
    2. Leave it unset: we open the Copilot 3D page (if ``params['open']`` is truthy) and
       raise :class:`GenerationPending` with instructions; re-run with the path set.
    """

    def __init__(self, opener=None) -> None:
        # opener injectable for tests; defaults to webbrowser.open at call time
        self._opener = opener

    def generate(self, image_path: str, out_dir: str, params: dict) -> str:
        supplied = params.get("downloaded_glb")
        if supplied:
            if not os.path.exists(supplied):
                raise GenerationPending(f"downloaded_glb not found: {supplied}")
            return _copy_into(out_dir, supplied, params.get("asset_id", "asset"))

        if params.get("open"):
            opener = self._opener
            if opener is None:
                import webbrowser
                opener = webbrowser.open
            opener(COPILOT_3D_URL)

        raise GenerationPending(
            "Copilot 3D is a manual step: open "
            f"{COPILOT_3D_URL}, upload your image, click Create, download the GLB, "
            "then re-run with params['generate']['downloaded_glb'] = <path to .glb>."
        )


class PlaywrightDriver:
    """Full browser automation. Optional dependency; import is deferred so the rest of the
    project works without Playwright installed.

    Uses a persistent browser context so a one-time Microsoft login is reused. The exact
    selectors are isolated here because they are the brittle part (DEVELOPMENT_PLAN.md §5
    risk: automation breaks on UI change) and will need maintenance against the live site.
    """

    def __init__(self, user_data_dir: str = ".assetforge/copilot_profile", headless: bool = False) -> None:
        self.user_data_dir = user_data_dir
        self.headless = headless

    def generate(self, image_path: str, out_dir: str, params: dict) -> str:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise GenerationPending(
                "PlaywrightDriver needs Playwright: `pip install playwright` then "
                "`playwright install chromium`. Or use ManualDriver."
            ) from exc

        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(self.user_data_dir, exist_ok=True)
        dest = os.path.join(out_dir, f"{params.get('asset_id', 'asset')}_copilot3d.glb")

        # NOTE: selectors below target the live Copilot 3D UI and must be verified/updated
        # against the current page. Kept in one place on purpose.
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.user_data_dir, headless=self.headless, accept_downloads=True)
            page = context.new_page()
            try:
                page.goto(COPILOT_3D_URL, wait_until="domcontentloaded")
                if "login" in page.url or page.get_by_text("Sign in").count():
                    raise GenerationPending(
                        "Not signed in. Run once with headless=False and sign into your "
                        "Microsoft account; the session is then reused.")
                page.set_input_files("input[type=file]", image_path)
                page.get_by_role("button", name="Create").click()
                with page.expect_download(timeout=180_000) as dl_info:
                    page.get_by_role("button", name="Download").click()
                dl_info.value.save_as(dest)
            finally:
                context.close()
        return dest


class McpAgentDriver:
    """Phase 7 placeholder: Claude drives Copilot 3D via its Chrome/computer-use tools and
    writes the GLB to a known path, then this driver returns it. Interface only for now."""

    def generate(self, image_path: str, out_dir: str, params: dict) -> str:
        raise GenerationPending(
            "McpAgentDriver is the Phase 7 path (Claude drives the browser). Not yet wired.")
