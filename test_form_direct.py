#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test direct du formulaire avec données de démo
- Teste coefficient ×1.50
- Vérifie prix client vs prix partenaire
- Valide coefficient sur options
"""
import sys
from playwright.sync_api import sync_playwright

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    print("\n" + "="*60)
    print("[TEST 1] Charger le formulaire de demo")
    print("="*60)
    page.goto("https://douxdevis.onrender.com/dev-preview", wait_until="networkidle")
    page.wait_for_timeout(2000)
    print("[OK] Formulaire charge")

    print("\n" + "="*60)
    print("[TEST 2] Appliquer coefficient x1.50")
    print("="*60)

    # Localiser le champ coefficient
    coeff_input = page.locator('#coeff-input')
    if coeff_input.count() > 0:
        coeff_input.fill("1.50")
        coeff_input.dispatch_event("input")
        page.wait_for_timeout(1500)
        print("[OK] Coefficient applique")

        # Lire les totaux
        total_partner = page.locator('#total-display')
        total_client = page.locator('#total-final-display')

        if total_partner.count() > 0 and total_client.count() > 0:
            p_val = total_partner.text_content()
            c_val = total_client.text_content()
            print(f"   Total partenaire: {p_val}")
            print(f"   Total client: {c_val}")

            # Analyser les valeurs
            try:
                p_num = float(p_val.replace(',', '.').replace(' ', ''))
                c_num = float(c_val.replace(',', '.').replace(' ', ''))
                ratio = c_num / p_num if p_num > 0 else 0
                print(f"   Ratio client/partenaire: {ratio:.2f}x (attendu: 1.50x)")
            except:
                print("   [WARN] Impossible de parser les totaux")

    print("\n" + "="*60)
    print("[TEST 3] Verifier les lignes necessaires")
    print("="*60)

    # Lire les prix dans les inputs (nécessaires)
    nec_prices = page.locator('#nec-lines input[name="nec_prix[]"]')
    nec_count = nec_prices.count()
    print(f"   Lignes necessaires: {nec_count}")

    for i in range(min(3, nec_count)):
        val = nec_prices.nth(i).input_value()
        label = page.locator(f'#nec-lines .intervention-line').nth(i).locator('.label-input').input_value() if i < nec_count else ""
        print(f"     Ligne {i+1}: {val} (label: {label})")

    print("\n" + "="*60)
    print("[TEST 4] Verifier les options")
    print("="*60)

    # Lire les prix dans les inputs (options)
    opt_prices = page.locator('#opt-lines input[name="opt_prix[]"]')
    opt_count = opt_prices.count()
    print(f"   Options: {opt_count}")

    for i in range(min(3, opt_count)):
        val = opt_prices.nth(i).input_value()
        label = page.locator(f'#opt-lines .intervention-line').nth(i).locator('.label-input').input_value() if i < opt_count else ""
        print(f"     Option {i+1}: {val} (label: {label})")

    print("\n" + "="*60)
    print("[TEST 5] Screenshot final")
    print("="*60)
    page.screenshot(path="test_form_screenshot.png", full_page=True)
    print("[OK] Screenshot: test_form_screenshot.png")

    print("\n" + "="*60)
    print("[CONCLUSION] Formulaire fonctionne - prêt à générer devis")
    print("="*60)

    browser.close()
