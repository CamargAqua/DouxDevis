"""Verification rapide du toggle coefficient + panneau devis source."""
import io
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app import app, _form_to_data


def has_aside(html: str) -> str:
    if 'class="source-pdf-frame"' in html:
        return "pdf"
    if 'class="source-mail-card"' in html:
        return "text"
    return "none"


client = app.test_client()

print("=== TEST 1 : Breitling (PDF) — defaults JS attendus nec=False / opt=True ===")
pdf_bytes = (Path("test_pdfs") / "devis_breitling_navitimer.pdf").read_bytes()
resp = client.post(
    "/extract",
    data={"pdf": (io.BytesIO(pdf_bytes), "devis_breitling_navitimer.pdf")},
    content_type="multipart/form-data",
    follow_redirects=True,
)
html = resp.get_data(as_text=True)
print("status:", resp.status_code)
m = re.search(r"const BRAND_COEFFS_RAW = (\{.*?\});", html, re.DOTALL)
coeffs = json.loads(m.group(1))
print("Breitling coeff_nec_default:", coeffs["Breitling"].get("coeff_nec_default", True), "(attendu: False)")
print("Breitling coeff_opt_default:", coeffs["Breitling"].get("coeff_opt_default", True), "(attendu: True)")
print("source panel:", has_aside(html), "(attendu: pdf)")

with client.session_transaction() as sess:
    token = sess.get("token")
    print("source_kind session:", sess.get("source_kind"), "source_pdf:", sess.get("source_pdf"))
src = client.get(f"/source/{token}")
print("/source/<token> status:", src.status_code, "content-type:", src.content_type)

print()
print("=== TEST 2 : Omega (PDF) — defaults JS attendus nec=False / opt=False ===")
pdf_bytes = (Path("test_pdfs") / "devis_omega_seamaster.pdf").read_bytes()
resp = client.post(
    "/extract",
    data={"pdf": (io.BytesIO(pdf_bytes), "devis_omega_seamaster.pdf")},
    content_type="multipart/form-data",
    follow_redirects=True,
)
html = resp.get_data(as_text=True)
print("status:", resp.status_code)
m = re.search(r"const BRAND_COEFFS_RAW = (\{.*?\});", html, re.DOTALL)
coeffs = json.loads(m.group(1))
print("Omega coeff_nec_default:", coeffs["Omega"].get("coeff_nec_default", True), "(attendu: False)")
print("Omega coeff_opt_default:", coeffs["Omega"].get("coeff_opt_default", True), "(attendu: False)")
print("source panel:", has_aside(html), "(attendu: pdf)")

print()
print("=== TEST 3 : marque normale (Chanel, PDF) — defaults nec=True / opt=True ===")
pdf_bytes = (Path("test_pdfs") / "devis_chanel_j12.pdf").read_bytes()
resp = client.post(
    "/extract",
    data={"pdf": (io.BytesIO(pdf_bytes), "devis_chanel_j12.pdf")},
    content_type="multipart/form-data",
    follow_redirects=True,
)
html = resp.get_data(as_text=True)
print("status:", resp.status_code)
m = re.search(r"const BRAND_COEFFS_RAW = (\{.*?\});", html, re.DOTALL)
coeffs = json.loads(m.group(1))
print("Chanel coeff_nec_default:", coeffs["Chanel"].get("coeff_nec_default", True), "(attendu: True)")
print("Chanel coeff_opt_default:", coeffs["Chanel"].get("coeff_opt_default", True), "(attendu: True)")
print("source panel:", has_aside(html), "(attendu: pdf)")

print()
print("=== TEST 4 : coller un email texte (Fred) — panneau texte attendu ===")
paste = (
    "Bonjour,\n\n"
    "SAV 391234-1\n"
    "DEVIS 1: ECHANGE PENDENTIF A NEUF: 42€HT (prix public recommandé 84€TTC)\n"
    "Cordialement"
)
resp = client.post("/extract", data={"paste_text": paste}, follow_redirects=True)
html = resp.get_data(as_text=True)
print("status:", resp.status_code)
print("source panel:", has_aside(html), "(attendu: text)")
print("contient le texte source:", "ECHANGE PENDENTIF" in html)

print()
print("=== TEST 5 : backend _form_to_data — toggle OFF = passthrough (pas de coeff/ceil5) ===")


class FakeForm(dict):
    def get(self, k, default=None):
        return super().get(k, default)

    def getlist(self, k):
        v = super().get(k)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


# Simule 1 ligne nécessaire à 533.00 (prix client final saisi tel quel, coeff_nec désactivé)
# 533 n'est pas multiple de 5 -> si ceil5 etait applique par erreur, on verrait 535.
form = FakeForm({
    "marque": "Omega",
    "client_nom": "TEST CLIENT",
    "sav_numero": "123456",
    "sav_date": "10.06.2026",
    "sav_lieu": "Avignon",
    "modele": "SEAMASTER", "reference": "REF", "numero_serie": "SN",
    "coeff": "1.6", "coeff_opt": "", "coeff_base": "ht",
    "coeff_nec_enabled": "0", "coeff_opt_enabled": "0",
    "nec_description[]": ["REVISION"], "nec_prix[]": ["533.00"], "nec_base_prix[]": ["533.00"], "nec_label[]": [""],
    "opt_description[]": ["GRAVURE"], "opt_prix[]": ["123.00"], "opt_base_prix[]": ["123.00"], "opt_label[]": [""],
    "total_override": "656.00",
})
data = _form_to_data(form)
nec = data["interventions_necessaires"][0]
opt = data["interventions_optionnelles"][0]
print("nec prix_client (attendu 533.0, pas de ceil5/coeff):", nec.get("prix_client"))
print("nec prix HT (attendu 533.0 = passthrough):", nec.get("prix"))
print("opt prix_client (attendu 123.0, pas de coeff_opt):", opt.get("prix_client"))
print("opt prix HT (attendu 123.0 = passthrough):", opt.get("prix"))
print("total_ttc (attendu 533.0):", data.get("total_ttc"))
print("coeff_nec_enabled:", data.get("coeff_nec_enabled"), "(attendu False)")
print("coeff_opt_enabled:", data.get("coeff_opt_enabled"), "(attendu False)")

print()
print("=== TEST 6 : backend _form_to_data — toggle ON = coeff + ceil5 (comportement existant) ===")
form2 = FakeForm({
    "marque": "Chanel",
    "client_nom": "TEST CLIENT",
    "sav_numero": "123456",
    "sav_date": "10.06.2026",
    "sav_lieu": "Avignon",
    "modele": "J12", "reference": "REF", "numero_serie": "SN",
    "coeff": "2.1", "coeff_opt": "", "coeff_base": "ht",
    "coeff_nec_enabled": "1", "coeff_opt_enabled": "1",
    "nec_description[]": ["REVISION"], "nec_prix[]": ["210.00"], "nec_base_prix[]": ["100.00"], "nec_label[]": [""],
    "opt_description[]": ["GRAVURE"], "opt_prix[]": ["21.00"], "opt_base_prix[]": ["10.00"], "opt_label[]": [""],
    "total_override": "210.00",
})
data2 = _form_to_data(form2)
nec2 = data2["interventions_necessaires"][0]
opt2 = data2["interventions_optionnelles"][0]
print("nec prix_client (base 100 x 2.1 = 210, ceil5 -> 210):", nec2.get("prix_client"))
print("opt prix_client (base 10 x 2.1 = 21, ceil5 -> 25):", opt2.get("prix_client"))
print("coeff_nec_enabled:", data2.get("coeff_nec_enabled"), "(attendu True)")
print("coeff_opt_enabled:", data2.get("coeff_opt_enabled"), "(attendu True)")

print()
print("=== TOUS LES TESTS TERMINÉS ===")
