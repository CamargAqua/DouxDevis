# DouxDevis — Todo

## Session 2026-05-20

- [x] Fix coefficient auto-update sur brand pré-sélectionnée (setTimeout)
- [x] Supprimer section signature de done.html
- [x] Brand recognition case-insensitive
- [x] Générer 3-5 devis partenaires de test (INCL, OFFERT, options)
- [x] Répartition delta coefficient sur lignes nécessaires
- [x] Omega : extraction colonne HT dans pdf_extractor.py
- [x] Omega : coefficient appliqué sur HT, résultat TTC sans ×1.20 supplémentaire
- [x] Frais de refus par marque dans le footer du docx
- [x] Download logos marques manquantes
- [x] Fix frais de refus — placement dans cellule REFUS
- [x] Fix overflow table options docx (14cm → 13.5cm)


## Session 2026-05-22

- [x] Totaux conditionnels : "TOTAL TTC EN EURO" si pas d'options, "HORS OPTIONS" sinon
- [x] Support .eml en upload (en plus de .pdf)
- [x] Extraction emails : corps texte + PDF joint si présent
- [x] Détection HT dans emails → coeff_base="ht" automatique
- [x] Marques joaillerie ajoutées : Pomellato, Fred, Ginette NY, Chopard, Van Cleef, Boucheron, Chaumet, Mauboussin, Dior Joaillerie
- [x] Prompt étendu bijoux : champ montre accepte bagues, pendentifs, etc.
- [x] Fix service_complet_description : sous-points affichés uniquement pour RÉVISION/SERVICE/OVERHAUL

## Session 2026-05-26

- [x] Règle HT universelle : coefficients.json → tous en base "ht"
- [x] form.html : coeff-base-hidden default → "ht"
- [x] pdf_extractor.py : prompt universel HT (toutes variantes FR/EN/DE)
- [x] pdf_extractor.py : _clean() force coeff_base="ht" pour toutes les marques
- [x] app.py : _form_to_data → prix_client = prix_input, prix = prix_input / coeff (HT)

## Session 2026-06-02

- [x] Traduction FR : devis source en anglais → champs texte traduits en français (prompt extraction)
- [x] Arrondi total au multiple de 5 supérieur (ceiling 5) — ex 847→850, 323→325
- [x] Ajuster la dernière ligne nécessaire pour que la somme = total arrondi (app.py _form_to_data)
- [x] Ajuster la dernière option pour que "total avec options" soit aussi arrondi à 5
- [x] form.html : afficher le total client TTC arrondi dans la preview
- [x] Vérifié via test _form_to_data : 847→850 (lignes somment), grand total 976→980

## Session 2026-06-06

- [x] Full site audit (quick mode) — douxdevis.onrender.com
- [x] P0 fix : `/dev-preview` bloquée en production (`if not app.debug: abort(404)`)
- [x] P0 fix : `FLASK_SECRET_KEY` — warning CRITICAL si absente + clé fixe fournie pour Render
- [x] Suppression section feedback fidélité (done.html + JS)
- [x] Suppression accès stats (bouton, modal, routes /stats + /stats-auth, template stats.html)
- [x] Suppression route `/feedback` + `_supabase_client()` + `FEEDBACK_FILE`
- [x] Nettoyage requirements.txt : retrait de `supabase`

## Session 2026-06-09

- [x] Créer GUIDE_UTILISATEUR.md — documentation client-friendly (workflow, règles métier, FAQ, contact)
- [x] Créer README.md — documentation technique (stack, installation, déploiement, structure code, troubleshooting)

## Backlog
- [ ] Section signature (Yousign) — à ajouter plus tard
- [ ] Tests unitaires pdf_extractor
- [ ] Screenshots intégrées au GUIDE_UTILISATEUR.md
