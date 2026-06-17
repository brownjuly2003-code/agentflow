"""Drive Playwright through dbt-docs (auto-generated), record a webm.

Prereqs:
  pip install playwright
  python -m playwright install chromium

Cluster side (iMac):
  bash infrastructure/dv2/dbt/run.sh   # builds the dbt-project ConfigMap
  kubectl apply -f infrastructure/dv2/dbt/dbt-docs-pod.yaml
  # Wait for "Serving docs at 8080" in `kubectl -n dv2 logs dbt-docs-serve`
  kubectl -n dv2 port-forward pod/dbt-docs-serve 8080:8080

Windows side:
  ssh -fN -L 8080:localhost:8080 <user>@<mac-host>

Then (from repo root):
  python docs/dv2-multi-branch/demo_dbt_docs.capture.py

Post-process (same edge-tts + ffmpeg pipeline as the cast):
  edge-tts --voice ru-RU-SvetlanaNeural --rate=+20% \\
    --file docs/dv2-multi-branch/demo_dbt_docs.narration.txt \\
    --write-media .demo_dbt_docs.narration.mp3
  # Stretch video to narration length:
  #   PTS = narration_dur / native_video_dur (~54.70 / 45.76 = 1.20)
  ffmpeg -y -i <captured.webm> -i .demo_dbt_docs.narration.mp3 \\
    -filter_complex "[0:v]setpts=1.20*PTS,fps=20[v]" -map "[v]" -map 1:a \\
    -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p \\
    -c:a aac -b:a 128k docs/dv2-multi-branch/demo_dbt_docs.mp4

Cleanup (revert cluster state):
  kubectl -n dv2 delete pod dbt-docs-serve --ignore-not-found
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys

from playwright.async_api import async_playwright

VIDEO_DIR = pathlib.Path(os.environ.get("TEMP", "/tmp")) / "dbt_capture_videos"
VIDEO_DIR.mkdir(exist_ok=True)
for stale in VIDEO_DIR.glob("*.webm"):
    stale.unlink()


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1440, "height": 900},
        )
        page = await ctx.new_page()
        try:
            await page.goto("http://localhost:8080/#!/overview", wait_until="domcontentloaded")
            await page.wait_for_timeout(6000)
            # Expand dv2_marts folder in the sidebar tree.
            for label in ("dv2_marts", "models", "marts"):
                try:
                    await page.locator(f'text={label}').first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
            await page.wait_for_timeout(2000)
            # Visit each mart model. dbt docs uses hashbang URLs:
            #   #!/model/<package>.<name>
            for model_id in (
                "model.dv2_marts.customer_360",
                "model.dv2_marts.branch_pnl",
                "model.dv2_marts.returns_velocity",
            ):
                await page.goto(
                    f"http://localhost:8080/#!/model/{model_id}",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(6000)
                # Try to surface the lineage panel.
                try:
                    await page.locator(
                        '[title*="lineage" i], [aria-label*="lineage" i]'
                    ).first.click(timeout=2500)
                    await page.wait_for_timeout(4000)
                except Exception:
                    pass
            print("OK", file=sys.stderr)
        finally:
            await ctx.close()
            await browser.close()
    vids = sorted(VIDEO_DIR.glob("*.webm"))
    if vids:
        print(vids[-1])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
