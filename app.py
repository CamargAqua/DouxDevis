"""Flask app — Devis DOUX Joaillier."""
from __future__ import annotations

import math
import os
import re
import secrets
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
FEEDBACK_FILE = RUNTIME_DIR / "feedback.jsonl"
UPLOAD_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

ALLOWED_DOC = {"pdf", "eml"}

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


def _load_coefficients() -> dict:
    path = BASE_DIR / "coefficients.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _has_extension(filename: str, allowed: set[str]) -> bool:
    if "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in allowed


def create_app() -> Flask:
    template_folder = str(BASE_DIR / "templates")
    static_folder = str(BASE_DIR / "static")
    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

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

        upload_file = request.files.get("pdf")
        if not upload_file or not upload_file.filename:
            flash("Veuillez sélectionner un fichier.", "error")
            return redirect(url_for("index"))
        if not _has_extension(upload_file.filename, ALLOWED_DOC):
            flash("Le fichier doit être un PDF ou un email (.eml).", "error")
            return redirect(url_for("index"))

        file_bytes = upload_file.read()
        if not file_bytes:
            flash("Le fichier est vide.", "error")
            return redirect(url_for("index"))

        ext = upload_file.filename.rsplit(".", 1)[-1].lower()
        try:
            if ext == "eml":
                data = extract_from_eml(file_bytes, api_key=api_key, filename=upload_file.filename)
            else:
                data = extract_from_pdf(file_bytes, api_key=api_key, filename=upload_file.filename)
        except Exception as exc:
            flash(f"Erreur lors de l'extraction : {exc}", "error")
            return redirect(url_for("index"))

        # Date du jour si absente ou vide
        if not (data.get("sav") or {}).get("date"):
            if "sav" not in data or not isinstance(data["sav"], dict):
                data["sav"] = {}
            data["sav"]["date"] = datetime.now().strftime("%d.%m.%Y")

        token = uuid.uuid4().hex
        session_dir = UPLOAD_DIR / token
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / secure_filename(upload_file.filename)
        file_path.write_bytes(file_bytes)

        session["token"] = token
        session["data"] = data
        session["source_pdf"] = file_path.name

        return redirect(url_for("review"))


    @app.route("/dev-preview")
    def dev_preview():
        """Route de test locale uniquement — injecte des données de démo."""
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
                               coefficients_json=json.dumps(_load_coefficients(), ensure_ascii=False))

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
            marque=data.get("marque", ""),
            sav_num=(data.get("sav") or {}).get("numero", ""),
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

    @app.route("/feedback", methods=["POST"])
    def feedback():
        payload = request.get_json(silent=True) or {}
        extracted = session.get("data") or {}
        extraction_snapshot = {
            "marque": extracted.get("marque", ""),
            "sav": (extracted.get("sav") or {}).get("numero", ""),
            "montre": extracted.get("montre", {}),
            "interventions_necessaires": extracted.get("interventions_necessaires", []),
            "interventions_optionnelles": extracted.get("interventions_optionnelles", []),
            "total_ttc": extracted.get("total_ttc", 0),
        }
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "marque": str(payload.get("marque", "")),
            "sav": str(payload.get("sav", "")),
            "ok": bool(payload.get("ok", True)),
            "comment": str(payload.get("comment", "")).strip(),
            "extraction": extraction_snapshot,
        }
        sb = _supabase_client()
        if sb:
            try:
                sb.table("feedback").insert(entry).execute()
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500
        else:
            # Fallback local
            try:
                with FEEDBACK_FILE.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as exc:
                return jsonify({"error": str(exc)}), 500
        return jsonify({"status": "ok"})

    @app.route("/stats-auth", methods=["POST"])
    def stats_auth():
        payload = request.get_json(silent=True) or {}
        password = str(payload.get("password", ""))
        expected = os.environ.get("STATS_KEY", "")
        if not expected or password != expected:
            return jsonify({"ok": False}), 403
        session["stats_auth"] = True
        return jsonify({"ok": True})

    @app.route("/stats")
    def stats():
        if not session.get("stats_auth"):
            abort(403)

        entries: list[dict] = []
        sb = _supabase_client()
        if sb:
            try:
                result = sb.table("feedback").select("*").order("ts", desc=True).execute()
                entries = result.data or []
            except Exception:
                entries = []
        elif FEEDBACK_FILE.exists():
            for line in FEEDBACK_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        total = len(entries)
        ok_count = sum(1 for e in entries if e.get("ok"))
        ko_count = total - ok_count
        pct = round(ok_count / total * 100) if total else None
        kos = [e for e in entries if not e.get("ok")][:20]

        return render_template(
            "stats.html",
            total=total,
            ok_count=ok_count,
            ko_count=ko_count,
            pct=pct,
            kos=kos,
        )

    @app.errorhandler(413)
    def too_large(_):
        flash("Fichier trop volumineux (limite 25 Mo).", "error")
        return redirect(url_for("index"))

    return app


def _supabase_client():
    """Retourne un client Supabase si les vars d'env sont configurées, sinon None."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


def _ceil5(value: float) -> float:
    """Arrondit au multiple de 5 supérieur (ex: 847 → 850, 323 → 325).

    Un montant déjà multiple de 5 reste inchangé (epsilon pour absorber le bruit float).
    """
    return float(math.ceil(round(value, 2) / 5 - 1e-9) * 5)


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
    descs = form.getlist(f"{prefix}_description[]")
    prices = form.getlist(f"{prefix}_prix[]")
    labels = form.getlist(f"{prefix}_label[]")
    out: list[dict] = []
    for i, desc in enumerate(descs):
        desc_clean = desc.strip()
        if not desc_clean:
            continue
        price_raw = prices[i] if i < len(prices) else ""
        label = labels[i].strip() if i < len(labels) else ""
        item: dict = {"description": desc_clean}
        if label:
            item["prix_label"] = label
            item["prix"] = _parse_price(label)
        else:
            item["prix"] = _parse_price(price_raw)
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
    coeff_base = (form.get("coeff_base") or "ttc").lower()  # "ht" ou "ttc"

    # Les inputs soumettent déjà les prix clients appliqués dans le JS :
    # - marques TTC : inp.value = prix_partenaire_TTC × coeff
    # - Omega (HT)  : inp.value = prix_partenaire_HT  × coeff  → doit être converti en TTC ici
    total_client = 0.0
    last_nec_priced: dict | None = None
    for line in necessaires:
        lbl = line.get("prix_label") or ""
        if lbl in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
            continue
        prix_input = float(line.get("prix") or 0)  # prix soumis = prix_partenaire × coeff
        line["prix_client"] = prix_input
        # Reconstituer le prix partenaire original (= prix_client / coeff) pour que
        # "Modifier le devis" affiche les prix partenaires, pas les prix clients
        prix_partenaire = round(prix_input / coeff, 2) if coeff and coeff != 0 else prix_input
        line["prix"] = prix_partenaire
        total_client += prix_input
        last_nec_priced = line

    total_client = round(total_client, 2)

    for line in optionnelles:
        lbl = line.get("prix_label") or ""
        if lbl in ("OFFERT", "INCL"):
            line["prix_client"] = 0.0
            continue
        prix_input = float(line.get("prix") or 0)
        line["prix_client"] = prix_input
        prix_partenaire = round(prix_input / coeff, 2) if coeff and coeff != 0 else prix_input
        line["prix"] = prix_partenaire

    # ── Arrondi des totaux au multiple de 5 supérieur ──
    # La dernière ligne tarifée encaisse le delta pour que la somme affichée = total arrondi.
    def _adjust_last(line: dict | None, delta: float) -> None:
        if line is None or abs(delta) < 0.005:
            return
        line["prix_client"] = round((line.get("prix_client") or 0) + delta, 2)
        if coeff and coeff != 0:
            line["prix"] = round(line["prix_client"] / coeff, 2)

    if total_client > 0:
        rounded_nec = _ceil5(total_client)
        _adjust_last(last_nec_priced, rounded_nec - total_client)
        total_client = rounded_nec

    # Total "si toutes les options retenues" également arrondi à 5
    priced_opts = [l for l in optionnelles if (l.get("prix_label") or "") not in ("OFFERT", "INCL")]
    if priced_opts:
        total_opt = round(sum(float(l.get("prix_client") or 0) for l in priced_opts), 2)
        grand = round(total_client + total_opt, 2)
        _adjust_last(priced_opts[-1], _ceil5(grand) - grand)

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
        "interventions_necessaires": necessaires,
        "interventions_optionnelles": optionnelles,
        "total_ttc": total_client,
        "coeff": coeff,
        "coeff_base": coeff_base,
        "delai": form.get("delai", "4 à 6 semaines").strip() or "4 à 6 semaines",
    }


def _build_filename(data: dict) -> str:
    nom = (data.get("client") or {}).get("nom", "").strip() or "CLIENT"
    sav = (data.get("sav") or {}).get("numero", "").strip() or datetime.now().strftime("%Y%m%d")
    nom_short = "_".join(nom.split()[:2])  # max 2 mots du nom
    raw = f"DEVIS_DOUX_{nom_short}_{sav}"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")
    return (safe or "DEVIS_DOUX")[:80]  # cap 80 chars


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
