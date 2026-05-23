"""Drive Playwright through Argo UI + MinIO console, record a webm.

Prereqs:
  pip install playwright
  python -m playwright install chromium

Tunnels (run before invoking this script):
  ssh -fN -L 2746:localhost:2746 -L 9001:localhost:9001 julia@192.168.1.133
  # On the iMac side, kubectl port-forward into argo-server and minio.

Argo auth-mode must be "server" for the screencast to bypass token entry:
  kubectl -n argo patch deploy argo-server --type json -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--auth-mode=server"}]'

Usage (from repo root):
  python docs/dv2-multi-branch/demo_webui.capture.py

Then post-process:
  edge-tts --voice ru-RU-SvetlanaNeural --rate=+20% \\
    --file docs/dv2-multi-branch/demo_webui.narration.txt \\
    --write-media .demo_webui.narration.mp3
  ffmpeg -y -i docs/dv2-multi-branch/demo_webui_videos/page@*.webm \\
    -i .demo_webui.narration.mp3 \\
    -filter_complex "[0:v]fps=20[v]" -map "[v]" -map 1:a \\
    -c:v libx264 -preset slow -crf 23 -pix_fmt yuv420p \\
    -c:a aac -b:a 128k docs/dv2-multi-branch/demo_webui.mp4
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

from playwright.async_api import async_playwright

VIDEO_DIR = pathlib.Path(__file__).parent / "demo_webui_videos"
VIDEO_DIR.mkdir(exist_ok=True)


async def beat_argo(page) -> None:
    """~30s: Argo workflow archive + DAG of a completed dv2-refresh run."""
    await page.goto("https://localhost:2746/workflows/dv2", wait_until="domcontentloaded")
    for selector in (
        'button:has-text("Close")',
        '[aria-label="Close"]',
        'i.fa-times',
        'svg[class*="close"]',
        'text=×',
    ):
        try:
            await page.locator(selector).first.click(timeout=2000)
            await page.wait_for_timeout(500)
        except Exception:
            pass
    await page.evaluate(
        """() => {
            try {
                Object.keys(localStorage).filter(k => /first|modal|feedback|new/i.test(k))
                    .forEach(k => localStorage.removeItem(k));
            } catch (e) {}
            document.querySelectorAll('.argo-modal, [class*=modal], [class*=Modal]').forEach(el => {
                el.style.display = 'none';
            });
        }"""
    )
    await page.wait_for_timeout(2000)
    await page.wait_for_timeout(8000)
    try:
        await page.locator('a[href*="/workflows/dv2/dv2-refresh-"]').first.click(timeout=4000)
        await page.wait_for_timeout(12000)
    except Exception:
        await page.wait_for_timeout(12000)
    await page.wait_for_timeout(4000)


async def beat_minio(page) -> None:
    """~25s: MinIO console login + cold-tier bucket browser."""
    await page.goto("http://localhost:9001/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    await page.locator('input[name="accessKey"], input#accessKey').first.fill("dv2admin")
    await page.locator('input[name="secretKey"], input#secretKey').first.fill("dv2admin-demo")
    await page.wait_for_timeout(800)
    await page.locator('button[type="submit"]').first.click()
    await page.wait_for_timeout(5000)
    try:
        await page.goto("http://localhost:9001/browser/cold-tier", wait_until="domcontentloaded")
        await page.wait_for_timeout(10000)
    except Exception:
        await page.wait_for_timeout(10000)
    await page.wait_for_timeout(5000)


async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=True,
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1440, "height": 900},
        )
        page = await ctx.new_page()
        try:
            print("[1/2] Argo UI...", file=sys.stderr)
            await beat_argo(page)
            print("[2/2] MinIO console...", file=sys.stderr)
            await beat_minio(page)
        finally:
            await ctx.close()
            await browser.close()
    vids = sorted(VIDEO_DIR.glob("*.webm"))
    if vids:
        print(f"video: {vids[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
