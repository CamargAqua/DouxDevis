"""
Extraction PDF sans IA — pdfplumber + regex par marque.
Fonctionne 100% hors-ligne, aucune clé requise.
"""
from __future__ import annotations

import re
from typing import Any

import pdfplumber


def extract_from_pdf(pdf_bytes: bytes, api_key: str | None = None) -> dict[str, Any]:
    with pdfplumber.open(__import__("io").BytesIO(pdf_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    full_text = "\n".join(pages)

    brand = _detect_brand(full_text)
    parsers = {
        "Breitling":  _parse_breitling,
        "Chanel":     _parse_chanel,
        "Tag Heuer":  _parse_tag_heuer,
        "Rolex":      _parse_rolex,
    }
    parser = parsers.get(brand, _parse_generic)
    data = parser(full_text, pages)
    data["marque"] = brand
    return data


# ── Détection marque ─────────────────────────────────────────

def _detect_brand(text: str) -> str:
    t = text.upper()
    if "BREITLING" in t:  return "Breitling"
    if "CHANEL"   in t:  return "Chanel"
    if "TAG HEUER" in t: return "Tag Heuer"
    if "ROLEX"    in t:  return "Rolex"
    return "Autre"


# ── Helpers ──────────────────────────────────────────────────

def _find(pattern: str, text: str, group: int = 1, flags: int = re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""

def _price(text: str) -> float:
    m = re.search(r"(\d[\d\s]*[,\.]\d{2})", text)
    if not m: return 0.0
    return float(m.group(1).replace(" ", "").replace(",", "."))

def _fmt_date(raw: str) -> str:
    m = re.search(r"(\d{1,2})[/\.\-](\d{1,2})[/\.\-](\d{2,4})", raw)
    if not m: return raw
    j, mo, a = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3)
    if len(a) == 2: a = "20" + a
    return f"{j}.{mo}.{a}"

def _base() -> dict:
    return {
        "client":   {"nom": ""},
        "sav":      {"numero": "", "date": "", "lieu": "Avignon"},
        "montre":   {"modele": "", "reference": "", "numero_serie": "",
                     "poids": "", "metal": "", "taille": "", "etat": []},
        "service_complet_description": "",
        "interventions_necessaires":  [],
        "interventions_optionnelles": [],
        "total_ttc": 0.0,
        "delai":    "4 à 6 semaines",
    }


# ── BREITLING ─────────────────────────────────────────────────

def _parse_breitling(text: str, pages: list[str]) -> dict:
    d = _base()
    d["sav"]["numero"] = _find(r"Votre r[eé]f[eé]rence\s+(\S+)", text)
    d["sav"]["lieu"]   = "Avignon"

    raw_date = _find(r"Besan[cç]on\s+(\d{1,2}/\d{2}/\d{4})", text)
    d["sav"]["date"] = _fmt_date(raw_date)

    # Modèle / Référence / Série : ligne de tableau "NOM   REF   SERIE"
    # ex: "NAVITIMER HERITAGE A3535016/C538 424054"
    m_table = re.search(
        r"([A-Z][A-Z0-9 \-]+?)\s{2,}([A-Z0-9]+/[A-Z0-9]+)\s+(\d{5,})",
        text, re.IGNORECASE
    )
    if m_table:
        d["montre"]["modele"]       = m_table.group(1).strip().upper()
        d["montre"]["reference"]    = m_table.group(2).strip()
        d["montre"]["numero_serie"] = m_table.group(3).strip()
    else:
        d["montre"]["modele"]       = _find(r"([A-Z]{3,}(?:\s+[A-Z]+)+)\s+[A-Z0-9]+/", text)
        d["montre"]["reference"]    = _find(r"([A-Z0-9]{4,}/[A-Z0-9]+)", text)
        d["montre"]["numero_serie"] = _find(r"(?:N[°o]?\s*s[eé]rie|serie)\s+(\d{5,})", text, flags=re.IGNORECASE)

    # Constats état depuis tirets du diagnostic
    etat = []
    for line in pages[0].splitlines() if pages else []:
        stripped = line.strip()
        if stripped.startswith("- ") and len(stripped) > 4:
            etat.append(stripped[2:].upper())
    d["montre"]["etat"] = etat or ["VOIR DIAGNOSTIC"]

    # Prestations nécessaires (page 2)
    p2 = pages[1] if len(pages) > 1 else ""
    nec = []
    in_nec = False
    for line in p2.splitlines():
        if re.search(r"n[eé]cessaire", line, re.IGNORECASE):
            in_nec = True; continue
        if re.search(r"optionnel|TOTAL PREST", line, re.IGNORECASE):
            in_nec = False
        if not in_nec:
            continue
        m = re.match(r"(.+?)\s{2,}([\d\s,\.]+)\s+([\d\s,\.]+)$", line.strip())
        if m and "TOTAL" not in line.upper():
            desc = m.group(1).strip()
            prix = _price(m.group(3))
            if len(desc) > 3:
                nec.append({"description": desc.upper(), "prix": prix})
    d["interventions_necessaires"] = nec

    # Service complet description
    svc = re.search(r"Ce service comprend[:\s]+(.+?)(?=Echange|TOTAL|$)", p2, re.DOTALL | re.IGNORECASE)
    if svc:
        d["service_complet_description"] = svc.group(1).strip().replace("\n", " ")

    # Total
    tot = _find(r"TOTAL PRESTATIONS NECESSAIRES \(EUR\)\s+(\d[\d\s]*[,\.]\d{2})", p2)
    d["total_ttc"] = _price(tot) if tot else sum(l["prix"] for l in nec)

    # Optionnelles
    opt = []
    nec_descs = {n["description"] for n in nec}
    in_opt = False
    for line in p2.splitlines():
        if re.search(r"optionnel", line, re.IGNORECASE):
            in_opt = True; continue
        if not in_opt:
            continue
        m = re.match(r"(.+?)\s{2,}([\d\s,\.]+)\s+([\d\s,\.]+)$", line.strip())
        if m and "TOTAL" not in line.upper():
            desc = m.group(1).strip().upper()
            prix = _price(m.group(3))
            if prix > 0 and len(desc) > 3 and desc not in nec_descs:
                opt.append({"description": desc.upper(), "prix": prix})
    d["interventions_optionnelles"] = opt

    d["delai"] = _find(r"D[eé]lai.*?:\s*(.+?)(?:\n|après)", text) or "4 semaines"
    return d


# ── CHANEL ────────────────────────────────────────────────────

def _parse_chanel(text: str, pages: list[str]) -> dict:
    d = _base()
    d["sav"]["numero"] = _find(r"(?:Dossier|R[eé]f[eé]rence)[^\d]*(\d{5,})", text)
    d["sav"]["date"]   = _fmt_date(_find(r"(\d{1,2}[/\.\-]\d{2}[/\.\-]\d{4})", text))
    d["montre"]["modele"]       = _find(r"(?:Mod[eè]le|Montre)\s*[:\-]?\s*([^\n]+)", text)
    d["montre"]["reference"]    = _find(r"R[eé]f[eé]rence\s*[:\-]?\s*([\w/\-]+)", text)
    d["montre"]["numero_serie"] = _find(r"(?:N[°o]?\s*de?\s*s[eé]rie|S[eé]rie)\s*[:\-]?\s*([\w]+)", text)
    d["montre"]["etat"] = _extract_etat_generic(text)
    d["interventions_necessaires"] = _extract_prices_generic(text, "nécessaires")
    d["interventions_optionnelles"] = _extract_prices_generic(text, "optionnelles")
    d["total_ttc"] = _find_total(text)
    return d


# ── TAG HEUER ─────────────────────────────────────────────────

def _parse_tag_heuer(text: str, pages: list[str]) -> dict:
    d = _base()
    d["sav"]["numero"] = _find(r"(?:N[°o]?\s*dossier|R[eé]f)[^\d]*(\d{5,})", text)
    d["sav"]["date"]   = _fmt_date(_find(r"(\d{1,2}[/\.\-]\d{2}[/\.\-]\d{4})", text))
    d["montre"]["modele"]       = _find(r"(?:Mod[eè]le)\s*[:\-]?\s*([^\n]+)", text)
    d["montre"]["reference"]    = _find(r"R[eé]f[eé]rence\s*[:\-]?\s*([\w/\-]+)", text)
    d["montre"]["numero_serie"] = _find(r"(?:S[eé]rie|N[°o]?\s*de?\s*s[eé]rie)\s*[:\-]?\s*([\w]+)", text)
    d["montre"]["etat"] = _extract_etat_generic(text)
    d["interventions_necessaires"] = _extract_prices_generic(text, "nécessaires")
    d["interventions_optionnelles"] = _extract_prices_generic(text, "optionnelles")
    d["total_ttc"] = _find_total(text)
    return d


# ── ROLEX ─────────────────────────────────────────────────────

def _parse_rolex(text: str, pages: list[str]) -> dict:
    d = _base()
    d["sav"]["numero"] = _find(r"(?:Ref|N[°o]?)[^\d]*(\d{5,})", text)
    d["sav"]["date"]   = _fmt_date(_find(r"(\d{1,2}[/\.\-]\d{2}[/\.\-]\d{4})", text))
    d["montre"]["modele"]       = _find(r"(?:Mod[eè]le|Model)\s*[:\-]?\s*([^\n]+)", text)
    d["montre"]["reference"]    = _find(r"R[eé]f[eé]rence\s*[:\-]?\s*([\w/\-]+)", text)
    d["montre"]["numero_serie"] = _find(r"(?:S[eé]rie|Serial)\s*[:\-]?\s*([\w]+)", text)
    d["montre"]["etat"] = _extract_etat_generic(text)
    d["interventions_necessaires"] = _extract_prices_generic(text, "nécessaires")
    d["interventions_optionnelles"] = _extract_prices_generic(text, "optionnelles")
    d["total_ttc"] = _find_total(text)
    return d


# ── GÉNÉRIQUE (autre marque) ──────────────────────────────────

def _parse_generic(text: str, pages: list[str]) -> dict:
    d = _base()
    d["sav"]["date"]   = _fmt_date(_find(r"(\d{1,2}[/\.\-]\d{2}[/\.\-]\d{4})", text))
    d["montre"]["modele"]       = _find(r"(?:Mod[eè]le)\s*[:\-]?\s*([^\n]+)", text)
    d["montre"]["reference"]    = _find(r"R[eé]f[eé]rence\s*[:\-]?\s*([\w/\-]+)", text)
    d["montre"]["numero_serie"] = _find(r"(?:S[eé]rie|N[°o]?\s*de?\s*s[eé]rie)\s*[:\-]?\s*([\w]+)", text)
    d["montre"]["etat"] = _extract_etat_generic(text)
    d["interventions_necessaires"] = _extract_prices_generic(text, "nécessaires")
    d["interventions_optionnelles"] = _extract_prices_generic(text, "optionnelles")
    d["total_ttc"] = _find_total(text)
    return d


# ── Helpers communs ───────────────────────────────────────────

def _extract_etat_generic(text: str) -> list[str]:
    keywords = [
        "rayé", "marqué", "endommagé", "hors critères",
        "distendu", "cassé", "altéré", "usé", "tâché",
        "poussière", "arrêt", "précision"
    ]
    found = []
    for line in text.splitlines():
        for kw in keywords:
            if re.search(kw, line, re.IGNORECASE) and line.strip() not in found:
                found.append(line.strip().upper())
                break
    return found[:8]


def _extract_prices_generic(text: str, section: str) -> list[dict]:
    lines = []
    in_section = False
    for line in text.splitlines():
        if re.search(section, line, re.IGNORECASE):
            in_section = True
        elif in_section:
            m = re.match(r"(.{5,}?)\s{2,}(\d[\d\s]*[,\.]\d{2})\s+(\d[\d\s]*[,\.]\d{2})", line)
            if m and "TOTAL" not in line.upper():
                lines.append({
                    "description": m.group(1).strip().upper(),
                    "prix": _price(m.group(3)),
                })
            elif re.search(r"TOTAL|^\s*$", line) and in_section and lines:
                break
    return lines


def _find_total(text: str) -> float:
    m = re.search(r"TOTAL[^\d]*(\d[\d\s]*[,\.]\d{2})", text, re.IGNORECASE)
    return _price(m.group(1)) if m else 0.0


# ── Test rapide ───────────────────────────────────────────────

if __name__ == "__main__":
    import json, sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor_local.py chemin/vers/devis.pdf")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        result = extract_from_pdf(f.read())
    print(json.dumps(result, ensure_ascii=False, indent=2))
