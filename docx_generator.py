"""Génération du devis DOUX Joaillier au format .docx."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Cm, Pt, RGBColor


GREY_BG = "D9D9D9"
DOUX_GOLD = RGBColor(0xC8, 0xA8, 0x55)


def _set_cell_bg(cell, color_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    tc_pr.append(shd)


def _set_cell_borders(cell) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_borders = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        border = OxmlElement(f"w:{edge}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "4")
        border.set(qn("w:color"), "000000")
        tc_borders.append(border)
    tc_pr.append(tc_borders)


def _add_run(paragraph, text: str, *, bold: bool = False, italic: bool = False,
             size: int = 10, color: RGBColor | None = None) -> None:
    run = paragraph.add_run(text)
    run.font.name = "Arial"
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color


def _clear_paragraph(paragraph) -> None:
    for run in list(paragraph.runs):
        run.text = ""


def _add_header(doc: Document, marque: str) -> None:
    header_table = doc.add_table(rows=1, cols=2)
    header_table.autofit = False
    header_table.columns[0].width = Cm(9)
    header_table.columns[1].width = Cm(9)

    left = header_table.cell(0, 0)
    left.width = Cm(9)
    p = left.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _add_run(p, "DOUX", bold=True, size=44, color=RGBColor(0, 0, 0))
    sub = left.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _add_run(sub, "JOAILLIER", bold=True, size=12, color=DOUX_GOLD)

    right = header_table.cell(0, 1)
    right.width = Cm(9)
    p2 = right.paragraphs[0]
    p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _add_run(p2, marque.upper(), bold=True, size=24)
    doc.add_paragraph()


def _add_client_row(doc: Document, nom: str, sav: str, date_lieu: str) -> None:
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    widths = (Cm(6), Cm(5.5), Cm(6.5))
    for cell, width, text in zip(table.rows[0].cells, widths, (nom, f"SAV  {sav}", date_lieu)):
        cell.width = width
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        _add_run(p, text, size=11)


def _add_section_title(doc: Document, title: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    _set_cell_bg(cell, GREY_BG)
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(p, title, bold=True, size=11)
    run = p.runs[0]
    run.underline = True


def _add_montre_table(doc: Document, montre: dict[str, Any], photo_bytes: bytes | None,
                      marque: str = "") -> None:
    table = doc.add_table(rows=2, cols=4)
    table.style = "Table Grid"
    table.autofit = False
    widths = (Cm(5), Cm(4.5), Cm(4.5), Cm(4))
    for col_idx, width in enumerate(widths):
        for row in table.rows:
            row.cells[col_idx].width = width

    photo_cell = table.cell(0, 0)
    photo_cell.merge(table.cell(1, 0))
    photo_cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    photo_p = photo_cell.paragraphs[0]
    photo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if photo_bytes:
        run = photo_p.add_run()
        try:
            run.add_picture(BytesIO(photo_bytes), width=Cm(4.5))
        except Exception:
            _add_run(photo_p, "[photo invalide]", italic=True, size=9)
    else:
        _add_run(photo_p, "", size=9)

    for col, label in enumerate(("POIDS :", "METAL :", "TAILLE :"), start=1):
        cell = table.cell(0, col)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        p = cell.paragraphs[0]
        _add_run(p, f"{label} {montre.get(label.split()[0].lower(), '')}", size=10)

    info_cell = table.cell(1, 1)
    info_cell.merge(table.cell(1, 3))
    info_cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
    _clear_paragraph(info_cell.paragraphs[0])

    first_lines: list[str] = []
    if montre.get("modele"):
        first_lines.append(montre["modele"].upper())
    if montre.get("reference"):
        first_lines.append(montre["reference"])
    if montre.get("numero_serie"):
        first_lines.append(f"N° SÉRIE : {montre['numero_serie']}")

    etat_lines = montre.get("etat") or []
    if isinstance(etat_lines, str):
        etat_lines = [line.strip() for line in etat_lines.splitlines() if line.strip()]

    all_lines = first_lines + list(etat_lines)
    if not all_lines:
        # Aucune info montre : phrase par défaut avec marque et modèle
        default = f"Montre {marque.upper()}"
        if montre.get("modele"):
            default += f" — {montre['modele'].upper()}"
        all_lines = [default]

    first = True
    for line in all_lines:
        para = info_cell.paragraphs[0] if first else info_cell.add_paragraph()
        first = False
        _add_run(para, line.upper() if line else "", size=10)


def _add_work_table(doc: Document, title: str, lines: list[dict[str, Any]],
                    *, total_label: str | None = None, total_value: float | None = None,
                    intro: str | None = None) -> None:
    header = doc.add_table(rows=1, cols=2)
    header.style = "Table Grid"
    header.autofit = False
    header.columns[0].width = Cm(14)
    header.columns[1].width = Cm(4)
    h_left = header.cell(0, 0)
    h_right = header.cell(0, 1)
    h_left.width = Cm(14)
    h_right.width = Cm(4)
    _set_cell_bg(h_left, GREY_BG)
    _set_cell_bg(h_right, GREY_BG)
    p_left = h_left.paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(p_left, title, bold=True, size=11)
    p_left.runs[0].underline = True
    p_right = h_right.paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(p_right, "PRIX TTC EN EUR", bold=True, size=10)
    p_right.runs[0].underline = True

    body_rows = max(len(lines), 1)
    body = doc.add_table(rows=body_rows, cols=2)
    body.style = "Table Grid"
    body.autofit = False
    body.columns[0].width = Cm(14)
    body.columns[1].width = Cm(4)

    for i, line in enumerate(lines):
        desc_cell = body.cell(i, 0)
        price_cell = body.cell(i, 1)
        desc_cell.width = Cm(14)
        price_cell.width = Cm(4)
        _clear_paragraph(desc_cell.paragraphs[0])

        description = (line.get("description") or "").strip()
        if i == 0 and intro:
            p = desc_cell.paragraphs[0]
            _add_run(p, description.upper() if description else "", bold=True, size=10)
            for intro_line in intro.split("\n"):
                if intro_line.strip():
                    extra = desc_cell.add_paragraph()
                    _add_run(extra, intro_line.strip(), italic=True, size=9)
        else:
            p = desc_cell.paragraphs[0]
            _add_run(p, description.upper(), size=10)

        price_p = price_cell.paragraphs[0]
        price_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        prix = line.get("prix", 0)
        prix_text = line.get("prix_label") or _format_price(prix)
        _add_run(price_p, prix_text, size=10)

    if not lines:
        empty = body.cell(0, 0)
        _add_run(empty.paragraphs[0], "", size=10)

    if total_label is not None and total_value is not None:
        total = doc.add_table(rows=1, cols=2)
        total.style = "Table Grid"
        total.autofit = False
        total.columns[0].width = Cm(14)
        total.columns[1].width = Cm(4)
        tl = total.cell(0, 0)
        tr = total.cell(0, 1)
        tl.width = Cm(14)
        tr.width = Cm(4)
        p = tl.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _add_run(p, total_label, italic=True, bold=True, size=10)
        p2 = tr.paragraphs[0]
        p2.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _add_run(p2, _format_price(total_value), bold=True, size=10)


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
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", " ")


def _add_footer_block(doc: Document, delai: str) -> None:
    p = doc.add_paragraph()
    _add_run(p, f"DELAIS APRES ACCORD {delai.upper()} SOUS RESERVE DE DISPONIBILITE DES PIECES",
             size=9)

    table = doc.add_table(rows=2, cols=2)
    table.autofit = False
    table.columns[0].width = Cm(11)
    table.columns[1].width = Cm(7)

    for row in table.rows:
        for cell in row.cells:
            for edge in ("top", "left", "bottom", "right"):
                tc_pr = cell._tc.get_or_add_tcPr()
                borders = tc_pr.find(qn("w:tcBorders"))
                if borders is None:
                    borders = OxmlElement("w:tcBorders")
                    tc_pr.append(borders)
                b = OxmlElement(f"w:{edge}")
                b.set(qn("w:val"), "nil")
                borders.append(b)

    accord = table.cell(0, 0)
    refus = table.cell(1, 0)
    _add_run(accord.paragraphs[0], "☐  ACCORD AU DEVIS", size=10)
    p_refus = refus.paragraphs[0]
    _add_run(p_refus, "☐  REFUS DU DEVIS    ", size=10)
    _add_run(p_refus, "(30€ FRAIS DE REFUS)", bold=True, size=9)

    sig_cell = table.cell(0, 1)
    sig_cell.merge(table.cell(1, 1))
    _set_cell_borders(sig_cell)
    _add_run(sig_cell.paragraphs[0], "DATE ET SIGNATURE :", size=10)
    sig_cell.add_paragraph()
    sig_cell.add_paragraph()

    doc.add_paragraph()
    legal = doc.add_paragraph()
    legal.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(legal,
             "SARL DOUX Développement au Capital de 15 245 € - R.C. Avignon 65 A 59 – Siret 315 215 442 00023 – APE 4777 Z – TVA",
             size=8)
    legal2 = doc.add_paragraph()
    legal2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_run(legal2, "Intracommunautaire FR 313 152 15442  ", size=8)
    _add_run(legal2, "sav@douxjoaillier.com", size=8, color=RGBColor(0x05, 0x63, 0xC1))


def build_docx(data: dict[str, Any], photo_bytes: bytes | None = None) -> bytes:
    """Construit le devis DOUX et renvoie le contenu binaire .docx."""
    doc = Document()

    for section in doc.sections:
        section.top_margin = Cm(1.2)
        section.bottom_margin = Cm(1.2)
        section.left_margin = Cm(1.5)
        section.right_margin = Cm(1.5)

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)

    marque = data.get("marque") or "PARTENAIRE"
    client = data.get("client") or {}
    sav = data.get("sav") or {}
    montre = data.get("montre") or {}

    _add_header(doc, marque)

    # Titre "DEVIS DE RÉPARATION"
    titre = doc.add_paragraph()
    titre.alignment = WD_ALIGN_PARAGRAPH.CENTER
    titre.paragraph_format.space_before = Pt(4)
    titre.paragraph_format.space_after = Pt(4)
    _add_run(titre, "DEVIS DE RÉPARATION", bold=True, size=14)

    _add_client_row(
        doc,
        nom=(client.get("nom") or "").upper(),
        sav=sav.get("numero", ""),
        date_lieu=f"Le {sav.get('date', '')} à {sav.get('lieu', 'Avignon')}",
    )

    _add_section_title(doc, "INFORMATIONS DE LA MONTRE")
    _add_montre_table(doc, montre, photo_bytes, marque=marque)

    necessaires = data.get("interventions_necessaires") or []
    intro = (data.get("service_complet_description") or "").strip() or None
    total_ttc = data.get("total_ttc")
    if total_ttc in (None, "", 0) and necessaires:
        try:
            total_ttc = sum(float(line.get("prix") or 0) for line in necessaires)
        except (TypeError, ValueError):
            total_ttc = 0

    _add_work_table(
        doc,
        "TRAVAIL À RÉALISER",
        necessaires,
        total_label="TOTAL TTC EN EURO",
        total_value=total_ttc,
        intro=intro,
    )

    optionnelles = data.get("interventions_optionnelles") or []
    if optionnelles:
        _add_work_table(doc, "TRAVAIL OPTIONNEL", optionnelles)

    _add_footer_block(doc, delai=data.get("delai") or "4 à 6 semaines")

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
