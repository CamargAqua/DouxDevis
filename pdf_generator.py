"""Génération PDF — format DOUX Joaillier (ReportLab)."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

GOLD = colors.HexColor("#C8A028")
DARK = colors.HexColor("#1A1814")

# Dossier des logos (static/logos/)
LOGOS_DIR = Path(__file__).parent / "static" / "logos"

# Mapping marque → nom de fichier logo (sans extension)
BRAND_LOGOS: dict[str, str] = {
    "breitling":              "breitling",
    "chanel":                 "chanel",
    "rolex":                  "rolex",
    "tag heuer":              "tag_heuer",
    "tagheuer":               "tag_heuer",
    "patek philippe":         "patek_philippe",
    "patek":                  "patek_philippe",
    "march la.b":             "march_lab",
    "march lab":              "march_lab",
    "cartier":                "cartier",
    "omega":                  "omega",
    "iwc":                    "iwc",
    "iwc schaffhausen":       "iwc",
    "longines":               "longines",
    "tudor":                  "tudor",
    "hublot":                 "hublot",
    "audemars piguet":        "audemars_piguet",
    "ap":                     "audemars_piguet",
    "doux":                   "doux",
}


def _logo_path(name: str) -> Path | None:
    """Retourne le chemin du logo si le fichier existe (png, jpg, jpeg)."""
    key = name.lower().strip()
    slug = BRAND_LOGOS.get(key, re.sub(r"[^a-z0-9]+", "_", key).strip("_"))
    for ext in ("png", "jpg", "jpeg"):
        p = LOGOS_DIR / f"{slug}.{ext}"
        if p.exists():
            return p
    return None


def _logo_img(path: Path, max_w: float, max_h: float) -> Image:
    img = Image(str(path))
    ratio = img.imageWidth / img.imageHeight
    w = min(max_w, max_h * ratio)
    h = w / ratio
    if h > max_h:
        h = max_h
        w = h * ratio
    img._restrictSize(w, h)
    return img


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
    """Texte brut → échappe les caractères spéciaux."""
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe = safe.replace("\n", "<br/>")
    return Paragraph(safe, style)


def _html(markup: str, style: ParagraphStyle) -> Paragraph:
    """Markup ReportLab déjà formé → passe sans échappement."""
    return Paragraph(markup or "", style)


def render_pdf(data: dict[str, Any], photo_bytes: bytes | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )

    base  = ParagraphStyle("base",  fontName="Helvetica",       fontSize=9,  leading=13)
    bold  = ParagraphStyle("bold",  fontName="Helvetica-Bold",  fontSize=9,  leading=13)
    small = ParagraphStyle("small", fontName="Helvetica",       fontSize=7.5, alignment=1, leading=10)
    rb    = ParagraphStyle("rb",    fontName="Helvetica-Bold",  fontSize=9,  alignment=2, leading=13)

    story: list[Any] = []

    # ── En-tête ───────────────────────────────────────────────────────────────
    marque_raw = (data.get("marque") or "PARTENAIRE")
    marque_up  = marque_raw.upper()

    # Logo DOUX (gauche) — Image ou texte
    doux_logo = _logo_path("doux")
    if doux_logo:
        left_cell = _logo_img(doux_logo, 8 * cm, 1.4 * cm)
        left_cell.hAlign = 'LEFT'
    else:
        left_cell = _html('<font face="Helvetica-Bold" size="28">DOUX JOAILLIER</font>', base)

    # Logo marque partenaire (droite) — Image ou nom en or
    brand_logo = _logo_path(marque_raw)
    if brand_logo:
        right_cell = _logo_img(brand_logo, 8 * cm, 1.4 * cm)
        right_cell.hAlign = 'RIGHT'
    else:
        right_cell = _html(
            f'<para align="right"><font face="Helvetica-Bold" size="22"'
            f' color="#C8A028">{marque_up}</font></para>', base
        )

    hdr = Table([[left_cell, right_cell]], colWidths=[9 * cm, 9 * cm],
                rowHeights=[1.6 * cm])
    hdr.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
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

    serie       = montre.get("numero_serie", "")
    modele      = montre.get("modele", "").upper()
    metal       = (montre.get("metal") or "").upper()
    modele_full = f"{modele} — {metal}" if metal else modele

    etat_html  = "<br/>".join(f"• {l.upper()}" for l in etat)
    info_html  = f"{serie}<br/><b>{modele_full}</b>"
    if etat_html:
        info_html += f"<br/><br/>{etat_html}"

    ref        = montre.get("reference", "")
    right_html = f"<b>Référence :</b><br/>{ref}"
    if serie:
        right_html += f"<br/><br/><b>N° de série :</b><br/>{serie}"

    if photo_bytes:
        try:
            photo_img = Image(BytesIO(photo_bytes))
            photo_img._restrictSize(4 * cm, 5 * cm)
        except Exception:
            photo_img = _p("", base)

        montre_tbl = Table([[
            photo_img,
            _html(info_html, base),
            _html(right_html, base),
        ]], colWidths=[4.5 * cm, 8.5 * cm, 5 * cm])
        montre_tbl.setStyle(TableStyle([
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID",     (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("ALIGN",         (0, 0), (0, 0),   "CENTER"),
            ("VALIGN",        (0, 0), (0, 0),   "MIDDLE"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
    else:
        montre_tbl = Table([[
            _html(info_html, base),
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
                f'. <font size="8" face="Helvetica-Oblique">{l.strip()}</font>'
                for l in intro.split("\n") if l.strip()
            )
            cell_desc = _html(f"<b>{desc}</b><br/>{intro_lines}", base)
        else:
            cell_desc = _p(desc, base)

        if prix_txt == "OFFERT":
            cell_prix = _html(
                '<para align="right"><font color="#C8A028"><b>OFFERT</b></font></para>', base
            )
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
