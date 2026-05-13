"""Flask app — Devis DOUX Joaillier."""
from __future__ import annotations

import os
import re
import secrets
import uuid
from datetime import datetime
from pathlib import Path

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
)
from flask_session import Session
from werkzeug.utils import secure_filename

from docx_generator import build_docx
from pdf_extractor import confidence_score, extract_from_pdf
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

ALLOWED_PDF = {"pdf"}
ALLOWED_IMG = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_CONTENT_LENGTH = 25 * 1024 * 1024

MARQUES = ["Chanel", "Tag Heuer", "Breitling", "Rolex", "Autre"]


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

        pdf_file = request.files.get("pdf")
        if not pdf_file or not pdf_file.filename:
            flash("Veuillez sélectionner un PDF.", "error")
            return redirect(url_for("index"))
        if not _has_extension(pdf_file.filename, ALLOWED_PDF):
            flash("Le fichier doit être un PDF.", "error")
            return redirect(url_for("index"))

        pdf_bytes = pdf_file.read()
        if not pdf_bytes:
            flash("Le PDF est vide.", "error")
            return redirect(url_for("index"))

        try:
            data = extract_from_pdf(pdf_bytes, api_key=api_key)
        except Exception as exc:
            flash(f"Erreur lors de l'extraction : {exc}", "error")
            return redirect(url_for("index"))

        # Date du jour si absente ou vide
        if not (data.get("sav") or {}).get("date"):
            if "sav" not in data or not isinstance(data["sav"], dict):
                data["sav"] = {}
            data["sav"]["date"] = datetime.now().strftime("%d.%m.%Y")

        token = uuid.uuid4().hex
        session_dir = UPLOAD_DIR / token
        session_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = session_dir / secure_filename(pdf_file.filename)
        pdf_path.write_bytes(pdf_bytes)

        session["token"] = token
        session["data"] = data
        session["source_pdf"] = pdf_path.name

        return redirect(url_for("review"))

    @app.route("/review", methods=["GET"])
    def review():
        data = session.get("data")
        if not data:
            return redirect(url_for("index"))
        return render_template("form.html", data=data, marques=MARQUES)

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

    @app.errorhandler(413)
    def too_large(_):
        flash("Fichier trop volumineux (limite 25 Mo).", "error")
        return redirect(url_for("index"))

    return app


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

    necessaires = _collect_lines(form, "nec")
    optionnelles = _collect_lines(form, "opt")

    total_raw = form.get("total_ttc", "").strip()
    if total_raw:
        total = _parse_price(total_raw)
    else:
        total = sum(line.get("prix") or 0 for line in necessaires)

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
        "total_ttc": total,
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
