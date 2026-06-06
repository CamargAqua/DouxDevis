# Lessons — DouxDevis

## 2026-05-21 — Prix partenaire affiché au lieu de prix client dans PDF
**Erreur :** `pdf_generator.py` lisait `line.get("prix")` (prix partenaire recalculé = prix_client / coeff) au lieu de `line.get("prix_client")` pour les lignes du devis.
**Conséquence :** Le PDF affichait les prix partenaires sur les lignes, mais le total affichait les prix client. Incohérence visuelle.
**Règle :** Toujours lire `prix_client` EN PRIORITÉ dans le PDF. Fallback sur `prix` seulement si `prix_client` n'existe pas.
```python
# ❌ Avant
prix_val = line.get("prix", 0)

# ✅ Après
prix_val = line.get("prix_client") if "prix_client" in line else line.get("prix", 0)
```

## 2026-05-21 — Coefficient non appliqué aux options
**Erreur :** `form.html` — `applyCoeffToLines()` ciblait uniquement `#nec-lines`, ignorant `#opt-lines`. Les options ne recevaient jamais le coefficient du formulaire JS.
**Conséquence :** Les options conservaient le prix partenaire brut, sans coefficient. Incohérence dans le calcul du total client.
**Règle :** Tout ce qui est un "prix utilisateur" (necessaires OU options) DOIT passer par `applyCoeffToLines()`. Utiliser une boucle `.forEach()` sur un array de sélecteurs.
```javascript
// ❌ Avant
document.querySelectorAll('#nec-lines .intervention-line').forEach(...)

// ✅ Après
['#nec-lines', '#opt-lines'].forEach(selector => {
  document.querySelectorAll(selector + ' .intervention-line').forEach(...)
});
```
**Aussi:** `app.py` ligne 460+ — ajouter le même bloc de traitement coefficient aux options qu'aux nécessaires.

## 2026-05-20 — Coefficient init sur brand pré-sélectionnée
**Erreur :** `selectMarque` override défini après le code d'init, donc le coefficient ne se mettait pas à jour au chargement.
**Règle :** Utiliser `setTimeout(() => fn(), 0)` pour différer un appel qui dépend d'un override défini plus bas dans le script.

## 2026-05-20 — Omega ×1.20 double-appliqué
**Erreur :** Ajout d'un ×1.20 HT→TTC en plus du coefficient Omega, alors que le coefficient Omega *inclut déjà* la conversion TVA (`prix_HT × 1.6 = prix_TTC_client`).
**Règle :** Pour Omega, `prix_client = prix_HT_fournisseur × coeff` — pas de TVA supplémentaire. Le coefficient est un multiplicateur direct HT→TTC.

## 2026-05-20 — Overflow table options docx
**Erreur :** Colonnes 14cm+4cm=18cm = largeur utile exacte (21cm − 2×1.5cm marges). Les bordures de table font dépasser le contenu → les prix s'affichent dans la colonne description.
**Règle :** Laisser une marge de sécurité de 0.5cm minimum. Utiliser 13.5cm+4cm=17.5cm pour les tables de travail.

## 2026-05-20 — Frais de refus — placement
**Erreur :** Phrase frais de refus placée avant le tableau footer ET dans la cellule REFUS, créant un doublon.
**Règle :** Placer la phrase uniquement dans la cellule REFUS via `cell.add_paragraph()`, jamais en dehors du tableau.


## 2026-05-22 — service_complet_description affiché sur toute première intervention
**Erreur :** `pdf_generator.py` et `docx_generator.py` affichaient les sous-points `service_complet_description` sous la première intervention quelle qu'elle soit. Pour un devis Chopard avec "ECHANGE DU FERMOIR" en premier, les sous-points du POLISSAGE apparaissaient sous l'échange du fermoir.
**Règle :** Afficher `service_complet_description` uniquement si la description contient SERVICE, RÉVISION, OVERHAUL ou ENTRETIEN. Un échange de fermoir ou une réparation de pendentif ne doit jamais avoir de sous-points.

## 2026-05-26 — Règle HT universelle pour toutes les marques
**Erreur antérieure :** Le coeff_base="ht" était uniquement forcé pour Omega dans `_clean()`. Toutes les autres marques restaient en "ttc", causant une double-conversion (coeff × HT × 1.20).
**Règle :** `_clean()` dans `pdf_extractor.py` doit toujours poser `coeff_base = "ht"` sans condition de marque. Le prompt force l'extraction HT universellement (colonnes FR/EN/DE). `coefficients.json` : tous les `"base"` à `"ht"`. `form.html` : default `coeff-base-hidden` à `"ht"`.
**Rappel coefficient :** `prix_client = prix_HT_partenaire × coeff` — jamais de ×1.20 supplémentaire.

## 2026-06-06 — replace_between avec ancres f5 (lignes vides) = ambigu
**Erreur :** mcp__hex-line__edit_file avec replace_between ciblant des ancres `f5.xxx` (lignes vides) après d'autres édits dans la même passe → les ancres numériques sont obsolètes après les premiers édits, ce qui a supprimé les décorateurs `@app.route` et la def de `_ceil5`.
**Règle :** Ne jamais empiler plusieurs replace_between ciblant des `f5` (blank lines) dans une seule passe. Faire des passes séparées, ou cibler des ancres de lignes non-vides (contenu unique). Vérifier après chaque passe sur les zones adjacentes.

## 2026-06-06 — Supprimer stats/feedback : retirer aussi supabase de requirements.txt
**Règle :** Quand on supprime des routes liées à Supabase (feedback, stats), penser à retirer la dépendance `supabase` de requirements.txt — sinon Render installe un package inutile à chaque déploiement.

## 2026-05-22 — Emails : prix HT vs TTC
**Règle :** Les partenaires envoient leurs prix en HT dans les emails (prix revendeur). Détecter `\d HT` dans le corps → poser `coeff_base="ht"`. Le coefficient DOUX convertit directement HT → prix client TTC, sans ajouter la TVA en plus.
**Attention :** Le prix public TTC entre parenthèses (ex: "prix public recommandé 530€TTC") est à ignorer complètement.
