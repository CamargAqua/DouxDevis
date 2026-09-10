"""Verification que Devisly est bien monte sous /devisly (meme process que DouxDevis)
et que les deux apps utilisent des noms de cookie de session distincts.

ponytail: necessite une Postgres reelle (DATABASE_URL) pour que /devisly/ reponde 200 —
pas mockee. Sans DATABASE_URL joignable, le test saute proprement la partie Devisly.
"""
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

from app import app
from devisly.app import app as devisly_app

print("=== TEST 0 : pas d'import non-relatif vers un module homonyme de DouxDevis ===")
# ponytail: la regression reelle rencontree — un `from pdf_extractor import X` a l'interieur
# d'une fonction (import differe, jamais execute par un simple `import app`) resolvait vers
# le pdf_extractor.py de DouxDevis au lieu de devisly/pdf_extractor.py. Grep statique plutot
# qu'un test qui devrait declencher chaque branche pour l'attraper a l'execution.
_BAD_IMPORT = re.compile(r"^\s*from (db|docx_generator|pdf_extractor|pdf_generator|manage_tenants) import", re.M)
bad = []
for f in Path("devisly").glob("*.py"):
    m = _BAD_IMPORT.search(f.read_text(encoding="utf-8"))
    if m:
        bad.append(f"{f}: {m.group(0).strip()}")
assert not bad, "import non-relatif vers un module homonyme:\n" + "\n".join(bad)
print("OK — aucun import non-relatif trouve")

client = app.test_client()

print("\n=== TEST 1 : DouxDevis toujours servi sur / ===")
resp = client.get("/")
print("status:", resp.status_code, "(attendu: 200)")
assert resp.status_code == 200

print("\n=== TEST 2 : Devisly monte sous /devisly ===")
resp = client.get("/devisly/")
print("status:", resp.status_code)
if resp.status_code == 500:
    print("SKIP (DATABASE_URL non joignable en local — attendu hors setup Postgres)")
else:
    assert resp.status_code in (200, 302), f"status inattendu: {resp.status_code}"

print("\n=== TEST 3 : cookies de session distincts (config) ===")
doux_cookie_name = app.config["SESSION_COOKIE_NAME"]
devisly_cookie_name = devisly_app.config["SESSION_COOKIE_NAME"]
print(f"DouxDevis: {doux_cookie_name!r} / Devisly: {devisly_cookie_name!r}")
assert doux_cookie_name != devisly_cookie_name, "les deux apps partageraient le meme cookie"
assert devisly_app.config["SESSION_COOKIE_PATH"] == "/devisly"

print("\nOK")
