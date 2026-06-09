# DouxDevis — Générateur automatique de devis

**DouxDevis** est une application web Flask qui automatise la génération de devis clients à partir des devis partenaires. L'outil extrait les données, applique les coefficients commerciaux, traduit en français, et génère un PDF professionnel.

---

## 📖 Documentation

- **[GUIDE_UTILISATEUR.md](./GUIDE_UTILISATEUR.md)** — Guide complet pour les utilisateurs (comment utiliser l'outil, règles métier, FAQ)
- **[README.md](./README.md)** — Ce fichier (documentation technique pour les développeurs)

---

## ⚙️ Stack technique

- **Framework** : Flask (Python)
- **Frontend** : HTML5, CSS3, JavaScript vanilla
- **PDF Generation** : reportlab + custom templates
- **Word Generation** : python-docx
- **AI Extraction** : Claude API (Anthropic)
- **Deployment** : Render.com
- **Email** : SMTP
- **Signature numérique** : Yousign API (optionnel)

---

## 🚀 Installation & Setup

### Prérequis
- Python 3.9+
- pip
- Variables d'environnement configurées

### Installation locale

```bash
# Clone le dépôt
git clone https://github.com/CamargAqua/DouxDevis.git
cd DouxDevis

# Crée un environnement virtuel
python -m venv venv
source venv/bin/activate  # Sur Windows: venv\Scripts\activate

# Installe les dépendances
pip install -r requirements.txt

# Configure les variables d'env
cp .env.example .env
# Édite .env avec tes clés API
```

### Variables d'environnement requises

```env
# API Keys
ANTHROPIC_API_KEY=sk-...
FLASK_SECRET_KEY=<secret-key-long>

# Email
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-app-password

# Optionnel — Signature numérique
YOUSIGN_API_KEY=<api-key-yousign>

# Optionnel — Render.com (déploiement)
RENDER_API_KEY=<api-key-render>
```

### Lancer le serveur local

```bash
python app.py
```

Visite `http://localhost:5000`

---

## 📁 Structure du projet

```
DouxDevis/
├── app.py                     # Application Flask principale
├── pdf_extractor.py           # Extraction données (PDF/EML/MSG)
├── pdf_generator.py           # Génération PDF final
├── docx_generator.py          # Génération DOCX
├── coefficients.json          # Coefficients par marque
├── requirements.txt           # Dépendances Python
│
├── templates/
│   ├── index.html             # Page d'accueil (upload)
│   ├── form.html              # Page review/édition
│   ├── done.html              # Page succès
│   └── base.html              # Layout de base
│
├── static/
│   ├── style.css              # Styles
│   ├── logos/                 # Logos des marques (*.png)
│   ├── doux.png               # Logo DOUX
│   ├── cgv.pdf                # Conditions générales
│   └── qr_cgv.png             # QR code CGV
│
├── tasks/
│   ├── todo.md                # Tâches en cours
│   ├── lessons.md             # Leçons apprises
│   └── [audit files]
│
├── GUIDE_UTILISATEUR.md       # Guide pour les clients
└── README.md                  # Ce fichier
```

---

## 🔄 Flux de l'application

```
1. INDEX (GET /)
   ↓
   Upload PDF/EML/MSG
   ↓
2. EXTRACT (POST /extract)
   ├── Parse fichier → pdf_extractor.py
   ├── Extraction IA (Claude API)
   ├── Auto-traduction FR
   └── Stockage session
   ↓
3. REVIEW (GET /review)
   ├── Affiche form.html
   ├── Édition données + coefficients
   └── Preview calculs de tarification
   ↓
4. GENERATE (POST /generate)
   ├── Applique règles métier
   ├── Arrondi total (multiple de 5)
   ├── Génère PDF via pdf_generator.py
   └── Envoie par email
   ↓
5. DONE (GET /done)
   └── Confirmation + lien download
```

---

## 🧠 Modules clés

### `pdf_extractor.py`
Extrait les données des documents partenaires :
- `extract_from_pdf()` — Parse PDFs
- `extract_from_eml()` — Parse emails (.eml)
- `extract_from_msg()` — Parse Outlook (.msg)
- `_extract_from_text()` — Extraction IA du contenu texte
- `confidence_score()` — Score de confiance extraction

**Données extraites :**
```python
{
    "marque": "Chanel",
    "client": {"nom": "DUPONT MARIE"},
    "sav": {
        "numero": "383750",
        "date": "13.05.2026",
        "lieu": "Avignon"
    },
    "montre": {
        "modele": "J12",
        "reference": "H2569",
        "numero_serie": "SS17159",
        "etat": ["RAYURES", "USURE"]
    },
    "interventions_necessaires": [
        {"description": "REVISION", "prix": 830.00},
        ...
    ],
    "interventions_optionnelles": [...],
    "total_ttc": 1046.25
}
```

### `pdf_generator.py`
Génère le PDF final avec les règles métier :
- `docx_to_pdf()` — Convertit DOCX → PDF
- Applique traduction FR
- Arrondit total au multiple de 5 supérieur
- Intègre logo DOUX + CGV

### `docx_generator.py`
Crée le template DOCX avant conversion PDF :
- `build_docx()` — Construit le document
- Mise en page professionnelle
- Gestion des images/logos

### `coefficients.json`
Coefficients appliqués par marque :
```json
{
  "Chanel": 2.10,
  "Tag Heuer": 1.85,
  "Breitling": 1.75,
  "Rolex": 2.0,
  ...
}
```

---

## 📋 Règles métier

### 1️⃣ Traduction automatique en français
- Si le devis source est en anglais, tout est traduit
- Utilise Claude API pour traduction sémantique
- Titres interventions, descriptions, termes techniques

### 2️⃣ Arrondi du total
- Le total TTC final est **toujours arrondi au multiple de 5 supérieur**
- Exemples :
  - 847,50 € → 850 €
  - 323 € → 325 €
  - 1046,25 € → 1050 €

### 3️⃣ Coefficients commerciaux
- Chaque marque a un coefficient par défaut
- L'utilisateur peut modifier le coefficient avant génération
- Appliqué : `Prix TTC = Prix HT × Coefficient × 1.20 TVA`

---

## 🔐 Sécurité

- ✅ Sessions côté serveur (filesystem)
- ✅ Secret key Flask configuré
- ✅ Validation fichiers (extension + taille)
- ✅ Pas de données sensibles en cookies
- ✅ CORS et CSRF tokens (à ajouter si besoin API)

---

## 📦 Déploiement

### Sur Render.com

```bash
git push render main
```

Le site redéploie automatiquement à chaque push.

**Variables d'env Render** :
Via Settings → Environment → Configure Vars

```
ANTHROPIC_API_KEY=sk-...
FLASK_SECRET_KEY=<secret-long>
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=...
MAIL_PASSWORD=...
```

---

## 🧪 Test local

### Route de démo
```
GET /dev-preview
```
Charge des données de démo pour tester le formulaire sans upload.

### Fichiers de test
Dossier `Devis partenaire/` contient des PDFs/emails de test.

---

## 🐛 Troubleshooting

### "Clé API manquante"
→ Vérifiez `ANTHROPIC_API_KEY` dans `.env` ou Render settings

### "L'extraction échoue"
→ Le PDF peut être mal formaté
→ Essayez l'option "Coller un email" à la place

### "Email ne s'envoie pas"
→ Vérifiez `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`
→ Gmail : utilise une [App Password](https://myaccount.google.com/apppasswords), pas le mot de passe direct

### "Le coefficient n'est pas appliqué"
→ Vérifiez `coefficients.json`
→ Assurez-vous que la marque est dans la liste

---

## 📝 Changelog

### v1.0 (Juin 2026)
- ✅ Extraction automatique PDF/EML/MSG
- ✅ Traduction FR via Claude API
- ✅ Génération PDF professionnel
- ✅ Coefficients commerciaux
- ✅ Arrondi automatique total
- ✅ Envoi email
- ✅ Interface web intuitive

---

## 👨‍💼 Support & Contribution

**Bugs / Suggestions** → Ouvrir une issue GitHub  
**Questions** → [Email support à ajouter]  
**Maintenance** → Contact développeur principal

---

**Repository** : https://github.com/CamargAqua/DouxDevis  
**Version** : 1.0  
**Dernière mise à jour** : Juin 2026  
**License** : Propriétaire (DOUX Joaillier)
