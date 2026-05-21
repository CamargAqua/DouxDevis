# Audit Codebase — DouxDevis
**Date:** 2026-05-21  
**Stack:** Flask + Python + Vanilla JS + ReportLab  
**Scope:** 1500+ lignes code, 5 modules Python, 4 templates, prod sur Render

---

## Résumé exécutif

DouxDevis est **production-ready pour vente** avec risques maîtrisés. Code bien structuré, pas de secrets en dur, gestion d'erreurs présente mais basique. Les 2 bugs récemment fixés ont démontré une excellente capacité à identifier et corriger des issues système. 

**Score général:** 7.5/10 — Bon pour MVP/early customers, à améliorer pour scaling.

---

## 🔴 Findings Critiques

**Aucun finding critique détecté.**

---

## 🟠 Findings Majeurs

### 1. Gestion d'erreurs trop générique (app.py)
```python
# ❌ Problème
except Exception as e:
    print(f"Exception: {e}")
    return None
```
**Risque:** Masque les vrais bugs. L'API Anthropic timeout? JSON parse error? Tous cachés.  
**Remédiation:**
```python
# ✅ À la place
except TimeoutError as e:
    logger.error(f"API timeout: {e}", exc_info=True)
    flash("Extraction trop lente, réessayez", "error")
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON from API: {e}", exc_info=True)
    flash("Erreur API parsing", "error")
except Exception as e:
    logger.critical(f"Unexpected error: {e}", exc_info=True)
    flash("Erreur système", "error")
```
**Fichiers affectés:** app.py:181, 190, 242, 320, 326  
**Priorité:** Majeur - avant production multi-clients

---

### 2. Pas de logging structuré
```python
# ❌ Actuellement
print(f"Creating Signature Request: {sr_data}")
print(f"SR Status: {resp.status_code}, Response: {resp.text[:300]}")
```
**Risque:** Logs en stdout = impossible à tracer en prod sur Render. Pas de timestamps. Données sensibles possible.  
**Remédiation:** Utiliser Python logging + structlog
```python
# ✅ À la place
import logging
logger = logging.getLogger(__name__)
logger.info("signature_request_created", extra={"sr_id": sr_id, "status": resp.status_code})
```
**Priorité:** Majeur - critique pour debug en prod

---

### 3. Session tokens basés sur UUID sans rotation
```python
# app.py:312
token = uuid.uuid4().hex
session["token"] = token
```
**Risque:** Si un utilisateur laisse son session ouvert et que quelqu'un accède à son historique (navigateur partagé, cache), le token peut être réutilisé pendant la session.  
**Remédiation:** 
- Ajouter expiration de session (15-30 min)
- Ajouter user-agent verification
- CSRF token sur les POST

**Priorité:** Majeur - avant multi-client

---

### 4. CSRF protection manquante sur POST
```html
<!-- templates/form.html POST -->
<form action="{{ url_for('generate') }}" method="post">
  <!-- Pas de token CSRF -->
</form>
```
**Risque:** Un attaquant peut faire générer des devis depuis un autre site.  
**Remédiation:** Flask-WTF ou token CSRF custom
```python
from flask_wtf.csrf import generate_csrf

@app.route("/generate", methods=["POST"])
def generate():
    token = request.form.get("csrf_token")
    if not token or token != session.get("csrf_token"):
        abort(403)
```

**Priorité:** Majeur

---

### 5. Validation de fichier insuffisante
```python
# app.py:234
pdf_file = request.files.get("pdf")
pdf_bytes = pdf_file.read()
```
**Risque:** 
- Pas de check de taille (max 25MB déclaré mais non enforced)
- Pas de magic bytes verification (quelqu'un peut uploader un .exe renommé en .pdf)
- Pas de scan virus

**Remédiation:**
```python
# ✅
MAX_SIZE = 25 * 1024 * 1024  # 25MB
if len(pdf_bytes) > MAX_SIZE:
    raise ValueError(f"File too large: {len(pdf_bytes)} > {MAX_SIZE}")

# Check magic bytes
if not pdf_bytes.startswith(b'%PDF'):
    raise ValueError("Invalid PDF: missing PDF signature")
```

**Priorité:** Majeur - avant clients externes

---

## 🟡 Findings Mineurs

### 1. Code en import circulaire potentiel
**Fichiers:** `app.py` importe de `pdf_generator.py` et `docx_generator.py`  
**Impact:** Minimal pour maintenant, mais limite la réutilisabilité  
**Remédiation:** Extraire une couche `core/` pour la logique métier

---

### 2. Pas de type hints (Python)
```python
# ❌ Actuellement
def extract_from_pdf(pdf_bytes, api_key, filename):

# ✅ À la place
def extract_from_pdf(pdf_bytes: bytes, api_key: str, filename: str) -> dict:
```
**Impact:** Mineur, mais améliore maintenabilité  
**Priorité:** Sprint suivant

---

### 3. Hardcoded paths
```python
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
GENERATED_DIR = BASE_DIR / "generated"
```
**Risque:** Ne fonctionne que sur le même système. Pas configurable.  
**Remédiation:** Lire depuis `.env` ou variables d'env
```python
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "uploads"))
```

---

### 4. Pas de health check
**Risque:** Render ne peut pas monitorer la santé de l'app  
**Remédiation:** Ajouter `/health` endpoint
```python
@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok", "service": "douxdevis"}, 200
```

---

### 5. Pas de rate limiting
**Risque:** Quelqu'un peut spammer des extractions PDF (coûteux en tokens Claude)  
**Remédiation:** Flask-Limiter
```python
from flask_limiter import Limiter
limiter = Limiter(app, key_func=lambda: session.get("token"))

@app.route("/extract", methods=["POST"])
@limiter.limit("5 per hour")
def extract():
    ...
```

---

## 📊 Domaines - État général

| Domaine | État | Notes |
|---------|------|-------|
| **1. Sécurité** | 🟡 Bon | Secrets via env OK. XSS/injection OK. CSRF/validation à fixer |
| **2. Build & Livraison** | 🟢 Excellent | GitHub Actions OK. Deploy Render automatique. Tests basiques OK |
| **3. Duplication** | 🟢 Excellent | Pas de code dupliqué détecté |
| **4. Maintenabilité** | 🟡 Bon | Modules clairs. Pas type hints. pdf_generator.py un peu dense (621 lignes) |
| **5. Dépendances** | 🟢 Excellent | Versions à jour. Pas de CVE détecté. Licences compatibles |
| **6. Code mort** | 🟢 Excellent | Toutes les fonctions utilisées. demo.py orphelin mais utile |
| **7. Observabilité** | 🟡 Faible | Print() au lieu de logging. Pas de monitoring Render. Pas de Sentry |
| **8. Concurrence** | 🟢 OK | Flask-Session thread-safe. Pas d'accès concurrent à fichiers |
| **9. Cycle de vie** | 🟡 Bon | Env vars OK. Pas de graceful shutdown. Pas de health check |

---

## 🚀 Plan de remédiation

### Immédiat (avant vendre à 1er client)
- [ ] Fix gestion d'erreurs par domaine (au lieu de Exception générique)
- [ ] Ajouter CSRF tokens sur tous les POST
- [ ] Valider magic bytes PDF + vérifier taille
- [ ] Ajouter logging structuré (remplacer print())
- [ ] Ajouter expiration session (15 min)

**Estimé:** 4-6 heures

### Court terme (après 1er client)
- [ ] Intégrer Flask-Limiter (rate limiting)
- [ ] Ajouter `/health` endpoint
- [ ] Ajouter Sentry pour error tracking
- [ ] Type hints sur tous les modules
- [ ] Tests unitaires pour pdf_extractor (LLM parsing)

**Estimé:** Sprint 1

### Long terme (scaling)
- [ ] Séparer API métier de la couche Flask
- [ ] Ajouter vraie DB (SQLite→PostgreSQL)
- [ ] Queue pour les extractions longues (Celery/RQ)
- [ ] Dashboard admin pour monitorer les extraits
- [ ] Intégration avec monitoring Render (DataDog/New Relic)

---

## ✅ Points positifs

1. **Extraction LLM performante:** 11.8s = très bon pour du PDF parsing Claude
2. **Code bien structuré:** 3 modules clairs (app, extractor, generator)
3. **Zero secrets en dur:** Tous les credentials en env vars
4. **Gestion de sessions:** Unique tokens par devis
5. **PDF generation robuste:** ReportLab utilisé correctement, pas d'overflow
6. **Template Jinja2 sûr:** Autoescape activé par défaut
7. **Responsive design:** Formulaire fonctionne mobile + desktop
8. **Lessons.md system:** Excellente capacité à capturer et ne pas répéter les erreurs

---

## 📋 Checklist avant vente à client

- [ ] Toutes les findings 🔴 résolues (aucune actuellement ✓)
- [ ] Toutes les findings 🟠 résolues (5 trouvés - voir plan)
- [ ] Tests e2e avec vrai PDF partenaire (Omega, Breitling, etc.) ✓
- [ ] Logs en production vérifiés
- [ ] Rate limiting testé
- [ ] Security headers vérifiés (CSP, X-Frame-Options, etc.)
- [ ] HTTPS enforced ✓ (Render)
- [ ] Environment variables documentées (.env.example)

---

## Conclusion

**DouxDevis est viable pour MVP mais a des dettes de sécurité qui doivent être adressées AVANT de vendre à plusieurs clients.** Les findings 🟠 sont tous fixables en 1 sprint. Après ça, le code est production-grade.

**Recommandation:** Faire les 5 fixes majeurs (4-6h), puis lancer avec 1-2 clients de confiance. Iterate sur les findings mineurs.
