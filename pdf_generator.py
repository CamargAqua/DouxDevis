"""Génération PDF via reportlab — autonome, aucune dépendance externe."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _format_price(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            return value
    if value == 0:
        return "OFFERT"
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _para(text: str, style: ParagraphStyle) -> Paragraph:
    safe = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe = safe.replace("\n", "<br/>")
    return Paragraph(safe, style)


def render_pdf(data: dict[str, Any], photo_bytes: bytes | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12)
    bold = ParagraphStyle("bold", parent=base, fontName="Helvetica-Bold")
    italic_s = ParagraphStyle("italic", parent=base, fontName="Helvetica-Oblique", fontSize=8, leading=10)
    small = ParagraphStyle("small", parent=base, fontSize=7.5, alignment=1)
    center_bold = ParagraphStyle("cbold", parent=bold, alignment=1, fontSize=10)
    right_n = ParagraphStyle("rightn", parent=base, alignment=2)
    right_b = ParagraphStyle("rightb", parent=bold, alignment=2)

    story: list[Any] = []

    # ── En-tête ──────────────────────────────────────────────────────────────
    marque = (data.get("marque") or "PARTENAIRE").upper()
    hdr = Table([[
        Paragraph('<font size="30" name="Helvetica-Bold"><b>DOUX</b></font>'
                  '<br/><font size="9" color="#C8A855"><b>JOAILLIER</b></font>', base),
        Paragraph(f'<para align="right"><font size="18"><b>{marque}</b></font></para>', base),
    ]], colWidths=[9 * cm, 9 * cm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 5 * mm))

    # ── Ligne client ─────────────────────────────────────────────────────────
    client = data.get("client") or {}
    sav = data.get("sav") or {}
    nom = (client.get("nom") or "").upper()
    num = sav.get("numero", "")
    date = sav.get("date", "")
    lieu = sav.get("lieu", "Avignon")

    cl = Table([[
        _para(nom, bold),
        _para(f"SAV  {num}", bold),
        _para(f"Le {date} à {lieu}", bold),
    ]], colWidths=[6 * cm, 5.5 * cm, 6.5 * cm])
    cl.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(cl)

    # ── Section INFORMATIONS DE LA MONTRE ────────────────────────────────────
    story.append(Table([[Paragraph("INFORMATIONS DE LA MONTRE", center_bold)]],
                       colWidths=[18 * cm]))
    story[-1].setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#D9D9D9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    montre = data.get("montre") or {}
    photo_cell: Any = ""
    if photo_bytes:
        try:
            img = Image(BytesIO(photo_bytes))
            img._restrictSize(4.5 * cm, 5 * cm)
            photo_cell = img
        except Exception:
            photo_cell = _para("[photo]", base)

    etat = montre.get("etat") or []
    if isinstance(etat, str):
        etat = [l.strip() for l in etat.splitlines() if l.strip()]

    info_lines: list[str] = []
    for key in ("modele", "reference"):
        if montre.get(key):
            info_lines.append(montre[key].upper())
    if montre.get("numero_serie"):
        info_lines.append(f"N° SÉRIE : {montre['numero_serie']}")
    info_lines += [l.upper() for l in etat]

    montre_tbl = Table([
        [photo_cell,
         _para(f"POIDS : {montre.get('poids', '')}", base),
         _para(f"METAL : {montre.get('metal', '')}", base),
         _para(f"TAILLE : {montre.get('taille', '')}", base)],
        ["", _para("\n".join(info_lines), base), "", ""],
    ], colWidths=[5 * cm, 4.5 * cm, 4.5 * cm, 4 * cm],
       rowHeights=[1.2 * cm, None])
    montre_tbl.setStyle(TableStyle([
        ("SPAN", (0, 0), (0, 1)),
        ("SPAN", (1, 1), (3, 1)),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, 1), "CENTER"),
        ("VALIGN", (0, 0), (0, 1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(montre_tbl)

    # ── TRAVAIL NECESSAIRE ────────────────────────────────────────────────────
    story.append(Table([[
        Paragraph("TRAVAIL NECESSAIRE", center_bold),
        Paragraph("PRIX TTC EN EUR", center_bold),
    ]], colWidths=[14 * cm, 4 * cm]))
    story[-1].setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#D9D9D9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    necessaires = data.get("interventions_necessaires") or []
    intro = (data.get("service_complet_description") or "").strip()
    rows = []
    for i, line in enumerate(necessaires):
        desc = (line.get("description") or "").upper()
        if i == 0 and intro:
            intro_html = "<br/>".join(
                f'<font size="8"><i>{l.strip()}</i></font>'
                for l in intro.split("\n") if l.strip()
            )
            cell = Paragraph(f"<b>{desc}</b><br/>{intro_html}", base)
        else:
            cell = _para(desc, base)
        prix_text = line.get("prix_label") or _format_price(line.get("prix"))
        rows.append([cell, _para(prix_text, right_n)])

    if not rows:
        rows = [[_para("", base), _para("", base)]]

    body = Table(rows, colWidths=[14 * cm, 4 * cm])
    body.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(body)

    total_ttc = data.get("total_ttc")
    if total_ttc in (None, "", 0) and necessaires:
        try:
            total_ttc = sum(float(l.get("prix") or 0) for l in necessaires)
        except (TypeError, ValueError):
            total_ttc = 0

    tot = Table([[_para("<i><b>TOTAL TTC EN EURO</b></i>", right_b),
                  _para(_format_price(total_ttc), right_b)]],
                colWidths=[14 * cm, 4 * cm])
    tot.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tot)

    # ── TRAVAIL OPTIONNEL ─────────────────────────────────────────────────────
    optionnelles = data.get("interventions_optionnelles") or []
    if optionnelles:
        story.append(Table([[Paragraph("TRAVAIL OPTIONNEL", center_bold)]],
                           colWidths=[18 * cm]))
        story[-1].setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#D9D9D9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        opt_rows = [[
            _para(f"☐  <b>{(l.get('description') or '').upper()}</b>", base),
            _para(l.get("prix_label") or _format_price(l.get("prix")), right_n),
        ] for l in optionnelles]
        opt_tbl = Table(opt_rows, colWidths=[14 * cm, 4 * cm])
        opt_tbl.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        story.append(opt_tbl)

    # ── Pied de page ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    delai = (data.get("delai") or "4 à 6 semaines").upper()
    story.append(_para(
        f'<font size="8">DELAIS APRES ACCORD {delai} SOUS RESERVE DE DISPONIBILITE DES PIECES</font>',
        base,
    ))
    story.append(Spacer(1, 3 * mm))

    sig = Table([
        [_para("☐  ACCORD AU DEVIS", base), _para("DATE ET SIGNATURE :", base)],
        [_para('☐  REFUS DU DEVIS    <b><font size="8">(30€ FRAIS DE REFUS)</font></b>', base), ""],
    ], colWidths=[11 * cm, 7 * cm], rowHeights=[1 * cm, 1.6 * cm])
    sig.setStyle(TableStyle([
        ("BOX", (1, 0), (1, 1), 0.5, colors.black),
        ("SPAN", (1, 0), (1, 1)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(sig)

    story.append(Spacer(1, 6 * mm))
    story.append(_para(
        "SARL DOUX Développement au Capital de 15 245 € — R.C. Avignon 65 A 59 "
        "— Siret 315 215 442 00023 — APE 4777 Z — TVA Intracommunautaire FR 313 152 15442 "
        "— sav@douxjoaillier.com",
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
