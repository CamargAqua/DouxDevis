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
