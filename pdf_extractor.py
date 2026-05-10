"""Extraction de données structurées depuis un PDF de devis partenaire via Gemini."""
from __future__ import annotations

import base64
import json
import os
from typing import Any

import google.generativeai as genai

MODEL = "gemini-2.0-flash"

EXTRACTION_PROMPT = """Tu es un assistant chargé d'extraire les informations d'un devis de service après-vente horloger envoyé par une marque partenaire (Chanel, Tag Heuer, Breitling, Rolex, etc.) à la bijouterie DOUX Joaillier.

Lis attentivement le PDF et renvoie UNIQUEMENT un objet JSON valide (sans texte avant ou après, sans bloc markdown) avec EXACTEMENT cette structure :

{
  "marque": "nom de la marque détectée",
  "client": {
    "nom": "NOM PRENOM en majuscules ou chaîne vide si absent"
  },
  "sav": {
    "numero": "numéro de SAV / dossier / votre référence",
    "date": "JJ.MM.AAAA",
    "lieu": "Avignon"
  },
  "montre": {
    "modele": "nom du modèle",
    "reference": "référence boîtier",
    "numero_serie": "numéro de série",
    "poids": "",
    "metal": "",
    "taille": "",
    "etat": ["liste des constats / défauts observés, un par ligne, en MAJUSCULES"]
  },
  "interventions_necessaires": [
    {"description": "intitulé de la prestation", "prix": 0.00}
  ],
  "service_complet_description": "description complète du service complet si présente, sinon chaîne vide",
  "interventions_optionnelles": [
    {"description": "intitulé de la prestation optionnelle", "prix": 0.00}
  ],
  "total_ttc": 0.00,
  "delai": "4 à 6 semaines"
}

Règles :
- Convertis tous les prix en nombres décimaux (ex: "705,50" → 705.50, "OFFERT" → 0.00).
- Si le total TTC n'est pas explicite, additionne les prestations nécessaires.
- Pour la date, utilise le format JJ.MM.AAAA.
- Si le client n'apparaît pas dans le PDF, laisse "nom" vide.
- Le numéro de SAV correspond souvent à "Votre référence" ou un numéro à 6 chiffres.
- N'invente jamais de données : si une information est absente, mets une chaîne vide ou 0.
- Renvoie UNIQUEMENT le JSON, rien d'autre."""


def extract_from_pdf(pdf_bytes: bytes, api_key: str | None = None) -> dict[str, Any]:
    """Envoie le PDF à Gemini et renvoie un dict structuré."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Clé API Google manquante. "
            "Récupérez-la gratuitement sur aistudio.google.com."
        )

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL)

    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = model.generate_content([
        {
            "inline_data": {
                "mime_type": "application/pdf",
                "data": pdf_b64,
            }
        },
        EXTRACTION_PROMPT,
    ])

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse Gemini non-JSON : {raw[:500]}") from exc
