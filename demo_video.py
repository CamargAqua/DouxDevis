"""
demo_video.py — Enregistrement automatique démo DouxWeb.
Lance Flask, joue la démo en direct via Playwright, enregistre la vidéo.

Usage :
    python demo_video.py
"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

BASE_DIR  = Path(__file__).parent
PDF_PATH  = BASE_DIR / "Devis partenaire" / "DEVIS_PARTENAIRE_ROLEX_DATEJUST.pdf"
VIDEO_DIR = BASE_DIR / "demo_output"
APP_URL   = "http://127.0.0.1:5000"
SLOW_MO   = 400   # ms entre chaque action Playwright


def _start_flask() -> subprocess.Popen:
    env = {**os.environ, "FLASK_ENV": "production"}
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(BASE_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _wait_server(timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(APP_URL, timeout=2)
            return True
        except Exception:
            await asyncio.sleep(0.5)
    return False


async def run_demo() -> None:
    VIDEO_DIR.mkdir(exist_ok=True)

    print("Démarrage de Flask…")
    proc = _start_flask()

    if not await _wait_server():
        proc.terminate()
        print("Erreur : Flask n'a pas démarré dans les temps.")
        return

    print("Flask prêt. Lancement Playwright…")

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False,
                slow_mo=SLOW_MO,
                args=["--start-maximized"],
            )
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                record_video_dir=str(VIDEO_DIR),
                record_video_size={"width": 1280, "height": 800},
            )
            page = await ctx.new_page()

            # ── Scène 1 : Page d'accueil ──────────────────────────────────
            await page.goto(APP_URL)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.2)

            # Upload du devis partenaire Rolex
            await page.locator('input[type="file"]').set_input_files(str(PDF_PATH))
            await asyncio.sleep(0.8)

            # Clic "Extraire les informations"
            await page.locator("#submit-file").click()
            await asyncio.sleep(0.5)

            # ── Scène 2 : Attente extraction IA (≈15-30 sec) ──────────────
            print("Extraction en cours (peut prendre 20-30 sec)…")
            await page.wait_for_url(f"{APP_URL}/review", timeout=90_000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.5)

            # ── Scène 3 : Scroll rapide pour montrer le formulaire ────────
            for y in [300, 700, 1100, 0]:
                await page.evaluate(f"window.scrollTo({{top:{y}, behavior:'smooth'}})")
                await asyncio.sleep(0.8)

            # ── Scène 4 : Modifications en rafale ─────────────────────────

            async def js_focus_select(selector: str) -> str:
                return await page.evaluate(f"""
                    () => {{
                        const el = document.querySelector('{selector}');
                        if (!el) return '';
                        el.scrollIntoView({{block:'center'}});
                        el.focus(); el.select();
                        return el.value;
                    }}
                """)

            async def js_click(selector: str) -> None:
                await page.evaluate(f"""
                    () => {{
                        const el = document.querySelector('{selector}');
                        if (el) {{ el.scrollIntoView({{block:'center'}}); el.click(); }}
                    }}
                """)

            # 1. Nom client
            await js_focus_select('input[name="client_nom"]')
            await asyncio.sleep(0.4)
            await page.keyboard.press("Control+A")
            await page.keyboard.type("MARTIN JEAN-PIERRE", delay=45)
            await asyncio.sleep(0.6)

            # 2. Prix intervention 1
            val1 = await js_focus_select('input[name="nec_prix[]"]')
            await asyncio.sleep(0.4)
            try:
                new1 = f"{float(str(val1).replace(',', '.')) + 80:.2f}"
            except ValueError:
                new1 = "320.00"
            await page.keyboard.press("Control+A")
            await page.keyboard.type(new1, delay=45)
            await asyncio.sleep(0.6)

            # 3. Prix intervention 2 (deuxième input nec_prix[])
            val2 = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('input[name="nec_prix[]"]');
                    if (els.length < 2) return '';
                    els[1].scrollIntoView({block:'center'});
                    els[1].focus(); els[1].select();
                    return els[1].value;
                }
            """)
            await asyncio.sleep(0.4)
            try:
                new2 = f"{float(str(val2).replace(',', '.')) + 30:.2f}"
            except ValueError:
                new2 = "180.00"
            await page.keyboard.press("Control+A")
            await page.keyboard.type(new2, delay=45)
            await asyncio.sleep(0.6)

            # 4. Coefficient ×1,50
            await js_click('button[data-coeff="1.50"]')
            await asyncio.sleep(1.0)

            # ── Scène 5 : Génération ───────────────────────────────────────
            await page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button[type="submit"]');
                    const btn = btns[btns.length - 1];
                    if (btn) btn.scrollIntoView({block:'center'});
                }
            """)
            await asyncio.sleep(0.8)
            await page.evaluate("""
                () => {
                    const btns = document.querySelectorAll('button[type="submit"]');
                    btns[btns.length - 1].click();
                }
            """)

            # Attendre le rendu de done.html (reste sur /generate)
            await page.wait_for_selector(".done-hero", timeout=30_000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(1.2)

            # Scroll pour montrer les boutons de téléchargement
            await page.evaluate("window.scrollTo({top: 400, behavior: 'smooth'})")
            await asyncio.sleep(2)

            # Fin
            await ctx.close()
            await browser.close()

    finally:
        proc.terminate()
        proc.wait()

    videos = sorted(VIDEO_DIR.glob("*.webm"), key=lambda v: v.stat().st_mtime)
    if videos:
        print(f"\nVidéo enregistrée : {videos[-1]}")
    else:
        print(f"Aucune vidéo trouvée dans {VIDEO_DIR}")


if __name__ == "__main__":
    asyncio.run(run_demo())
