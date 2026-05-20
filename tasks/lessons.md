# Lessons — DouxDevis

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
