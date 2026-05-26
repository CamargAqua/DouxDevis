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

## Backlog
- [ ] Section signature (Yousign) — à ajouter plus tard
- [ ] Tests unitaires pdf_extractor
