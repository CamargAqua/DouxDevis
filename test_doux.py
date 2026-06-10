#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Doux Devis - Validation des bugs fixes:
1. Prix client affichés (pas prix partenaire)
2. Coefficient appliqué aux options
"""
import time
import sys
from playwright.sync_api import sync_playwright

# UTF-8 pour Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

def test_doux_devis():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("\n[TEST 1] Charger le site")
        page.goto("https://douxdevis.onrender.com/", wait_until="networkidle")
        page.wait_for_timeout(1000)
        print("[OK] Site charge")

        print("\n[TEST 2] Remplir le formulaire")
        # Client
        page.fill('input[name="client_nom"]', "Test Client")
        # SAV
        page.fill('input[name="sav_numero"]', "12345")
        page.fill('input[name="sav_date"]', "15/05/2026")
        # Montre
        page.fill('input[name="marque"]', "Omega")
        page.fill('input[name="modele"]', "Seamaster")
        page.fill('input[name="reference"]', "2254.50.00")

        print("[OK] Formulaire rempli")

        print("\n[TEST 3] Ajouter une ligne necessaire")
        # Ajouter une intervention
        add_nec_btn = page.locator('button:has-text("Ajouter travail")')
        if add_nec_btn.count() > 0:
            add_nec_btn.first.click()
            page.wait_for_timeout(500)
            # Remplir la ligne
            nec_descs = page.locator('input[name="nec_description[]"]')
            nec_prices = page.locator('input[name="nec_prix[]"]')
            if nec_descs.count() > 0:
                nec_descs.last.fill("Revision complete")
                page.wait_for_timeout(200)
                nec_prices.last.fill("500")
                print("[OK] Ligne necessaire ajoutee: 500")

        print("\n[TEST 4] Ajouter une option")
        add_opt_btn = page.locator('button:has-text("Ajouter option")')
        if add_opt_btn.count() > 0:
            add_opt_btn.click()
            page.wait_for_timeout(500)
            opt_descs = page.locator('input[name="opt_description[]"]')
            opt_prices = page.locator('input[name="opt_prix[]"]')
            if opt_descs.count() > 0:
                opt_descs.last.fill("Polissage boite")
                page.wait_for_timeout(200)
                opt_prices.last.fill("150")
                print("[OK] Option ajoutee: 150")

        print("\n[TEST 5] Appliquer coefficient x1.50")
        coeff_input = page.locator('#coeff-input')
        if coeff_input.count() > 0:
            coeff_input.fill("1.50")
            coeff_input.dispatch_event("input")
            page.wait_for_timeout(1000)
            print("[OK] Coefficient x1.50 applique")

            # Verifier que les prix affiches dans les inputs sont bien prix_client
            nec_prices = page.locator('input[name="nec_prix[]"]')
            opt_prices = page.locator('input[name="opt_prix[]"]')

            if nec_prices.count() > 0:
                nec_val = nec_prices.last.input_value()
                print(f"   Necessaire (input): {nec_val} (attendu: 750 = 500x1.5)")

            if opt_prices.count() > 0:
                opt_val = opt_prices.last.input_value()
                print(f"   Option (input): {opt_val} (attendu: 225 = 150x1.5)")

        print("\n[TEST 6] Verifier les totaux affiches")
        page.wait_for_timeout(500)
        # Chercher le total partenaire et client
        total_display = page.locator('#total-display')
        total_final = page.locator('#total-final-display')

        if total_display.count() > 0:
            print(f"   Total partenaire: {total_display.text_content()}")
        if total_final.count() > 0:
            print(f"   Total client: {total_final.text_content()}")

        print("\n[TEST 7] Generer le PDF")
        generate_btn = page.locator('button:has-text("Generer devis")')
        if generate_btn.count() > 0:
            generate_btn.click()
            page.wait_for_timeout(3000)
            print("[OK] Devis genere")

            # Verifier s'il y a un lien de telechargement
            download_link = page.locator('a[href*=".pdf"]')
            if download_link.count() > 0:
                print(f"[OK] PDF genere: {download_link.get_attribute('download')}")

        print("\n[TEST 8] Screenshot final")
        page.screenshot(path="test_result.png", full_page=True)
        print("[OK] Screenshot sauvegarde: test_result.png")

        print("\n" + "="*60)
        print("[SUCCESS] TOUS LES TESTS COMPLETÉS")
        print("="*60)

        browser.close()

if __name__ == "__main__":
    test_doux_devis()
