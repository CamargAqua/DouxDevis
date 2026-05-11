"""
Démo terminal — DOUX Joaillier
Lance : python demo.py
"""
from __future__ import annotations

import os
import sys
import time
import random
from datetime import datetime

# Active les couleurs ANSI et UTF-8 sous Windows
if os.name == "nt":
    os.system("")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ───────────────────────── Palette DOUX ─────────────────────────
GOLD     = "\033[38;2;184;150;46m"
GOLD_LT  = "\033[38;2;212;184;106m"
INK      = "\033[38;2;26;24;20m"
SOFT     = "\033[38;2;158;155;150m"
MID      = "\033[38;2;107;103;96m"
CREAM    = "\033[48;2;247;245;240m"
WHITE    = "\033[97m"
GREEN    = "\033[38;2;46;125;75m"
RED      = "\033[38;2;138;26;20m"
BOLD     = "\033[1m"
DIM      = "\033[2m"
ITALIC   = "\033[3m"
RESET    = "\033[0m"
CLEAR    = "\033[2J\033[H"

# ───────────────────────── Utils visuels ────────────────────────
WIDTH = 78


def cls():
    print(CLEAR, end="")


def hr(char: str = "─", color: str = SOFT):
    print(f"{color}{char * WIDTH}{RESET}")


def center(text: str, color: str = "") -> str:
    pad = max(0, (WIDTH - _visible_len(text)) // 2)
    return f"{' ' * pad}{color}{text}{RESET}"


def _visible_len(s: str) -> int:
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def topbar():
    bar = f"{GOLD}D O U X{RESET}  {DIM}{SOFT}JOAILLIER · AVIGNON{RESET}"
    right = f"{DIM}{SOFT}Espace devis interne{RESET}"
    visible = _visible_len(bar) + _visible_len(right)
    spaces = " " * max(2, WIDTH - visible)
    print(f"{bar}{spaces}{right}")
    hr()


def card_top(title: str):
    print()
    print(f"{GOLD}┌{'─' * (WIDTH - 2)}┐{RESET}")
    pad = WIDTH - 4 - len(title)
    print(f"{GOLD}│ {BOLD}{INK}{title}{RESET}{' ' * pad} {GOLD}│{RESET}")
    print(f"{GOLD}├{'─' * (WIDTH - 2)}┤{RESET}")


def card_line(text: str = ""):
    raw_len = _visible_len(text)
    pad = max(0, WIDTH - 4 - raw_len)
    print(f"{GOLD}│{RESET} {text}{' ' * pad} {GOLD}│{RESET}")


def card_bottom():
    print(f"{GOLD}└{'─' * (WIDTH - 2)}┘{RESET}")


def slow_print(text: str, delay: float = 0.012):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def spinner(label: str, duration: float = 2.0, ok_text: str = "OK"):
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    start = time.time()
    i = 0
    while time.time() - start < duration:
        sys.stdout.write(f"\r  {GOLD}{frames[i % len(frames)]}{RESET}  {label}   ")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1
    sys.stdout.write(f"\r  {GREEN}✓{RESET}  {label}  {DIM}{SOFT}{ok_text}{RESET}{' ' * 20}\n")


def progress_bar(label: str, duration: float = 2.5, steps: int = 32):
    for s in range(steps + 1):
        pct = int(100 * s / steps)
        filled = "█" * s
        empty = "░" * (steps - s)
        sys.stdout.write(f"\r  {label}  {GOLD}{filled}{SOFT}{empty}{RESET}  {pct:3d}%")
        sys.stdout.flush()
        time.sleep(duration / steps)
    print()


def ask(prompt: str, default: str = "") -> str:
    suffix = f" {DIM}[{default}]{RESET}" if default else ""
    val = input(f"{GOLD}→{RESET} {prompt}{suffix} : ").strip()
    return val or default


def pause(msg: str = "Appuyez sur Entrée pour continuer"):
    input(f"\n{DIM}{SOFT}{msg}{RESET}")


# ───────────────────────── Données démo ─────────────────────────
PARTNERS = [
    {
        "id": "1",
        "file": "ROLEX_SUBMARINER_SAV_2026.pdf",
        "size": "1.2 Mo",
        "brand": "Rolex",
        "data": {
            "marque": "Rolex",
            "client_nom": "M. DUPONT",
            "sav_numero": "SAV-2026-0418",
            "sav_date": "11/05/2026",
            "modele": "Submariner Date",
            "reference": "126610LN",
            "numero_serie": "M9F4B729",
            "metal": "Acier Oystersteel",
            "taille": "41 mm",
            "etat": [
                "Rayures sur la lunette céramique",
                "Joint de couronne usé",
                "Lubrification mouvement nécessaire",
            ],
            "service": "Service complet : démontage, nettoyage, lubrification, contrôle d'étanchéité 30 ATM, polissage boîte et bracelet, remplacement joints.",
            "necessaires": [
                ("Service complet mouvement calibre 3235", 680.00),
                ("Remplacement joints étanchéité", 95.00),
                ("Polissage boîte + bracelet", 180.00),
            ],
            "optionnelles": [
                ("Remplacement lunette céramique", 450.00),
            ],
            "delai": "6 à 8 semaines",
        },
    },
    {
        "id": "2",
        "file": "TAG_HEUER_CARRERA_2026.pdf",
        "size": "840 Ko",
        "brand": "Tag Heuer",
        "data": {
            "marque": "Tag Heuer",
            "client_nom": "Mme MARTIN",
            "sav_numero": "TH-25118",
            "sav_date": "11/05/2026",
            "modele": "Carrera Chronograph",
            "reference": "CBN2A1B",
            "numero_serie": "RDH4221",
            "metal": "Acier",
            "taille": "44 mm",
            "etat": [
                "Chronographe ne se réinitialise pas",
                "Verre rayé en façade",
            ],
            "service": "Révision mouvement Calibre Heuer 02, remplacement verre saphir, contrôle étanchéité.",
            "necessaires": [
                ("Révision complète Calibre Heuer 02", 520.00),
                ("Remplacement verre saphir bombé", 220.00),
            ],
            "optionnelles": [
                ("Polissage boîte", 110.00),
            ],
            "delai": "4 à 6 semaines",
        },
    },
    {
        "id": "3",
        "file": "CHANEL_J12_2026.pdf",
        "size": "1.5 Mo",
        "brand": "Chanel",
        "data": {
            "marque": "Chanel",
            "client_nom": "Mme LEROY",
            "sav_numero": "CH-2026-0772",
            "sav_date": "11/05/2026",
            "modele": "J12 Automatique",
            "reference": "H5697",
            "numero_serie": "ZL.95014",
            "metal": "Céramique blanche",
            "taille": "38 mm",
            "etat": [
                "Microcoupure secondes",
                "Bracelet céramique : maillon ébréché",
            ],
            "service": "Service mouvement Calibre 12.1, remplacement maillon céramique, contrôle étanchéité 200 m.",
            "necessaires": [
                ("Service mouvement Calibre 12.1", 590.00),
                ("Remplacement maillon céramique blanche", 240.00),
                ("Contrôle étanchéité", 60.00),
            ],
            "optionnelles": [],
            "delai": "5 à 7 semaines",
        },
    },
]


# ───────────────────────── Écrans ───────────────────────────────
def screen_intro():
    cls()
    topbar()
    print()
    print(center(f"{GOLD}╔═════════════════════════════════════════════════════╗{RESET}"))
    print(center(f"{GOLD}║{RESET}                                                     {GOLD}║{RESET}"))
    print(center(f"{GOLD}║{RESET}        {BOLD}{INK}D  O  U  X{RESET}   {DIM}JOAILLIER{RESET}                  {GOLD}║{RESET}"))
    print(center(f"{GOLD}║{RESET}        {DIM}{GOLD_LT}Avignon · depuis 1952{RESET}                    {GOLD}║{RESET}"))
    print(center(f"{GOLD}║{RESET}                                                     {GOLD}║{RESET}"))
    print(center(f"{GOLD}║{RESET}      {ITALIC}Espace devis SAV — démonstration{RESET}             {GOLD}║{RESET}"))
    print(center(f"{GOLD}║{RESET}                                                     {GOLD}║{RESET}"))
    print(center(f"{GOLD}╚═════════════════════════════════════════════════════╝{RESET}"))
    print()
    print(center(f"{SOFT}Génération automatique de devis à partir des PDF partenaires{RESET}"))
    print(center(f"{DIM}{SOFT}Rolex · Chanel · Tag Heuer · Breitling{RESET}"))
    print()
    pause("Appuyez sur Entrée pour commencer la démonstration")


def screen_upload():
    cls()
    topbar()
    card_top("Nouveau devis — Importer un PDF partenaire")
    card_line()
    card_line(f"{MID}Importez le devis PDF reçu d'un partenaire horloger.{RESET}")
    card_line(f"{MID}Les informations seront extraites automatiquement par l'IA.{RESET}")
    card_line()
    card_line(f"{DIM}{SOFT}┌─ Glisser-déposer le PDF du partenaire ──────────────────┐{RESET}")
    card_line(f"{DIM}{SOFT}│                                                          │{RESET}")
    card_line(f"{DIM}{SOFT}│   Sélectionnez un PDF de démonstration ci-dessous :     │{RESET}")
    card_line(f"{DIM}{SOFT}│                                                          │{RESET}")
    for p in PARTNERS:
        line = f"{GOLD}[{p['id']}]{RESET} {BOLD}{p['file']}{RESET}  {DIM}{SOFT}— {p['size']} · {p['brand']}{RESET}"
        card_line(f"{DIM}{SOFT}│{RESET}   {line}")
    card_line(f"{DIM}{SOFT}│                                                          │{RESET}")
    card_line(f"{DIM}{SOFT}└──────────────────────────────────────────────────────────┘{RESET}")
    card_line()
    card_bottom()
    print()

    while True:
        choice = ask("Choix du PDF (1, 2 ou 3)", "1")
        for p in PARTNERS:
            if p["id"] == choice:
                return p
        print(f"  {RED}Choix invalide.{RESET}")


def screen_extract(partner: dict):
    cls()
    topbar()
    card_top("Extraction IA en cours")
    card_line()
    card_line(f"  PDF source : {BOLD}{partner['file']}{RESET}")
    card_line(f"  Taille     : {partner['size']}")
    card_line(f"  Marque     : {GOLD}{partner['brand']}{RESET}")
    card_line()
    card_bottom()
    print()

    spinner("Téléversement du PDF...", 1.0, "1 fichier · 0 erreur")
    spinner("Analyse du document (Gemini 2.0 Flash)...", 2.6, "12 pages parcourues")
    spinner("Extraction des champs structurés...", 1.8, "23 champs détectés")
    spinner("Validation et nettoyage des données...", 0.9, "Cohérence OK")

    print()
    print(f"  {GREEN}●{RESET} {BOLD}Extraction terminée avec succès{RESET}  {DIM}{SOFT}({random.randint(11, 18)}.{random.randint(0,9)}s){RESET}")
    time.sleep(0.8)


def screen_review(data: dict) -> dict:
    cls()
    topbar()
    card_top("Vérification des informations extraites")
    card_line(f"  {DIM}{SOFT}Vous pouvez corriger chaque champ. Entrée = conserver la valeur.{RESET}")
    card_line()
    card_bottom()

    print()
    print(f"  {GOLD}■ CLIENT{RESET}")
    data["client_nom"] = ask("Nom du client", data["client_nom"])
    data["sav_numero"] = ask("N° SAV", data["sav_numero"])
    data["sav_date"]   = ask("Date", data["sav_date"])

    print(f"\n  {GOLD}■ MONTRE{RESET}")
    print(f"    Marque         : {BOLD}{data['marque']}{RESET}")
    print(f"    Modèle         : {BOLD}{data['modele']}{RESET}")
    print(f"    Référence      : {data['reference']}")
    print(f"    N° de série    : {data['numero_serie']}")
    print(f"    Métal          : {data['metal']}")
    print(f"    Taille         : {data['taille']}")

    print(f"\n  {GOLD}■ ÉTAT CONSTATÉ{RESET}")
    for line in data["etat"]:
        print(f"    {SOFT}•{RESET} {line}")

    print(f"\n  {GOLD}■ INTERVENTIONS NÉCESSAIRES{RESET}")
    total = 0.0
    for desc, prix in data["necessaires"]:
        print(f"    {SOFT}•{RESET} {desc:<48} {BOLD}{prix:>8.2f} €{RESET}")
        total += prix

    if data["optionnelles"]:
        print(f"\n  {GOLD}■ INTERVENTIONS OPTIONNELLES{RESET}")
        for desc, prix in data["optionnelles"]:
            print(f"    {SOFT}•{RESET} {desc:<48} {DIM}{prix:>8.2f} €{RESET}")

    print()
    print(f"  {SOFT}{'─' * 60}{RESET}")
    print(f"  {BOLD}TOTAL TTC (interventions nécessaires){RESET}      {BOLD}{GOLD}{total:>8.2f} €{RESET}")
    print(f"  Délai estimé : {data['delai']}")
    data["total"] = total

    print()
    confirm = ask("Tout est correct ? (o/n)", "o").lower()
    if confirm not in ("o", "oui", "y", "yes"):
        print(f"  {DIM}{SOFT}(Dans la vraie app : retour au formulaire édition complète){RESET}")
        time.sleep(1.0)
    return data


def screen_generate(data: dict):
    cls()
    topbar()
    card_top("Génération du devis DOUX Joaillier")
    card_line()
    card_line(f"  Client : {BOLD}{data['client_nom']}{RESET}")
    card_line(f"  Montre : {BOLD}{data['marque']} {data['modele']}{RESET}")
    card_line(f"  Total  : {BOLD}{GOLD}{data['total']:.2f} €{RESET}")
    card_line()
    card_bottom()
    print()

    progress_bar("Génération .docx (mise en page DOUX)        ", 1.6)
    progress_bar("Insertion logo + signature électronique      ", 1.0)
    progress_bar("Conversion .docx → .pdf (haute qualité)      ", 1.8)
    progress_bar("Application filigrane DOUX                   ", 0.8)

    base = f"DEVIS_DOUX_{data['client_nom'].replace(' ', '_').replace('.', '')}_{data['sav_numero']}"
    docx_name = f"{base}.docx"
    pdf_name = f"{base}.pdf"

    print()
    print(f"  {GREEN}✓{RESET}  {BOLD}Devis généré avec succès{RESET}")
    time.sleep(0.6)

    return docx_name, pdf_name


def screen_done(data: dict, docx_name: str, pdf_name: str):
    cls()
    topbar()
    print()
    print(center(f"{GREEN}●{RESET}  {BOLD}Devis prêt — DOUX Joaillier{RESET}"))
    print(center(f"{DIM}{SOFT}Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}{RESET}"))
    print()

    card_top("Fichiers générés")
    card_line()
    card_line(f"  {GOLD}┌─ WORD ───────────────────────────────────────────────┐{RESET}")
    card_line(f"  {GOLD}│{RESET} {BOLD}{docx_name}{RESET}")
    card_line(f"  {GOLD}│{RESET} {DIM}{SOFT}Modifiable — Microsoft Word / Pages{RESET}")
    card_line(f"  {GOLD}│{RESET} {GOLD}↓ Télécharger le .docx{RESET}")
    card_line(f"  {GOLD}└──────────────────────────────────────────────────────┘{RESET}")
    card_line()
    card_line(f"  {GOLD}┌─ PDF ────────────────────────────────────────────────┐{RESET}")
    card_line(f"  {GOLD}│{RESET} {BOLD}{pdf_name}{RESET}")
    card_line(f"  {GOLD}│{RESET} {DIM}{SOFT}Prêt à envoyer au client — qualité presse{RESET}")
    card_line(f"  {GOLD}│{RESET} {GOLD}↓ Télécharger le .pdf{RESET}")
    card_line(f"  {GOLD}└──────────────────────────────────────────────────────┘{RESET}")
    card_line()
    card_bottom()

    print()
    print(f"  {DIM}{SOFT}Méthode de conversion : LibreOffice headless · 300 dpi{RESET}")
    print()
    pause("Appuyez sur Entrée pour voir l'aperçu du devis")


def screen_preview(data: dict):
    cls()
    print(f"{DIM}{SOFT}Aperçu du PDF généré (mode démo){RESET}")
    print()

    INNER = WIDTH - 2  # largeur intérieure entre les bordures

    def pline(left: str = "", right: str = ""):
        ll = _visible_len(left)
        rl = _visible_len(right)
        space = max(1, INNER - 2 - ll - rl)  # marges gauche/droite = 1 chacune
        print(f"{GOLD}│{RESET} {left}{' ' * space}{right} {GOLD}│{RESET}")

    def pcenter(text: str):
        tl = _visible_len(text)
        left = max(0, (INNER - tl) // 2)
        right = max(0, INNER - tl - left)
        print(f"{GOLD}│{RESET}{' ' * left}{text}{' ' * right}{GOLD}│{RESET}")

    def psep():
        print(f"{GOLD}├{'─' * INNER}┤{RESET}")

    print(f"{GOLD}┌{'─' * INNER}┐{RESET}")
    pline()
    pcenter(f"{BOLD}D  O  U  X{RESET}")
    pcenter(f"{DIM}{GOLD_LT}JOAILLIER · AVIGNON · 1952{RESET}")
    pline()
    pline(f"{BOLD}DOUX JOAILLIER — Place de l'Horloge, 84000 Avignon{RESET}")
    pline(f"{DIM}{SOFT}contact@douxjoaillier.fr  ·  04 90 XX XX XX{RESET}")
    pline()
    psep()
    pline()
    pline(f"{BOLD}DEVIS N° {data['sav_numero']}{RESET}", f"{DIM}{datetime.now().strftime('%d/%m/%Y')}{RESET}")
    pline()
    pline(f"Client    : {BOLD}{data['client_nom']}{RESET}")
    pline(f"Montre    : {BOLD}{data['marque']} {data['modele']}{RESET}")
    pline(f"Référence : {data['reference']}")
    pline(f"N° série  : {data['numero_serie']}")
    pline(f"Métal     : {data['metal']}  ·  {data['taille']}")
    pline()
    psep()
    pline()
    pline(f"{GOLD}{BOLD}ÉTAT CONSTATÉ{RESET}")
    for e in data["etat"]:
        pline(f"  • {e}")
    pline()
    pline(f"{GOLD}{BOLD}INTERVENTIONS NÉCESSAIRES{RESET}")
    for desc, prix in data["necessaires"]:
        pline(f"  {desc}", f"{BOLD}{prix:.2f} €{RESET}")
    pline()
    if data["optionnelles"]:
        pline(f"{GOLD}{BOLD}OPTIONNELLES{RESET}")
        for desc, prix in data["optionnelles"]:
            pline(f"  {desc}", f"{DIM}{prix:.2f} €{RESET}")
        pline()
    psep()
    pline()
    pline(f"{BOLD}TOTAL TTC{RESET}", f"{BOLD}{GOLD}{data['total']:.2f} €{RESET}")
    pline(f"{DIM}{SOFT}Délai estimé : {data['delai']}{RESET}")
    pline()
    pline(f"{DIM}{ITALIC}{SOFT}Devis valable 30 jours. Garantie 24 mois sur les pièces remplacées.{RESET}")
    pline()
    print(f"{GOLD}└{'─' * INNER}┘{RESET}")
    print()


def screen_outro():
    print()
    hr("═", GOLD)
    print()
    print(center(f"{BOLD}Démonstration terminée{RESET}"))
    print()
    print(center(f"{SOFT}Ce que vous venez de voir :{RESET}"))
    print()
    print(center(f"  {GOLD}1.{RESET}  Import d'un PDF partenaire (Rolex / Chanel / Tag Heuer)"))
    print(center(f"  {GOLD}2.{RESET}  Extraction automatique par IA (Gemini)               "))
    print(center(f"  {GOLD}3.{RESET}  Vérification & édition rapide des champs            "))
    print(center(f"  {GOLD}4.{RESET}  Génération devis .docx + .pdf aux couleurs DOUX      "))
    print()
    print(center(f"{DIM}{SOFT}Version web en ligne · accessible depuis n'importe quel poste{RESET}"))
    print()
    hr("═", GOLD)
    print()


# ───────────────────────── Main ─────────────────────────
def main():
    try:
        screen_intro()
        partner = screen_upload()
        screen_extract(partner)
        pause("Appuyez sur Entrée pour vérifier les données extraites")
        data = screen_review(dict(partner["data"]))
        pause("Appuyez sur Entrée pour générer le devis")
        docx, pdf = screen_generate(data)
        screen_done(data, docx, pdf)
        screen_preview(data)
        pause("Appuyez sur Entrée pour terminer")
        screen_outro()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n{DIM}{SOFT}Démonstration interrompue.{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
