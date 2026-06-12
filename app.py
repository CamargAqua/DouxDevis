"""Flask app — Devis DOUX Joaillier."""
from __future__ import annotations

import functools
import hmac
import math
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path

import json
import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    jsonify,
)
from flask_session import Session
from werkzeug.utils import secure_filename

from docx_generator import build_docx
from pdf_extractor import confidence_score, extract_from_eml, extract_from_pdf

from pdf_generator import docx_to_pdf

# Quand on tourne depuis l'exe PyInstaller, launcher.py pose ces vars
# pour séparer les ressources statiques (sys._MEIPASS) des données runtime.
_runtime = os.environ.get("DOUX_RUNTIME_DIR")
_base = os.environ.get("DOUX_BASE_DIR")

BASE_DIR = Path(_base) if _base else Path(__file__).parent

load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
load_dotenv(override=False)
RUNTIME_DIR = Path(_runtime) if _runtime else BASE_DIR

UPLOAD_DIR = RUNTIME_DIR / "uploads"
GENERATED_DIR = RUNTIME_DIR / "generated"
UPLOAD_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

# Coefficients : graine versionnée (repo) + stockage persistant via GitHub Gist.
# Sur Render (disque éphémère), définir GIST_ID + GITHUB_TOKEN (scope « gist »)
# pour que les modifications faites depuis l'admin survivent aux redémarrages.
# Sans token (dev local), on lit/écrit le fichier du repo directement.
COEFFICIENTS_SEED = BASE_DIR / "coefficients.json"
COEFFICIENTS_PATH = Path(os.environ.get("COEFFICIENTS_PATH") or (RUNTIME_DIR / "coefficients.json"))

GIST_ID = os.environ.get("GIST_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GIST_FILENAME = os.environ.get("GIST_FILENAME", "coefficients.json")
_GIST_API = "https://api.github.com/gists"
_COEFF_TTL = 60.0  # cache lecture (secondes)
_coeff_cache: dict = {"data": None, "ts": 0.0}

ALLOWED_DOC = {"pdf", "eml", "msg"}

ALLOWED_IMG = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_CONTENT_LENGTH = 25 * 1024 * 1024

MARQUES = ["Chanel", "Tag Heuer", "Breitling", "Rolex", "Autre"]

def _create_yousign_signature_request(pdf_bytes: bytes, client_email: str, devis_name: str) -> dict | None:
    """Crée une signature request Yousign et retourne le lien."""
    api_key = os.environ.get("YOUSIGN_API_KEY")
    if not api_key:
        print("ERROR: YOUSIGN_API_KEY not found")
        return None

    try:
        base_url = "https://api-sandbox.yousign.app/v3"
        headers = {"Authorization": f"Bearer {api_key}"}

        # Crée la signature request
        sr_data = {
            "name": f"Devis {devis_name}",
            "delivery_mode": "email",
            "timezone": "Europe/Paris"
        }

        print(f"Creating Signature Request: {sr_data}")
        resp = requests.post(
            f"{base_url}/signature_requests",
            headers=headers,
            json=sr_data,
            timeout=10,
        )

        print(f"SR Status: {resp.status_code}, Response: {resp.text[:300]}")
        if resp.status_code not in (200, 201):
            return None

        sr = resp.json()
        sr_id = sr.get("id")

        # Upload le PDF
        pdf_tmp = RUNTIME_DIR / f"tmp_{devis_name}.pdf"
        pdf_tmp.write_bytes(pdf_bytes)

        with open(pdf_tmp, "rb") as f:
            files = {"file": f, "nature": (None, "signable_document")}
            headers_doc = {"Authorization": f"Bearer {api_key}"}
            resp2 = requests.post(
                f"{base_url}/signature_requests/{sr_id}/documents",
                headers=headers_doc,
                files=files,
                timeout=10,
            )

        print(f"Doc Status: {resp2.status_code}, Response: {resp2.text[:300]}")
        if resp2.status_code not in (200, 201):
            return None

        doc = resp2.json()
        doc_id = doc.get("id")

        # Ajoute le signataire avec fields
        signer_data = {
            "info": {
                "first_name": "Client",
                "last_name": "Doux",
                "email": client_email,
                "locale": "fr"
            },
            "signature_authentication_mode": "no_otp",
            "signature_level": "electronic_signature",
            "fields": [
                {
                    "document_id": doc_id,
                    "type": "signature",
                    "height": 40,
                    "width": 85,
                    "page": 1,
                    "x": 100,
                    "y": 100
                }
            ]
        }

        resp3 = requests.post(
            f"{base_url}/signature_requests/{sr_id}/signers",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=signer_data,
            timeout=10,
        )

        print(f"Signer Status: {resp3.status_code}, Response: {resp3.text[:300]}")
        if resp3.status_code not in (200, 201):
            return None

        signer = resp3.json()

        # Active la signature request
        resp4 = requests.post(
            f"{base_url}/signature_requests/{sr_id}/activate",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )

        print(f"Activate Status: {resp4.status_code}")
        if resp4.status_code not in (200, 201, 204):
            return None

        # Récupère la signature request mise à jour pour obtenir le lien
        resp5 = requests.get(
            f"{base_url}/signature_requests/{sr_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )

        if resp5.status_code == 200:
            sr_updated = resp5.json()
            signers = sr_updated.get("signers", [])
            if signers:
                signer_id = signers[0].get("id")
                # Essaie d'obtenir le lien depuis la réponse
                sign_url = signers[0].get("signature_link")
                # Si null, construis le lien manuellement
                if not sign_url:
                    sign_url = f"https://sandbox.yousign.app/sign/{signer_id}"
                print(f"Sign URL: {sign_url}")
                return {
                    "signature_request_id": sr_id,
                    "signer_id": signer_id,
                    "sign_url": sign_url,
                }

        return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


def _gist_enabled() -> bool:
    return bool(GIST_ID and GITHUB_TOKEN)


def _gist_headers() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _seed_coefficients() -> dict:
    try:
        return json.loads(COEFFICIENTS_SEED.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_coefficients() -> dict:
    """Charge les coefficients : Gist si configuré, sinon fichier local du repo.

    La lecture Gist est mise en cache 60 s. Toute erreur réseau retombe sur le
    dernier cache, puis sur la graine versionnée — jamais de liste vide servie.
    """
    if not _gist_enabled():
        try:
            return json.loads(COEFFICIENTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return _seed_coefficients()

    now = time.time()
    if _coeff_cache["data"] is not None and now - _coeff_cache["ts"] < _COEFF_TTL:
        return _coeff_cache["data"]
    try:
        resp = requests.get(f"{_GIST_API}/{GIST_ID}", headers=_gist_headers(), timeout=8)
        resp.raise_for_status()
        f = (resp.json().get("files") or {}).get(GIST_FILENAME)
        if not f or not f.get("content"):
            raise ValueError("fichier coefficients absent du gist")
        data = json.loads(f["content"])
        _coeff_cache.update(data=data, ts=now)
        return data
    except Exception as exc:
        print(f"WARN _load_coefficients (gist): {exc}")
        if _coeff_cache["data"] is not None:
            return _coeff_cache["data"]
        return _seed_coefficients()


def _save_coefficients(data: dict) -> None:
    """Persiste les coefficients : Gist si configuré, sinon fichier local (atomique)."""
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if not _gist_enabled():
        COEFFICIENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = COEFFICIENTS_PATH.with_name(COEFFICIENTS_PATH.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(COEFFICIENTS_PATH)
    else:
        resp = requests.patch(
            f"{_GIST_API}/{GIST_ID}",
            headers=_gist_headers(),
            json={"files": {GIST_FILENAME: {"content": payload}}},
            timeout=10,
        )
        resp.raise_for_status()
    _coeff_cache.update(data=data, ts=time.time())


def _coefficients_from_form(form) -> dict:
    """Reconstruit le dict coefficients depuis les tableaux du formulaire admin.

    Conserve la convention du fichier : `coeff_opt` et les `*_default` ne sont
    écrits que lorsqu'ils diffèrent du défaut (absent = true / pas d'option).
    """
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
        entry: dict = {
            "coeff": round(coeff, 4),
            "base": "ht",
        }
        coeff_opt = _num(coeff_opts, i)
        if coeff_opt is not None and coeff_opt > 0:
            entry["coeff_opt"] = round(coeff_opt, 4)
        if (nec_defs[i] if i < len(nec_defs) else "1") != "1":
            entry["coeff_nec_default"] = False
        if (opt_defs[i] if i < len(opt_defs) else "1") != "1":
            entry["coeff_opt_default"] = False
        new[name] = entry
    return new


def _has_extension(filename: str, allowed: set[str]) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in allowed


def create_app() -> Flask:
    template_folder = str(BASE_DIR / "templates")
    static_folder = str(BASE_DIR / "static")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    _secret_key = os.environ.get("FLASK_SECRET_KEY")
    if not _secret_key:
        import sys
        print(
            "CRITICAL: FLASK_SECRET_KEY non définie — les sessions seront "
            "invalidées à chaque redémarrage. Ajoutez cette variable sur Render.",
            file=sys.stderr,
        )
        _secret_key = secrets.token_hex(32)
    app.secret_key = _secret_key

    # Sessions côté serveur (filesystem) — évite la limite 4KB des cookies
    SESSION_DIR = RUNTIME_DIR / "flask_sessions"
    SESSION_DIR.mkdir(exist_ok=True)
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = str(SESSION_DIR)
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    Session(app)

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html", marques=MARQUES)

    @app.route("/extract", methods=["POST"])
    def extract():
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            flash("Clé API manquante — contactez l'administrateur.", "error")
            return redirect(url_for("index"))

        paste_text = request.form.get("paste_text", "").strip()

        # ── Mode "coller un email" ──────────────────────────────────────────
        if paste_text:
            from pdf_extractor import _extract_from_text, _detect_brand_from_text
            import re as _re
            try:
                data = _extract_from_text(paste_text, api_key=api_key)
            except Exception as exc:
                exc_str = str(exc).lower()
                if "api" in exc_str or "anthropic" in exc_str:
                    flash("Service temporairement indisponible. Réessayez dans 1 minute.", "error")
                else:
                    flash("Impossible d'extraire les données de ce texte. Vérifiez que c'est bien un devis.", "error")
                return redirect(url_for("index"))
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
            token = uuid.uuid4().hex
            session["token"] = token
            session["data"]  = data
            session["source_kind"] = "text"
            session["source_text"] = paste_text
            return redirect(url_for("review"))

        # ── Mode fichier ────────────────────────────────────────────────────
        upload_file = request.files.get("pdf")
        if not upload_file or not upload_file.filename:
            flash("Veuillez sélectionner un fichier ou coller un email.", "error")
            return redirect(url_for("index"))
        if not _has_extension(upload_file.filename, ALLOWED_DOC):
            flash("Le fichier doit être un PDF, un email (.eml) ou un message Outlook (.msg).", "error")
            return redirect(url_for("index"))

        file_bytes = upload_file.read()
        if not file_bytes:
            flash("Le fichier est vide.", "error")
            return redirect(url_for("index"))

        ext = upload_file.filename.rsplit(".", 1)[-1].lower()
        source_kind = "pdf"
        source_payload: bytes | str = file_bytes
        try:
            if ext == "eml":
                data, source_kind, source_payload = extract_from_eml(file_bytes, api_key=api_key, filename=upload_file.filename)
            elif ext == "msg":
                from pdf_extractor import extract_from_msg
                data, source_kind, source_payload = extract_from_msg(file_bytes, api_key=api_key, filename=upload_file.filename)
            else:
                data = extract_from_pdf(file_bytes, api_key=api_key, filename=upload_file.filename)
        except ValueError as exc:
            flash(f"Format invalide : {str(exc)}", "error")
            return redirect(url_for("index"))
        except TimeoutError:
            flash("L'extraction a pris trop de temps. Essayez un fichier plus simple.", "error")
            return redirect(url_for("index"))
        except Exception as exc:
            exc_str = str(exc).lower()
            if "empty" in exc_str or "no data" in exc_str:
                flash("Le fichier semble vide. Vérifiez que c'est un devis valide.", "error")
            elif "parse" in exc_str or "format" in exc_str:
                flash("Impossible de lire ce PDF. Essayez un email (.eml) à la place.", "error")
            elif "api" in exc_str or "anthropic" in exc_str:
                flash("Service temporairement indisponible. Réessayez dans 1 minute.", "error")
            else:
                flash("Erreur lors de l'extraction. Essayez un autre fichier.", "error")
            return redirect(url_for("index"))

        # Date du jour si absente ou vide
        if not (data.get("sav") or {}).get("date"):
            if "sav" not in data or not isinstance(data["sav"], dict):
                data["sav"] = {}
            data["sav"]["date"] = datetime.now().strftime("%d.%m.%Y")

        # Détecter extraction vide ou hors-sujet
        interventions = data.get("interventions_necessaires") or []
        has_prix = any(float(i.get("prix") or 0) > 0 for i in interventions)
        if not interventions or not has_prix:
            flash("⚠️ Aucune intervention trouvée dans ce fichier. Vérifiez que c'est bien un devis partenaire horlogerie ou joaillerie.", "warning")


        token = uuid.uuid4().hex
        session["token"] = token
        session["data"] = data

        if source_kind == "pdf":
            session_dir = UPLOAD_DIR / token
            session_dir.mkdir(parents=True, exist_ok=True)
            file_path = session_dir / "source.pdf"
            file_path.write_bytes(source_payload)
            session["source_kind"] = "pdf"
            session["source_pdf"] = file_path.name
        else:
            session["source_kind"] = "text"
            session["source_text"] = source_payload

        return redirect(url_for("review"))


    @app.route("/dev-preview")
    def dev_preview():
        """Route de test locale uniquement — injecte des données de démo."""
        if not app.debug:
            abort(404)
        import uuid
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
            "interventions_optionnelles": [
                {"description": "DORURE OR JAUNE 18K", "prix": 320.00},
            ],
            "total_ttc": 1046.25,
            "delai": "6 à 8 semaines",
        }
        return redirect(url_for("review"))

    @app.route("/review", methods=["GET"])
    def review():
        data = session.get("data")
        if not data:
            return redirect(url_for("index"))
        return render_template("form.html", data=data, marques=MARQUES,
                               coefficients_json=json.dumps(_load_coefficients(), ensure_ascii=False),
                               source_kind=session.get("source_kind", "none"),
                               source_text=session.get("source_text", ""),
                               token=session.get("token"))

    @app.route("/generate", methods=["POST"])
    def generate():
        token = session.get("token")
        if not token:
            flash("Session expirée, veuillez recharger un PDF.", "error")
            return redirect(url_for("index"))

        form = request.form
        data = _form_to_data(form)
        score, missing = confidence_score(data)
        session["data"] = data

        photo_bytes: bytes | None = None
        photo = request.files.get("photo")
        if photo and photo.filename and _has_extension(photo.filename, ALLOWED_IMG):
            photo_bytes = photo.read()

        try:
            docx_bytes = build_docx(data, photo_bytes=photo_bytes)
        except Exception as exc:
            flash(f"Erreur génération .docx : {exc}", "error")
            return redirect(url_for("review"))

        try:
            pdf_bytes, method = docx_to_pdf(docx_bytes, data=data, photo_bytes=photo_bytes)
        except Exception as exc:
            flash(f"Erreur conversion PDF : {exc}", "error")
            return redirect(url_for("review"))

        out_dir = GENERATED_DIR / token
        out_dir.mkdir(parents=True, exist_ok=True)

        base_name = _build_filename(data)
        docx_name = f"{base_name}.docx"
        pdf_name = f"{base_name}.pdf"
        (out_dir / docx_name).write_bytes(docx_bytes)
        (out_dir / pdf_name).write_bytes(pdf_bytes)

        return render_template(
            "done.html",
            token=token,
            docx_name=docx_name,
            pdf_name=pdf_name,
            method=method,
            confidence=score,
            confidence_missing=missing,
        )

    @app.route("/download/<token>/<path:filename>")
    def download(token: str, filename: str):
        if token != session.get("token"):
            abort(403)
        safe_token = secure_filename(token)
        safe_name = secure_filename(filename)
        directory = GENERATED_DIR / safe_token
        if not (directory / safe_name).is_file():
            abort(404)
        return send_from_directory(directory, safe_name, as_attachment=True)

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

        safe_token = secure_filename(token)
        directory = GENERATED_DIR / safe_token

        # Cherche le PDF généré
        pdf_files = list(directory.glob("*.pdf"))
        if not pdf_files:
            return jsonify({"error": "No PDF found"}), 404

        pdf_path = pdf_files[0]
        pdf_bytes = pdf_path.read_bytes()
        devis_name = pdf_path.stem

        # Crée la signature request Yousign
        result = _create_yousign_signature_request(pdf_bytes, client_email, devis_name)
        if not result:
            return jsonify({"error": "Failed to create Yousign procedure"}), 500

        return jsonify(result)


    @app.route("/cgv")
    def cgv():
        return send_from_directory(str(BASE_DIR / "static"), "cgv.pdf",
                                   mimetype="application/pdf")

    @app.route("/guide")
    def guide():
        return render_template("guide.html")

    # ── Administration : édition protégée des coefficients ────────────────────
    def _admin_password_ok(submitted: str) -> bool:
        expected = os.environ.get("ADMIN_PASSWORD") or ""
        return bool(expected) and hmac.compare_digest(submitted, expected)

    def admin_required(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("is_admin"):
                return redirect(url_for("admin_login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        if session.get("is_admin"):
            return redirect(url_for("admin_coefficients"))
        if request.method == "POST":
            if not os.environ.get("ADMIN_PASSWORD"):
                flash("Aucun mot de passe admin n'est configuré (variable ADMIN_PASSWORD).", "error")
            elif _admin_password_ok(request.form.get("password", "")):
                session["is_admin"] = True
                dest = request.args.get("next")
                if not dest or not dest.startswith("/"):
                    dest = url_for("admin_coefficients")
                return redirect(dest)
            else:
                flash("Mot de passe incorrect.", "error")
        return render_template("admin_login.html")

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return redirect(url_for("index"))

    @app.route("/admin/coefficients", methods=["GET"])
    @admin_required
    def admin_coefficients():
        return render_template("admin_coefficients.html", coefficients=_load_coefficients())

    @app.route("/admin/coefficients", methods=["POST"])
    @admin_required
    def admin_coefficients_save():
        new = _coefficients_from_form(request.form)
        if not new:
            flash("Aucune marque valide à enregistrer — modifications ignorées.", "error")
            return redirect(url_for("admin_coefficients"))
        try:
            _save_coefficients(new)
        except Exception as exc:
            flash(f"Échec de l'enregistrement : {exc}", "error")
            return redirect(url_for("admin_coefficients"))
        flash(f"{len(new)} marque(s) enregistrée(s).", "success")
        return redirect(url_for("admin_coefficients"))


    @app.errorhandler(413)
    def too_large(_):
        flash("Fichier trop volumineux (limite 25 Mo).", "error")
        return redirect(url_for("index"))

    return app



def _ceil5(value: float) -> float:
    """Arrondit au multiple de 5 supérieur (ex: 847 → 850, 323 → 325).

    Un montant déjà multiple de 5 reste inchangé (epsilon pour absorber le bruit float).
    """
    return float(math.ceil((round(value, 2) - 0.01) / 5) * 5)


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


def _collect_lines(form, prefix: str) -> list[dict]:
    descs       = form.getlist(f"{prefix}_description[]")
    prices      = form.getlist(f"{prefix}_prix[]")
    base_prices = form.getlist(f"{prefix}_base_prix[]")   # prix HT partenaire original
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
        # Conserver le prix HT partenaire original (hidden input) pour éviter
        # la dérive due au back-compute arrondi ÷ coeff
        if base_raw:
            item["_base_prix"] = _parse_price(base_raw)
        out.append(item)
    return out


def _form_to_data(form) -> dict:
    etat_raw = form.get("etat", "")
    etat_lines = [line.strip() for line in etat_raw.splitlines() if line.strip()]

    necessaires  = _collect_lines(form, "nec")
    optionnelles = _collect_lines(form, "opt")

    # Coefficient et base tarifaire transmis par le formulaire
    try:
        coeff = float((form.get("coeff") or "1.0").replace(",", "."))
    except (ValueError, TypeError):
        coeff = 1.0
    try:
        coeff_opt_raw = (form.get("coeff_opt") or "").strip()
        coeff_opt = float(coeff_opt_raw.replace(",", ".")) if coeff_opt_raw else coeff
    except (ValueError, TypeError):
        coeff_opt = coeff
    coeff_base = (form.get("coeff_base") or "ttc").lower()  # "ht" ou "ttc"
    coeff_nec_enabled = (form.get("coeff_nec_enabled") or "1") == "1"
    coeff_opt_enabled = (form.get("coeff_opt_enabled") or "1") == "1"

    # Les inputs soumettent déjà les prix clients appliqués dans le JS :
    # - marques TTC : inp.value = prix_partenaire_TTC × coeff
    # - Omega (HT)  : inp.value = prix_partenaire_HT  × coeff  → doit être converti en TTC ici
    # Prix client = prix soumis (partenaire × coeff) arrondi à l'euro entier
    def _set_prix(line: dict, prix_client: float) -> None:
        """Pose prix_client et prix (HT partenaire original si dispo, sinon back-compute)."""
        line["prix_client"] = prix_client
        base = line.get("_base_prix")          # HT original transmis par hidden input
        if base is not None and base > 0:
            line["prix"] = base                # ← conserve le HT original intact
        elif coeff and coeff != 0:
            line["prix"] = round(prix_client / coeff, 2)
        else:
            line["prix"] = prix_client

    # Séparer les lignes OFFERT/INCL des lignes à prix
    for line in necessaires:
        if (line.get("prix_label") or "") in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
        else:
            line["prix_client"] = float(line.get("prix") or 0)  # valeur soumise par le form
    priced_nec = [l for l in necessaires if (l.get("prix_label") or "") not in ("OFFERT", "INCL")]

    for line in optionnelles:
        if (line.get("prix_label") or "") in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
        else:
            line["prix_client"] = float(line.get("prix") or 0)
    priced_opts = [l for l in optionnelles if (l.get("prix_label") or "") not in ("OFFERT", "INCL")]

    # ── NÉCESSAIRES : algo ceil5 avec dernière ligne compensatrice (si coeff actif) ──
    # T = ceil5(sum_HT × coeff) ; lignes[:-1] → ceil5 individuel ; dernière = T − somme
    # Si le coefficient est désactivé, le prix saisi = prix client final (passthrough).
    if priced_nec:
        if coeff_nec_enabled:
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
                # Fallback si pas de _base_prix (ligne ajoutée manuellement)
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

    # ── OPTIONS : ceil5 par ligne avec coeff_opt si défini (si coeff actif) ──
    if coeff_opt_enabled:
        for l in priced_opts:
            base = l.get("_base_prix") or 0
            l["prix_client"] = _ceil5(base * coeff_opt) if base > 0 else _ceil5(l["prix_client"])

    # Fixer prix (HT partenaire) sur toutes les lignes
    for line in necessaires + optionnelles:
        base = line.get("_base_prix")
        if base is not None and base > 0:
            line["prix"] = base
        elif coeff and coeff != 0 and line.get("prix_client", 0) > 0:
            line["prix"] = round(line["prix_client"] / coeff, 2)
        line.pop("_base_prix", None)  # nettoyer le champ intermédiaire

    return {
        "marque": (form.get("marque_custom") or form.get("marque") or "Autre").strip(),
        "client": {"nom": form.get("client_nom", "").strip()},
        "sav": {
            "numero": form.get("sav_numero", "").strip(),
            "date": form.get("sav_date", "").strip(),
            "lieu": form.get("sav_lieu", "Avignon").strip() or "Avignon",
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
        "service_complet_description": form.get("service_complet", "").strip(),
        "interventions_necessaires": (
            [l for l in necessaires if (l.get("prix_label") or "") != "OFFERT"] +
            [l for l in necessaires if (l.get("prix_label") or "") == "OFFERT"]
        ),
        "interventions_optionnelles": optionnelles,
        "total_ttc": total_client,
        "coeff": coeff,
        "coeff_opt": coeff_opt if coeff_opt != coeff else None,
        "coeff_base": coeff_base,
        "coeff_nec_enabled": coeff_nec_enabled,
        "coeff_opt_enabled": coeff_opt_enabled,
        "delai": form.get("delai", "4 à 6 semaines").strip() or "4 à 6 semaines",
    }


def _build_filename(data: dict) -> str:
    nom = (data.get("client") or {}).get("nom", "").strip() or "CLIENT"
    sav = (data.get("sav") or {}).get("numero", "").strip() or datetime.now().strftime("%Y%m%d")
    nom_short = "_".join(nom.split()[:2])  # max 2 mots du nom
    raw = f"DEVIS_DOUX_{nom_short}_{sav}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return (safe or "DEVIS_DOUX")[:80]  # cap 80 chars


def _generate_qr_cgv() -> None:
    """Génère static/qr_cgv.png pointant vers CGV_URL (GitHub Pages) ou APP_URL/cgv."""
    # CGV_URL prioritaire (GitHub Pages) — sinon fallback sur l'app
    cgv_url = os.environ.get("CGV_URL", "https://bit.ly/Doux-cgv")
    if not cgv_url.startswith("http"):
        return
    try:
        import qrcode  # type: ignore
        from qrcode.image.styledpil import StyledPilImage  # type: ignore
        from qrcode.image.styles.moduledrawers.pil import CircleModuleDrawer, RoundedModuleDrawer  # type: ignore
        from qrcode.image.styles.colormasks import SolidFillColorMask  # type: ignore

        GOLD = (200, 160, 40)   # #C8A028 — or DOUX
        DARK = (26, 24, 20)     # #1A1814 — quasi-noir
        WHITE = (255, 255, 255)

        url = cgv_url
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=CircleModuleDrawer(),
            color_mask=SolidFillColorMask(
                front_color=DARK,
                back_color=WHITE,
            ),
        )
        img.save(str(BASE_DIR / "static" / "qr_cgv.png"))
    except Exception as e:
        # Fallback sans style si la version de qrcode ne supporte pas StyledPilImage
        print(f"[QR] Style non supporté ({e}), génération classique.")
        try:
            import qrcode as _qr  # type: ignore
            url = cgv_url
            q = _qr.QRCode(version=1, error_correction=_qr.constants.ERROR_CORRECT_M,
                            box_size=8, border=2)
            q.add_data(url)
            q.make(fit=True)
            q.make_image(fill_color="#1A1814", back_color="white").save(
                str(BASE_DIR / "static" / "qr_cgv.png"))
        except Exception as e2:
            print(f"[QR] Génération échouée : {e2}")


app = create_app()
_generate_qr_cgv()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
