"""Extraction de données structurées depuis un PDF de devis partenaire via Claude."""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-5"

EXTRACTION_SYSTEM = """Tu es un assistant chargé d'extraire les informations d'un devis de service après-vente (horlogerie ou joaillerie) envoyé par une marque partenaire à la bijouterie DOUX Joaillier (Avignon).

Le document peut être un PDF structuré ou un email en texte libre.

Renvoie UNIQUEMENT un objet JSON valide (sans texte avant ou après, sans bloc markdown) avec cette structure exacte :

{
  "marque": "Nom exact de la marque",
  "client": {
    "nom": "NOM PRENOM en majuscules, ou chaîne vide si absent du document"
  },
  "sav": {
    "numero": "numéro SAV DOUX (6 chiffres, sans suffixe)",
    "date": "JJ.MM.AAAA",
    "lieu": "Avignon"
  },
  "montre": {
    "modele": "nom du modèle ou du bijou en majuscules (ex: NAVITIMER, BAGUE FORCE10, PENDENTIF HAPPY DIAMONDS)",
    "reference": "référence boîtier ou référence article",
    "numero_serie": "numéro de série, matricule ou gravure",
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


═══ LANGUE — TRADUCTION EN FRANÇAIS (OBLIGATOIRE) ═══
Le devis final est destiné à un client français. Si le document source est rédigé dans une autre langue (anglais, allemand, italien...) :
  → Traduis EN FRANÇAIS tout le texte libre que tu extrais : descriptions des interventions, état/constats du diagnostic, modèle (si c'est une description et non un nom propre), sous-points du service complet, délai.
  → NE traduis PAS : le nom de la marque, les noms propres de modèles/collections (NAVITIMER, J12, HAPPY DIAMONDS...), les références, numéros de série, numéros SAV.
  → EXEMPLE : "Full service movement" → "RÉVISION COMPLÈTE DU MOUVEMENT" | "Scratches on the case" → "RAYURES SUR LE BOÎTIER" | "Crown replacement" → "REMPLACEMENT DE LA COURONNE"
  → Conserve la règle des MAJUSCULES pour les descriptions et l'état.

═══ RECONNAISSANCE DE LA MARQUE ═══
Identifie la marque à partir du logo, de l'en-tête, du nom mentionné dans le document, de l'expéditeur de l'email, ou du nom de fichier.
Exemples de valeurs attendues (respecter la casse) :
  Horlogerie : "Breitling", "Chanel", "TAG Heuer", "Rolex", "March LA.B", "Omega", "IWC Schaffhausen", "Audemars Piguet", "Patek Philippe", "Cartier", "Tudor", "Longines"
  Joaillerie  : "Pomellato", "Fred", "Ginette NY", "Chopard", "Van Cleef & Arpels", "Boucheron", "Chaumet", "Mauboussin", "Dior Joaillerie"
  "Autre"     uniquement si la marque est vraiment illisible ou inconnue

═══ NUMÉRO SAV DOUX ═══
Le numéro SAV DOUX est un nombre à 6 chiffres, parfois suivi d'un suffixe à ignorer :
- Breitling  → champ "Votre référence"   ex: "384054-1" → "384054"
- TAG Heuer  → champ "VOTRE REFERENCE"   ex: "383954-1" → "383954"
- Chanel     → champ "N° DEMANDE CLIENT" ex: "383750-1" → "383750"
- Rolex/autres → chercher un numéro à 6 chiffres dans les références
- Emails → chercher dans l'objet ou le corps : "SAV 330624-1" → "330624"
Supprime toujours le suffixe "-1", "-2", etc.

═══ ⚠️ RÈGLE UNIVERSELLE — PRIX HT OBLIGATOIRE (NE PAS IGNORER) ⚠️ ═══
Pour TOUTES les marques, sans exception :
  → Tu DOIS extraire le prix HORS TAXES (HT) — jamais le prix TTC
  → Le coefficient appliqué par DOUX convertit HT → TTC client : ne pas faire cette conversion toi-même
  → Si le document affiche à la fois HT et TTC, prendre UNIQUEMENT le HT
  → EXEMPLE : PU HT = 1 021,00 € et PU TTC = 1 225,20 € → retourner 1021.00 — PAS 1225.20

Colonnes/libellés HT à reconnaître (toutes variantes) :
  Français  : "HT", "H.T.", "Hors Taxe", "Hors TVA", "Prix HT", "Montant HT",
              "Total HT", "PU HT", "Prix unitaire HT", "Net HT", "Prix de gros HT",
              "Votre prix HT", "Prix public HT", "Tarif HT"
  Anglais   : "Ex VAT", "Excl. VAT", "Excl VAT", "Net", "Before Tax", "Ex Tax",
              "Unit price (ex VAT)", "Price excl. tax", "Net price", "Wholesale"
  Allemand  : "Netto", "zzgl. MwSt", "ohne MwSt"

Si le document ne montre QUE des prix TTC (aucune colonne HT) :
  → Diviser par 1.20 pour obtenir le HT : prix_ht = prix_ttc / 1.20
  → Arrondir à 2 décimales

═══ ⚠️ EMAILS AVEC PRIX HT — RÈGLE ABSOLUE ⚠️ ═══
Si le document est un email et que les prix sont exprimés en HT (ex: "28€HT", "270 €HT", "42€") :
  → Extraire le prix HT tel quel (ne PAS ajouter la TVA)
  → Le prix public recommandé TTC (entre parenthèses) est à IGNORER
  → EXEMPLE : "270 €HT (prix public recommandé 530 €TTC)" → total_ttc: 270.00
  → EXEMPLE : "DEVIS 1: ECHANGE PENDENTIF A NEUF: 42€" → interventions_necessaires[0].prix: 42.00, total_ttc: 42.00
Pour les emails avec plusieurs options (séparées par //// ou numérotées) : la première est interventions_necessaires, les suivantes sont interventions_optionnelles.

═══ LISTE D'INTERVENTIONS AVEC UN SEUL PRIX GLOBAL ═══
Si l'email liste plusieurs interventions de détail (tirets/puces) SANS prix individuel, et qu'un prix global unique est donné ensuite :
  → Ne pas créer une ligne par intervention
  → Créer UNE SEULE entrée dans interventions_necessaires avec "SERVICE COMPLET" ou "RÉVISION COMPLÈTE" comme description (jamais le nom de l'objet)
  → Mettre le prix global dans cette ligne
  → Copier les items de détail dans service_complet_description (un par ligne, sans tirets ni puces)
  → EXEMPLE (email Fred) : 6 items détaillés + "270 €HT" global
    → interventions_necessaires: [{"description": "SERVICE COMPLET", "prix": 270.00}]
    → service_complet_description: "diagnostic\nfournitures des 3 pierres\ncontrôle du serti\nremise en forme et soudure\npolissage\ncontrôle technique et esthétique"

═══ CONVERSION DES PRIX ═══
- Nombre décimal : "705,50" → 705.50 | "310.00" → 310.0
- Gratuit : "OFFERT" → 0.00
- Inclus dans le prix : "Incl." | "inclus" | "inclus au service" → mettre la valeur "INCL" (chaîne, pas un nombre)
- Si le total HT n'est pas explicite, additionner les prix HT des interventions nécessaires.

═══ ÉTAT DE LA MONTRE OU DU BIJOU ═══
Lister les constats du diagnostic (rayures, chocs, défauts, usure...) EN MAJUSCULES, un par entrée.
Ne pas inclure le contenu du service (démontage, nettoyage...) dans l'état.
Pour Breitling : les constats sont dans le tableau "Diagnostic" (colonne gauche du modèle).
Si le diagnostic est dans le corps d'un email (tirets, liste) : extraire chaque point.

═══ SERVICE COMPLET ═══
Si la première intervention est un "service complet" ou "révision complète" avec sous-points :
- interventions_necessaires[0].description = intitulé principal EN MAJUSCULES
- service_complet_description = les sous-points, un par ligne, sans tirets ni puces
- Les lignes suivantes (couronne, joints, etc.) avec prix 0 → prix: 0.00

═══ MODÈLE ═══
Si le nom du modèle n'est pas écrit, l'inférer de la référence si possible :
- H2569 → J12 | A3535016 → NAVITIMER HERITAGE | CJF7110 → FORMULA 1
Pour un bijou : utiliser la description complète (ex: "BAGUE FORCE10 RUBAN PM OR ROSE").

═══ DÉLAI ═══
Extraire uniquement la durée, format "X semaines" ou "X à Y semaines" :
- "4 semaines après réception de votre accord" → "4 semaines"
- "6 À 8 SEMAINES SOUS RÉSERVE..." → "6 à 8 semaines"
- "10 jours" → "10 jours"

═══ DATE ═══
Format JJ.MM.AAAA. Si absente ou non trouvée, chaîne vide."""



# ── Normalisation des variantes de marques ──────────────────────────────────
_BRAND_CANONICAL: dict[str, str] = {
    "breitling": "Breitling",
    "chanel": "Chanel",
    "tag heuer": "TAG Heuer",
    "tag-heuer": "TAG Heuer",
    "tagheuer": "TAG Heuer",
    "tag_heuer": "TAG Heuer",
    "rolex": "Rolex",
    "march la.b": "March LA.B",
    "march lab": "March LA.B",
    "march l.a.b": "March LA.B",
    "march la.b.": "March LA.B",
    "omega": "Omega",
    "cartier": "Cartier",
    "iwc": "IWC Schaffhausen",
    "iwc schaffhausen": "IWC Schaffhausen",
    "patek philippe": "Patek Philippe",
    "patek": "Patek Philippe",
    "audemars piguet": "Audemars Piguet",
    "ap": "Audemars Piguet",
    "vacheron constantin": "Vacheron Constantin",
    "vacheron": "Vacheron Constantin",
    "jaeger-lecoultre": "Jaeger-LeCoultre",
    "jaeger lecoultre": "Jaeger-LeCoultre",
    "jaeger": "Jaeger-LeCoultre",
    "jlc": "Jaeger-LeCoultre",
    "a. lange & söhne": "A. Lange & Söhne",
    "a. lange & sohne": "A. Lange & Söhne",
    "lange": "A. Lange & Söhne",
    "hublot": "Hublot",
    "tudor": "Tudor",
    "longines": "Longines",
    "panerai": "Panerai",
    "zenith": "Zenith",
    "blancpain": "Blancpain",
    "girard-perregaux": "Girard-Perregaux",
    "girard perregaux": "Girard-Perregaux",
    "chopard": "Chopard",
    "grand seiko": "Grand Seiko",
    "piaget": "Piaget",
    "bvlgari": "Bvlgari",
    "bulgari": "Bvlgari",
    "richard mille": "Richard Mille",
    "breguet": "Breguet",
    "frederique constant": "Frederique Constant",
    "fred. constant": "Frederique Constant",
    "hermes": "Hermès",
    "hermès": "Hermès",
    "louis vuitton": "Louis Vuitton",
    "lv": "Louis Vuitton",
    "pomellato": "Pomellato",
    "ginette ny": "Ginette NY",
    "ginette-ny": "Ginette NY",
    "fred": "Fred",
    "fred joaillier": "Fred",
    "van cleef": "Van Cleef & Arpels",
    "van cleef & arpels": "Van Cleef & Arpels",
    "boucheron": "Boucheron",
    "chaumet": "Chaumet",
    "mauboussin": "Mauboussin",
    "dior joaillerie": "Dior Joaillerie",
    "dior fine jewelry": "Dior Joaillerie",

}

# ── Détection de marque depuis texte libre (nom de fichier, etc.) ────────────
# Ordonné du plus spécifique au plus générique pour éviter les faux positifs
_BRAND_DETECT: list[tuple[str, str]] = [
    ("TAG Heuer",           r"tag[\s\-_]?heuer"),
    ("Patek Philippe",      r"patek(?:[\s\-_]?philippe)?"),
    ("Audemars Piguet",     r"audemars(?:[\s\-_]?piguet)?"),
    ("Vacheron Constantin", r"vacheron(?:[\s\-_]?constantin)?"),
    ("Jaeger-LeCoultre",    r"jaeger|lecoultre|j[\-\._]?l[\-\._]?c\b"),
    ("A. Lange & Söhne",    r"a[\.\s]?lange"),
    ("Richard Mille",       r"richard[\s\-_]?mille"),
    ("March LA.B",          r"march[\s\-_]?la\.?b"),
    ("Girard-Perregaux",    r"girard[\s\-_]?perregaux"),
    ("Frederique Constant", r"frederique[\s\-_]?constant"),
    ("Grand Seiko",         r"grand[\s\-_]?seiko"),
    ("Breitling",           r"breitling"),
    ("Chanel",              r"chanel"),
    ("Rolex",               r"rolex"),
    ("Omega",               r"omega"),
    ("Cartier",             r"cartier"),
    ("IWC Schaffhausen",    r"iwc"),
    ("Longines",            r"longines"),
    ("Tudor",               r"tudor"),
    ("Hublot",              r"hublot"),
    ("Panerai",             r"panerai"),
    ("Zenith",              r"zenith"),
    ("Blancpain",           r"blancpain"),
    ("Chopard",             r"chopard"),
    ("Piaget",              r"piaget"),
    ("Bvlgari",             r"bvlgari|bulgari"),
    ("Breguet",             r"breguet"),
    ("Hermès",              r"herm[eè]s"),
    ("Louis Vuitton",       r"louis[\s\-_]?vuitton"),
    ("Pomellato",          r"pomellato"),
    ("Ginette NY",          r"ginette[\s\-_]?ny"),
    ("Fred",                r"\bfred(?:\s+joaillier)?\b"),
    ("Van Cleef & Arpels",  r"van[\s\-_]?cleef"),
    ("Boucheron",           r"boucheron"),
    ("Chaumet",             r"chaumet"),
    ("Mauboussin",          r"mauboussin"),
    ("Dior Joaillerie",     r"dior(?:[\s\-_]?joaillerie|[\s\-_]?fine[\s\-_]?jewelry)?"),

]


def _detect_brand_from_text(text: str) -> str | None:
    """Détecte une marque dans un nom de fichier ou texte libre. Retourne None si rien trouvé."""
    t = text.lower()
    for brand, pattern in _BRAND_DETECT:
        if re.search(pattern, t):
            return brand
    return None


def _normalize_brand(brand: str) -> str:
    return _BRAND_CANONICAL.get(brand.strip().lower(), brand.strip())


def _clean(data: dict[str, Any]) -> dict[str, Any]:
    """Post-traitement pour corriger les cas que le prompt rate parfois."""

    # Marque : normaliser la casse / variantes
    data["marque"] = _normalize_brand(data.get("marque") or "Autre")

    # SAV : supprimer le suffixe -1, -2, etc.
    sav = data.get("sav") or {}
    num = str(sav.get("numero") or "")
    num = re.sub(r"-\d+$", "", num).strip()
    sav["numero"] = num
    data["sav"] = sav

    _INCL_LABELS = {"incl.", "incl", "inclus", "included", "compris", "comprise"}
    _ZERO_LABELS = {"offert", "0,00", "0.00", "0", ""}

    def _to_float(v: Any) -> float:
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().lower().replace(",", ".")
        if s in _ZERO_LABELS or s in _INCL_LABELS:
            return 0.0
        try:
            return float(re.sub(r"[^\d.]", "", s))
        except ValueError:
            return 0.0

    _INCL_DESC_KEYWORDS = ("inclus", "included", "compris", "comprise")

    for key in ("interventions_necessaires", "interventions_optionnelles"):
        lines = data.get(key) or []
        for line in lines:
            raw = line.get("prix")
            raw_str = str(raw).strip().lower() if raw is not None else ""
            if raw_str in _INCL_LABELS:
                line["prix"] = 0.0
                if not line.get("prix_label"):
                    line["prix_label"] = "INCL"
            else:
                line["prix"] = _to_float(raw)
                # Si prix == 0 et description contient un mot-clé "inclus"
                if line["prix"] == 0.0 and not line.get("prix_label"):
                    desc_lower = (line.get("description") or "").lower()
                    if any(kw in desc_lower for kw in _INCL_DESC_KEYWORDS):
                        line["prix_label"] = "INCL"
        data[key] = lines

    data["total_ttc"] = _to_float(data.get("total_ttc"))

    # Recalcul total si manquant ou nul
    if data["total_ttc"] == 0.0:
        data["total_ttc"] = sum(
            l.get("prix") or 0.0 for l in (data.get("interventions_necessaires") or [])
        )

    # Fallback prix : si total_ttc > 0 mais toutes les interventions sont à 0,
    # mettre le total sur la première intervention (cas email avec prix global)
    nec = data.get("interventions_necessaires") or []
    if data["total_ttc"] > 0 and nec:
        sum_prix = sum(
            l.get("prix") or 0.0
            for l in nec
            if not l.get("prix_label")  # ignorer OFFERT/INCL
        )
        if sum_prix == 0.0:
            # Trouver la première ligne sans label
            for line in nec:
                if not line.get("prix_label"):
                    line["prix"] = data["total_ttc"]
                    break

    # Délai : normaliser en minuscules
    delai = (data.get("delai") or "4 à 6 semaines").lower().strip()
    delai = re.sub(r"\s+", " ", delai)
    data["delai"] = delai

    return data


def confidence_score(data: dict[str, Any]) -> tuple[int, list[str]]:
    """Retourne (score/10, liste des champs manquants ou invalides).

    Appelé sur les données finales du formulaire (après correction manuelle).
    """
    sav = data.get("sav") or {}
    montre = data.get("montre") or {}
    client = data.get("client") or {}
    missing: list[str] = []

    checks = [
        (
            (data.get("marque") or "").lower() not in ("", "autre"),
            "Marque non identifiée",
        ),
        (
            bool((client.get("nom") or "").strip()),
            "Nom client absent",
        ),
        (
            bool(re.match(r"^\d{6}$", str(sav.get("numero") or "").strip())),
            "N° SAV invalide ou absent",
        ),
        (
            bool((sav.get("date") or "").strip()),
            "Date SAV absente",
        ),
        (
            bool((montre.get("modele") or "").strip()),
            "Modèle montre absent",
        ),
        (
            bool((montre.get("reference") or "").strip()),
            "Référence boîtier absente",
        ),
        (
            bool((montre.get("numero_serie") or "").strip()),
            "Numéro de série absent",
        ),
        (
            bool(montre.get("etat")),
            "État / diagnostic absent",
        ),
        (
            bool(data.get("interventions_necessaires")),
            "Aucune intervention détectée",
        ),
        (
            (data.get("total_ttc") or 0) > 0,
            "Total TTC nul ou absent",
        ),
    ]

    score = 0
    for ok, label in checks:
        if ok:
            score += 1
        else:
            missing.append(label)

    return score, missing


def extract_from_pdf(pdf_bytes: bytes, api_key: str | None = None,
                     filename: str | None = None) -> dict[str, Any]:
    """Envoie le PDF à Claude et renvoie un dict structuré.

    Args:
        pdf_bytes: Contenu brut du PDF.
        api_key: Clé API Anthropic (lit ANTHROPIC_API_KEY si omise).
        filename: Nom du fichier PDF (aide à la reconnaissance de marque).
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Clé API Anthropic manquante. "
            "Récupérez-la sur console.anthropic.com."
        )

    client = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    user_content: list[dict] = [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        },
    ]
    if filename:
        user_content.append({
            "type": "text",
            "text": f"Nom du fichier PDF : {filename}",
        })

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        timeout=60.0,
        system=[
            {
                "type": "text",
                "text": EXTRACTION_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
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

    cleaned = _clean(data)

    # Fallback brand detection depuis le nom de fichier si le modèle n'a pas trouvé
    if cleaned.get("marque", "Autre").lower() in ("autre", "") and filename:
        detected = _detect_brand_from_text(filename)
        if detected:
            cleaned["marque"] = detected

    # Toutes les marques : les prix extraits sont TOUJOURS en HT
    cleaned["coeff_base"] = "ht"

    return cleaned



def _parse_claude_response(raw: str) -> dict[str, Any]:
    """Parse la réponse texte de Claude en dict JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Réponse Claude non-JSON : {raw[:500]}") from exc


def _extract_from_text(text: str, api_key: str | None = None,
                       hint: str | None = None) -> dict[str, Any]:
    """Envoie un texte brut à Claude pour extraction structurée (emails, etc.)."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Clé API Anthropic manquante.")

    client = anthropic.Anthropic(api_key=api_key)
    user_content: list[dict] = [{"type": "text", "text": text}]
    if hint:
        user_content.append({"type": "text", "text": f"Contexte : {hint}"})

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        timeout=60.0,
        system=[{
            "type": "text",
            "text": EXTRACTION_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
    )
    return _clean(_parse_claude_response(response.content[0].text))


def extract_from_eml(eml_bytes: bytes, api_key: str | None = None,
                     filename: str | None = None) -> dict[str, Any]:
    """Extrait les donnees structurees depuis un email .eml.

    Si le mail contient un PDF en piece jointe, delegue a extract_from_pdf.
    Sinon extrait le corps texte et l'envoie au LLM.
    """

    import email as _email_lib

    msg = _email_lib.message_from_bytes(eml_bytes)
    subject = msg.get("Subject") or ""
    sender  = msg.get("From") or ""

    # 1. Chercher un PDF joint
    for part in msg.walk():
        if part.get_content_type() == "application/pdf":
            pdf_bytes = part.get_payload(decode=True)
            if pdf_bytes:
                pdf_fn = part.get_filename() or filename or "attachment.pdf"
                return extract_from_pdf(pdf_bytes, api_key=api_key, filename=pdf_fn)

    # 2. Extraire le corps texte
    body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                for enc in ("utf-8", "latin-1", "cp1252"):
                    try:
                        body = payload.decode(enc)
                        break
                    except (UnicodeDecodeError, AttributeError):
                        continue
            if body:
                break

    if not body.strip():
        raise RuntimeError("Aucun contenu extractible dans l'email (ni PDF, ni texte).")

    # Construire le contexte complet pour le LLM
    email_context = f"Expéditeur : {sender}\nObjet : {subject}\n\n{body}"
    hint = f"Nom du fichier : {filename}" if filename else None

    data = _extract_from_text(email_context, api_key=api_key, hint=hint)

    # Détection HT : si le corps contient des prix en HT → coeff_base = "ht"
    if re.search(r"\d[\s ]*[€$]?\s*HT\b|\bHT\s*[:=]\s*\d", body, re.IGNORECASE):
        data["coeff_base"] = "ht"

    # Fallback marque depuis expéditeur / objet si non détecté
    if data.get("marque", "Autre").lower() in ("autre", ""):
        for txt in (sender, subject, body[:300]):
            detected = _detect_brand_from_text(txt)
            if detected:
                data["marque"] = detected
                break

    return data


def extract_from_msg(msg_bytes: bytes, api_key: str | None = None,
                     filename: str | None = None) -> dict[str, Any]:
    """Extrait les données depuis un email Outlook .msg (drag & drop depuis Outlook).

    Si le .msg contient un PDF en pièce jointe, délègue à extract_from_pdf.
    Sinon extrait le corps texte comme pour un .eml.
    """
    try:
        import extract_msg as _msg_lib
    except ImportError:
        raise RuntimeError(
            "La bibliothèque extract-msg est requise pour les fichiers .msg. "
            "Installez-la avec : pip install extract-msg"
        )

    from io import BytesIO
    msg = _msg_lib.Message(BytesIO(msg_bytes))

    subject = msg.subject or ""
    sender  = msg.sender  or ""

    # 1. Chercher un PDF joint
    for att in (msg.attachments or []):
        name = (att.longFilename or att.shortFilename or "").lower()
        if name.endswith(".pdf"):
            pdf_bytes = att.data
            if pdf_bytes:
                return extract_from_pdf(pdf_bytes, api_key=api_key, filename=name)

    # 2. Extraire le corps texte
    body = msg.body or ""
    if not body.strip():
        raise RuntimeError("Aucun contenu extractible dans le fichier .msg.")

    email_context = f"Expéditeur : {sender}\nObjet : {subject}\n\n{body}"
    hint = f"Nom du fichier : {filename}" if filename else None

    data = _extract_from_text(email_context, api_key=api_key, hint=hint)

    if re.search(r"\d[\s ]*[€$]?\s*HT\b|\bHT\s*[:=]\s*\d", body, re.IGNORECASE):
        data["coeff_base"] = "ht"

    if data.get("marque", "Autre").lower() in ("autre", ""):
        for txt in (sender, subject, body[:300]):
            detected = _detect_brand_from_text(txt)
            if detected:
                data["marque"] = detected
                break

    return data
