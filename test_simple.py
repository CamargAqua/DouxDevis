#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("[TEST] Charger le site Render...")
    page.goto("https://douxdevis.onrender.com/", wait_until="networkidle")
    page.wait_for_timeout(2000)

    # Prendre screenshot
    page.screenshot(path="screenshot_site.png", full_page=True)
    print("[OK] Screenshot pris: screenshot_site.png")

    # Lister les inputs
    inputs = page.locator('input').all()
    print(f"\n[INFO] Nombre d'inputs trouves: {len(inputs)}")
    for i, inp in enumerate(inputs[:10]):
        name = inp.get_attribute('name') or 'N/A'
        type_val = inp.get_attribute('type') or 'text'
        print(f"  {i+1}. name={name} type={type_val}")

    # Verifier le titre
    title = page.title()
    print(f"\n[INFO] Titre page: {title}")

    # Verifier si le site est accessible
    if "DOUX" in page.content() or "Devis" in page.content():
        print("[SUCCESS] Site charge correctement!")
    else:
        print("[ERROR] Le site ne semble pas avoir charge le contenu attendu")

    browser.close()
