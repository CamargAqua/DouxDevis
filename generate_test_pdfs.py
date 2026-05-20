"""Génère des PDFs de test simulant des devis partenaires horlogers."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white, grey
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from pathlib import Path

OUT = Path("test_pdfs")
OUT.mkdir(exist_ok=True)

def base_doc(filename):
    return SimpleDocTemplate(
        str(OUT / filename),
        pagesize=A4,
        topMargin=20*mm, bottomMargin=20*mm,
        leftMargin=20*mm, rightMargin=20*mm,
    )

styles = getSampleStyleSheet()

def style(name="Normal", size=10, bold=False, color=black, align=TA_LEFT):
    return ParagraphStyle(
        name,
        parent=styles["Normal"],
        fontSize=size,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        textColor=color,
        alignment=align,
    )

GOLD = HexColor("#B8962E")
DARK = HexColor("#1A1A2E")
LIGHT_GREY = HexColor("#F5F5F5")
MID_GREY = HexColor("#888888")

# ─────────────────────────────────────────────
# DEVIS 1 — ROLEX (révision complète + options)
# ─────────────────────────────────────────────
def make_rolex():
    doc = base_doc("devis_rolex_submariner.pdf")
    story = []

    # Header
    story.append(Paragraph("ROLEX SA", style("h1", 22, bold=True, color=DARK, align=TA_CENTER)))
    story.append(Paragraph("Centre de Service Agréé — Genève", style("s", 9, color=MID_GREY, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))
    story.append(HRFlowable(width="100%", thickness=1, color=GOLD))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("BON D'INTERVENTION N° SAV-2024-38741", style("n", 11, bold=True, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))

    # Infos client / montre
    info_data = [
        ["CLIENT", "MARTIN Pierre", "DATE", "12.05.2026"],
        ["MODÈLE", "Submariner Date", "RÉFÉRENCE", "126610LN"],
        ["N° SÉRIE", "V827439B", "BRACELET", "Oyster acier 20mm"],
        ["MÉTAL", "Acier 904L", "DIAMÈTRE", "41 mm"],
    ]
    info_table = Table(info_data, colWidths=[35*mm, 60*mm, 35*mm, 45*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_GREY),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph("ÉTAT CONSTATÉ À LA RÉCEPTION", style("s", 10, bold=True, color=DARK)))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Rayures importantes sur la boîte et le bracelet. Lunette céramique éraflée. "
        "Étanchéité hors norme (test pression 10 bar). Mécanisme – 12 sec/j.",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 6*mm))

    # Interventions
    story.append(Paragraph("DEVIS D'INTERVENTIONS", style("s", 10, bold=True, color=DARK)))
    story.append(Spacer(1, 2*mm))

    interv_data = [
        ["DÉSIGNATION", "PU HT", "TVA", "PU TTC"],
        ["RÉVISION COMPLÈTE MANUFACTURE\n(démontage, nettoyage ultrason, huilage,\nréglage chrono, remontage)", "650,00 €", "20%", "780,00 €"],
        ["REMPLACEMENT JOINT D'ÉTANCHÉITÉ\ncouronne + fond de boîte", "68,00 €", "20%", "81,60 €"],
        ["POLISSAGE ET SATINAGE COMPLET\nboîte + bracelet (5 links)", "140,00 €", "20%", "168,00 €"],
        ["REMPLACEMENT VERRE SAPHIR\nadapté ref. 126610", "95,00 €", "20%", "114,00 €"],
        ["TEST PRESSION 30 ATM + CERTIFICAT", "35,00 €", "20%", "42,00 €"],
    ]
    interv_table = Table(interv_data, colWidths=[90*mm, 25*mm, 20*mm, 25*mm])
    interv_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("BACKGROUND", (0,0), (-1,0), DARK),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(interv_table)
    story.append(Spacer(1, 4*mm))

    # Total
    total_data = [
        ["TOTAL HT", "988,00 €"],
        ["TVA 20%", "197,60 €"],
        ["TOTAL TTC", "1 185,60 €"],
    ]
    total_table = Table(total_data, colWidths=[130*mm, 30*mm])
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTSIZE", (0,-1), (-1,-1), 11),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,-1), (-1,-1), GOLD),
        ("TEXTCOLOR", (0,-1), (-1,-1), white),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(total_table)
    story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Délai estimé : 6 à 8 semaines — Garantie 2 ans internationale", style("f", 8, color=MID_GREY, align=TA_CENTER)))

    doc.build(story)
    print("✓ devis_rolex_submariner.pdf")

# ─────────────────────────────────────────────
# DEVIS 2 — CHANEL (J12, avec polissage offert)
# ─────────────────────────────────────────────
def make_chanel():
    doc = base_doc("devis_chanel_j12.pdf")
    story = []

    story.append(Paragraph("CHANEL HORLOGERIE", style("h1", 20, bold=True, color=DARK, align=TA_CENTER)))
    story.append(Paragraph("Service Après-Vente — Paris", style("s", 9, color=MID_GREY, align=TA_CENTER)))
    story.append(Spacer(1, 5*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=black))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("FICHE DE RÉPARATION N° CH-2026-007821", style("n", 11, bold=True, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))

    info_data = [
        ["Nom client", "BERNARD Sophie", "Date réception", "08.05.2026"],
        ["Modèle", "J12 Chronographe", "Référence", "H2419"],
        ["N° de série", "CC47832 A", "Matière", "Céramique noire / Acier"],
        ["Diamètre", "41 mm", "Année estimée", "2018"],
    ]
    info_table = Table(info_data, colWidths=[35*mm, 60*mm, 35*mm, 45*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT_GREY, white]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("OBSERVATIONS", style("s", 10, bold=True)))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Boîtier en céramique présentant de légères griffures. Bracelet avec maillon manquant (pos. 3 gauche). "
        "Chronographe totalisant bloqué à 12h. Fond de boîte oxydé.",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("DEVIS DE RÉPARATION", style("s", 10, bold=True)))
    story.append(Spacer(1, 2*mm))

    interv_data = [
        ["PRESTATION", "MONTANT TTC"],
        ["Révision complète mouvement quartz chronographe\n(nettoyage, lubrification, réglage, test)", "698,00 €"],
        ["Remplacement pile lithium haute performance", "18,00 €"],
        ["Remplacement maillon bracelet céramique\n(origine Chanel, réf. H2419-BL-03)", "185,00 €"],
        ["Remplacement joint fond de boîte + test étanchéité", "55,00 €"],
        ["Polissage boîtier céramique — OFFERT (goodwill)", "0,00 €"],
    ]
    interv_table = Table(interv_data, colWidths=[130*mm, 30*mm])
    interv_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("BACKGROUND", (0,0), (-1,0), black),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TEXTCOLOR", (0,-1), (-1,-1), HexColor("#999999")),  # ligne offerte en gris
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Oblique"),
    ]))
    story.append(interv_table)
    story.append(Spacer(1, 3*mm))

    total_data = [
        ["Sous-total TTC (hors offert)", "956,00 €"],
        ["TOTAL À RÉGLER TTC", "956,00 €"],
    ]
    total_table = Table(total_data, colWidths=[130*mm, 30*mm])
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTSIZE", (0,-1), (-1,-1), 11),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,-1), (-1,-1), black),
        ("TEXTCOLOR", (0,-1), (-1,-1), white),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(total_table)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("Délai : 4 à 6 semaines | Garantie Chanel 2 ans", style("f", 8, color=MID_GREY, align=TA_CENTER)))

    doc.build(story)
    print("✓ devis_chanel_j12.pdf")

# ────────────────────────────────────────────────────────
# DEVIS 3 — TAG HEUER (Monaco, chrono + bracelet inclus)
# ────────────────────────────────────────────────────────
def make_tagheuer():
    doc = base_doc("devis_tagheuer_monaco.pdf")
    story = []

    story.append(Paragraph("TAG HEUER", style("h1", 22, bold=True, color=HexColor("#C8102E"), align=TA_CENTER)))
    story.append(Paragraph("Swiss Avant-Garde Since 1860 — Manufacture Le Locle", style("s", 8, color=MID_GREY, align=TA_CENTER)))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#C8102E")))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("ESTIMATION DE RÉPARATION — Réf. TH/SAV/2026/092341", style("n", 10, bold=True, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))

    info_data = [
        ["Client", "LEROY Thomas", "Date", "15.05.2026"],
        ["Modèle", "Monaco Chronographe", "Réf.", "CAW211P.FC6356"],
        ["Mouvement", "Calibre Heuer 02", "N° série", "TH24-881923"],
        ["Boîtier", "Acier – 39 mm carré", "Bracelet", "Cuir bleu alligator"],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 65*mm, 25*mm, 55*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("DIAGNOSTIC", style("s", 10, bold=True, color=HexColor("#C8102E"))))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Remontoir bloqué en position 2. Poussoir chronographe H4 ne répond plus. "
        "Bracelet cuir fissuré. Verre bombé présentant micro-éclat angle bas droit. "
        "Précision : +23 sec/jour (limite tolérance 0/+5 sec).",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("ESTIMATION TRAVAUX", style("s", 10, bold=True, color=HexColor("#C8102E"))))
    story.append(Spacer(1, 2*mm))

    interv_data = [
        ["DÉSIGNATION PRESTATION", "PRIX TTC"],
        ["SERVICE COMPLET CALIBRE HEUER 02\nDémontage, nettoyage, remplacement pièces d'usure,\nlubrification, remontage, réglage 6 positions", "980,00 €"],
        ["REMPLACEMENT REMONTOIR + TIGE\n(pièce d'origine, référence TH-02-CROWN)", "120,00 €"],
        ["REMPLACEMENT VERRE SAPHIR BOMBÉ\nadapté Monaco carré 39mm", "195,00 €"],
        ["REMPLACEMENT BRACELET ALLIGATOR BLEU\n(inclus dans le forfait service TAG > 800€)", "0,00 € INCL."],
        ["NETTOYAGE BOÎTIER + POLISSAGE PARTIEL\n(angles brossés conservés — inclus forfait)", "0,00 € INCL."],
    ]
    interv_table = Table(interv_data, colWidths=[130*mm, 30*mm])
    interv_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("BACKGROUND", (0,0), (-1,0), HexColor("#C8102E")),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TEXTCOLOR", (0,-2), (-1,-1), HexColor("#888888")),
    ]))
    story.append(interv_table)
    story.append(Spacer(1, 3*mm))

    total_data = [
        ["Sous-total (interventions facturées)", "1 295,00 €"],
        ["TOTAL TTC", "1 295,00 €"],
    ]
    total_table = Table(total_data, colWidths=[130*mm, 30*mm])
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTSIZE", (0,-1), (-1,-1), 11),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,-1), (-1,-1), HexColor("#C8102E")),
        ("TEXTCOLOR", (0,-1), (-1,-1), white),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(total_table)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph("Délai de réparation estimé : 8 à 10 semaines", style("f", 8, color=MID_GREY, align=TA_CENTER)))

    doc.build(story)
    print("✓ devis_tagheuer_monaco.pdf")

# ────────────────────────────────────────────────
# DEVIS 4 — OMEGA (Seamaster, service + options)
# ────────────────────────────────────────────────
def make_omega():
    doc = base_doc("devis_omega_seamaster.pdf")
    story = []

    story.append(Paragraph("Ω  OMEGA", style("h1", 22, bold=True, color=HexColor("#003DA5"), align=TA_CENTER)))
    story.append(Paragraph("Official Omega Service Centre — Biel/Bienne", style("s", 8, color=MID_GREY, align=TA_CENTER)))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=2, color=HexColor("#003DA5")))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("DEVIS SERVICE — N° OM-SAV-2026-415882", style("n", 10, bold=True, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))

    info_data = [
        ["Titulaire", "DUPONT Anne-Claire", "Date entrée", "10.05.2026"],
        ["Collection", "Seamaster Diver 300M", "Référence", "210.30.42.20.01.001"],
        ["Mouvement", "Calibre 8800 Co-Axial", "N° série montre", "OM84712638"],
        ["Boîtier", "Acier — 42 mm", "Bracelet", "Acier bicolore Sedna"],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 65*mm, 28*mm, 52*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT_GREY, white]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("CONSTAT D'ÉTAT", style("s", 10, bold=True, color=HexColor("#003DA5"))))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Verre hélium fissuré (choc). Couronne vissée présentant un jeu anormal — étanchéité compromise. "
        "Fond de boîte avec trace de corrosion légère. Mouvement retardant de –8 sec/j. "
        "Bracelet avec fermoir présentant un ressort cassé (position 2).",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("PROPOSITIONS D'INTERVENTION", style("s", 10, bold=True, color=HexColor("#003DA5"))))
    story.append(Spacer(1, 2*mm))

    interv_data = [
        ["LIBELLÉ", "PRIX HT", "TTC"],
        ["RÉVISION COMPLÈTE CAL. 8800 CO-AXIAL\nDémontage / nettoyage / remplacement spirale\net rubis usés / lubrification / réglage / test COSC", "725,00 €", "870,00 €"],
        ["REMPLACEMENT VERRE SAPHIR HÉLIUM\n(anti-reflets double face, adapté 210.30)", "110,00 €", "132,00 €"],
        ["REMPLACEMENT ENSEMBLE COURONNE + TIGE", "78,00 €", "93,60 €"],
        ["TRAITEMENT FOND DE BOÎTE\n(dépose, brossage, retraitement anti-corrosion)", "45,00 €", "54,00 €"],
        ["REMPLACEMENT RESSORT FERMOIR BRACELET\n(pièce d'origine Omega Sedna)", "35,00 €", "42,00 €"],
        ["TEST PRESSION HELIUM 12 ATM + RAPPORT", "28,00 €", "33,60 €"],
        ["SATINAGE FOND DE BOÎTE — OFFERT", "—", "0,00 €"],
    ]
    interv_table = Table(interv_data, colWidths=[100*mm, 28*mm, 28*mm])
    interv_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("BACKGROUND", (0,0), (-1,0), HexColor("#003DA5")),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,0), (-1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("TEXTCOLOR", (0,-1), (-1,-1), HexColor("#999999")),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Oblique"),
    ]))
    story.append(interv_table)
    story.append(Spacer(1, 3*mm))

    total_data = [
        ["Total HT", "1 021,00 €"],
        ["TVA 20%", "204,20 €"],
        ["TOTAL TTC (satinage offert)", "1 225,20 €"],
    ]
    total_table = Table(total_data, colWidths=[130*mm, 30*mm])
    total_table.setStyle(TableStyle([
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTSIZE", (0,-1), (-1,-1), 11),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,-1), (-1,-1), HexColor("#003DA5")),
        ("TEXTCOLOR", (0,-1), (-1,-1), white),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(total_table)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        "Délai d'exécution : 10 à 12 semaines | Certificat Omega COSC inclus | Garantie 5 ans",
        style("f", 8, color=MID_GREY, align=TA_CENTER)
    ))

    doc.build(story)
    print("✓ devis_omega_seamaster.pdf")


# ──────────────────────────────────────────────────────────────────
# DEVIS 5 — BREITLING (Navitimer, révision + options multiples)
# ──────────────────────────────────────────────────────────────────
def make_breitling():
    doc = base_doc("devis_breitling_navitimer.pdf")
    story = []

    story.append(Paragraph("BREITLING", style("h1", 24, bold=True, color=HexColor("#1A1A2E"), align=TA_CENTER)))
    story.append(Paragraph("Instruments for Professionals — Service Centre Genève", style("s", 8, color=MID_GREY, align=TA_CENTER)))
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=HexColor("#1A1A2E")))
    story.append(Spacer(1, 4*mm))

    story.append(Paragraph("DEVIS D'ENTRETIEN — Réf. BR/2026/SAV/047319", style("n", 10, bold=True, align=TA_CENTER)))
    story.append(Spacer(1, 6*mm))

    info_data = [
        ["Titulaire", "MOREAU Jean-François", "Date entrée", "14.05.2026"],
        ["Collection", "Navitimer B01 Chrono 43", "Référence", "AB0138241B1P1"],
        ["Mouvement", "Calibre BREITLING 01 (Manufacture)", "N° série", "BR19-347821"],
        ["Boîtier", "Acier brossé — 43 mm", "Bracelet", "Pilote en cuir brun croco"],
    ]
    info_table = Table(info_data, colWidths=[30*mm, 65*mm, 28*mm, 52*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 9),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTNAME", (2,0), (2,-1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [LIGHT_GREY, white]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("CONSTAT D'ÉTAT", style("s", 10, bold=True)))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Chronographe bloqué — retour à zéro inopérant. Remontoir avec jeu important "
        "(côté couronne). Verre de cadran fissuré angle 4h. Bracelet cuir très usé. "
        "Boucle ardillon lâche. Précision : +34 sec/jour.",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 5*mm))

    # --- INTERVENTIONS NÉCESSAIRES ---
    story.append(Paragraph("INTERVENTIONS NÉCESSAIRES", style("s", 10, bold=True)))
    story.append(Spacer(1, 2*mm))
    nec_data = [
        ["DÉSIGNATION", "PRIX TTC"],
        ["RÉVISION COMPLÈTE CALIBRE BREITLING 01\nDémontage chronographe, nettoyage ultrason,\nremplacement ressorts, lubrification, réglage COSC", "920,00 €"],
        ["REMPLACEMENT REMONTOIR + TIGE DE REMONTAGE\n(pièces d'origine manufacture B01)", "145,00 €"],
        ["REMPLACEMENT VERRE SAPHIR BOMBÉ\n(anti-reflets, adapté Navitimer 43 mm)", "210,00 €"],
        ["REMPLACEMENT BOUCLE ARDILLON ACIER\n(origine Breitling 20 mm)", "65,00 €"],
        ["TEST PRESSION + CERTIFICAT BREITLING\n(certificat de révision manufacture)", "40,00 €"],
    ]
    nec_table = Table(nec_data, colWidths=[130*mm, 30*mm])
    nec_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("BACKGROUND", (0,0), (-1,0), HexColor("#1A1A2E")),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, LIGHT_GREY]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(nec_table)
    story.append(Spacer(1, 3*mm))

    total_nec_data = [["TOTAL NÉCESSAIRE TTC", "1 380,00 €"]]
    total_nec = Table(total_nec_data, colWidths=[130*mm, 30*mm])
    total_nec.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 10),
        ("BACKGROUND", (0,0), (-1,0), HexColor("#1A1A2E")),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,0), 6),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
    ]))
    story.append(total_nec)
    story.append(Spacer(1, 6*mm))

    # --- OPTIONS ---
    story.append(Paragraph("OPTIONS PROPOSÉES (au choix du client)", style("s", 10, bold=True, color=HexColor("#B8962E"))))
    story.append(Spacer(1, 2*mm))
    story.append(Paragraph(
        "Les options suivantes sont indépendantes et peuvent être choisies séparément.",
        style("c", 9, color=MID_GREY)
    ))
    story.append(Spacer(1, 3*mm))

    opt_data = [
        ["OPTION", "PRIX TTC"],
        ["OPT. A — REMPLACEMENT BRACELET CUIR\nBracelet pilote Breitling cuir brun croco,\nboucle ardillon acier 20mm (origine)", "185,00 €"],
        ["OPT. B — POLISSAGE COMPLET BOÎTIER\nPolissage faces + satinage flancs\n(conserve le rendu d'origine brossé/poli)", "135,00 €"],
        ["OPT. C — REMPLACEMENT LUNETTE TACHYMÈTRE\nLunette acier avec insert céramique noire\ngravée, origine Navitimer B01", "295,00 €"],
        ["OPT. D — DORURE BOÎTIER OR JAUNE 18K\nApplicatione d'une couche d'or PVD\n(valable 3 à 5 ans selon utilisation)", "380,00 €"],
    ]
    opt_table = Table(opt_data, colWidths=[130*mm, 30*mm])
    opt_table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("BACKGROUND", (0,0), (-1,0), HexColor("#B8962E")),
        ("TEXTCOLOR", (0,0), (-1,0), white),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [white, HexColor("#FFFDF5")]),
        ("GRID", (0,0), (-1,-1), 0.3, grey),
        ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(opt_table)
    story.append(Spacer(1, 3*mm))

    total_opt_data = [
        ["Si toutes options incluses (A+B+C+D)", "2 375,00 €"],
    ]
    total_opt = Table(total_opt_data, colWidths=[130*mm, 30*mm])
    total_opt.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,0), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,0), 9),
        ("ALIGN", (1,0), (1,0), "RIGHT"),
        ("TOPPADDING", (0,0), (-1,0), 4),
        ("BOTTOMPADDING", (0,0), (-1,0), 4),
        ("TEXTCOLOR", (0,0), (-1,0), MID_GREY),
    ]))
    story.append(total_opt)
    story.append(Spacer(1, 5*mm))
    story.append(Paragraph(
        "Délai nécessaire : 6 à 8 semaines | Garantie Breitling 2 ans | Toutes options facultatives",
        style("f", 8, color=MID_GREY, align=TA_CENTER)
    ))

    doc.build(story)
    print("Breitling devis_breitling_navitimer.pdf")


if __name__ == "__main__":
    make_rolex()
    make_chanel()
    make_tagheuer()
    make_omega()
    make_breitling()
    print(f"\n5 PDFs dans ./{OUT}/")
