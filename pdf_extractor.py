"""Extraction de données structurées depuis un PDF de devis partenaire via Claude."""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-6"

EXTRACTION_PROMPT = """Tu es un assistant chargé d'extraire les informations d'un devis de service après-vente horloger envoyé par une marque partenaire à la bijouterie DOUX Joaillier (Avignon).

Renvoie UNIQUEMENT un objet JSON valide (sans texte avant ou après, sans bloc markdown) avec cette structure exacte :

{
  "marque": "Breitling" | "Chanel" | "Tag Heuer" | "Rolex" | "March LA.B" | "Autre",
  "client": {
    "nom": "NOM PRENOM en majuscules, ou chaîne vide si absent du document"
  },
  "sav": {
    "numero": "numéro SAV DOUX (6 chiffres, sans suffixe)",
    "date": "JJ.MM.AAAA",
    "lieu": "Avignon"
  },
  "montre": {
    "modele": "nom du modèle en majuscules",
    "reference": "référence boîtier",
    "numero_serie": "numéro de série ou matricule",
    "poids": "",
    "metal": "",
    "taille": "",
    "etat": ["CONSTAT 1 EN MAJUSCULES", "CONSTAT 2 EN MAJUSCULES"]
  },
  "service_complet_description": "sous-points du service complet, un par ligne (sans puces ni tirets)",
  "interventions_necessaires": [
    {"description": "INTITULÉ EN MAJUSCULES", "prix": 0.00}
  ],
  "interventions_optionnelles": [
    {"description": "INTITULÉ EN MAJUSCULES", "prix": 0.00}
  ],
  "total_ttc": 0.00,
  "delai": "X à Y semaines"
}

═══ NUMÉRO SAV DOUX ═══
Le numéro SAV DOUX est un nombre à 6 chiffres, parfois suivi d'un suffixe à ignorer :
- Breitling  → champ "Votre référence"   ex: "384054-1" → "384054"
- Tag Heuer  → champ "VOTRE REFERENCE"   ex: "383954-1" → "383954"
- Chanel     → champ "N° DEMANDE CLIENT" ex: "383750-1" → "383750"
- Rolex/autres → chercher un numéro à 6 chiffres dans les références
Supprime toujours le suffixe "-1", "-2", etc.

═══ COLONNE DE PRIX À UTILISER ═══
Chaque partenaire a plusieurs colonnes de prix — utilise UNIQUEMENT la colonne TTC public :
- Breitling  → colonne "Prix total TTC"       (ignorer "Total HT")
- Tag Heuer  → colonne "PRIX PUBLIC TTC"       (ignorer "VOTRE PRIX HT" et "VOTRE PRIX TTC")
- Chanel     → colonne "MONTANT TTC CONSEILLÉ" (ignorer "PRIX DE GROS HT")
- Rolex / March LA.B / autres → prendre le prix TTC affiché

═══ CONVERSION DES PRIX ═══
- Nombre décimal : "705,50" → 705.50 | "310.00" → 310.0
- Gratuit : "OFFERT" → 0.00 | "Incl." → 0.00 | "inclus au service" → 0.00 | "0,00" → 0.00
- Si le total TTC n'est pas explicite, additionner les prix des interventions nécessaires.

═══ ÉTAT DE LA MONTRE ═══
Lister les constats du diagnostic (rayures, chocs, défauts, usure...) EN MAJUSCULES, un par entrée.
Ne pas inclure le contenu du service (démontage, nettoyage...) dans l'état.
Pour Breitling : les constats sont dans le tableau "Diagnostic" (colonne gauche du modèle).

═══ SERVICE COMPLET ═══
Si la première intervention est un "service complet" ou "révision complète" avec sous-points :
- interventions_necessaires[0].description = intitulé principal EN MAJUSCULES
- service_complet_description = les sous-points, un par ligne, sans tirets ni puces
- Les lignes suivantes (couronne, joints, etc.) avec prix 0 ou "Incl." → prix: 0.00

═══ MODÈLE ═══
Si le nom du modèle n'est pas écrit, l'inférer de la référence si possible :
- H2569 → J12 | A3535016 → NAVITIMER HERITAGE | CJF7110 → FORMULA 1

═══ DÉLAI ═══
Extraire uniquement la durée, format "X semaines" ou "X à Y semaines" :
- "4 semaines après réception de votre accord" → "4 semaines"
- "6 À 8 SEMAINES SOUS RÉSERVE..." → "6 à 8 semaines"
- "4 à 6 semaines" → "4 à 6 semaines"

═══ DATE ═══
Format JJ.MM.AAAA. Si absente ou non trouvée, chaîne vide."""


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Post-traitement pour corriger les cas que le prompt rate parfois."""

    # SAV : supprimer le suffixe -1, -2, etc.
    sav = data.get("sav") or {}
    num = str(sav.get("numero") or "")
    num = re.sub(r"-\d+$", "", num).strip()
    sav["numero"] = num
    data["sav"] = sav

    # Prix : normaliser "Incl.", "inclus", "OFFERT", "0,00" → 0.0
    _ZERO_LABELS = {"incl.", "inclus", "offert", "0,00", "0.00", "0", ""}

    def _to_float(v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().lower().replace(",", ".")
        if s in _ZERO_LABELS:
            return 0.0
        try:
            return float(re.sub(r"[^\d.]", "", s))
        except ValueError:
            return 0.0

    for key in ("interventions_necessaires", "interventions_optionnelles"):
        lines = data.get(key) or []
        for line in lines:
            line["prix"] = _to_float(line.get("prix"))
        data[key] = lines

    data["total_ttc"] = _to_float(data.get("total_ttc"))

    # Recalcul total si manquant ou nul
    if data["total_ttc"] == 0.0:
        data["total_ttc"] = sum(
            l.get("prix") or 0.0 for l in (data.get("interventions_necessaires") or [])
        )

    # Délai : normaliser en minuscules
    delai = (data.get("delai") or "4 à 6 semaines").lower().strip()
    delai = re.sub(r"\s+", " ", delai)
    data["delai"] = delai

    return data


def extract_from_pdf(pdf_bytes: bytes, api_key: str | None = None) -> dict[str, Any]:
    """Envoie le PDF à Claude et renvoie un dict structuré."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Clé API Anthropic manquante. "
            "Récupérez-la sur console.anthropic.com."
        )

    client = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        timeout=60.0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": EXTRACTION_PROMPT,
                    },
                ],
            }
        ],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse Claude non-JSON : {raw[:500]}") from exc

    return _clean(data)
