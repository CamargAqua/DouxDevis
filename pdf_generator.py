"""Génération PDF — format DOUX Joaillier (ReportLab)."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

GOLD = colors.HexColor("#C8A028")
DARK = colors.HexColor("#1A1814")


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            return value
    if value == 0:
        return "OFFERT"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    """Texte brut → échappe les caractères spéciaux avant de passer à ReportLab."""
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe = safe.replace("\n", "<br/>")
    return Paragraph(safe, style)


def _html(markup: str, style: ParagraphStyle) -> Paragraph:
    """Markup ReportLab déjà formé → passe directement sans échappement."""
    return Paragraph(markup or "", style)


def render_pdf(data: dict[str, Any], photo_bytes: bytes | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )

    base  = ParagraphStyle("base",  fontName="Helvetica",          fontSize=9,  leading=13)
    bold  = ParagraphStyle("bold",  fontName="Helvetica-Bold",     fontSize=9,  leading=13)
    small = ParagraphStyle("small", fontName="Helvetica",          fontSize=7.5, alignment=1, leading=10)
    rb    = ParagraphStyle("rb",    fontName="Helvetica-Bold",     fontSize=9,  alignment=2, leading=13)

    story: list[Any] = []

    # ── En-tête ───────────────────────────────────────────────────────────────
    marque = (data.get("marque") or "PARTENAIRE").upper()
    hdr = Table([[
        _html('<font name="Helvetica-Bold" size="28">DOUX JOAILLIER</font>', base),
        _html(f'<para align="right"><font name="Helvetica-Bold" size="22" color="#C8A028">{marque}</font></para>', base),
    ]], colWidths=[9 * cm, 9 * cm])
    hdr.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW",     (0, 0), (-1, -1), 1, colors.black),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 4 * mm))

    # ── Ligne client ──────────────────────────────────────────────────────────
    client = data.get("client") or {}
    sav    = data.get("sav") or {}
    nom    = (client.get("nom") or "").upper()
    num    = sav.get("numero", "")
    date   = sav.get("date", "")
    lieu   = sav.get("lieu", "Avignon")

    cl = Table([[
        _p(nom, bold),
        _p(f"SAV {num}", bold),
        _p(f"Le {date} à {lieu}", base),
    ]], colWidths=[6 * cm, 5.5 * cm, 6.5 * cm])
    cl.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#F0F0F0")),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(cl)
    story.append(Spacer(1, 5 * mm))

    # ── INFORMATIONS DE LA MONTRE ─────────────────────────────────────────────
    story.append(_html("<b><u>INFORMATIONS DE LA MONTRE</u></b>", bold))
    story.append(Spacer(1, 2 * mm))

    montre = data.get("montre") or {}
    etat = montre.get("etat") or []
    if isinstance(etat, str):
        etat = [l.strip() for l in etat.splitlines() if l.strip()]

    serie  = montre.get("numero_serie", "")
    modele = montre.get("modele", "").upper()
    metal  = (montre.get("metal") or "").upper()
    modele_full = f"{modele} — {metal}" if metal else modele

    etat_html = "<br/>".join(f"• {l.upper()}" for l in etat)
    left_html = f"{serie}<br/><b>{modele_full}</b>"
    if etat_html:
        left_html += f"<br/><br/>{etat_html}"

    ref = montre.get("reference", "")
    right_html = f"<b>Référence :</b><br/>{ref}"
    if serie:
        right_html += f"<br/><br/><b>N° de série :</b><br/>{serie}"

    montre_tbl = Table([[
        _html(left_html, base),
        _html(right_html, base),
    ]], colWidths=[13 * cm, 5 * cm])
    montre_tbl.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(montre_tbl)
    story.append(Spacer(1, 5 * mm))

    # ── TRAVAIL NÉCESSAIRE ────────────────────────────────────────────────────
    hdr_nec = Table([[
        _html('<font color="white"><b>INTERVENTION</b></font>', bold),
        _html('<para align="right"><font color="white"><b>PRIX TTC EN EUR</b></font></para>', bold),
    ]], colWidths=[14 * cm, 4 * cm])
    hdr_nec.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), DARK),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(hdr_nec)

    necessaires = data.get("interventions_necessaires") or []
    intro = (data.get("service_complet_description") or "").strip()
    rows_nec = []
    for i, line in enumerate(necessaires):
        desc     = (line.get("description") or "").upper()
        prix_val = line.get("prix", 0)
        prix_txt = line.get("prix_label") or _fmt(prix_val)

        if i == 0 and intro:
            intro_lines = "<br/>".join(
                f'. <font size="8" name="Helvetica-Oblique">{l.strip()}</font>'
                for l in intro.split("\n") if l.strip()
            )
            cell_desc = _html(f"<b>{desc}</b><br/>{intro_lines}", base)
        else:
            cell_desc = _p(desc, base)

        if prix_txt == "OFFERT":
            cell_prix = _html('<para align="right"><font color="#C8A028"><b>OFFERT</b></font></para>', base)
        else:
            cell_prix = _html(f'<para align="right">{prix_txt}</para>', base)

        rows_nec.append([cell_desc, cell_prix])

    if not rows_nec:
        rows_nec = [[_p("", base), _p("", base)]]

    body_nec = Table(rows_nec, colWidths=[14 * cm, 4 * cm])
    body_nec.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(body_nec)

    # Ligne total
    total_ttc = data.get("total_ttc")
    if total_ttc in (None, "", 0) and necessaires:
        try:
            total_ttc = sum(float(l.get("prix") or 0) for l in necessaires)
        except (TypeError, ValueError):
            total_ttc = 0
    total_str = _fmt(total_ttc)
    if total_str and total_str != "OFFERT":
        total_str += " €"

    tot = Table([[
        _html("<b>TOTAL TTC EN EURO</b>", rb),
        _html(f"<b>{total_str}</b>", rb),
    ]], colWidths=[14 * cm, 4 * cm])
    tot.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(tot)
    story.append(Spacer(1, 5 * mm))

    # ── TRAVAIL OPTIONNEL ─────────────────────────────────────────────────────
    optionnelles = data.get("interventions_optionnelles") or []
    if optionnelles:
        hdr_opt = Table([[
            _html('<font color="white"><b>OPTION</b></font>', bold),
            _html('<para align="right"><font color="white"><b>PRIX TTC EN EUR</b></font></para>', bold),
        ]], colWidths=[14 * cm, 4 * cm])
        hdr_opt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), DARK),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ]))
        story.append(hdr_opt)

        opt_rows = []
        for l in optionnelles:
            desc     = (l.get("description") or "").upper()
            prix_txt = l.get("prix_label") or _fmt(l.get("prix"))
            opt_rows.append([
                _html(f"■  <b>{desc}</b>", bold),
                _html(f'<para align="right"><b>{prix_txt}</b></para>', bold),
            ])
        opt_tbl = Table(opt_rows, colWidths=[14 * cm, 4 * cm])
        opt_tbl.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(opt_tbl)
        story.append(Spacer(1, 5 * mm))

    # ── Pied de page ─────────────────────────────────────────────────────────
    delai = (data.get("delai") or "4 à 6 semaines").upper()
    story.append(_html(
        f"<b>DÉLAIS APRÈS ACCORD : {delai} SOUS RÉSERVE DE DISPONIBILITÉ DES PIÈCES</b>",
        bold,
    ))
    story.append(Spacer(1, 3 * mm))

    sig = Table([
        [_p("■  ACCORD AU DEVIS", base),  _html("<b>DATE ET SIGNATURE :</b>", bold)],
        [_p("■  REFUS DU DEVIS",  base),  ""],
    ], colWidths=[11 * cm, 7 * cm], rowHeights=[1.2 * cm, 1.2 * cm])
    sig.setStyle(TableStyle([
        ("BOX",          (1, 0), (1, 1), 0.5, colors.black),
        ("SPAN",         (1, 0), (1, 1)),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(sig)

    # ── Mentions légales — page 2 ─────────────────────────────────────────────
    story.append(PageBreak())
    story.append(_p(
        "SARL DOUX Développement au Capital de 15 245 € — R.C. Avignon 65 A 59 "
        "— Siret 315 215 442 00023 — APE 4777 Z — TVA Intracommunautaire FR 313 152 15442 "
        "| sav@douxjoaillier.com",
        small,
    ))

    doc.build(story)
    return buf.getvalue()


# Alias pour compatibilité avec app.py
def docx_to_pdf(docx_bytes: bytes, data: dict[str, Any] | None = None,
                photo_bytes: bytes | None = None) -> tuple[bytes, str]:
    if data is None:
        raise RuntimeError("Données requises pour la génération PDF.")
    return render_pdf(data, photo_bytes), "reportlab"
