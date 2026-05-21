# Security Review — DouxDevis
**Date:** 2026-05-21  
**Framework:** OWASP Top 10 2024  
**Scope:** app.py, pdf_extractor.py, pdf_generator.py, templates

---

## Résumé exécutif

DouxDevis a une **bonne posture sécurité de base** mais nécessite des corrections avant vente multi-clients:
- ✅ Pas de secrets en dur
- ✅ XSS mitigé (autoescape Jinja2)
- ❌ CSRF non protégé
- ❌ Validation fichier insuffisante
- ❌ Gestion d'erreurs masque les bugs

**Risk Level:** 🟠 Moyen → à réduire à 🟢 Bas avant production

---

## OWASP Top 10 — État

### 1. 🔴 Broken Access Control
**Status:** 🟢 OK  
**Analyse:**
- Chaque devis a un UUID unique (token)
- Les téléchargements vérifiaient le token: `if token != session.get("token")`
- Pas de path traversal (utilise UUID comme clé, pas de chemin user)

**Risque résiduel:** Session token sans expiration → réutilisable longtemps  
**Fix:** Ajouter TTL (Time-To-Live) sur les sessions
```python
session["token_created"] = time.time()
if time.time() - session.get("token_created", 0) > 900:  # 15 min
    abort(403)
```

---

### 2. 🔴 Cryptographic Failures
**Status:** 🟢 OK  
**Analyse:**
- HTTPS activé par défaut (Render)
- Pas de données sensibles stockées en clair
- ANTHROPIC_API_KEY via env var
- Session secret auto-généré: `secrets.token_hex(32)` ✓

**Risque:** Aucun détecté

---

### 3. 🔴 Injection
**Status:** 🟡 Partiellement OK  

#### 3a. SQL Injection
✅ **OK** — Pas de DB SQL utilisée (Flask sessions seulement)

#### 3b. JSON/Python Injection
⚠️ **À vérifier** — `pdf_extractor.py` parse JSON de Claude API
```python
# app.py:241
data = extract_from_pdf(pdf_bytes, api_key=api_key, filename=pdf_file.filename)
```

Regarde `pdf_extractor.py`:
```python
# ❌ Problème potentiel
def extract_from_pdf(...):
    ...
    response = client.messages.create(...)
    # Pas de validation du JSON reçu
    resp_json = json.loads(response.content[0].text)
    return normalize_pdf_data(resp_json)  # ← Injection possible ici
```

**Risque:** Si Claude API retourne du JSON malformé ou malveillant, `normalize_pdf_data()` pourrait crash  
**Fix:**
```python
# ✅ À la place
try:
    resp_json = json.loads(response.content[0].text)
    # Validation du schéma
    required_keys = ["interventions_necessaires", "interventions_optionnelles"]
    if not all(k in resp_json for k in required_keys):
        raise ValueError("Missing required keys in response")
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON from Claude: {e}")
    raise ValueError("API returned invalid JSON")
```

#### 3c. Template Injection (XSS)
✅ **OK** — Jinja2 autoescape activé par défaut
```html
<!-- Sûr — {{ user_input }} sera échappé -->
<p>{{ client_name }}</p>
```

Vérification: Pas de `|safe` ou Markup non-échappé détecté. ✓

---

### 4. 🟠 Insecure Design
**Status:** 🟡 À améliorer  

**Session management sans rotation:**
```python
# app.py:312
token = uuid.uuid4().hex
session["token"] = token
# ← Token ne change jamais pendant la session
```

**Risque:** Token volé = accès permanent aux devis de cette session  
**Fix:**
- Expiration après 15-30 min
- Régénération après chaque opération sensible
- User-Agent binding

---

### 5. 🟠 Security Misconfiguration
**Status:** 🟡 À améliorer  

**Logs en stdout (print):**
```python
# app.py:73, 81, 102
print(f"Creating Signature Request: {sr_data}")
print(f"Response: {resp.text[:300]}")
```

**Risque:** Données sensibles visibles dans les logs publics Render  
**Fix:** Logger structuré avec masquage
```python
import logging
logger = logging.getLogger(__name__)

# ✅ À la place
logger.info("signature_request", extra={
    "sr_id": sr_id,
    "status": resp.status_code,
    # Pas de response.text en full
})
```

**Headers sécurité manquants:**
```python
# ❌ Actuellement
@app.route("/")
def index():
    return render_template("index.html")
    # Pas de Content-Security-Policy
    # Pas de X-Frame-Options
    # Pas de X-Content-Type-Options
```

**Fix:**
```python
# ✅ À la place
@app.before_request
def set_security_headers():
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
```

---

### 6. 🟠 Vulnerable & Outdated Components
**Status:** 🟢 OK  

**Dépendances vérifiées:**
```
Flask==3.0.3 ✓ (latest 3.0.x)
anthropic>=0.40.0 ✓
reportlab==4.2.5 ✓
requests>=2.31.0 ✓
```

Aucune CVE détecté. Licences compatibles (MIT, BSD, Apache 2.0).

**Recommandation:** `pip install --upgrade pip && pip check` régulièrement

---

### 7. 🔴 Authentication & Session Management
**Status:** 🟡 À améliorer  

**Pas d'authentification utilisateur:**
- Chaque utilisateur est anonymous
- Identifié uniquement par UUID de session

✅ **OK pour MVP**, mais:
- Pas d'audit trail (qui a généré quel devis?)
- Pas de rate limiting par utilisateur
- Pas de brute-force protection

**Fix future:** Ajouter email + link de confirmation (pas besoin de password)

---

### 8. 🔴 Software & Data Integrity Failures
**Status:** 🟡 À améliorer  

**Validation de fichier insuffisante:**
```python
# app.py:234
pdf_file = request.files.get("pdf")
pdf_bytes = pdf_file.read()
# ❌ Pas de vérification:
# - Magic bytes (quelqu'un upload un .exe renommé .pdf)
# - Taille max (25MB déclaré mais pas enforced)
# - Scan antivirus
```

**Risque:** Upload de malware déguisé en PDF  
**Fix:**
```python
# ✅ À la place
MAX_SIZE = 25 * 1024 * 1024
pdf_bytes = pdf_file.read()

if len(pdf_bytes) > MAX_SIZE:
    raise ValueError(f"File too large: {len(pdf_bytes)} > {MAX_SIZE}")

# Vérifier magic bytes PDF
if not pdf_bytes.startswith(b'%PDF'):
    raise ValueError("Invalid PDF: missing PDF signature")

# Log du hash pour audit
file_hash = hashlib.sha256(pdf_bytes).hexdigest()
logger.info(f"pdf_uploaded", extra={"size": len(pdf_bytes), "hash": file_hash})
```

---

### 9. 🟠 Logging & Monitoring Failures
**Status:** 🟡 Faible  

**Actuellement:** `print()` statements, pas de structured logging  
**En prod sur Render:** Logs invisibles après 24h

**Fix:**
```python
import logging
import json

# ✅ Setup structuré
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log les events critiques
logger.info("pdf_extraction_started", extra={"filename": filename})
logger.error("api_error", extra={"status": resp.status_code, "error": str(e)})
```

---

### 10. 🔴 Server-Side Request Forgery (SSRF)
**Status:** 🟢 OK  

**Analyse:**
- PDF upload via `request.files` (local)
- API calls à Anthropic et YouSign (fixed endpoints, pas d'user input)
- Pas de `requests.get(user_input_url)`

Aucun risque SSRF détecté.

---

## 🔐 Vulnérabilités détectées — Résumé

| # | Vulnérabilité | Sévérité | Fichier | Fix Effort |
|---|---|---|---|---|
| 1 | Session token sans expiration | 🟠 Moyen | app.py:312 | 30 min |
| 2 | CSRF non protégé | 🟠 Moyen | templates/*.html | 1h |
| 3 | Validation fichier (magic bytes) | 🟠 Moyen | app.py:234 | 30 min |
| 4 | Logging en stdout | 🟠 Moyen | app.py (multiple) | 1h |
| 5 | Headers sécurité manquants | 🟡 Faible | app.py (global) | 30 min |
| 6 | JSON parsing non validé | 🟡 Faible | pdf_extractor.py | 30 min |
| 7 | Gestion Exception générique | 🟠 Moyen | app.py (5 locations) | 1.5h |

**Total effort:** 5-6 heures de work

---

## ✅ Points positifs

1. ✅ Secrets en variables d'environnement (pas hardcodés)
2. ✅ HTTPS enforced (Render)
3. ✅ Autoescape Jinja2 active (XSS mitigé)
4. ✅ UUID tokens unique par session (pas de séquentiels)
5. ✅ Pas de SQL injection (pas de DB SQL)
6. ✅ Pas de direct RCE (pas d'eval/exec)
7. ✅ Dépendances à jour, pas de CVE

---

## 🚀 Priorités de sécurité

### P1 - Faire avant vente (4-5h)
- [ ] Session token expiration (TTL)
- [ ] CSRF tokens sur tous les POST
- [ ] Validation magic bytes PDF
- [ ] Gestion d'erreurs par type (pas Exception générique)

### P2 - Avant 2ème client (2-3h)
- [ ] Structured logging (remplacer print)
- [ ] Security headers (CSP, X-Frame-Options)
- [ ] Rate limiting par session (Flask-Limiter)
- [ ] JSON validation schema (pour Claude API)

### P3 - Long terme
- [ ] User authentication (email link)
- [ ] Audit trail des devis
- [ ] Encryption at rest (TBD)
- [ ] Pentesting par professionnel

---

## Checklist sécurité avant production multi-clients

- [ ] Session expiration: 15-30 min
- [ ] CSRF tokens: sur form.html + generate POST
- [ ] File validation: magic bytes + max size
- [ ] Exception handling: try/except par type
- [ ] Logging: replacer print() par logger
- [ ] Headers: CSP, X-Frame-Options, X-Content-Type-Options
- [ ] Rate limiting: 5-10 req/min par session
- [ ] API validation: JSON schema pour Claude response
- [ ] Secrets: vérifier aucun hardcoded
- [ ] HTTPS: enforced ✓ (Render)

---

## Conclusion

**DouxDevis est sûr pour MVP avec 1-2 clients de confiance.** Les vulnerabilités trouvées sont classiques de startup early-stage et fixables en 1 sprint.

**Avant de vendre à des clients "hostiles"** (qui tesseraient la sécurité), faire les P1 fixes (4-5h de travail).

**Recommandation:** Corriger P1 cette semaine, lancer avec early customers, faire P2 après feedback.
