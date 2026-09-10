"""Flask app — Reverso : génération de devis SAV multi-tenant (résolu par sous-domaine)."""
from __future__ import annotations

import csv
import functools
import hmac
import io
import json
import logging
import math
import os
import pickle
import re
import secrets
import shutil
import threading
import time
import uuid
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    jsonify,
)
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from . import db
from .docx_generator import build_docx
from .pdf_extractor import ExtractionError, confidence_score, extract_from_eml, extract_from_pdf
from .pdf_generator import docx_to_pdf

# Format horodaté pour Render/gunicorn (stderr). No-op si un handler existe déjà.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
load_dotenv(override=False)
RUNTIME_DIR = BASE_DIR

UPLOAD_DIR = RUNTIME_DIR / "uploads"
GENERATED_DIR = RUNTIME_DIR / "generated"
SESSION_DIR = RUNTIME_DIR / "flask_sessions"
UPLOAD_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

# ── Limitation par IP, en mémoire (1 worker gunicorn) ────────────────────────
# ponytail: dict en mémoire — passer en table Postgres si multi-worker un jour.
_ATTEMPTS: dict[tuple[str, str], list[float]] = {}

# ── Extraction de lot en tâche de fond ───────────────────────────────────────
# ponytail: thread daemon + état sur disque (data.pkl/prepared.pkl par token) —
# suffisant pour 1 worker gunicorn. File de tâches (RQ/Celery) seulement si multi-worker.
_lot_lock = threading.Lock()
_lot_spawns: dict[str, list[dict]] = {}  # lot_id → parts issues d'un split détecté en fond


def _record_extract_hit(ip: str | None) -> None:
    """Enregistre un appel d'extraction dans le compteur de throttle, sans contexte
    de requête (utilisable depuis un thread de fond). ip capturé côté requête."""
    key = ("extract", ip or "?")
    now = time.time()
    hits = [t for t in _ATTEMPTS.get(key, ()) if now - t < 600]
    hits.append(now)
    _ATTEMPTS[key] = hits


def _ip_extract_count(ip: str | None) -> int:
    """Nb d'extractions récentes pour cette IP (fenêtre 10 min), sans contexte requête."""
    now = time.time()
    return len([t for t in _ATTEMPTS.get(("extract", ip or "?"), ()) if now - t < 600])


def _throttled(bucket: str, limit: int, window: int, record: bool = True) -> bool:
    """True si l'IP courante a atteint `limit` occurrences sur `window` secondes."""
    if len(_ATTEMPTS) > 10_000:  # garde-fou mémoire, reset brutal acceptable
        _ATTEMPTS.clear()
    now = time.time()
    key = (bucket, request.remote_addr or "?")
    hits = [t for t in _ATTEMPTS.get(key, ()) if now - t < window]
    blocked = len(hits) >= limit
    if record and not blocked:
        hits.append(now)
    _ATTEMPTS[key] = hits
    return blocked


def _throttle_retry_in(bucket: str, window: int) -> int:
    """Secondes avant que le quota se libère (à appeler après un _throttled() True)."""
    hits = _ATTEMPTS.get((bucket, request.remote_addr or "?")) or []
    if not hits:
        return 0
    return max(0, int(min(hits) + window - time.time()))


# ── Purge des fichiers de plus de 24 h (RGPD : rétention limitée) ────────────
_PURGE_MAX_AGE = 24 * 3600
_last_purge = 0.0


def _purge_old_files() -> None:
    """Supprime uploads/, generated/ et sessions de plus de 24 h. Au plus 1 fois/heure."""
    global _last_purge
    now = time.time()
    if now - _last_purge < 3600:
        return
    _last_purge = now
    for d in (UPLOAD_DIR, GENERATED_DIR, SESSION_DIR):
        if not d.is_dir():
            continue
        for sub in d.iterdir():
            try:
                if now - sub.stat().st_mtime > _PURGE_MAX_AGE:
                    if sub.is_dir():
                        shutil.rmtree(sub, ignore_errors=True)
                    else:
                        sub.unlink(missing_ok=True)
            except OSError:
                pass


def _safe_next(dest: str | None) -> str | None:
    """N'accepte que les chemins relatifs internes (bloque //evil.com, protocol-relative)."""
    if dest and dest.startswith("/") and not dest.startswith("//"):
        return dest
    return None

ALLOWED_DOC = {"pdf", "eml", "msg"}
# Garde-fou lot : au-delà, on refuse l'envoi (protège le quota API 30/10 min et évite
# qu'un dépôt massif "pour voir" ne consomme des extractions à la chaîne).
_BATCH_MAX_FILES = 20
ALLOWED_IMG = {"jpg", "jpeg", "png", "webp", "gif"}
ALLOWED_LOGO_IMG = ALLOWED_IMG | {"svg"}
ALLOWED_PHOTO_IMG = {"jpg", "jpeg", "png", "webp"}  # photos SAV/options


def _normalize_photo(data: bytes, size: int = 900) -> bytes | None:
    """Recadre en carré + réencode JPEG sur fond BLANC — format uniforme quelle que

    soit la source (upload jpg/png/webp ou extraction auto depuis un PDF fournisseur),
    pour une grille de photos régulière dans le devis généré. Toute transparence
    (PNG/webp) est composée sur blanc — un simple .convert("RGB") remplirait les
    zones transparentes en noir, pas blanc.
    """
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(data))
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
        if side != size:
            img = img.resize((size, size), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception:
        return None


def _sync_section_photos(photo_dir, prefix: str, kept: list[str], uploads,
                         max_count: int | None) -> tuple[list[bytes], bool]:
    """Combine les photos déjà attachées (conservées) + les nouveaux uploads de la

    section montre, réécrit l'état final sur disque sous des noms stables
    (<prefix>_N.jpg, purge les anciens) — c'est cet état que /review relit ensuite.
    Retourne (photos, une_photo_a_ete_rejetee).
    """
    result: list[bytes] = []
    rejected = False
    for name in kept:
        if re.fullmatch(rf"{prefix}_\d+\.jpg", name):
            p = photo_dir / name
            if p.exists():
                result.append(p.read_bytes())
    for f in uploads:
        if not (f and f.filename):
            continue
        if max_count is not None and len(result) >= max_count:
            rejected = True
            continue
        if not _has_extension(f.filename, ALLOWED_PHOTO_IMG):
            rejected = True
            continue
        normalized = _normalize_photo(f.read())
        if normalized:
            result.append(normalized)
        else:
            rejected = True
    if max_count is not None and len(result) > max_count:
        rejected = True
        result = result[:max_count]
    for old in photo_dir.glob(f"{prefix}_*.jpg"):
        old.unlink(missing_ok=True)
    for i, blob in enumerate(result):
        (photo_dir / f"{prefix}_{i}.jpg").write_bytes(blob)
    return result, rejected


def _hydrate_option_photos(lines: list[dict], photo_dir) -> list[dict]:
    """Copie des lignes d'options avec les octets de la photo relus depuis le disque

    (clé privée _photo_bytes, jamais stockée en session) — la ligne d'origine ne
    garde que la référence légère `photo_file`.
    """
    out = []
    for line in lines:
        line2 = dict(line)
        photo_file = line2.get("photo_file")
        if photo_file:
            p = photo_dir / photo_file
            if p.exists():
                line2["_photo_bytes"] = p.read_bytes()
        out.append(line2)
    return out


MAX_CONTENT_LENGTH = 25 * 1024 * 1024

MARQUES = ["Chanel", "Tag Heuer", "Breitling", "Rolex", "Autre"]

# ── Résolution du tenant par sous-domaine + cache mémoire (TTL 60s) ──────────
_TENANT_TTL = 60.0
_tenant_cache: dict[str, tuple[db.Tenant | None, float]] = {}


def _resolve_tenant_slug(host: str) -> str:
    """Extrait le slug (sous-domaine) depuis l'hôte de la requête.

    doux.devisly.fr / doux.localhost → "doux" ; apex, localhost nu et URL Render
    brute (*.onrender.com) → PRIMARY_TENANT_SLUG (secours pendant la propagation DNS).
    """
    host = (host or "").split(":")[0].strip().lower()
    primary = os.environ.get("PRIMARY_TENANT_SLUG", "")
    if not host or host in ("localhost", "127.0.0.1"):
        return primary
    if host.endswith(".onrender.com"):
        return primary
    if host.endswith(".localhost"):
        sub = host[: -len(".localhost")]
        return sub.split(".")[0] if sub else primary
    labels = host.split(".")
    if len(labels) >= 3 and labels[0] != "www":
        return labels[0]
    return primary  # apex (ex: devisly.fr) ou host à 2 labels


def _is_apex_host(host: str) -> bool:
    """True si l'hôte est le domaine nu/www (devisly.fr, www.devisly.fr) — pas un sous-domaine tenant."""
    host = (host or "").split(":")[0].strip().lower()
    if not host or host in ("localhost", "127.0.0.1") or host.endswith(".localhost") or host.endswith(".onrender.com"):
        return False  # dev/staging : on garde le secours vers PRIMARY_TENANT_SLUG
    labels = host.split(".")
    return len(labels) < 3 or labels[0] == "www"


def _get_tenant_cached(slug: str) -> db.Tenant | None:
    now = time.time()
    hit = _tenant_cache.get(slug)
    if hit and now - hit[1] < _TENANT_TTL:
        return hit[0]
    tenant = db.get_tenant_by_slug(slug) if slug else None
    _tenant_cache[slug] = (tenant, now)
    return tenant


def _invalidate_tenant(slug: str) -> None:
    _tenant_cache.pop(slug, None)


def _create_yousign_signature_request(pdf_bytes: bytes, client_email: str, devis_name: str) -> dict | None:
    """Crée une signature request Yousign et retourne le lien."""
    api_key = os.environ.get("YOUSIGN_API_KEY")
    if not api_key:
        print("ERROR: YOUSIGN_API_KEY not found")
        return None
    try:
        # Sandbox par défaut — définir YOUSIGN_API_URL=https://api.yousign.app/v3 en prod.
        base_url = os.environ.get("YOUSIGN_API_URL", "https://api-sandbox.yousign.app/v3")
        headers = {"Authorization": f"Bearer {api_key}"}
        sr_data = {"name": f"Devis {devis_name}", "delivery_mode": "email", "timezone": "Europe/Paris"}
        resp = requests.post(f"{base_url}/signature_requests", headers=headers, json=sr_data, timeout=10)
        if resp.status_code not in (200, 201):
            return None
        sr_id = resp.json().get("id")

        pdf_tmp = RUNTIME_DIR / f"tmp_{devis_name}.pdf"
        pdf_tmp.write_bytes(pdf_bytes)
        try:
            with open(pdf_tmp, "rb") as f:
                files = {"file": f, "nature": (None, "signable_document")}
                resp2 = requests.post(f"{base_url}/signature_requests/{sr_id}/documents",
                                      headers={"Authorization": f"Bearer {api_key}"}, files=files, timeout=10)
        finally:
            pdf_tmp.unlink(missing_ok=True)  # données client — ne pas laisser traîner
        if resp2.status_code not in (200, 201):
            return None
        doc_id = resp2.json().get("id")

        signer_data = {
            "info": {"first_name": "Client", "last_name": "Signataire", "email": client_email, "locale": "fr"},
            "signature_authentication_mode": "no_otp",
            "signature_level": "electronic_signature",
            "fields": [{"document_id": doc_id, "type": "signature", "height": 40, "width": 85,
                        "page": 1, "x": 100, "y": 100}],
        }
        resp3 = requests.post(f"{base_url}/signature_requests/{sr_id}/signers",
                              headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                              json=signer_data, timeout=10)
        if resp3.status_code not in (200, 201):
            return None

        resp4 = requests.post(f"{base_url}/signature_requests/{sr_id}/activate",
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if resp4.status_code not in (200, 201, 204):
            return None

        resp5 = requests.get(f"{base_url}/signature_requests/{sr_id}",
                             headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if resp5.status_code == 200:
            signers = resp5.json().get("signers", [])
            if signers:
                signer_id = signers[0].get("id")
                sign_url = signers[0].get("signature_link") or f"https://sandbox.yousign.app/sign/{signer_id}"
                return {"signature_request_id": sr_id, "signer_id": signer_id, "sign_url": sign_url}
        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


# Champs gérés par le formulaire admin — tout le reste (ex: coeff_split_nec, base)
# est une option avancée non exposée et doit être préservé tel quel à la sauvegarde.
_ADMIN_MANAGED_KEYS = {"coeff", "coeff_opt", "coeff_nec_default", "coeff_opt_default"}


def _coefficients_from_form(form, existing: dict | None = None) -> dict:
    """Reconstruit le dict coefficients depuis les tableaux du formulaire admin."""
    existing = existing or {}
    brands     = form.getlist("brand[]")
    coeffs     = form.getlist("coeff[]")
    coeff_opts = form.getlist("coeff_opt[]")
    nec_defs   = form.getlist("nec_default[]")
    opt_defs   = form.getlist("opt_default[]")

    def _num(values, i):
        raw = (values[i] if i < len(values) else "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    new: dict = {}
    for i, name in enumerate(brands):
        name = (name or "").strip()
        if not name:
            continue
        coeff = _num(coeffs, i)
        if coeff is None or coeff <= 0:
            continue
        entry: dict = {"coeff": round(coeff, 4)}
        coeff_opt = _num(coeff_opts, i)
        if coeff_opt is not None and coeff_opt > 0:
            entry["coeff_opt"] = round(coeff_opt, 4)
        if (nec_defs[i] if i < len(nec_defs) else "1") != "1":
            entry["coeff_nec_default"] = False
        if (opt_defs[i] if i < len(opt_defs) else "1") != "1":
            entry["coeff_opt_default"] = False
        old_entry = existing.get(name)
        if isinstance(old_entry, dict):
            for k, v in old_entry.items():
                if k not in _ADMIN_MANAGED_KEYS:
                    entry[k] = v
        entry.setdefault("base", "ht")  # défaut seulement si la marque n'avait pas déjà une base définie
        new[name] = entry
    return new


def _has_extension(filename: str, allowed: set[str]) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in allowed


def _all_coeffs_activated(coefficients: dict) -> dict:
    """Copie des coefficients d'un tenant, sans les flags coeff_nec_default/coeff_opt_default.

    Utilisé pour amorcer un nouveau client : les règles de désactivation par marque
    (ex: Breitling désactivé chez doux) sont spécifiques à ce tenant, pas une référence
    à reproduire — un nouveau client démarre avec toutes les marques activées.
    """
    return {
        name: {k: v for k, v in entry.items() if k not in ("coeff_nec_default", "coeff_opt_default")}
        for name, entry in coefficients.items()
    }


def _parse_devis_limit(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


def create_app() -> Flask:
    app = Flask(__name__,
                template_folder=str(BASE_DIR / "templates"),
                static_folder=str(BASE_DIR / "static"))
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    _secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not _secret_key:
        import sys
        print("CRITICAL: FLASK_SECRET_KEY non définie — sessions invalidées à chaque redémarrage.",
              file=sys.stderr)
        _secret_key = secrets.token_hex(32)
    app.secret_key = _secret_key

    SESSION_DIR.mkdir(exist_ok=True)
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = str(SESSION_DIR)
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    # Ne PAS définir SESSION_COOKIE_DOMAIN : le cookie reste lié au sous-domaine
    # exact → isolation naturelle des sessions admin entre tenants.
    # Nom/chemin par défaut inchangés (déploiement standalone) — le déploiement fusionné
    # DouxDevis (app monté sous /devisly, même domaine) les override pour ne pas écraser
    # le cookie "session" de DouxDevis.
    app.config["SESSION_COOKIE_NAME"] = os.environ.get("SESSION_COOKIE_NAME", "session")
    app.config["SESSION_COOKIE_PATH"] = os.environ.get("SESSION_COOKIE_PATH", "/")
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Secure seulement derrière Render (HTTPS) — en local http://*.localhost doit marcher.
    app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))
    Session(app)

    # Render met un proxy devant l'app : sans ProxyFix, request.remote_addr est
    # l'IP du proxy (le rate limiting par IP serait global) et le scheme est http.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.teardown_appcontext(db.close_conn)

    @app.before_request
    def _load_tenant():
        _purge_old_files()
        if request.endpoint == "static" or (request.endpoint or "").startswith("superadmin_"):
            return None
        if _is_apex_host(request.host):
            if request.endpoint in ("mentions_legales", "confidentialite"):
                return None  # pages légales accessibles aussi depuis la landing
            return render_template("landing.html")
        tenant = _get_tenant_cached(_resolve_tenant_slug(request.host))
        if tenant is None:
            abort(404)
        if not tenant.active:
            return render_template("suspended.html", maison_name=tenant.maison_name), 403
        g.tenant = tenant

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if os.environ.get("RENDER"):  # HSTS seulement en prod HTTPS
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    # Pages rendues sans la coquille ERP (pas de sidebar) : connexion et espace
    # superadmin. Les erreurs et la landing tombent déjà dessus faute de tenant.
    _BARE_ENDPOINTS = {"admin_login", "superadmin_login", "superadmin_list",
                       "superadmin_new", "superadmin_edit"}

    @app.context_processor
    def inject_maison():
        tenant = getattr(g, "tenant", None)
        tickets = session.get("demo_tickets") or []
        return {
            "maison_name": tenant.maison_name if tenant else "Reverso",
            # ponytail: n'apparaît que dans le déploiement fusionné DouxDevis (var posée
            # dans son .env/render.yaml) — jamais chez les vrais clients Devisly standalone.
            "show_douxdevis_link": bool(os.environ.get("SHOW_DOUXDEVIS_TOGGLE")),
            # Coquille ERP : sidebar persistante dès qu'on est dans un tenant.
            # Hors tenant (landing, superadmin) et sur les pages de connexion /
            # d'erreur, on retombe sur l'ancien bandeau simple.
            "shell": "full" if tenant and request.endpoint not in _BARE_ENDPOINTS else "bare",
            "nav_active": None,
            "erp_nav": {
                "en_cours": sum(1 for t in tickets if t["status"] == "en_cours"),
                "a_valider": sum(1 for t in tickets if t["status"] == "a_valider"),
                # Devis partenaires encore à traiter (extraction, vérification, ou généré mais
                # pas encore envoyé — cf. bug remonté : un devis "généré" est une action à
                # prendre, il ne doit pas disparaître des compteurs avant d'être envoyé).
                "partenaires": sum(1 for p in _partner_devis_rows()
                                   if p["status"] in ("extraction", "a_verifier", "genere")),
            },
        }

    @app.route("/logo.png")
    def tenant_logo():
        if not g.tenant.logo_png:
            abort(404)
        return Response(g.tenant.logo_png, mimetype="image/png")

    @app.route("/", methods=["GET"])
    def index():
        devis_used = None
        devis_pct = 0
        if g.tenant.devis_limit is not None:
            devis_used = db.get_monthly_devis_count(g.tenant.slug)
            devis_pct = min(100, round(devis_used / g.tenant.devis_limit * 100)) if g.tenant.devis_limit else 100
        return render_template("index.html", marques=MARQUES, devis_used=devis_used,
                               devis_limit=g.tenant.devis_limit, devis_pct=devis_pct,
                               lot_status=_lot_status())

    def _lot_status() -> str | None:
        """État du lot partenaire courant : None, "open" (à vérifier) ou "generated"."""
        lot = session.get("lot") or []
        if not lot:
            return None
        to_generate = [e for e in lot if e["status"] in ("ready", "verified")]
        done_tokens = {g_["token"] for g_ in (session.get("lot_generated") or [])}
        fully_generated = bool(to_generate) and all(e["token"] in done_tokens for e in to_generate) \
            and not any(e["status"] == "pending" for e in lot)
        if fully_generated:
            # Déjà vu sur /lot/done (accusé de réception) → n'ennuie plus l'accueil.
            return None if session.get("lot_ack") else "generated"
        return "open"

    # ── Lot de devis (plusieurs fichiers déposés / PDF multi-devis) ──
    # Modèle : session["lot"] = liste d'entrées {token, status, summary, source_kind, err_ref}.
    # Un devis = un token stable ; ses fichiers vivent sous UPLOAD_DIR/<token>/ (source, photos,
    # data.pkl = données extraites/éditées) et GENERATED_DIR/<token>/ (docx/pdf générés).

    def _lot_get() -> list:
        return session.get("lot") or []

    def _lot_entry(token: str) -> dict | None:
        for e in _lot_get():
            if e["token"] == token:
                return e
        return None

    def _clear_single() -> None:
        """Efface l'état d'un devis unique en session (hors lot)."""
        for k in ("token", "data", "source_kind", "source_pdf", "source_text"):
            session.pop(k, None)

    def _lot_clear() -> None:
        """Supprime les dossiers de tous les devis du lot courant + l'état session/mémoire."""
        for e in _lot_get():
            shutil.rmtree(UPLOAD_DIR / e["token"], ignore_errors=True)
            shutil.rmtree(GENERATED_DIR / e["token"], ignore_errors=True)
        lot_id = session.get("lot_id")
        if lot_id:
            with _lot_lock:
                _lot_spawns.pop(lot_id, None)
        for k in ("lot", "lot_id", "lot_active_token", "lot_generated", "lot_ack"):
            session.pop(k, None)

    def _summary(data: dict) -> dict:
        montre = data.get("montre") or {}
        client = data.get("client") or {}
        lines = len(data.get("interventions_necessaires") or []) + \
            len(data.get("interventions_optionnelles") or [])
        return {"marque": data.get("marque") or "", "modele": montre.get("modele") or "",
                "numero": (data.get("sav") or {}).get("numero") or "",
                "client": client.get("nom") or "", "total": data.get("total_ttc") or 0, "lines": lines}

    @app.template_filter("ticket_tiers")
    def ticket_tiers(ticket: dict) -> list[float]:
        """Montants cumulés d'un devis horloger : nécessaire seul, puis + chaque option dans
        l'ordre — même principe que _partner_tiers, pour choisir le palier réellement retenu
        par le client à l'acceptation (le devis peut avoir des options en plus du nécessaire)."""
        nec = sum(l["prix_client"] for l in ticket["lines"]["nec"])
        tiers = [nec]
        for l in ticket["lines"]["opt"][:3]:
            tiers.append(tiers[-1] + l["prix_client"])
        return tiers

    def _is_relance(iso_str: str | None, days: int = 7) -> bool:
        """Vrai si l'horodatage ISO donné date de plus de `days` jours — sert à marquer un
        devis envoyé/généré sans réponse client comme « à relancer »."""
        if not iso_str:
            return False
        try:
            return datetime.now() - datetime.fromisoformat(iso_str) > timedelta(days=days)
        except ValueError:
            return False

    @app.template_filter("brand_color")
    def brand_color(marque: str) -> str:
        """Fond de la vignette d'un devis sans photo. Une couleur par marque (hash déterministe)
        a été essayée puis retirée (retour utilisateur : trop de couleurs différentes dans
        l'appli, ça brouille la lecture) — un seul ton neutre partout, marque connue ou non."""
        return "var(--erp-sunken)"

    def _partner_status() -> dict:
        """Réponse client saisie à la main sur un devis partenaire :
        {token: "refuse"} ou {token: {"decision": "accepte", "amount": 470.0}} quand un
        palier (nécessaire seul / +options) a été choisi à l'acceptation.

        Le flux partenaire n'a pas le SMS/réponse automatique de la démo horloger — c'est
        l'accueil qui coche le résultat, sinon un devis partenaire payé ne compterait
        jamais dans l'encaissé du mois."""
        return session.get("partner_status") or {}

    def _partner_tiers(token: str, kind: str) -> list[float]:
        """Montants cumulés : le total du devis (nécessaire), puis + chaque option dans l'ordre
        — sert à choisir le palier réellement retenu par le client à l'acceptation.

        Part du `total_ttc` extrait (déjà le montant affiché partout ailleurs pour ce devis),
        pas d'une somme des `prix` par ligne : sur un devis partenaire extrait par l'IA depuis
        un PDF externe, ces prix par ligne peuvent être bruités (unitaire vs total, remise
        globale non répercutée...) alors que `total_ttc` est le champ que l'extraction traite
        comme la vérité — sommer les lignes dérivait du vrai total (bug remonté : 208,40 €
        affiché contre 400 € TTC réels)."""
        if kind == "single":
            data = session.get("data") or {}
        else:
            dpath = UPLOAD_DIR / secure_filename(token) / "data.pkl"
            data = pickle.loads(dpath.read_bytes()) if dpath.is_file() else {}
        try:
            base = float(data.get("total_ttc") or 0)
        except (TypeError, ValueError):
            base = 0.0
        if not base:
            base = sum((l.get("prix") or 0) for l in (data.get("interventions_necessaires") or []))
        tiers = [base]
        for l in (data.get("interventions_optionnelles") or [])[:3]:
            # prix_client = prix HT * coefficient (devis revu via le formulaire) — la seule
            # valeur homogène avec `base` (déjà un montant client). `prix` seul, une fois passé
            # par _form_to_data, est réécrit en HT (bug remonté : total faux dès qu'une option
            # est ajoutée). Fallback sur `prix` pour un devis fraîchement extrait par l'IA, pas
            # encore revu — là il n'y a pas de split HT/TTC, `prix` est déjà le montant final.
            montant = l.get("prix_client")
            if montant is None:
                montant = l.get("prix") or 0
            tiers.append(tiers[-1] + montant)
        return tiers

    def _partner_devis_rows() -> list[dict]:
        """Devis partenaires suivis (import PDF/email) — ne passent jamais par l'atelier,
        mais restent visibles côté dashboard/registre tant qu'ils ne sont pas générés.
        Couvre le lot (plusieurs fichiers / PDF multi-devis) ET le devis unique classique,
        qui ne vit lui que dans session['token']/['data'] hors de tout lot.

        Statuts : extraction → a_verifier → genere → accepte / refuse."""
        generated = {g_["token"]: g_ for g_ in (session.get("lot_generated") or [])}
        answered = _partner_status()

        def _row(token: str, kind: str, summary: dict, raw_status: str) -> dict:
            entry = generated.get(token) or {}
            reply = answered.get(token)
            total_override = sent_at = None
            if isinstance(reply, dict):
                status = reply.get("decision")
                total_override = reply.get("amount")
                sent_at = reply.get("sent_at")
            elif reply:
                status = reply
            elif token in generated:
                status = "genere"
            else:
                status = "extraction" if raw_status == "pending" else "a_verifier"
            names = entry.get("names") or []
            return {
                "token": token, "kind": kind,
                "client": summary.get("client") or "—",
                "marque": summary.get("marque") or "",
                "piece": summary.get("modele") or "",
                "numero": summary.get("numero") or "",
                "total": total_override if total_override is not None else (summary.get("total") or 0),
                "status": status,
                "pdf_name": next((n for n in names if n.lower().endswith(".pdf")), None),
                "photo_file": next(iter(_existing_photos(token, "montre")), None),
                "tiers": _partner_tiers(token, kind) if token in generated else [],
                "relance": status == "envoye" and _is_relance(sent_at),
            }

        rows = []
        for e in _lot_get():
            if e["status"] == "ignored":
                continue
            rows.append(_row(e["token"], "lot", e.get("summary") or {}, e["status"]))
        single_token = session.get("token")
        if single_token and not _lot_entry(single_token):
            rows.append(_row(single_token, "single", _summary(session.get("data") or {}), "ready"))
        return rows

    def _partner_encaisse() -> float:
        """Montant des devis partenaires marqués acceptés — s'ajoute à l'encaissé horloger."""
        return sum(p["total"] for p in _partner_devis_rows() if p["status"] == "accepte")

    def _error_ref(context: str) -> str:
        """À appeler dans un except : log la trace complète et renvoie une référence courte.

        La référence est montrée à l'utilisateur et permet de retrouver la trace
        exacte dans les logs serveur (Render) — plus jamais muet en démo.
        """
        ref = uuid.uuid4().hex[:8].upper()
        tenant = getattr(getattr(g, "tenant", None), "slug", "?")
        app.logger.exception("[%s] réf=%s tenant=%s ip=%s", context, ref, tenant, request.remote_addr)
        return ref

    def _flash_extract_error(exc: Exception) -> None:
        ref = _error_ref("extraction")
        if isinstance(exc, ExtractionError):
            # Message déjà rédigé pour l'utilisateur (cause + action)
            flash(f"{exc} (réf. {ref})", "error")
        else:
            flash(
                "Erreur inattendue pendant l'extraction. Réessayez — si le problème persiste, "
                f"transmettez la référence {ref} à votre prestataire.",
                "error",
            )

    def _flash_internal_error(action: str) -> None:
        """À appeler dans un except : log + message générique (jamais l'exception brute)."""
        ref = _error_ref(action)
        flash(
            f"Erreur interne pendant {action}. Réessayez — si le problème persiste, "
            f"transmettez la référence {ref} à votre prestataire.",
            "error",
        )

    def _extract_prepared(file_bytes: bytes, filename: str, api_key: str, tenant_slug: str) -> dict:
        """Extrait un fichier source (pdf/eml/msg) → dict 'prepared', SANS toucher à
        session/g/flash/request. Sûr à exécuter dans un thread de fond.

        Renvoie {data, source_kind, source_payload, extra_parts:[(bytes,name)], warnings:[str]}.
        Détecte les PDF multi-devis (parts supplémentaires renvoyées dans extra_parts,
        mises en file par l'appelant côté requête). Lève l'exception d'origine en cas d'échec.
        """
        ext = filename.rsplit(".", 1)[-1].lower()
        source_kind = "pdf"
        source_payload: bytes | str = file_bytes
        extra_parts: list[tuple[bytes, str]] = []
        warnings: list[str] = []
        t0 = time.time()
        # Pas de nom de fichier dans les logs : il contient souvent le nom du client (RGPD)
        app.logger.info("extraction démarrée tenant=%s type=%s taille=%d o",
                        tenant_slug, ext, len(file_bytes))

        if ext == "eml":
            data, source_kind, source_payload = extract_from_eml(file_bytes, api_key=api_key, filename=filename)
        elif ext == "msg":
            from .pdf_extractor import extract_from_msg
            data, source_kind, source_payload = extract_from_msg(file_bytes, api_key=api_key, filename=filename)
        else:
            # PDF de 4+ pages : détection de plusieurs devis concaténés
            # ponytail: seuil 4 pages pour éviter un appel API sur les devis 1-3 pages (cas ultra-majoritaire)
            from .pdf_extractor import detect_multi_devis, split_pdf_pages
            try:
                from pypdf import PdfReader
                n_pages = len(PdfReader(io.BytesIO(file_bytes)).pages)
            except Exception:
                n_pages = 1
            if n_pages >= 4:
                ranges = detect_multi_devis(file_bytes, api_key=api_key)
                parts = split_pdf_pages(file_bytes, ranges) if ranges else []
                if len(parts) > 1:
                    base = filename.rsplit(".", 1)[0]
                    extra_parts = [(p, f"{base}_devis{i + 2}.pdf") for i, p in enumerate(parts[1:])]
                    warnings.append(f"{len(parts)} devis détectés dans ce PDF — ils seront proposés l'un après l'autre.")
                    file_bytes = parts[0]
            data = extract_from_pdf(file_bytes, api_key=api_key, filename=filename)
            source_payload = file_bytes

        if not (data.get("sav") or {}).get("date"):
            if "sav" not in data or not isinstance(data["sav"], dict):
                data["sav"] = {}
            data["sav"]["date"] = datetime.now().strftime("%d.%m.%Y")

        interventions = data.get("interventions_necessaires") or []
        has_prix = any(float(i.get("prix") or 0) > 0 for i in interventions)
        if not interventions or not has_prix:
            warnings.append("⚠️ Aucune intervention trouvée dans ce fichier. Vérifiez que c'est bien un devis partenaire horlogerie ou joaillerie.")

        app.logger.info("extraction réussie tenant=%s type=%s durée=%.1fs marque=%s",
                        tenant_slug, ext, time.time() - t0, data.get("marque", "?"))
        return {"data": data, "source_kind": source_kind, "source_payload": source_payload,
                "extra_parts": extra_parts, "warnings": warnings}

    def _install_prepared(prepared: dict) -> None:
        """Installe un résultat 'prepared' d'un devis UNIQUE dans la session (token,
        données, source, photos). À appeler DANS un contexte de requête. Les lots passent
        par _materialize_entry, pas ici."""
        data = prepared["data"]
        source_kind = prepared["source_kind"]
        source_payload = prepared["source_payload"]
        for msg in prepared.get("warnings") or []:
            flash(msg, "warning")

        token = uuid.uuid4().hex
        session["token"] = token
        session["data"] = data
        if source_kind == "pdf":
            session_dir = UPLOAD_DIR / token
            session_dir.mkdir(parents=True, exist_ok=True)
            (session_dir / "source.pdf").write_bytes(source_payload)
            session["source_kind"] = "pdf"
            session["source_pdf"] = "source.pdf"
        else:
            session["source_kind"] = "text"
            session["source_text"] = source_payload
        app.logger.info("devis installé tenant=%s marque=%s",
                        getattr(g.tenant, "slug", "?"), data.get("marque", "?"))

    def _materialize_entry(entry: dict, prepared: dict) -> None:
        """Écrit source + photos + data.pkl sous le token de l'entrée, remplit son
        résumé et passe le statut à 'ready'. Foreground (réconciliation ou démarrage)."""
        token = entry["token"]
        data = prepared["data"]
        source_kind = prepared["source_kind"]
        source_payload = prepared["source_payload"]
        tdir = UPLOAD_DIR / token
        tdir.mkdir(parents=True, exist_ok=True)
        if source_kind == "pdf":
            (tdir / "source.pdf").write_bytes(source_payload)
        else:
            (tdir / "source.txt").write_text(source_payload, encoding="utf-8")
        (tdir / "data.pkl").write_bytes(pickle.dumps(data))
        (tdir / "prepared.pkl").unlink(missing_ok=True)
        (tdir / "queued.bin").unlink(missing_ok=True)
        entry["source_kind"] = source_kind
        entry["summary"] = _summary(data)
        entry["status"] = "ready"

    def _lot_reconcile() -> list:
        """Intègre les résultats d'extraction de fond (prepared.pkl / prepared.err) et
        les parts issues d'un split, dans session['lot']. À appeler en contexte requête."""
        lot = _lot_get()
        lot_id = session.get("lot_id")
        known = {e["token"] for e in lot}
        if lot_id:
            with _lot_lock:
                for s in _lot_spawns.get(lot_id) or []:
                    if s["token"] not in known:
                        lot.append({"token": s["token"], "status": "pending",
                                    "summary": None, "source_kind": None, "err_ref": None})
                        known.add(s["token"])
                _lot_spawns[lot_id] = []
        changed = False
        for e in lot:
            if e["status"] != "pending":
                continue
            tdir = UPLOAD_DIR / e["token"]
            if (tdir / "prepared.err").exists():
                e["status"] = "error"
                e["err_ref"] = (tdir / "prepared.err").read_text().strip() or "?"
                changed = True
            elif (tdir / "prepared.pkl").exists():
                try:
                    _materialize_entry(e, pickle.loads((tdir / "prepared.pkl").read_bytes()))
                except Exception:
                    e["status"] = "error"
                    e["err_ref"] = _error_ref("lot reconcile")
                changed = True
        if changed:
            session["lot"] = lot
        return lot

    def _lot_extract_bg(lot_id: str, jobs: list[tuple[str, str]],
                        api_key: str, ip: str | None, slug: str) -> None:
        """Worker de fond : extrait chaque (token, filename), écrit prepared.pkl/err.
        Un PDF multi-devis rencontré ici enfile ses parts supplémentaires (spawn)."""
        def worker() -> None:
            pending = list(jobs)
            i = 0
            while i < len(pending):
                token, filename = pending[i]
                i += 1
                tdir = UPLOAD_DIR / token
                src = tdir / "queued.bin"
                if not src.exists():
                    continue
                # Garde-fou quota : le fond ne doit pas dépasser 30 extractions/10 min.
                if _ip_extract_count(ip) >= 30:
                    (tdir / "prepared.err").write_text("QUOTA")
                    continue
                try:
                    result = _extract_prepared(src.read_bytes(), filename, api_key, slug)
                    for pbytes, pname in result.get("extra_parts") or []:
                        stoken = uuid.uuid4().hex
                        sdir = UPLOAD_DIR / stoken
                        sdir.mkdir(parents=True, exist_ok=True)
                        (sdir / "queued.bin").write_bytes(pbytes)
                        with _lot_lock:
                            _lot_spawns.setdefault(lot_id, []).append({"token": stoken, "filename": pname})
                        pending.append((stoken, pname))
                    result["extra_parts"] = []
                    tmp = tdir / "prepared.pkl.tmp"
                    tmp.write_bytes(pickle.dumps(result))  # ponytail: pickle interne, même process
                    tmp.replace(tdir / "prepared.pkl")  # publication atomique
                    _record_extract_hit(ip)
                except Exception:
                    ref = uuid.uuid4().hex[:8].upper()
                    app.logger.exception("[lot] réf=%s tenant=%s token=%s", ref, slug, token)
                    try:
                        (tdir / "prepared.err").write_text(ref)
                    except OSError:
                        pass

        threading.Thread(target=worker, daemon=True).start()

    def _start_lot(entries: list, jobs: list[tuple[str, str]], api_key: str) -> None:
        """Installe un nouveau lot en session et lance l'extraction de fond des 'jobs'."""
        _clear_single()
        lot_id = uuid.uuid4().hex
        session["lot"] = entries
        session["lot_id"] = lot_id
        session.pop("lot_active_token", None)
        session.pop("lot_generated", None)
        if jobs:
            _lot_extract_bg(lot_id, jobs, api_key, request.remote_addr, getattr(g.tenant, "slug", "?"))

    def _extract_quota_message() -> str:
        wait = _throttle_retry_in("extract", 600)
        mins = max(1, -(-wait // 60))  # arrondi supérieur
        return (f"Limite d'extractions atteinte (30 sur 10 minutes). "
                f"Réessayez dans {mins} minute{'s' if mins > 1 else ''}.")

    @app.route("/extract", methods=["POST"])
    def extract():
        # Chaque extraction coûte un appel API Anthropic — 30 par IP / 10 min
        # (relevé de 10 → 30 pour les lots de devis, cf. flux batch).
        if _throttled("extract", limit=30, window=600):
            flash(_extract_quota_message(), "error")
            return redirect(url_for("index"))
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            flash("Clé API d'extraction non configurée — contactez votre prestataire.", "error")
            return redirect(url_for("index"))

        paste_text = request.form.get("paste_text", "").strip()
        session["fast_mode"] = request.form.get("fast_mode") == "1"

        def _post_extract_redirect():
            return redirect(url_for("quick_client") if session.get("fast_mode") else url_for("review"))

        # ── Mode "coller un email" ──
        if paste_text:
            _lot_clear()
            from .pdf_extractor import _extract_from_text, _detect_brand_from_text
            import re as _re
            t0 = time.time()
            app.logger.info("extraction démarrée tenant=%s type=paste taille=%d car.",
                            getattr(g.tenant, "slug", "?"), len(paste_text))
            try:
                data = _extract_from_text(paste_text, api_key=api_key)
            except Exception as exc:
                _flash_extract_error(exc)
                return redirect(url_for("index"))
            app.logger.info("extraction réussie tenant=%s type=paste durée=%.1fs marque=%s",
                            getattr(g.tenant, "slug", "?"), time.time() - t0, data.get("marque", "?"))
            if _re.search(r"\d[\s ]*[€$]?\s*HT\b|\bHT\s*[:=]\s*\d", paste_text, _re.IGNORECASE):
                data["coeff_base"] = "ht"
            if data.get("marque", "Autre").lower() in ("autre", ""):
                detected = _detect_brand_from_text(paste_text[:500])
                if detected:
                    data["marque"] = detected
            if not (data.get("sav") or {}).get("date"):
                if "sav" not in data or not isinstance(data["sav"], dict):
                    data["sav"] = {}
                data["sav"]["date"] = datetime.now().strftime("%d.%m.%Y")
            session["token"] = uuid.uuid4().hex
            session["data"] = data
            session["source_kind"] = "text"
            session["source_text"] = paste_text
            return _post_extract_redirect()

        # ── Mode fichier(s) ──
        uploads = [f for f in request.files.getlist("pdf") if f and f.filename]
        if not uploads:
            flash("Veuillez sélectionner un fichier ou coller un email.", "error")
            return redirect(url_for("index"))
        if len(uploads) > _BATCH_MAX_FILES:
            flash(f"Trop de fichiers ({len(uploads)}). Maximum {_BATCH_MAX_FILES} par lot — "
                  "divisez en plusieurs envois.", "error")
            return redirect(url_for("index"))
        for f in uploads:
            if not _has_extension(f.filename, ALLOWED_DOC):
                flash(f"'{f.filename}' : le fichier doit être un PDF, un email (.eml) ou un message Outlook (.msg).", "error")
                return redirect(url_for("index"))

        _lot_clear()

        # ── Plusieurs fichiers → lot direct (tout extrait en fond, vue lot live) ──
        if len(uploads) > 1:
            entries, jobs = [], []
            for f in uploads:
                b = f.read()
                if not b:
                    continue
                token = uuid.uuid4().hex
                tdir = UPLOAD_DIR / token
                tdir.mkdir(parents=True, exist_ok=True)
                (tdir / "queued.bin").write_bytes(b)
                entries.append({"token": token, "status": "pending",
                                "summary": None, "source_kind": None, "err_ref": None})
                jobs.append((token, f.filename))
            if not entries:
                flash("Les fichiers sont vides.", "error")
                return redirect(url_for("index"))
            _start_lot(entries, jobs, api_key)
            return redirect(url_for("lot"))

        # ── Un seul fichier : extraction synchrone ; si multi-devis détecté → lot ──
        first = uploads[0]
        file_bytes = first.read()
        if not file_bytes:
            flash("Le fichier est vide.", "error")
            return redirect(url_for("index"))
        try:
            prepared = _extract_prepared(file_bytes, first.filename, api_key, getattr(g.tenant, "slug", "?"))
        except Exception as exc:
            _flash_extract_error(exc)
            return redirect(url_for("index"))

        extra = prepared.get("extra_parts") or []
        if extra:
            # PDF multi-devis : part 1 déjà extraite (ready), les autres en fond.
            for msg in prepared.get("warnings") or []:
                flash(msg, "warning")
            t1 = uuid.uuid4().hex
            entry1 = {"token": t1, "status": "pending", "summary": None,
                      "source_kind": None, "err_ref": None}
            _materialize_entry(entry1, {"data": prepared["data"], "source_kind": prepared["source_kind"],
                                        "source_payload": prepared["source_payload"]})
            entries, jobs = [entry1], []
            base = first.filename.rsplit(".", 1)[0]
            for pbytes, pname in extra:
                tok = uuid.uuid4().hex
                tdir = UPLOAD_DIR / tok
                tdir.mkdir(parents=True, exist_ok=True)
                (tdir / "queued.bin").write_bytes(pbytes)
                entries.append({"token": tok, "status": "pending", "summary": None,
                                "source_kind": None, "err_ref": None})
                jobs.append((tok, pname))
            _start_lot(entries, jobs, api_key)
            return redirect(url_for("lot"))

        # Devis unique classique.
        prepared["extra_parts"] = []
        _install_prepared(prepared)
        return _post_extract_redirect()

    def _lot_counts(lot: list) -> dict:
        return {
            "total": len(lot),
            "pending": sum(1 for e in lot if e["status"] == "pending"),
            "ready": sum(1 for e in lot if e["status"] == "ready"),
            "verified": sum(1 for e in lot if e["status"] == "verified"),
            "ignored": sum(1 for e in lot if e["status"] == "ignored"),
            "error": sum(1 for e in lot if e["status"] == "error"),
            "to_generate": sum(1 for e in lot if e["status"] in ("ready", "verified")),
        }

    @app.route("/lot")
    def lot():
        lot = _lot_reconcile()
        if not lot:
            return redirect(url_for("index"))
        return render_template("lot.html", lot=lot, counts=_lot_counts(lot),
                               generated=bool(session.get("lot_generated")))

    @app.route("/lot/status")
    def lot_status():
        lot = _lot_reconcile()
        counts = _lot_counts(lot)
        counts["entries"] = [{"token": e["token"], "status": e["status"]} for e in lot]
        return jsonify(counts)

    @app.route("/lot/edit/<token>")
    def lot_edit(token: str):
        entry = _lot_entry(token)
        if not entry or entry["status"] not in ("ready", "verified"):
            return redirect(url_for("lot"))
        tdir = UPLOAD_DIR / token
        dpath = tdir / "data.pkl"
        if not dpath.exists():
            flash("Données du devis introuvables — relancez l'extraction.", "error")
            return redirect(url_for("lot"))
        session["token"] = token
        session["data"] = pickle.loads(dpath.read_bytes())
        session["source_kind"] = entry.get("source_kind") or "none"
        if entry.get("source_kind") == "text":
            stxt = tdir / "source.txt"
            session["source_text"] = stxt.read_text(encoding="utf-8") if stxt.exists() else ""
            session.pop("source_pdf", None)
        else:
            session["source_pdf"] = "source.pdf"
            session.pop("source_text", None)
        session["lot_active_token"] = token
        return redirect(url_for("review"))

    @app.route("/lot/<token>/ignore", methods=["POST"])
    def lot_ignore(token: str):
        entry = _lot_entry(token)
        if entry and entry["status"] in ("ready", "verified"):
            entry["prev_status"] = entry["status"]
            entry["status"] = "ignored"
            session["lot"] = _lot_get()
        return redirect(url_for("lot"))

    @app.route("/lot/<token>/restore", methods=["POST"])
    def lot_restore(token: str):
        entry = _lot_entry(token)
        if entry and entry["status"] == "ignored":
            entry["status"] = entry.pop("prev_status", None) or "ready"
            session["lot"] = _lot_get()
        return redirect(url_for("lot"))

    @app.route("/lot/generate", methods=["POST"])
    def lot_generate():
        lot = _lot_reconcile()
        to_gen = [e for e in lot if e["status"] in ("ready", "verified")]
        if not to_gen:
            flash("Aucun devis à générer dans ce lot.", "error")
            return redirect(url_for("lot"))

        # Régénération (après modif) : un devis déjà généré ne recompte pas dans le quota.
        already = {g_["token"] for g_ in (session.get("lot_generated") or [])}
        new_count = sum(1 for e in to_gen if e["token"] not in already)
        if g.tenant.devis_limit is not None and new_count:
            used = db.get_monthly_devis_count(g.tenant.slug)
            if used + new_count > g.tenant.devis_limit:
                left = max(0, g.tenant.devis_limit - used)
                flash(f"Limite mensuelle : {new_count} nouveau(x) devis à générer mais {left} restant(s). "
                      "Ignorez-en ou contactez votre prestataire.", "error")
                return redirect(url_for("lot"))

        generated = []
        for e in to_gen:
            token = e["token"]
            tdir = UPLOAD_DIR / token
            dpath = tdir / "data.pkl"
            if not dpath.exists():
                continue
            data = pickle.loads(dpath.read_bytes())
            if e["status"] == "ready":
                # Non vérifié : applique les coefficients marque par défaut (comme le mode rapide).
                client_nom = (data.get("client") or {}).get("nom", "") or "CLIENT"
                fake_form = _data_to_quick_form(data, client_nom, g.tenant.coefficients)
                data = _form_to_data(fake_form, photo_dir=tdir)
            photos = {
                "montre": [(tdir / n).read_bytes() for n in _existing_photos(token, "montre")],
            }
            names = _write_devis_files(token, data, photos, log=token not in already)
            if names:
                generated.append({"token": token, "names": names["names"],
                                   "generated_at": datetime.now().isoformat()})

        if not generated:
            flash("Aucun devis n'a pu être généré.", "error")
            return redirect(url_for("lot"))
        session["lot_generated"] = generated
        return redirect(url_for("lot_done"))

    @app.route("/lot/done")
    def lot_done():
        generated = session.get("lot_generated") or []
        if not generated:
            return redirect(url_for("index"))
        # Vue des téléchargements = accusé de réception : la bannière d'accueil s'efface.
        session["lot_ack"] = True
        return render_template("lot_done.html", nav_active="fournisseur", generated=generated)

    _PHOTO_NAME_RE = re.compile(r"montre_\d+\.jpg|opt_[0-9a-f]{8}\.jpg")

    @app.route("/photo/<token>/<name>")
    def session_photo(token: str, name: str):
        """Sert une photo déjà attachée à ce devis (session courante uniquement)."""
        if token != session.get("token") or not _PHOTO_NAME_RE.fullmatch(name):
            abort(404)
        path = UPLOAD_DIR / token / name
        if not path.exists():
            abort(404)
        return Response(path.read_bytes(), mimetype="image/jpeg")

    @app.route("/dev-preview")
    def dev_preview():
        """Route de test locale uniquement — injecte des données de démo."""
        if not app.debug:
            abort(404)
        session["token"] = uuid.uuid4().hex
        session["data"] = {
            "marque": "Chanel",
            "client": {"nom": "DUPONT MARIE"},
            "sav": {"numero": "383750", "date": "13.05.2026", "lieu": "Avignon"},
            "montre": {
                "modele": "J12", "reference": "H2569 - UNI P",
                "numero_serie": "SS17159", "poids": "", "metal": "", "taille": "",
                "etat": ["RAYURES SUR LA BOITE", "USURE DU BRACELET"],
            },
            "service_complet_description": "Démontage complet\nNettoyage ultrason\nHuilage et réglage",
            "interventions_necessaires": [
                {"description": "REVISION COMPLETE - CHRONO QUARTZ", "prix": 830.00},
                {"description": "REMPLACEMENT BRACELET", "prix": 216.25},
                {"description": "POLISSAGE BOITE", "prix": 95.00, "prix_label": "INCL"},
                {"description": "REMPLACEMENT VERRE SAPHIR", "prix": 0.00},
            ],
            "interventions_optionnelles": [{"description": "DORURE OR JAUNE 18K", "prix": 320.00}],
            "total_ttc": 1046.25,
            "delai": "6 à 8 semaines",
        }
        return redirect(url_for("review"))

    def _existing_photos(token: str | None, prefix: str) -> list[str]:
        """Noms des photos déjà attachées à ce devis (extraction, ou générations précédentes)."""
        if not token:
            return []
        session_dir = UPLOAD_DIR / token
        if not session_dir.is_dir():
            return []
        return sorted(p.name for p in session_dir.glob(f"{prefix}_*.jpg"))

    @app.route("/review", methods=["GET"])
    def review():
        data = session.get("data")
        if not data:
            return redirect(url_for("index"))
        # tenant mono-boutique : le lieu affiché doit être celui qui sera vraiment
        # utilisé à la génération (_form_to_data applique le même défaut autoritaire),
        # sinon le champ affiche une valeur extraite qui sera silencieusement ignorée.
        if _default_lieu():
            data.setdefault("sav", {})["lieu"] = _default_lieu()
        token = session.get("token")
        lot_mode = bool(session.get("lot_active_token") == token and token)
        return render_template("form.html", data=data, marques=MARQUES,
                               coefficients_json=json.dumps(g.tenant.coefficients, ensure_ascii=False),
                               source_kind=session.get("source_kind", "none"),
                               source_text=session.get("source_text", ""),
                               token=token, lot_mode=lot_mode,
                               montre_photo_files=_existing_photos(token, "montre"))

    def _write_devis_files(token: str, data: dict, photos: dict, log: bool = True) -> dict | None:
        """Construit docx/pdf(+csv) sous GENERATED_DIR/token, logue le devis (sauf régé). Renvoie
        {docx_name, pdf_name, csv_name, method} ou None (flash d'erreur déjà posé)."""
        gen_data = dict(data)
        gen_data["interventions_optionnelles"] = _hydrate_option_photos(
            data.get("interventions_optionnelles") or [], UPLOAD_DIR / token
        )
        try:
            docx_bytes = build_docx(gen_data, maison_name=g.tenant.maison_name,
                                    legal_footer=g.tenant.legal_footer, photos=photos)
        except Exception:
            _flash_internal_error("la génération du document Word")
            return None
        try:
            pdf_bytes, method = docx_to_pdf(
                docx_bytes, data=gen_data,
                maison_name=g.tenant.maison_name, logo_bytes=g.tenant.logo_png,
                legal_footer=g.tenant.legal_footer, photos=photos,
            )
        except Exception:
            _flash_internal_error("la génération du PDF")
            return None

        out_dir = GENERATED_DIR / token
        out_dir.mkdir(parents=True, exist_ok=True)
        base_name = _build_filename(data, g.tenant.maison_name)
        docx_name = f"{base_name}.docx"
        pdf_name = f"{base_name}.pdf"
        (out_dir / docx_name).write_bytes(docx_bytes)
        (out_dir / pdf_name).write_bytes(pdf_bytes)
        csv_name = None
        if g.tenant.feature_bijoux3_export:
            csv_name = f"{base_name}_bijoux3.csv"
            (out_dir / csv_name).write_bytes(_data_to_bijoux3_csv(data))
        if log:
            db.log_devis(g.tenant.slug)
        return {"docx_name": docx_name, "pdf_name": pdf_name,
                "csv_name": csv_name, "method": method,
                "names": [n for n in (docx_name, pdf_name, csv_name) if n]}

    def _finalize_devis(token: str, data: dict, photos: dict, score=None, missing=None):
        """Génère un devis UNIQUE et rend done.html. None si échec (flash déjà posé)."""
        names = _write_devis_files(token, data, photos)
        if names is None:
            return None
        session["lot_generated"] = [{"token": token, "names": names["names"],
                                      "generated_at": datetime.now().isoformat()}]
        return render_template("done.html", nav_active="fournisseur", token=token,
                               docx_name=names["docx_name"], pdf_name=names["pdf_name"],
                               csv_name=names["csv_name"], method=names["method"],
                               confidence=score, confidence_missing=missing)

    @app.route("/generate", methods=["POST"])
    def generate():
        token = session.get("token")
        if not token:
            flash("Session expirée, veuillez recharger un PDF.", "error")
            return redirect(url_for("index"))

        lot_token = session.get("lot_active_token")
        is_lot = bool(lot_token == token)

        # Quota : contrôlé à la génération finale du lot, pas à chaque enregistrement.
        if not is_lot and g.tenant.devis_limit is not None \
                and db.get_monthly_devis_count(g.tenant.slug) >= g.tenant.devis_limit:
            flash("Limite de devis mensuelle atteinte. Contactez votre prestataire pour l'augmenter.", "error")
            return redirect(url_for("review"))

        photo_dir = UPLOAD_DIR / token
        photo_dir.mkdir(parents=True, exist_ok=True)

        data = _form_to_data(request.form, request.files, photo_dir=photo_dir)
        score, missing = confidence_score(data)
        session["data"] = data  # léger : les options ne portent qu'un nom de fichier, pas les octets

        # Montre (max 2, dans la même case infos) : on combine les photos déjà
        # attachées (conservées) + les nouveaux uploads, et on réécrit l'état final
        # sur disque sous des noms stables — c'est ce même état que /review relira
        # si l'utilisateur revient modifier le devis (cf. bug "les photos disparaissent").
        montre_photos, montre_rejected = _sync_section_photos(
            photo_dir, "montre",
            kept=request.form.getlist("montre_photos_kept[]"),
            uploads=request.files.getlist("photos_montre"),
            max_count=2,
        )
        if montre_rejected:
            flash("Certaines photos ont été ignorées : formats acceptés = jpg, png, webp (2 max pour la pièce).", "warning")
        photos = {"montre": montre_photos}

        # ── Lot : on ENREGISTRE le devis (statut vérifié), génération différée à la fin ──
        if is_lot:
            (photo_dir / "data.pkl").write_bytes(pickle.dumps(data))
            entry = _lot_entry(token)
            if entry:
                entry["status"] = "verified"
                entry["summary"] = _summary(data)
                session["lot"] = _lot_get()
            session.pop("lot_active_token", None)
            flash("Devis vérifié et enregistré dans le lot.", "success")
            return redirect(url_for("lot"))

        result = _finalize_devis(token, data, photos, score=score, missing=missing)
        if result is None:
            return redirect(url_for("review"))
        return result

    @app.route("/review/quick", methods=["GET"])
    def quick_client():
        """Mode rapide : juste le nom du client, pas de relecture détaillée."""
        data = session.get("data")
        if not data:
            return redirect(url_for("index"))
        token = session.get("token")
        return render_template("quick_client.html", data=data,
                               client_nom=(data.get("client") or {}).get("nom", ""),
                               montre_photo_files=_existing_photos(token, "montre"))

    @app.route("/review/quick", methods=["POST"])
    def quick_client_submit():
        token = session.get("token")
        if not token:
            flash("Session expirée, veuillez recharger un PDF.", "error")
            return redirect(url_for("index"))
        if g.tenant.devis_limit is not None and db.get_monthly_devis_count(g.tenant.slug) >= g.tenant.devis_limit:
            flash("Limite de devis mensuelle atteinte. Contactez votre prestataire pour l'augmenter.", "error")
            return redirect(url_for("quick_client"))

        client_nom = request.form.get("client_nom", "").strip()
        if not client_nom:
            flash("Le nom du client est obligatoire.", "error")
            return redirect(url_for("quick_client"))

        photo_dir = UPLOAD_DIR / token
        photo_dir.mkdir(parents=True, exist_ok=True)

        # Formulaire synthétique = ce que /review soumettrait sans aucun ajustement
        # manuel (coefficient de marque appliqué automatiquement) — délègue le calcul
        # du prix client à _form_to_data, la même logique que le flux complet.
        fake_form = _data_to_quick_form(session.get("data") or {}, client_nom, g.tenant.coefficients)
        data = _form_to_data(fake_form, photo_dir=photo_dir)
        score, missing = confidence_score(data)
        session["data"] = data

        photos = {
            "montre": [(photo_dir / n).read_bytes() for n in _existing_photos(token, "montre")],
        }

        result = _finalize_devis(token, data, photos, score=score, missing=missing)
        if result is None:
            return redirect(url_for("quick_client"))
        return result

    def _allowed_download_tokens() -> set[str]:
        """Tokens téléchargeables dans cette session : le devis courant + tous ceux générés
        (devis unique ou lot partenaire) présents dans session['lot_generated'] + tous les
        devis horloger générés dans cette session (session['demo_tickets'])."""
        tokens = {t for t in (session.get("token"),) if t}
        tokens |= {d["token"] for d in (session.get("lot_generated") or [])}
        tokens |= {t["token"] for t in _demo_tickets() if t.get("token")}
        return tokens

    @app.route("/download/<token>/<path:filename>")
    def download(token: str, filename: str):
        if token not in _allowed_download_tokens():
            abort(403)
        directory = GENERATED_DIR / secure_filename(token)
        safe_name = secure_filename(filename)
        if not (directory / safe_name).is_file():
            abort(404)
        return send_from_directory(directory, safe_name, as_attachment=True)

    @app.route("/demo/view/<token>/<path:filename>")
    def demo_view_pdf(token: str, filename: str):
        """Comme /download mais sans Content-Disposition: attachment — nécessaire pour
        que l'iframe de la popup d'aperçu affiche le PDF au lieu de déclencher un téléchargement."""
        if token not in _allowed_download_tokens():
            abort(403)
        directory = GENERATED_DIR / secure_filename(token)
        safe_name = secure_filename(filename)
        if not (directory / safe_name).is_file():
            abort(404)
        return send_from_directory(directory, safe_name, as_attachment=False)

    @app.route("/demo/photo-piece/<token>/<path:filename>")
    def demo_view_photo(token: str, filename: str):
        """Photo de la pièce jointe à un devis partenaire (extraite avec le PDF) — affichée
        dans le popup d'aperçu Fournisseur, même garde que /demo/view."""
        if token not in _allowed_download_tokens():
            abort(403)
        directory = UPLOAD_DIR / secure_filename(token)
        safe_name = secure_filename(filename)
        if not (directory / safe_name).is_file():
            abort(404)
        return send_from_directory(directory, safe_name, as_attachment=False)

    @app.route("/download-all")
    def download_all():
        """ZIP de tous les devis générés (lot courant, session courante)."""
        done_list = session.get("lot_generated") or []
        if not done_list:
            flash("Aucun devis généré à télécharger.", "error")
            return redirect(url_for("index"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            seen_names: set[str] = set()
            for entry in done_list:
                directory = GENERATED_DIR / secure_filename(entry["token"])
                for name in entry.get("names") or []:
                    if not name.lower().endswith(".pdf"):
                        continue
                    path = directory / secure_filename(name)
                    if not path.is_file():
                        continue
                    arcname = name
                    if arcname in seen_names:  # collision improbable, filet de sécurité
                        arcname = f"{entry['token'][:8]}_{name}"
                    seen_names.add(arcname)
                    zf.write(path, arcname=arcname)
        buf.seek(0)
        return Response(
            buf.getvalue(), mimetype="application/zip",
            headers={"Content-Disposition": "attachment; filename=devis.zip"},
        )

    @app.route("/source/<token>")
    def source_file(token: str):
        if token != session.get("token") or session.get("source_kind") != "pdf":
            abort(404)
        directory = UPLOAD_DIR / secure_filename(token)
        filename = secure_filename(session.get("source_pdf", ""))
        if not filename or not (directory / filename).is_file():
            abort(404)
        return send_from_directory(directory, filename, mimetype="application/pdf")

    @app.route("/prepare-signature", methods=["POST"])
    def prepare_signature():
        token = session.get("token")
        client_email = request.json.get("email") if request.json else None
        if not token or not client_email:
            return jsonify({"error": "Missing token or email"}), 400
        directory = GENERATED_DIR / secure_filename(token)
        pdf_files = list(directory.glob("*.pdf"))
        if not pdf_files:
            return jsonify({"error": "No PDF found"}), 404
        pdf_path = pdf_files[0]
        result = _create_yousign_signature_request(pdf_path.read_bytes(), client_email, pdf_path.stem)
        if not result:
            return jsonify({"error": "Failed to create Yousign procedure"}), 500
        return jsonify(result)

    @app.route("/cgv")
    def cgv():
        # static/cgv.pdf = CGV Doux (les QR des devis legal_footer pointent ici).
        # ponytail: CGV par tenant (colonne bytea) si un autre client en veut.
        if not g.tenant.legal_footer:
            abort(404)
        return send_from_directory(str(BASE_DIR / "static"), "cgv.pdf", mimetype="application/pdf")

    @app.route("/guide")
    def guide():
        return render_template("guide.html")

    @app.route("/mentions-legales")
    def mentions_legales():
        return render_template("mentions_legales.html")

    @app.route("/confidentialite")
    def confidentialite():
        return render_template("confidentialite.html")

    # ── Administration : édition protégée des coefficients (par tenant) ──
    def _admin_password_ok(submitted: str) -> bool:
        return check_password_hash(g.tenant.admin_password_hash, submitted or "")

    def admin_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not (session.get("is_admin") and session.get("admin_tenant_slug") == g.tenant.slug):
                return redirect(url_for("admin_login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("is_admin") and session.get("admin_tenant_slug") == g.tenant.slug:
            return redirect(url_for("admin_coefficients"))
        if request.method == "POST":
            if _throttled("admin_login", limit=5, window=900, record=False):
                flash("Trop de tentatives. Réessayez dans 15 minutes.", "error")
            elif _admin_password_ok(request.form.get("password", "")):
                session["is_admin"] = True
                session["admin_tenant_slug"] = g.tenant.slug
                return redirect(_safe_next(request.args.get("next")) or url_for("admin_coefficients"))
            else:
                _throttled("admin_login", limit=5, window=900)  # enregistre l'échec
                flash("Mot de passe incorrect.", "error")
        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        session.pop("admin_tenant_slug", None)
        return redirect(url_for("index"))

    @app.route("/admin/coefficients", methods=["GET"])
    @admin_required
    def admin_coefficients():
        return render_template("admin_coefficients.html", nav_active="marques",
                               coefficients=g.tenant.coefficients)

    @app.route("/admin/coefficients", methods=["POST"])
    @admin_required
    def admin_coefficients_save():
        new = _coefficients_from_form(request.form, existing=g.tenant.coefficients)
        if not new:
            flash("Aucune marque valide à enregistrer — modifications ignorées.", "error")
            return redirect(url_for("admin_coefficients"))
        try:
            db.save_tenant_coefficients(g.tenant.slug, new)
            _invalidate_tenant(g.tenant.slug)
        except Exception:
            _flash_internal_error("l'enregistrement des coefficients")
            return redirect(url_for("admin_coefficients"))
        flash(f"{len(new)} marque(s) enregistrée(s).", "success")
        return redirect(url_for("admin_coefficients"))

    def _generate_devis_files(data: dict) -> tuple[str, str, str, str | None]:
        """Construit le docx/pdf (+ csv Bijoux3 si activé) et les enregistre sous un nouveau token.

        Retourne (token, docx_name, pdf_name, csv_name | None).
        """
        docx_bytes = build_docx(data, maison_name=g.tenant.maison_name, legal_footer=g.tenant.legal_footer)
        pdf_bytes, _method = docx_to_pdf(docx_bytes, data=data, maison_name=g.tenant.maison_name,
                                         logo_bytes=g.tenant.logo_png, legal_footer=g.tenant.legal_footer)
        token = uuid.uuid4().hex
        session["token"] = token
        out_dir = GENERATED_DIR / token
        out_dir.mkdir(parents=True, exist_ok=True)
        base_name = _build_filename(data, g.tenant.maison_name)
        docx_name = f"{base_name}.docx"
        pdf_name = f"{base_name}.pdf"
        (out_dir / docx_name).write_bytes(docx_bytes)
        (out_dir / pdf_name).write_bytes(pdf_bytes)
        csv_name = None
        if g.tenant.feature_bijoux3_export:
            csv_name = f"{base_name}_bijoux3.csv"
            (out_dir / csv_name).write_bytes(_data_to_bijoux3_csv(data))
        db.log_devis(g.tenant.slug)
        return token, docx_name, pdf_name, csv_name

    @app.route("/admin/creation", methods=["GET"])
    @admin_required
    def admin_creation():
        if not g.tenant.feature_creation:
            abort(404)
        return render_template("admin_creation.html", nav_active="creation")

    @app.route("/admin/creation", methods=["POST"])
    @admin_required
    def admin_creation_save():
        if not g.tenant.feature_creation:
            abort(404)
        if g.tenant.devis_limit is not None and db.get_monthly_devis_count(g.tenant.slug) >= g.tenant.devis_limit:
            flash("Limite de devis mensuelle atteinte. Contactez votre prestataire pour l'augmenter.", "error")
            return redirect(url_for("admin_creation"))

        client_nom = request.form.get("client_nom", "").strip()
        type_piece = request.form.get("type_piece", "").strip()
        materiau = request.form.get("materiau", "").strip()
        description = request.form.get("description", "").strip()
        try:
            prix_ht = float((request.form.get("prix_ht") or "0").replace(",", "."))
        except ValueError:
            prix_ht = 0.0

        if not client_nom or not description or prix_ht <= 0:
            flash("Nom du client, description et prix sont obligatoires.", "error")
            return redirect(url_for("admin_creation"))

        db.create_creation(g.tenant.slug, client_nom, description, prix_ht)
        data = _creation_to_data(client_nom, type_piece, materiau, description, prix_ht)

        try:
            token, docx_name, pdf_name, csv_name = _generate_devis_files(data)
        except Exception:
            _flash_internal_error("la génération du devis")
            return redirect(url_for("admin_creation"))

        return render_template("done.html", token=token, docx_name=docx_name, pdf_name=pdf_name,
                               csv_name=csv_name, method="creation", confidence=None, confidence_missing=None)

    @app.route("/admin/sav-rapide", methods=["GET"])
    @admin_required
    def admin_sav_rapide():
        if not g.tenant.feature_sav_rapide:
            abort(404)
        return render_template("admin_sav_rapide.html", nav_active="sav_rapide",
                               creations=db.list_creations(g.tenant.slug))

    @app.route("/admin/sav-rapide", methods=["POST"])
    @admin_required
    def admin_sav_rapide_save():
        if not g.tenant.feature_sav_rapide:
            abort(404)
        if g.tenant.devis_limit is not None and db.get_monthly_devis_count(g.tenant.slug) >= g.tenant.devis_limit:
            flash("Limite de devis mensuelle atteinte. Contactez votre prestataire pour l'augmenter.", "error")
            return redirect(url_for("admin_sav_rapide"))

        client_nom = request.form.get("client_nom", "").strip()
        note = request.form.get("note", "").strip()
        try:
            prix = float((request.form.get("prix") or "0").replace(",", "."))
        except ValueError:
            prix = 0.0

        if not client_nom or not note or prix <= 0:
            flash("Nom du client, travaux effectués et prix sont obligatoires.", "error")
            return redirect(url_for("admin_sav_rapide"))

        data = _sav_quick_to_data(client_nom, note, prix)

        try:
            token, docx_name, pdf_name, csv_name = _generate_devis_files(data)
        except Exception:
            _flash_internal_error("la génération du devis")
            return redirect(url_for("admin_sav_rapide"))

        return render_template("done.html", token=token, docx_name=docx_name, pdf_name=pdf_name,
                               csv_name=csv_name, method="sav_rapide", confidence=None, confidence_missing=None)

    # ── DÉMO CAUBET (jeudi) : Accueil (comptoir) + Atelier (horloger), plusieurs SAV en
    # file simultanément, en session — rien en base au-delà du tenant `caubet` lui-même.
    # Réutilise le moteur de prix/PDF existant (_brand_coeff_defaults, _ceil5,
    # _write_devis_files) — aucune logique de prix dupliquée.
    # ponytail : SMS/email 100% simulés (pas de Twilio/Resend), pas de vraie vérif de stock,
    # pas de photo par ticket (retiré avec la v1 mono-ticket, pas demandé dans le nouveau design).
    def _demo_preconisation(motif: str) -> str:
        try:
            phrases = json.loads((BASE_DIR / "static" / "phrases.json").read_text(encoding="utf-8"))
        except Exception:
            phrases = {}
        low = (motif or "").lower()
        hits = [sentence for kw, sentence in phrases.items() if kw in low]
        return " ".join(hits) if hits else "À examiner à réception — aucune préconisation automatique déduite du motif."

    def _demo_preconisation_ai(motif: str, etat: str) -> dict:
        """Préconisation horloger + travaux recommandés déduits du motif/état via Haiku,
        contraints au référentiel réel d'opérations (_DEMO_OP_CATEGORIES, recopiées à
        l'identique) pour ne jamais suggérer un travail qui n'existe pas dans l'outil.
        Calculé une seule fois par ticket — mis en cache dessus (cf. appelant), jamais relancé
        à chaque affichage de la fiche atelier. Repli sur l'ancien mot-clé si l'IA est
        indisponible : {"text": ..., "ops": []}."""
        motif, etat = (motif or "").strip(), (etat or "").strip()
        fallback = {"text": _demo_preconisation(motif), "ops": []}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not (motif or etat) or not api_key or _throttled("describe", limit=40, window=600):
            return fallback
        all_ops = {op for _, ops in _DEMO_OP_CATEGORIES for op in ops}
        catalogue = "\n".join(f"- {op} ({fam})" for fam, ops in _DEMO_OP_CATEGORIES for op in ops)
        prompt = (
            "Tu es horloger dans un SAV. Un client a déposé une pièce avec :\n"
            f"Motif du dépôt : {motif or '—'}\n"
            f"État constaté : {etat or '—'}\n\n"
            "Référentiel d'opérations possibles (choisis UNIQUEMENT dans cette liste, "
            "recopie les libellés à l'identique, sans les modifier) :\n" + catalogue + "\n\n"
            "Réponds EXACTEMENT sur ce format, rien d'autre :\n"
            "PRECONISATION: <3 à 6 mots MAXIMUM, pas de phrase, pas de verbe conjugué — "
            "juste l'essentiel de l'approche recommandée, ex. \"Révision complète + contrôle "
            "d'étanchéité\">\n"
            "TRAVAUX:\n"
            "- <opération recopiée du référentiel>\n"
            "(2 à 5 opérations maximum, seulement les plus pertinentes pour ce motif/état)"
        )
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in msg.content if getattr(b, "text", None)).strip()
        except Exception:
            app.logger.exception("préconisation IA : échec, repli sur le mot-clé")
            return fallback
        text, ops = fallback["text"], []
        for line in raw.splitlines():
            line = line.strip()
            if line.upper().startswith("PRECONISATION:"):
                text = line.split(":", 1)[1].strip() or text
            elif line.startswith("-"):
                # Haiku ajoute parfois "(Famille)" après l'opération malgré la consigne —
                # on le retire avant de comparer au référentiel exact.
                op = re.sub(r"\s*\([^)]*\)\s*$", "", line[1:].strip())
                if op in all_ops:
                    ops.append(op)
        return {"text": text, "ops": ops[:5]}

    _DEMO_STOCK_KEYWORDS = {"verre": "En stock", "bracelet": "En stock", "pile": "En stock", "vitre": "En stock"}

    _DEMO_MOTIF_CHIPS = [
        ("Révision complète", "Révision complète."),
        ("Montre ne fonctionne plus", "Montre ne fonctionne plus."),
        ("Avance / retard", "Avance / retard."),
        ("Problème de remontage", "Problème de remontage."),
        ("Problème de date / calendrier", "Problème de date / calendrier."),
        ("Problème de chronographe", "Problème de chronographe."),
        ("Remplacement de pile / accumulateur", "Remplacement de pile / accumulateur."),
        ("Problème d'étanchéité / humidité", "Problème d'étanchéité / humidité."),
        ("Choc / chute", "Choc / chute."),
        ("Casse ou détérioration esthétique", "Casse ou détérioration esthétique."),
    ]

    _DEMO_ETAT_CHIPS = [
        ("Bon état général", "Bon état général."),
        ("Usure normale", "Usure normale."),
        ("Rayures sur le boîtier", "Rayures sur le boîtier."),
        ("Rayures sur le verre", "Rayures sur le verre."),
        ("Chocs / impacts visibles", "Chocs / impacts visibles."),
        ("Bracelet usé / détérioré", "Bracelet usé / détérioré."),
        ("Boîtier détérioré / marqué", "Boîtier détérioré / marqué."),
        ("Présence d'humidité / condensation", "Présence d'humidité / condensation."),
        ("Montre arrêtée / ne fonctionne pas", "Montre arrêtée / ne fonctionne pas."),
        ("État très dégradé / nécessitant une remise en état", "État très dégradé / nécessitant une remise en état."),
    ]

    # Modèles courants par marque, pour la datalist du champ "Pièce" — suggestions seulement,
    # le champ reste du texte libre (marque absente d'ici → pas de suggestion, pas bloquant).
    _DEMO_PIECE_MODELS = {
        "Rolex": ["Submariner", "Datejust", "Daytona", "GMT-Master II", "Oyster Perpetual",
                  "Day-Date", "Explorer", "Sea-Dweller", "Yacht-Master", "Explorer II"],
        "Omega": ["Speedmaster", "Seamaster Diver 300M", "Seamaster Aqua Terra",
                  "Seamaster Planet Ocean", "Constellation", "De Ville", "Moonwatch",
                  "Seamaster Railmaster"],
        "Cartier": ["Tank", "Santos", "Panthère", "Ballon Bleu", "Pasha", "Santos-Dumont",
                    "Baignoire", "Tank Française", "Tank Américaine"],
        "Breitling": ["Navitimer", "Chronomat", "Superocean", "Avenger", "Premier",
                      "Endurance Pro", "Colt", "Top Time"],
        "TAG Heuer": ["Carrera", "Monaco", "Aquaracer", "Formula 1", "Autavia", "Link",
                      "Connected", "Monza"],
        "Tudor": ["Black Bay", "Black Bay 58", "Black Bay Chrono", "Pelagos", "Ranger",
                  "1926", "Royal", "Glamour"],
        "Longines": ["Conquest", "HydroConquest", "Master Collection", "Spirit", "DolceVita",
                     "Legend Diver", "Flagship", "PrimaLuna"],
        "Tissot": ["PRX", "Le Locle", "Gentleman", "Seastar", "T-Touch", "Chrono XL",
                   "Everytime", "Visodate"],
        "Patek Philippe": ["Nautilus", "Aquanaut", "Calatrava", "Grand Complications",
                           "Complications", "Twenty~4", "Gondolo"],
        "Audemars Piguet": ["Royal Oak", "Royal Oak Offshore", "Royal Oak Concept",
                            "Code 11.59", "Millenary", "Jules Audemars"],
    }

    # Référentiel d'opérations horlogerie, rangées par famille — remplace l'ancien mur de
    # puces plates (12 items, prix HT indicatif) par un sélecteur à deux niveaux : familles
    # numérotées à gauche, opérations de la famille active à droite (cf. maquette validée,
    # mockups/atelier_operations_picker.html). Ces opérations n'ont pas de prix associé —
    # elles ne remplissent que la Description, le Prix HT reste saisi à la main comme pour
    # toute intervention non chiffrée d'avance.
    _DEMO_OP_CATEGORIES = [
        ("Révision & Mouvement", [
            "Révision complète mécanique et automatique", "Nettoyage et huilage du mouvement",
            "Remplacement du ressort de barillet et des rouages", "Réglage de précision et d'amplitude",
            "Réparation du système antichoc"]),
        ("Boîtier & Finition", [
            "Polissage du boîtier", "Satinage", "Finition poli-satiné", "Micro-billage",
            "Redressage du boîtier", "Réparation des cornes", "Remplacement du fond",
            "Traitement anti-rayures PVD/DLC"]),
        ("Étanchéité", [
            "Contrôle d'étanchéité", "Remplacement des joints", "Graissage des joints", "Test 3 ATM",
            "Test 10 ATM", "Test plongée", "Test de condensation", "Test de surpression et dépression"]),
        ("Verre", [
            "Remplacement du verre saphir, minéral ou plexiglas", "Remplacement de verre bombé",
            "Remplacement avec loupe date", "Traitement antireflet", "Polissage des rayures superficielles",
            "Recollage du verre"]),
        ("Couronne & Poussoirs", [
            "Remplacement de couronne", "Couronne vissée", "Tige de remontoir", "Tube de couronne",
            "Réparation du filetage", "Remplacement des poussoirs",
            "Réparation des joints et mécanismes de poussoirs"]),
        ("Bracelet & Fermoir", [
            "Remplacement bracelet cuir ou métal", "Remplacement boucle ardillon ou déployante",
            "Retrait ou ajout de maillons", "Remplacement d'axes et goupilles", "Réparation des attaches",
            "Remplacement des barrettes", "Ajustement du bracelet"]),
        ("Quartz & Pile", [
            "Remplacement de pile", "Remplacement accumulateur solaire", "Contrôle de consommation",
            "Remplacement moteur pas-à-pas", "Remplacement circuit intégré", "Réparation des contacts",
            "Remplacement du mouvement quartz"]),
        ("Diagnostic & Contrôle", [
            "Diagnostic visuel", "Diagnostic du mouvement", "Test de fonctionnement",
            "Contrôle amplitude et précision", "Diagnostic d'étanchéité", "Contrôle final",
            "Certificat de service", "Mise à jour du carnet d'entretien"]),
    ]

    def _demo_stock_badge(motif: str) -> str:
        low = (motif or "").lower()
        for kw, badge in _DEMO_STOCK_KEYWORDS.items():
            if kw in low:
                return badge
        return "À commander"

    _DEMO_PHOTO_NAME_RE = re.compile(r"piece\.jpg|line_[0-9a-f]{8}\.jpg")

    def _demo_photo_dir(ticket_id: str):
        d = UPLOAD_DIR / "demo" / ticket_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _demo_save_photo(ticket_id: str, file_storage, name: str) -> str | None:
        """Normalise et écrit une photo uploadée pour ce ticket. None si absente/invalide."""
        if not file_storage or not file_storage.filename:
            return None
        if not _has_extension(file_storage.filename, ALLOWED_PHOTO_IMG):
            return None
        normalized = _normalize_photo(file_storage.read())
        if not normalized:
            return None
        (_demo_photo_dir(ticket_id) / name).write_bytes(normalized)
        return name

    def _demo_tickets() -> list[dict]:
        return session.get("demo_tickets") or []

    def _demo_save(tickets: list[dict]) -> None:
        session["demo_tickets"] = tickets

    def _demo_find(ticket_id: str) -> dict | None:
        for t in _demo_tickets():
            if t["id"] == ticket_id:
                return t
        return None

    def _demo_selected_id(tickets: list[dict]) -> str | None:
        requested = request.args.get("ticket")
        if requested and any(t["id"] == requested for t in tickets):
            return requested
        return tickets[-1]["id"] if tickets else None

    def _demo_context() -> dict:
        """Contexte partagé Comptoir / Atelier / Devis — même source, deux pages."""
        tickets = _demo_tickets()
        selected = _demo_find(_demo_selected_id(tickets))
        atelier_detail = None
        if selected and selected["status"] == "en_cours":
            if "preco_ai" not in selected:
                selected["preco_ai"] = _demo_preconisation_ai(selected["motif"], selected.get("etat_constate", ""))
                _demo_save([selected if t["id"] == selected["id"] else t for t in tickets])
            atelier_detail = {
                "preconisation": selected["preco_ai"]["text"],
                "recommended_ops": selected["preco_ai"]["ops"],
                "stock": _demo_stock_badge(selected["motif"]),
            }
        return {
            "tickets": tickets,
            "marques": sorted(g.tenant.coefficients.keys()),
            "en_cours": [t for t in tickets if t["status"] == "en_cours"],
            "a_valider": [t for t in tickets if t["status"] == "a_valider"],
            "envoyes": [t for t in tickets if t["status"] == "envoye"],
            "historique": [t for t in tickets if t["status"] in ("envoye", "valide", "refuse")],
            "selected": selected,
            "motif_chips": _DEMO_MOTIF_CHIPS,
            "etat_chips": _DEMO_ETAT_CHIPS,
            "piece_models": _DEMO_PIECE_MODELS,
            "op_categories": _DEMO_OP_CATEGORIES,
            "atelier_detail": atelier_detail,
        }

    @app.route("/demo")
    def demo_dashboard():
        """Ancienne page unique (accueil + atelier en onglets) → modules dédiés.

        Conservée comme redirection : tous les POST du flux démo renvoient encore
        ici avec ?tab=..., et les liens/marque-pages existants continuent de marcher.
        """
        target = "atelier" if request.args.get("tab") == "atelier" else "comptoir"
        args = {k: v for k, v in request.args.items() if k != "tab"}
        return redirect(url_for(target, **args))

    def _erp_kpis(ctx: dict, partenaires: list[dict]) -> dict:
        """Les 4 chiffres partagés par Comptoir et Tableau de bord — même source, même
        définition partout (sinon deux pages affichent deux vérités différentes)."""
        return {
            "kpi_atelier": len(ctx["en_cours"]),
            "kpi_a_valider": len(ctx["a_valider"]),
            "kpi_partenaires": sum(1 for p in partenaires if p["status"] in ("extraction", "a_verifier", "genere")),
            "kpi_encaisse": sum(t["total"] for t in ctx["tickets"] if t["status"] == "valide")
                            + sum(p["total"] for p in partenaires if p["status"] == "accepte"),
        }

    @app.route("/comptoir")
    def comptoir():
        ctx = _demo_context()
        partenaires = _partner_devis_rows()
        # La colonne Comptoir ne montre que ce qui attend encore une décision — un devis
        # accepté/refusé disparaît d'ici, il reste consultable dans Partenaire uniquement.
        partenaires_pending = [p for p in partenaires if p["status"] not in ("accepte", "refuse")]
        # 3 groupes toujours visibles (même à 0), miroir des 2 groupes du côté Horloger —
        # extraction se range avec à_vérifier : les deux attendent une action côté comptoir.
        # Vocabulaire de groupe unifié avec la frise (Chiffrage/Envoi/Décision client) — les
        # anciens noms ("Attente validation comptoir"...) répétaient parfois le tag responsable
        # de la ligne (Comptoir/Client), parfois pas : un seul jeu de mots, l'acteur ne vit
        # plus que dans le tag par ligne.
        partenaires_groups = [
            ("Chiffrage", "", [p for p in partenaires_pending if p["status"] in ("extraction", "a_verifier")]),
            ("Envoi", "is-option", [p for p in partenaires_pending if p["status"] == "genere"]),
            ("Décision client", "is-envoye", [p for p in partenaires_pending if p["status"] == "envoye"]),
        ]
        return render_template("comptoir.html", nav_active="comptoir",
                               lot_status=_lot_status(), partenaires=partenaires_pending,
                               partenaires_groups=partenaires_groups,
                               focus=request.args.get("focus"),
                               **_erp_kpis(ctx, partenaires), **ctx)

    @app.route("/atelier")
    def atelier():
        ctx = _demo_context()
        return render_template("atelier.html", nav_active="atelier",
                               focus=request.args.get("focus"), **ctx)

    @app.route("/comptoir/horloger")
    def horloger():
        """Sous-page de Comptoir : suivi des devis horloger. Aucune création ici.
        Le registre ne montre que ce qui est en attente — un devis accepté en sort et ne
        vit plus que dans la section « Devis validés » (repliée)."""
        ctx = _demo_context()
        statut = request.args.get("statut") or ""
        valides = [t for t in ctx["tickets"] if t["status"] == "valide"]
        suivis = [t for t in ctx["tickets"] if t["status"] not in ("en_cours", "valide")]
        if statut:
            suivis = [t for t in suivis if t["status"] == statut]
        return render_template(
            "horloger.html", nav_active="horloger", focus=request.args.get("focus"),
            suivis=list(reversed(suivis)), valides=list(reversed(valides)), statut=statut,
            statuts=[("", "Tous"), ("a_valider", "À envoyer"), ("envoye", "Envoyés"),
                     ("refuse", "Refusés")],
            **ctx)

    @app.route("/comptoir/fournisseur")
    def fournisseur():
        """Sous-page de Comptoir : suivi des devis partenaires. Aucune création ici —
        l'import reste sur Comptoir (bannière « Nouveau SAV »). Le registre ne montre que ce
        qui est en attente — un devis accepté en sort, il ne vit plus que dans la section
        « Devis validés » (repliée)."""
        partenaires = _partner_devis_rows()
        validees = [p for p in partenaires if p["status"] == "accepte"]
        pending = [p for p in partenaires if p["status"] != "accepte"]
        statut = request.args.get("statut") or ""
        rows = [p for p in pending if not statut or p["status"] == statut]
        return render_template(
            "fournisseur.html", nav_active="fournisseur", focus=request.args.get("focus"),
            partenaires=rows, validees=validees, tous=partenaires, statut=statut,
            statuts=[("", "Tous"), ("a_verifier", "À vérifier"), ("genere", "Générés"),
                     ("envoye", "Envoyés"), ("refuse", "Refusés")],
            lot_status=_lot_status(),
            lot_en_cours=[p for p in partenaires if p["status"] in ("extraction", "a_verifier")])

    @app.route("/fournisseur/<token>/respond", methods=["POST"])
    def fournisseur_respond(token: str):
        """Réponse client sur un devis partenaire — saisie à la main (pas de SMS ici),
        c'est ce qui le fait entrer (ou non) dans l'encaissé du mois."""
        decision = request.form.get("decision")
        if decision not in ("envoye", "accepte", "refuse", "reset"):
            abort(400)
        statuses = dict(_partner_status())
        if decision == "reset":
            statuses.pop(token, None)
            flash("Réponse client effacée.", "success")
        elif decision == "envoye":
            statuses[token] = {"decision": "envoye", "sent_at": datetime.now().isoformat()}
            flash("Devis partenaire marqué « envoyé ».", "success")
        elif decision == "accepte":
            try:
                amount = float((request.form.get("amount") or "0").replace(",", "."))
            except ValueError:
                amount = 0.0
            statuses[token] = {"decision": "accepte", "amount": amount}
            flash(f"Devis partenaire marqué « accepté » — {amount:.2f} € retenus.", "success")
        else:
            statuses[token] = decision
            flash("Devis partenaire marqué « refusé ».", "success")
        session["partner_status"] = statuses
        return redirect(request.referrer or url_for("fournisseur", focus=token))

    def _since_badge(hhmm: str | None) -> dict | None:
        """Ancienneté d'un dépôt pour la colonne "Depuis" du tableau "À traiter" — repère
        visuel vert/orange/rouge pour trier au coup d'œil quoi traiter en premier. Basé sur
        deposited_at (HH:MM, même jour) : renvoie None si absent (ex. devis partenaire, pas
        encore de timestamp stocké) plutôt que d'inventer une ancienneté.
        ponytail : pas de vraie date (juste HH:MM) → ne distingue pas "hier" de "il y a 3
        jours", suffisant pour une démo sur une seule journée d'ouverture."""
        if not hhmm:
            return None
        try:
            deposited = datetime.strptime(hhmm, "%H:%M").replace(
                year=datetime.now().year, month=datetime.now().month, day=datetime.now().day)
        except ValueError:
            return None
        minutes = max(0, (datetime.now() - deposited).total_seconds() / 60)
        if minutes < 120:
            label = f"{int(minutes)} min" if minutes >= 1 else "à l'instant"
            level = "ok"
        elif minutes < 720:
            label = f"{minutes / 60:.0f} h"
            level = "warn"
        else:
            label = f"{minutes / 60:.0f} h"
            level = "late"
        return {"label": label, "level": level}

    @app.route("/tableau-de-bord")
    def tableau_de_bord():
        ctx = _demo_context()
        devis_used = devis_pct = None
        if g.tenant.devis_limit is not None:
            devis_used = db.get_monthly_devis_count(g.tenant.slug)
            devis_pct = min(100, round(devis_used / g.tenant.devis_limit * 100)) \
                if g.tenant.devis_limit else 100
        partenaires = _partner_devis_rows()

        # ── À traiter : uniquement ce qui attend une action avant envoi (pas encore chez le
        # client) — chaque ligne porte la prochaine étape, pas seulement le statut actuel.
        # Vocabulaire unifié "À <verbe>" pour toute étape actionnable, même mot des deux côtés
        # quand l'étape est la même (généré horloger / généré partenaire → tous deux "À envoyer"). ──
        NEXT_STEP = {
            "en_cours": "À chiffrer", "a_valider": "À envoyer",
            "extraction": "Extraction en cours…", "a_verifier": "À vérifier", "genere": "À envoyer",
        }
        # Mini-frise "Avancement" (3 étapes : Chiffrage/préparation → Envoi → Décision client) —
        # même étape "avant envoi" pour horloger (en_cours) et partenaire (extraction/a_verifier),
        # même étape "prêt à envoyer" pour a_valider/genere. Décision client n'apparaît jamais ici
        # (ces devis passent dans "Tous les devis" dès qu'ils sont envoyés).
        STEP = {"en_cours": 0, "extraction": 0, "a_verifier": 0, "a_valider": 1, "genere": 1}
        a_traiter = []
        for t in ctx["en_cours"]:
            a_traiter.append({
                "origine": "horloger", "ref": "—", "client": t["client_nom"],
                "piece": t["piece"] + (" · " + t["marque"] if t["marque"] else ""),
                "total": None, "status": t["status"], "next": NEXT_STEP["en_cours"],
                "step": STEP["en_cours"],
                "responsable": "Atelier", "since": _since_badge(t.get("deposited_at")),
                "link": url_for("atelier", ticket=t["id"], focus=t["id"]),
            })
        for t in ctx["a_valider"]:
            a_traiter.append({
                "origine": "horloger", "ref": t["devis_numero"], "client": t["client_nom"],
                "piece": t["piece"] + (" · " + t["marque"] if t["marque"] else ""),
                "total": t["total"], "status": t["status"], "next": NEXT_STEP["a_valider"],
                "step": STEP["a_valider"],
                "responsable": "Comptoir", "since": _since_badge(t.get("deposited_at")),
                "link": url_for("horloger", focus=t["id"]),
            })
        for p in partenaires:
            if p["status"] not in ("extraction", "a_verifier", "genere"):
                continue
            next_step = NEXT_STEP[p["status"]]
            a_traiter.append({
                "origine": "partenaire", "ref": "—", "client": p["client"],
                "piece": p["marque"] or "—",
                "total": None if p["status"] == "extraction" else p["total"],
                "status": p["status"], "next": next_step,
                "step": STEP[p["status"]],
                "responsable": "Comptoir", "since": None,  # pas de timestamp stocké côté partenaire
                "link": url_for("fournisseur", focus=p["token"]),
            })

        # ── Tous les devis : uniquement ce qui est vraiment "en suivi" — envoyé (en attente
        # de validation), à relancer, ou accepté. Pas encore envoyé → dans "à traiter"
        # ci-dessus ; refusé → fin de parcours, plus rien à suivre. ──
        # Statut → groupe d'affichage : ce qui attend une réponse client vs ce qui est déjà
        # tranché — même vocabulaire que fournisseur.html/horloger.html ("Devis validés").
        tous_devis = []
        for t in ctx["tickets"]:
            if t["status"] not in ("envoye", "valide"):
                continue
            tous_devis.append({
                "origine": "horloger", "ref": t["devis_numero"], "client": t["client_nom"],
                "piece": t["piece"] + (" · " + t["marque"] if t["marque"] else ""),
                "total": t["total"], "status": t["status"],
                "relance": t["status"] == "envoye" and _is_relance(t.get("sent_at")),
                "group": "valide" if t["status"] == "valide" else "attente",
                "token": t["token"], "pdf_name": t["pdf_name"],
                "link": url_for("horloger", focus=t["id"]),
            })
        for p in partenaires:
            if p["status"] not in ("envoye", "accepte"):
                continue
            tous_devis.append({
                "origine": "partenaire", "ref": "—", "client": p["client"],
                "piece": p["marque"] or "—", "total": p["total"], "status": p["status"],
                "relance": p["relance"],
                "group": "valide" if p["status"] == "accepte" else "attente",
                "token": p["token"], "pdf_name": p["pdf_name"],
                "link": url_for("fournisseur", focus=p["token"]),
            })
        tous_devis.reverse()
        for i, d in enumerate(tous_devis):
            d["row_id"] = i

        # ── Répartition SAV : volumétrie horloger/partenaire + marques les plus représentées,
        # même source que les listes ci-dessus — pas de second comptage divergent. ──
        marques_count = Counter(
            [t["marque"] for t in ctx["tickets"] if t["marque"]] +
            [p["marque"] for p in partenaires if p["marque"]]
        )

        return render_template(
            "tableau_de_bord.html", nav_active="dashboard",
            a_traiter=a_traiter,
            tous_devis=tous_devis[:20],
            partenaires=partenaires,
            partenaires_a_traiter=sum(1 for p in partenaires
                                      if p["status"] in ("extraction", "a_verifier", "genere")),
            nb_sav_horloger=len(ctx["tickets"]), nb_sav_partenaire=len(partenaires),
            top_marques=marques_count.most_common(4),
            lot_status=_lot_status(), devis_used=devis_used,
            devis_limit=g.tenant.devis_limit, devis_pct=devis_pct,
            **_erp_kpis(ctx, partenaires), **ctx)

    @app.route("/devis")
    def devis_registre():
        """Ancien registre unique → éclaté en Horloger / Fournisseur. Redirection conservée
        pour les liens et marque-pages existants."""
        return redirect(url_for("horloger"))

    @app.route("/demo/photo/<ticket_id>/<name>")
    def demo_photo(ticket_id: str, name: str):
        if not _demo_find(ticket_id) or not _DEMO_PHOTO_NAME_RE.fullmatch(name):
            abort(404)
        path = UPLOAD_DIR / "demo" / ticket_id / name
        if not path.exists():
            abort(404)
        return Response(path.read_bytes(), mimetype="image/jpeg")

    @app.route("/demo/fiche", methods=["POST"])
    def demo_fiche_save():
        client_nom = request.form.get("client_nom", "").strip()
        client_tel = request.form.get("client_tel", "").strip()
        marque = request.form.get("marque", "").strip()
        piece = request.form.get("piece", "").strip()
        motif = request.form.get("motif", "").strip()
        etat_constate = request.form.get("etat_constate", "").strip()
        if not client_nom or not client_tel or not piece:
            flash("Nom, téléphone et pièce sont obligatoires.", "error")
            return redirect(url_for("demo_dashboard"))

        ticket_id = uuid.uuid4().hex[:8]
        photo_file = _demo_save_photo(ticket_id, request.files.get("photo"), "piece.jpg")
        prenom = client_nom.split()[0] if client_nom.split() else client_nom
        ticket = {
            "id": ticket_id,
            "client_nom": client_nom, "client_tel": client_tel, "marque": marque,
            "piece": piece, "motif": motif, "etat_constate": etat_constate,
            "deposited_at": datetime.now().strftime("%H:%M"),
            "status": "en_cours",
            "lines": {"nec": [], "opt": []},
            "total": 0.0,
            "photo_file": photo_file,
            "token": None, "pdf_name": None,
            "outbox": [{
                "channel": "sms", "side": "out", "time": datetime.now().strftime("%H:%M"),
                "text": (f"Bonjour {prenom}, votre {piece} a bien été déposée en SAV chez "
                         f"{g.tenant.maison_name}. Vous serez prévenu(e) dès le devis prêt."),
            }],
        }
        tickets = _demo_tickets()
        tickets.append(ticket)
        _demo_save(tickets)
        flash("Fiche enregistrée, l'horloger est notifié.", "success")
        # focus (pas ticket) : rouvre directement le popup SMS en direct sur Comptoir,
        # cf. auto-ouverture dans comptoir.html.
        return redirect(url_for("demo_dashboard", focus=ticket["id"]))

    @app.route("/demo/atelier/<ticket_id>/line", methods=["POST"])
    def demo_atelier_add_line(ticket_id: str):
        ticket = _demo_find(ticket_id)
        if not ticket or ticket["status"] != "en_cours":
            return redirect(url_for("demo_dashboard", tab="atelier"))

        kind = request.form.get("kind") if request.form.get("kind") in ("nec", "opt") else "nec"
        desc = request.form.get("description", "").strip()
        try:
            prix_ht = float((request.form.get("prix_ht") or "0").replace(",", "."))
        except ValueError:
            prix_ht = 0.0
        marque = request.form.get("marque", "").strip() or ticket.get("marque", "")
        if not desc:
            flash("Ajoutez une description avant d'enregistrer la ligne.", "error")
        elif prix_ht <= 0:
            flash("Indiquez un prix HT avant d'enregistrer la ligne.", "error")
        else:
            ticket["marque"] = marque
            defaults = _brand_coeff_defaults(marque, g.tenant.coefficients)
            if kind == "nec":
                coeff = defaults["coeff"] if defaults["nec_default"] else 1.0
            else:
                coeff = (defaults["coeff_opt"] or defaults["coeff"]) if defaults["opt_default"] else 1.0
            prix_client = _ceil5(prix_ht * coeff)
            photo_name = f"line_{secrets.token_hex(4)}.jpg"
            photo_file = _demo_save_photo(ticket_id, request.files.get("photo"), photo_name)
            ticket["lines"][kind].append({
                "description": desc, "prix_ht": prix_ht, "coeff": coeff, "prix_client": prix_client,
                "photo_file": photo_file,
            })
            ticket["total"] = sum(l["prix_client"] for l in ticket["lines"]["nec"])
        tickets = _demo_tickets()
        _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="atelier"))

    @app.route("/demo/atelier/<ticket_id>/line/<kind>/<int:idx>/delete", methods=["POST"])
    def demo_atelier_delete_line(ticket_id: str, kind: str, idx: int):
        ticket = _demo_find(ticket_id)
        # Verrou : un devis déjà finalisé a un PDF figé sur disque — retirer une ligne ici
        # désynchroniserait les données du ticket de ce PDF sans le regénérer. Le bouton est déjà
        # masqué côté template (editable=false) une fois finalisé ; ce garde-fou serveur est la
        # vraie protection (l'UI seule ne suffit jamais à empêcher un POST direct).
        if ticket and ticket["status"] != "en_cours":
            return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="accueil"))
        if ticket and kind in ("nec", "opt") and 0 <= idx < len(ticket["lines"][kind]):
            ticket["lines"][kind].pop(idx)
            ticket["total"] = sum(l["prix_client"] for l in ticket["lines"]["nec"])
            tickets = _demo_tickets()
            _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="atelier"))

    def _demo_build_pdf(ticket: dict, token: str, devis_numero: str) -> dict | None:
        """Construit/régénère le PDF (+ DOCX) d'un ticket vers UPLOAD_DIR/token — réutilisé par
        la finalisation (nouveau token) ET le recalcul de coefficient (même token, écrase les
        fichiers existants). Aucune logique de prix ici : les prix_client sont déjà calculés
        sur les lignes du ticket avant l'appel."""
        src_dir = UPLOAD_DIR / "demo" / ticket["id"]
        dst_dir = UPLOAD_DIR / token
        dst_dir.mkdir(parents=True, exist_ok=True)

        def _nec_line(l: dict) -> dict:
            out = {"description": l["description"], "prix": l["prix_client"], "prix_client": l["prix_client"]}
            if l.get("detail"):
                out["detail"] = l["detail"]
            # Hydraté ici directement (pas via _hydrate_option_photos, réservé à l'optionnel dans
            # _write_devis_files) — _photo_bytes lu depuis le dossier photos du ticket démo.
            if l.get("photo_file") and (src_dir / l["photo_file"]).is_file():
                out["_photo_bytes"] = (src_dir / l["photo_file"]).read_bytes()
            return out

        def _opt_line(l: dict) -> dict:
            out = {"description": l["description"], "prix": l["prix_client"], "prix_client": l["prix_client"]}
            # _write_devis_files hydrate lui-même l'optionnel via _hydrate_option_photos(..., UPLOAD_DIR/token)
            # → on copie le fichier photo dans ce dossier pour qu'il le retrouve par son nom.
            if l.get("photo_file") and (src_dir / l["photo_file"]).is_file():
                (dst_dir / l["photo_file"]).write_bytes((src_dir / l["photo_file"]).read_bytes())
                out["photo_file"] = l["photo_file"]
            return out

        data = {
            "marque": ticket["marque"],
            "client": {"nom": ticket["client_nom"]},
            "sav": {"numero": devis_numero,
                    "date": datetime.now().strftime("%d/%m/%Y"), "lieu": _default_lieu()},
            "montre": {
                "modele": ticket["piece"],
                # Puces "État constaté" saisies au comptoir (cf. _DEMO_ETAT_CHIPS) — même
                # slot PDF que l'"état" de l'app d'origine (liste à puces, pdf_generator.py).
                "etat": [s.strip() for s in (ticket.get("etat_constate") or "").split(".") if s.strip()],
            },
            "titre": "DEVIS DE RÉPARATION", "intro_text": "",
            "interventions_necessaires": [_nec_line(l) for l in ticket["lines"]["nec"]],
            "interventions_optionnelles": [_opt_line(l) for l in ticket["lines"]["opt"]],
            "total_ttc": ticket["total"], "delai": "à convenir",
        }
        piece_photos = []
        if ticket.get("photo_file") and (src_dir / ticket["photo_file"]).is_file():
            piece_photos = [(src_dir / ticket["photo_file"]).read_bytes()]
        return _write_devis_files(token, data, photos={"montre": piece_photos})

    def _haiku_polish(text: str) -> str:
        """Reformule une description de ligne en une phrase professionnelle via Haiku, à la
        finalisation du devis (automatique, aucun clic horloger). Best-effort : renvoie le
        texte d'origine si la clé API manque, si le quota est atteint ou si l'appel échoue —
        jamais bloquant pour la génération du devis."""
        text = (text or "").strip()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not text or not api_key or _throttled("describe", limit=40, window=600):
            return text
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            prompt = (
                "Reformule cette description d'intervention horlogerie en UNE SEULE phrase "
                "professionnelle et concise, pour un devis client (français, pas de liste, pas "
                "de puces, pas de guillemets, garde le sens) :\n" + text
            )
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001", max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            polished = "".join(b.text for b in msg.content if getattr(b, "text", None)).strip()
            return polished or text
        except Exception:
            app.logger.exception("Haiku polish : échec, conservation du texte d'origine")
            return text

    @app.route("/demo/atelier/<ticket_id>/finalize", methods=["POST"])
    def demo_atelier_finalize(ticket_id: str):
        ticket = _demo_find(ticket_id)
        if not ticket or not ticket["lines"]["nec"]:
            flash("Ajoutez au moins une ligne de travail nécessaire avant de finaliser.", "error")
            return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="atelier"))

        token = uuid.uuid4().hex[:12]
        seq = (session.get("demo_devis_seq") or 0) + 1
        session["demo_devis_seq"] = seq
        devis_numero = f"CAUBET-{datetime.now():%Y}-{seq:04d}"

        # Reformulation automatique des descriptions (Haiku) au moment de générer le devis —
        # une seule fois, le résultat reste sur la ligne (un recalcul de coefficient ne
        # relance pas l'appel). Best-effort : chaque ligne garde son texte d'origine si
        # l'appel échoue, cf. _haiku_polish. Le texte brut (souvent le détail concret des
        # opérations, ex. "+ Toute la famille") est gardé en petit sous la ligne du PDF
        # (nécessaire uniquement — cf. pdf_generator.py, "detail").
        for kind in ("nec", "opt"):
            for l in ticket["lines"][kind]:
                original = l["description"]
                polished = _haiku_polish(original)
                if polished and polished != original:
                    l["detail"] = original
                    l["description"] = polished

        names = _demo_build_pdf(ticket, token, devis_numero)
        if names is None:
            return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="atelier"))

        ticket["token"] = token
        ticket["pdf_name"] = names["pdf_name"]
        ticket["devis_numero"] = devis_numero
        ticket["status"] = "a_valider"
        lot = session.get("lot_generated") or []
        lot.append({"token": token, "names": names["names"]})
        session["lot_generated"] = lot

        tickets = _demo_tickets()
        _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        flash("Devis finalisé — vérifiez et envoyez-le au client.", "success")
        return redirect(url_for("atelier"))

    @app.route("/demo/<ticket_id>/recalc", methods=["POST"])
    def demo_recalc(ticket_id: str):
        """Accueil : ajuste le coefficient de chaque ligne (nec/opt) et régénère le PDF sur
        place (même token/numéro — le devis reste "le même", juste recalculé). Verrouillé aux
        devis pas encore envoyés : au-delà, le PDF a pu être vu/téléchargé par le client, le
        régénérer sous le même lien créerait une incohérence."""
        ticket = _demo_find(ticket_id)
        if not ticket or ticket["status"] != "a_valider":
            return redirect(url_for("demo_dashboard", ticket=ticket_id, tab="accueil"))

        for kind in ("nec", "opt"):
            submitted = request.form.getlist(f"{kind}_coeff[]")
            for i, line in enumerate(ticket["lines"][kind]):
                if i >= len(submitted):
                    continue
                try:
                    coeff = float(submitted[i].replace(",", "."))
                except (ValueError, AttributeError):
                    continue  # valeur invalide → coefficient existant conservé pour cette ligne
                line["coeff"] = coeff
                line["prix_client"] = _ceil5(line["prix_ht"] * coeff)
        ticket["total"] = sum(l["prix_client"] for l in ticket["lines"]["nec"])

        names = _demo_build_pdf(ticket, ticket["token"], ticket["devis_numero"])
        if names is None:
            flash("Erreur lors de la régénération du PDF.", "error")
            return redirect(url_for("horloger", focus=ticket_id))

        tickets = _demo_tickets()
        _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        flash("Devis recalculé et PDF régénéré.", "success")
        return redirect(url_for("horloger", focus=ticket_id))

    @app.route("/demo/<ticket_id>/send", methods=["POST"])
    def demo_send(ticket_id: str):
        ticket = _demo_find(ticket_id)
        if not ticket or ticket["status"] != "a_valider":
            return redirect(url_for("demo_dashboard"))
        prenom = ticket["client_nom"].split()[0] if ticket["client_nom"].split() else ticket["client_nom"]
        ticket["outbox"].append({
            "channel": "email", "side": "in", "time": datetime.now().strftime("%H:%M"),
            "text": "Votre devis SAV est prêt.", "attach": f"Devis_{prenom}.pdf",
        })
        ticket["outbox"].append({
            "channel": "sms", "side": "out", "time": datetime.now().strftime("%H:%M"),
            "text": (f"Votre devis SAV ({ticket['total']:.2f} €) est prêt et vous a été envoyé par email. "
                     "Vous pouvez aussi le consulter et le valider ici."),
        })
        ticket["status"] = "envoye"
        ticket["sent_at"] = datetime.now().isoformat()
        tickets = _demo_tickets()
        _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        flash("Devis envoyé au client — suivez sa réponse ci-dessous.", "success")
        return redirect(url_for("horloger", focus=ticket_id))

    @app.route("/demo/<ticket_id>/respond", methods=["POST"])
    def demo_respond(ticket_id: str):
        ticket = _demo_find(ticket_id)
        if not ticket or ticket["status"] != "envoye":
            return redirect(request.referrer or url_for("demo_dashboard"))
        decision = request.form.get("decision")
        if decision == "yes":
            # Le client peut avoir pris le nécessaire seul ou avec des options — le montant
            # choisi (palier) remplace le total par défaut, même principe que côté Partenaire.
            try:
                amount = float((request.form.get("amount") or "0").replace(",", "."))
            except ValueError:
                amount = 0.0
            if amount > 0:
                ticket["total"] = amount
            ticket["status"] = "valide"
        else:
            ticket["status"] = "refuse"
        ticket["outbox"].append({
            "channel": "sms", "side": "in", "time": datetime.now().strftime("%H:%M"),
            "text": "Devis accepté ✓ Lancez le SAV." if decision == "yes" else "Devis refusé.",
        })
        tickets = _demo_tickets()
        _demo_save([ticket if t["id"] == ticket_id else t for t in tickets])
        # Toujours vers Horloger avec le focus sur ce ticket — pas le referrer : le popup se
        # rouvre directement sur le fil client mis à jour (demande explicite : garder le popup
        # "ouvert" pour voir le SMS partir, plutôt que de retomber sur la liste).
        return redirect(url_for("horloger", focus=ticket_id))

    @app.route("/demo/reset")
    def demo_reset():
        session.pop("demo_tickets", None)
        session.pop("demo_devis_seq", None)
        flash("Démo réinitialisée.", "success")
        return redirect(url_for("demo_dashboard"))

    # ── Super-admin : gestion de tous les tenants (Victor uniquement) ──
    # Contourne la résolution par tenant (cf. before_request) — ces routes
    # gèrent tous les clients, pas un seul, et fonctionnent depuis n'importe quel hôte.
    def _superadmin_password_ok(submitted: str) -> bool:
        expected = os.environ.get("SUPERADMIN_PASSWORD") or ""
        return bool(expected) and hmac.compare_digest(submitted, expected)

    def superadmin_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("is_superadmin"):
                return redirect(url_for("superadmin_login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def _normalize_logo(file_storage) -> bytes | None:
        if not file_storage or not file_storage.filename:
            return None
        if not _has_extension(file_storage.filename, ALLOWED_LOGO_IMG):
            return None
        from io import BytesIO
        from PIL import Image
        data = file_storage.stream.read()
        if _has_extension(file_storage.filename, {"svg"}):
            # ponytail: rasterize via svglib/renderPM (pure-pip, no system Cairo needed)
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
            drawing = svg2rlg(BytesIO(data))
            scale = max(1.0, 400 / max(drawing.width, drawing.height))
            drawing.width *= scale
            drawing.height *= scale
            drawing.scale(scale, scale)
            png_buf = BytesIO()
            renderPM.drawToFile(drawing, png_buf, fmt="PNG", bg=0xffffff)
            data = png_buf.getvalue()
        img = Image.open(BytesIO(data)).convert("RGBA")
        # ponytail: rogne les marges blanches/transparentes pour que le logo
        # ne soit pas écrasé quand le template le contraint à height:44px
        alpha = img.getchannel("A")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        bg.paste(img, mask=alpha)
        content = Image.eval(bg.convert("L"), lambda x: 0 if x > 235 else 255)
        bbox = content.getbbox()
        if bbox:
            pad = max(4, round(max(img.size) * 0.03))
            left, top, right, bottom = bbox
            bbox = (max(0, left - pad), max(0, top - pad),
                    min(img.width, right + pad), min(img.height, bottom + pad))
            img = img.crop(bbox)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def _tenant_link(slug: str) -> str | None:
        """Construit l'URL publique du tenant à partir de l'hôte de la requête courante.

        Marche en local (slug.localhost:5000) comme en prod une fois le domaine
        branché (slug.devisly.fr) — pas de config séparée à maintenir.
        """
        host = request.host
        hostname, _, port = host.partition(":")
        labels = hostname.split(".")
        if hostname == "localhost" or hostname.endswith(".localhost"):
            base = "localhost"
        elif hostname == "127.0.0.1":
            base = "127.0.0.1"
        elif hostname.endswith(".onrender.com"):
            return None  # pas de sous-domaine wildcard sur l'URL Render brute
        elif len(labels) >= 3 and labels[0] != "www":
            base = ".".join(labels[1:])  # hôte déjà sur un sous-domaine → on le retire
        else:
            base = hostname  # apex (ex: devisly.fr)
        suffix = f":{port}" if port else ""
        return f"{request.scheme}://{slug}.{base}{suffix}"

    @app.route("/superadmin/login", methods=["GET", "POST"])
    def superadmin_login():
        if session.get("is_superadmin"):
            return redirect(url_for("superadmin_list"))
        if request.method == "POST":
            if _throttled("superadmin_login", limit=5, window=900, record=False):
                flash("Trop de tentatives. Réessayez dans 15 minutes.", "error")
            elif not os.environ.get("SUPERADMIN_PASSWORD"):
                flash("Aucun mot de passe super-admin configuré (variable SUPERADMIN_PASSWORD).", "error")
            elif _superadmin_password_ok(request.form.get("password", "")):
                session["is_superadmin"] = True
                return redirect(_safe_next(request.args.get("next")) or url_for("superadmin_list"))
            else:
                _throttled("superadmin_login", limit=5, window=900)  # enregistre l'échec
                flash("Mot de passe incorrect.", "error")
        return render_template("superadmin_login.html")

    @app.route("/superadmin/logout")
    def superadmin_logout():
        session.pop("is_superadmin", None)
        return redirect(url_for("superadmin_login"))

    @app.route("/superadmin/", methods=["GET"])
    @superadmin_required
    def superadmin_list():
        tenants = db.list_tenants()
        links = {t.slug: _tenant_link(t.slug) for t in tenants}
        counts = db.get_devis_counts()
        totals = {
            "month": sum(c["month"] for c in counts.values()),
            "total": sum(c["total"] for c in counts.values()),
            "active": sum(1 for t in tenants if t.active),
            "quota_reached": sum(
                1 for t in tenants
                if t.devis_limit is not None and counts.get(t.slug, {}).get("month", 0) >= t.devis_limit
            ),
        }
        quota_pct = {}
        for t in tenants:
            if t.devis_limit is not None:
                month = counts.get(t.slug, {}).get("month", 0)
                quota_pct[t.slug] = 100 if t.devis_limit == 0 else min(100, round(month / t.devis_limit * 100))
        return render_template("superadmin_list.html", tenants=tenants, links=links,
                               counts=counts, totals=totals, quota_pct=quota_pct)

    @app.route("/superadmin/new", methods=["GET", "POST"])
    @superadmin_required
    def superadmin_new():
        if request.method == "POST":
            slug = (request.form.get("slug") or "").strip().lower()
            slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-")
            if not slug:
                flash("Sous-domaine (slug) invalide.", "error")
                return redirect(url_for("superadmin_new"))
            if db.get_tenant_by_slug(slug):
                flash(f"Le sous-domaine '{slug}' existe déjà.", "error")
                return redirect(url_for("superadmin_new"))
            maison_name = (request.form.get("maison_name") or "").strip()
            admin_password = request.form.get("admin_password") or ""
            if not maison_name or not admin_password:
                flash("Nom de la maison et mot de passe admin sont obligatoires.", "error")
                return redirect(url_for("superadmin_new"))
            db.create_tenant(
                slug=slug,
                maison_name=maison_name,
                admin_password_hash=generate_password_hash(admin_password),
                coefficients=_coefficients_from_form(request.form, existing={}),
                logo_png=_normalize_logo(request.files.get("logo")),
                legal_footer=(request.form.get("legal_footer") == "1"),
                devis_limit=_parse_devis_limit(request.form.get("devis_limit")),
                feature_creation=(request.form.get("feature_creation") == "1"),
                feature_sav_rapide=(request.form.get("feature_sav_rapide") == "1"),
                feature_bijoux3_export=(request.form.get("feature_bijoux3_export") == "1"),
            )
            link = _tenant_link(slug)
            if link:
                flash(f"Client '{maison_name}' créé — lien à lui envoyer : {link}", "success")
            else:
                flash(f"Client '{maison_name}' créé (slug: {slug}).", "success")
            return redirect(url_for("superadmin_list"))

        copy_from = request.args.get("copy_from") or ""
        seed = db.get_tenant_by_slug(copy_from) if copy_from else None
        return render_template(
            "superadmin_form.html", mode="new", tenant=None,
            coefficients=(_all_coeffs_activated(seed.coefficients) if seed else {}),
            all_tenants=db.list_tenants(), copy_from=copy_from, tenant_link=None,
        )

    @app.route("/superadmin/<slug>/edit", methods=["GET", "POST"])
    @superadmin_required
    def superadmin_edit(slug: str):
        tenant = db.get_tenant_by_slug(slug)
        if not tenant:
            abort(404)
        if request.method == "POST":
            maison_name = (request.form.get("maison_name") or "").strip() or tenant.maison_name
            db.update_tenant_profile(
                slug, maison_name,
                legal_footer=(request.form.get("legal_footer") == "1"),
                active=(request.form.get("active") == "1"),
                devis_limit=_parse_devis_limit(request.form.get("devis_limit")),
                feature_creation=(request.form.get("feature_creation") == "1"),
                feature_sav_rapide=(request.form.get("feature_sav_rapide") == "1"),
                feature_bijoux3_export=(request.form.get("feature_bijoux3_export") == "1"),
            )
            db.save_tenant_coefficients(slug, _coefficients_from_form(request.form, existing=tenant.coefficients))
            new_logo = _normalize_logo(request.files.get("logo"))
            if new_logo:
                db.update_tenant_logo(slug, new_logo)
            new_password = request.form.get("admin_password") or ""
            if new_password:
                db.set_admin_password_hash(slug, generate_password_hash(new_password))
            _invalidate_tenant(slug)
            flash(f"'{tenant.maison_name}' mis à jour.", "success")
            return redirect(url_for("superadmin_list"))

        return render_template(
            "superadmin_form.html", mode="edit", tenant=tenant,
            coefficients=tenant.coefficients, all_tenants=[], copy_from="",
            tenant_link=_tenant_link(slug),
        )

    @app.route("/superadmin/<slug>/delete", methods=["POST"])
    @superadmin_required
    def superadmin_delete(slug: str):
        tenant = db.get_tenant_by_slug(slug)
        if not tenant:
            abort(404)
        db.delete_tenant(slug)
        _invalidate_tenant(slug)
        flash(f"'{tenant.maison_name}' supprimé.", "success")
        return redirect(url_for("superadmin_list"))

    @app.errorhandler(404)
    def not_found(_):
        return render_template("not_found.html"), 404

    @app.errorhandler(413)
    def too_large(_):
        flash("Fichier trop volumineux (limite 25 Mo). Compressez le PDF ou envoyez les fichiers un par un.", "error")
        return redirect(url_for("index"))

    @app.errorhandler(500)
    def internal_error(_):
        # L'exception d'origine est déjà tracée par Flask/gunicorn ; on ajoute la référence.
        ref = uuid.uuid4().hex[:8].upper()
        app.logger.error("[500] réf=%s url=%s ip=%s", ref, request.path, request.remote_addr)
        return render_template("error.html", ref=ref), 500

    return app


def _ceil5(value: float) -> float:
    """Arrondit au multiple de 5 supérieur (ex: 847 → 850, 323 → 325)."""
    return float(math.ceil((round(value, 2) - 0.01) / 5) * 5)


# ponytail: mapping en dur tenant→ville plutôt qu'un champ tenant dédié — seuls les
# tenants mono-boutique ont un vrai défaut sans ambiguïté. Les autres (ex. doux :
# Avignon/Nîmes) n'ont pas de ville par défaut fiable → laissé vide, l'utilisateur remplit.
# Pour un tenant listé ici, ce défaut est AUTORITAIRE (voir _default_lieu ci-dessous) :
# une seule boutique = un seul pied de page légal possible, peu importe ce que
# l'extraction ou le formulaire a rempli (ex. bug vu avec Daniel Gerard : un lieu
# "Avignon" extrait d'un document de test avait fait sortir le pied de page Doux).
_TENANT_DEFAULT_LIEU = {"lepage": "Lille", "daniel-gerard": "Thionville"}


def _default_lieu() -> str:
    return _TENANT_DEFAULT_LIEU.get(getattr(g.tenant, "slug", None), "")


def _brand_coeff_defaults(marque: str, tenant_coefficients: dict) -> dict:
    """Coefficient par défaut d'une marque pour ce tenant — réplique la logique de

    sélection JS (form.html::selectMarque), utilisée ici pour le mode rapide qui
    saute l'étape de vérification où l'utilisateur ajusterait manuellement.
    """
    entry = None
    ql = (marque or "").lower()
    for key, val in tenant_coefficients.items():
        if key.lower() == ql:
            entry = val
            break
    if isinstance(entry, dict):
        return {
            "coeff": entry.get("coeff") or 1.50,
            "coeff_opt": entry.get("coeff_opt"),
            "base": entry.get("base") or "ttc",
            "coeff_opt_base": entry.get("coeff_opt_base") or entry.get("base") or "ttc",
            "split_nec": entry.get("coeff_split_nec") is True,
            "nec_default": entry.get("coeff_nec_default") is not False,
            "opt_default": entry.get("coeff_opt_default") is not False,
        }
    if entry is not None:  # ancienne structure : juste un nombre
        return {"coeff": entry, "coeff_opt": None, "base": "ttc", "coeff_opt_base": "ttc",
                "split_nec": False, "nec_default": True, "opt_default": True}
    return {"coeff": 1.50, "coeff_opt": None, "base": "ttc", "coeff_opt_base": "ttc",
            "split_nec": False, "nec_default": True, "opt_default": True}


def _data_to_quick_form(data: dict, client_nom: str, tenant_coefficients: dict):
    """Reconstruit un MultiDict équivalent à ce que le formulaire /review soumettrait

    par défaut (coefficient de marque appliqué, aucun ajustement manuel), pour
    déléguer le calcul du prix client à _form_to_data (source de vérité unique —
    on ne réimplémente pas le ceil5/split_nec une 2e fois en Python).
    """
    from werkzeug.datastructures import MultiDict

    montre = data.get("montre") or {}
    sav = data.get("sav") or {}
    defaults = _brand_coeff_defaults(data.get("marque"), tenant_coefficients)

    md = MultiDict()
    md["client_nom"] = client_nom
    md["marque"] = data.get("marque", "") or ""
    md["sav_numero"] = sav.get("numero", "")
    md["sav_date"] = sav.get("date", "")
    md["sav_lieu"] = _default_lieu() or sav.get("lieu", "")
    md["modele"] = montre.get("modele", "")
    md["reference"] = montre.get("reference", "")
    md["numero_serie"] = montre.get("numero_serie", "")
    md["poids"] = montre.get("poids", "")
    md["metal"] = montre.get("metal", "")
    md["taille"] = montre.get("taille", "")
    etat = montre.get("etat") or []
    md["etat"] = "\n".join(etat) if isinstance(etat, list) else (etat or "")
    md["notes_partenaire"] = data.get("notes_partenaire", "") or ""
    md["service_complet"] = data.get("service_complet_description", "") or ""
    md["delai"] = data.get("delai", "") or "4 à 6 semaines"

    for prefix, lines in (("nec", data.get("interventions_necessaires") or []),
                          ("opt", data.get("interventions_optionnelles") or [])):
        for line in lines:
            prix = line.get("prix") or 0
            label = line.get("prix_label") or ""
            md.add(f"{prefix}_description[]", line.get("description", "") or "")
            md.add(f"{prefix}_prix[]", "" if label else f"{prix:.2f}")
            md.add(f"{prefix}_base_prix[]", f"{prix:.2f}" if prix else "")
            md.add(f"{prefix}_label[]", label)

    md["coeff"] = str(defaults["coeff"])
    md["coeff_opt"] = str(defaults["coeff_opt"]) if defaults["coeff_opt"] else ""
    md["coeff_base"] = defaults["base"]
    md["coeff_opt_base"] = defaults["coeff_opt_base"]
    md["coeff_split_nec"] = "1" if defaults["split_nec"] else "0"
    md["coeff_nec_enabled"] = "1" if defaults["nec_default"] else "0"
    md["coeff_opt_enabled"] = "1" if defaults["opt_default"] else "0"
    return md


def _parse_price(value: str | None) -> float:
    if value is None:
        return 0.0
    txt = value.strip().replace("€", "").replace(" ", "").replace(",", ".")
    if not txt:
        return 0.0
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _collect_lines(form, prefix: str, photo_dir=None, photo_files: list | None = None,
                   photo_kept: list | None = None) -> list[dict]:
    descs       = form.getlist(f"{prefix}_description[]")
    prices      = form.getlist(f"{prefix}_prix[]")
    base_prices = form.getlist(f"{prefix}_base_prix[]")
    labels      = form.getlist(f"{prefix}_label[]")
    out: list[dict] = []
    for i, desc in enumerate(descs):
        desc_clean = desc.strip()
        if not desc_clean:
            continue
        price_raw = prices[i] if i < len(prices) else ""
        base_raw  = base_prices[i] if i < len(base_prices) else ""
        label     = labels[i].strip() if i < len(labels) else ""
        item: dict = {"description": desc_clean}
        if label:
            item["prix_label"] = label
            item["prix"] = _parse_price(label)
        else:
            item["prix"] = _parse_price(price_raw)
        if base_raw:
            item["_base_prix"] = _parse_price(base_raw)
        # Photo attachée à cette ligne précise (options uniquement pour l'instant), persistée
        # sur disque et référencée par nom de fichier (pas les octets) — sinon elle disparaîtrait
        # dès qu'on revient sur /review sans la ré-uploader. Les <input type=file> non renseignés
        # soumettent quand même une entrée vide, donc l'alignement positionnel avec descs[] tient
        # (y compris après un glisser-déposer, qui déplace le vrai nœud DOM avec sa ligne).
        if photo_dir is not None:
            new_fs = photo_files[i] if photo_files and i < len(photo_files) else None
            kept_name = (photo_kept[i].strip() if photo_kept and i < len(photo_kept) else "")
            if new_fs and new_fs.filename and _has_extension(new_fs.filename, ALLOWED_PHOTO_IMG):
                normalized = _normalize_photo(new_fs.read())
                if normalized:
                    if kept_name:
                        (photo_dir / kept_name).unlink(missing_ok=True)
                    fname = f"opt_{secrets.token_hex(4)}.jpg"
                    photo_dir.mkdir(parents=True, exist_ok=True)
                    (photo_dir / fname).write_bytes(normalized)
                    item["photo_file"] = fname
            elif kept_name and (photo_dir / kept_name).exists():
                item["photo_file"] = kept_name
        out.append(item)
    return out


def _form_to_data(form, files=None, photo_dir=None) -> dict:
    etat_raw = form.get("etat", "")
    etat_lines = [line.strip() for line in etat_raw.splitlines() if line.strip()]

    necessaires  = _collect_lines(form, "nec")
    optionnelles = _collect_lines(
        form, "opt", photo_dir=photo_dir,
        photo_files=files.getlist("opt_photo[]") if files else None,
        photo_kept=form.getlist("opt_photo_file[]"),
    )

    try:
        coeff = float((form.get("coeff") or "1.0").replace(",", "."))
    except (ValueError, TypeError):
        coeff = 1.0
    try:
        coeff_opt_raw = (form.get("coeff_opt") or "").strip()
        coeff_opt = float(coeff_opt_raw.replace(",", ".")) if coeff_opt_raw else coeff
    except (ValueError, TypeError):
        coeff_opt = coeff
    coeff_base = (form.get("coeff_base") or "ttc").lower()
    coeff_opt_base = (form.get("coeff_opt_base") or coeff_base).lower()
    coeff_split_nec = (form.get("coeff_split_nec") or "0") == "1"
    coeff_nec_enabled = (form.get("coeff_nec_enabled") or "1") == "1"
    coeff_opt_enabled = (form.get("coeff_opt_enabled") or "1") == "1"
    service_complet_description = form.get("service_complet", "").strip()

    def _set_prix(line: dict, prix_client: float) -> None:
        line["prix_client"] = prix_client
        base = line.get("_base_prix")
        if base is not None and base > 0:
            line["prix"] = base
        elif coeff and coeff != 0:
            line["prix"] = round(prix_client / coeff, 2)
        else:
            line["prix"] = prix_client

    for line in necessaires:
        if (line.get("prix_label") or "") in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
        else:
            line["prix_client"] = float(line.get("prix") or 0)
    priced_nec = [l for l in necessaires if (l.get("prix_label") or "") not in ("OFFERT", "INCL")]

    for line in optionnelles:
        if (line.get("prix_label") or "") in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
        else:
            line["prix_client"] = float(line.get("prix") or 0)
    priced_opts = [l for l in optionnelles if (l.get("prix_label") or "") not in ("OFFERT", "INCL")]

    if priced_nec:
        if coeff_nec_enabled:
            if coeff_split_nec:
                if service_complet_description:
                    service_line, *rest_nec = priced_nec
                    base = service_line.get("_base_prix") or 0
                    service_line["prix_client"] = (
                        _ceil5(base * 1.20 * coeff) if base > 0 else _ceil5(service_line["prix_client"])
                    )
                else:
                    rest_nec = priced_nec
                for l in rest_nec:
                    base = l.get("_base_prix") or 0
                    l["prix_client"] = _ceil5(base * coeff_opt) if base > 0 else _ceil5(l["prix_client"])
            else:
                sum_ht = sum(l.get("_base_prix") or 0 for l in priced_nec)
                if sum_ht > 0:
                    T = _ceil5(sum_ht * coeff)
                    other_sum = 0.0
                    for l in priced_nec[:-1]:
                        base = l.get("_base_prix") or 0
                        pc = _ceil5(base * coeff) if base > 0 else _ceil5(l["prix_client"])
                        l["prix_client"] = pc
                        other_sum += pc
                    priced_nec[-1]["prix_client"] = T - other_sum
                else:
                    T = _ceil5(sum(l["prix_client"] for l in priced_nec))
                    other_sum = 0.0
                    for l in priced_nec[:-1]:
                        pc = _ceil5(l["prix_client"])
                        l["prix_client"] = pc
                        other_sum += pc
                    priced_nec[-1]["prix_client"] = T - other_sum
        total_client = float(sum(l["prix_client"] for l in priced_nec))
    else:
        total_client = 0.0

    if coeff_opt_enabled:
        for l in priced_opts:
            base = l.get("_base_prix") or 0
            l["prix_client"] = _ceil5(base * coeff_opt) if base > 0 else _ceil5(l["prix_client"])

    for line in necessaires + optionnelles:
        base = line.get("_base_prix")
        if base is not None and base > 0:
            line["prix"] = base
        elif coeff and coeff != 0 and line.get("prix_client", 0) > 0:
            line["prix"] = round(line["prix_client"] / coeff, 2)
        line.pop("_base_prix", None)

    notes_partenaire = form.get("notes_partenaire", "").strip()

    return {
        "marque": (form.get("marque_custom") or form.get("marque") or "Autre").strip(),
        "client": {"nom": form.get("client_nom", "").strip()},
        "sav": {
            "numero": form.get("sav_numero", "").strip(),
            "date": form.get("sav_date", "").strip(),
            "lieu": _default_lieu() or form.get("sav_lieu", "").strip(),
        },
        "montre": {
            "modele": form.get("modele", "").strip(),
            "reference": form.get("reference", "").strip(),
            "numero_serie": form.get("numero_serie", "").strip(),
            "poids": form.get("poids", "").strip(),
            "metal": form.get("metal", "").strip(),
            "taille": form.get("taille", "").strip(),
            "etat": etat_lines,
        },
        "service_complet_description": service_complet_description,
        "notes_partenaire": notes_partenaire,
        "interventions_necessaires": (
            [l for l in necessaires if (l.get("prix_label") or "") != "OFFERT"] +
            [l for l in necessaires if (l.get("prix_label") or "") == "OFFERT"]
        ),
        "interventions_optionnelles": optionnelles,
        "total_ttc": total_client,
        "coeff": coeff,
        "coeff_opt": coeff_opt if coeff_opt != coeff else None,
        "coeff_base": coeff_base,
        "coeff_opt_base": coeff_opt_base,
        "coeff_split_nec": coeff_split_nec,
        "coeff_nec_enabled": coeff_nec_enabled,
        "coeff_opt_enabled": coeff_opt_enabled,
        "delai": form.get("delai", "4 à 6 semaines").strip() or "4 à 6 semaines",
    }


def _creation_to_data(client_nom: str, type_piece: str, materiau: str,
                      description: str, prix_ht: float) -> dict:
    """Construit un data dict compatible build_docx/docx_to_pdf pour une pièce créée en atelier."""
    return {
        "marque": "",
        "client": {"nom": client_nom},
        "sav": {"numero": "", "date": datetime.now().strftime("%d.%m.%Y"), "lieu": ""},
        "montre": {"modele": type_piece, "metal": materiau, "etat": []},
        "service_complet_description": "",
        "notes_partenaire": "",
        "interventions_necessaires": [{"description": description, "prix": prix_ht, "prix_client": prix_ht}],
        "interventions_optionnelles": [],
        "total_ttc": prix_ht,
        "titre": "DEVIS",
        "intro_text": ("Madame, Monsieur,\n"
                       "Suite à notre échange, veuillez trouver ci-dessous le devis "
                       "pour la réalisation de votre pièce."),
        "delai": "à convenir",
    }


def _sav_quick_to_data(client_nom: str, note: str, prix: float) -> dict:
    """Construit un data dict compatible build_docx/docx_to_pdf pour un SAV rapide sur création maison."""
    return {
        "marque": "",
        "client": {"nom": client_nom},
        "sav": {"numero": "", "date": datetime.now().strftime("%d.%m.%Y"), "lieu": ""},
        "montre": {},
        "service_complet_description": "",
        "notes_partenaire": "",
        "interventions_necessaires": [{"description": note, "prix": prix, "prix_client": prix}],
        "interventions_optionnelles": [],
        "total_ttc": prix,
        "delai": "à convenir",
    }


def _line_montant(line: dict) -> str:
    """Reprend l'affichage du PDF/DOCX : prix_client sinon prix, ou le libellé (OFFERT/INCL) si présent."""
    label = line.get("prix_label")
    if label:
        return label
    prix = line.get("prix_client") if line.get("prix_client") is not None else line.get("prix")
    return prix if prix is not None else ""


def _data_to_bijoux3_csv(data: dict) -> bytes:
    """Une ligne par travail (nécessaire ET optionnel), mappée sur le tableau 'Travail à réaliser'
    de l'écran Bijoux3/Odéis (Code | Travail | Qté | Montant | C/T).

    Colonnes non collectées par Reverso (téléphone, destination, code article, acompte, TVA)
    laissées vides — à compléter à la main lors de l'import/ressaisie, en attendant un accès API.
    """
    client = data.get("client") or {}
    sav = data.get("sav") or {}
    montre = data.get("montre") or {}
    fieldnames = [
        "NUMERO", "CLIENT", "TELEPHONE", "DATE_DEPOT", "DELAI", "CODE_ARTICLE",
        "TYPE", "TRAVAIL_A_REALISER", "MONTANT", "METAL", "POIDS", "MARQUE",
        "MONTANT_TOTAL", "ACOMPTE", "A_PAYER",
    ]
    common = {
        "NUMERO": sav.get("numero", ""),
        "CLIENT": client.get("nom", ""),
        "TELEPHONE": "",
        "DATE_DEPOT": sav.get("date", ""),
        "DELAI": data.get("delai", ""),
        "CODE_ARTICLE": "",
        "METAL": montre.get("metal", ""),
        "POIDS": montre.get("poids", ""),
        "MARQUE": data.get("marque", ""),
        "MONTANT_TOTAL": data.get("total_ttc", ""),
        "ACOMPTE": "",
        "A_PAYER": data.get("total_ttc", ""),
    }

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=";")
    writer.writeheader()
    for type_label, key in (("Nécessaire", "interventions_necessaires"), ("Optionnelle", "interventions_optionnelles")):
        for line in data.get(key) or []:
            description = (line.get("description") or "").strip()
            if not description:
                continue
            writer.writerow({**common, "TYPE": type_label, "TRAVAIL_A_REALISER": description,
                             "MONTANT": _line_montant(line)})
    return buf.getvalue().encode("utf-8-sig")


def _build_filename(data: dict, maison_name: str = "DEVIS") -> str:
    nom = (data.get("client") or {}).get("nom", "").strip() or "CLIENT"
    sav = (data.get("sav") or {}).get("numero", "").strip() or datetime.now().strftime("%Y%m%d")
    nom_short = "_".join(nom.split()[:2])
    prefix = (maison_name or "DEVIS").upper().split()[0]
    raw = f"DEVIS_{prefix}_{nom_short}_{sav}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return (safe or "DEVIS")[:80]


app = create_app()


if __name__ == "__main__":
    # ponytail: debug=True + host 0.0.0.0 expose le débogueur Werkzeug (RCE) à quiconque
    # sur le même réseau — critique en démo client sur Wi-Fi partagé. Off par défaut ;
    # export FLASK_DEBUG=1 pour le réactiver en dev local.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0",
            port=int(os.environ.get("PORT", 5050)))
