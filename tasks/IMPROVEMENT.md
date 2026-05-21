# Système d'Auto-Amélioration — DouxDevis

## Comment Claude s'améliore

### 1. **Capture des erreurs** (lessons.md)
Chaque bug trouvé est documenté:
```markdown
## [DATE] — Titre court du bug
**Erreur:** Ce qui s'est passé
**Conséquence:** Impact observé
**Règle:** Ce qu'il faut faire à la place
[Code exemple]
```

### 2. **Relecture au démarrage**
À chaque session, Claude lit `tasks/lessons.md` automatiquement (voir CLAUDE.md global).
→ Les règles apprises deviennent des contraintes pour les futurs travaux.

### 3. **Validation des fixes**
Chaque fois qu'on corrige un bug documenté:
- Écrire la correction
- Tester (webapp-testing, codebase-audit)
- Documenter la règle
- Committer avec `fix: ` prefix

### 4. **Pattern Recognition**
Après 3-4 bugs du même type → créer une **règle générale** dans lessons.md.

Exemple:
```markdown
## Pattern: Affichage de données mal choisies
**Règle générale:** Avant de lire une valeur dans un dictionnaire/object:
1. Identifier ce qu'on affiche (partenaire? client? calculé?)
2. Vérifier la source de la donnée (où elle vient)
3. Chercher la version "finale" (après transformations: coeff, tva, etc.)
4. Lire EN PRIORITÉ la version finale, fallback sur brut
```

---

## Métriques d'amélioration

| Métrique | Baseline | Objectif |
|----------|----------|----------|
| Bugs par feature | 2-3 | < 1 |
| Temps fix | 15-30m | < 10m |
| Lessons.md entries | 6 | +1 per feature |
| Test coverage | 80% | > 90% |

---

## Checklist avant chaque feature nouvelle

- [ ] Lire `tasks/lessons.md` en entier
- [ ] Identifier quelle règle s'applique à cette feature
- [ ] Écrire les tests AVANT le code (TDD)
- [ ] Après première déploiement: chercher les bugs inévitables
- [ ] Documenter la leçon apprise
- [ ] Ajouter un test pour que le bug ne se reproduise pas

---

## Boucle de feedback

```
Feature Idea
    ↓
Read lessons.md → apply patterns
    ↓
Implement + Test
    ↓
Find bug? → Document in lessons.md
    ↓
Fix + Retest
    ↓
Ship → lessons updated
    ↓
Next session: Claude lit lessons.md + applique
```

---

## Exemples de règles devenues automatiques

✅ **Règle Omega HT:** Coefficient Omega inclut déjà HT→TTC, pas de TVA supplémentaire
✅ **Règle Table width:** Laisser 0.5cm marge de sécurité (14cm+4cm max = 17.5cm utilisé)
✅ **Règle Frais refus:** Placer le texte DANS la cellule, pas avant le tableau

Ces règles sont maintenant relues au démarrage et Claude les applique automatiquement aux nouvelles features.

---

## Comment accélérer l'apprentissage?

1. **Plus de tests** → plus d'erreurs détectées tôt
2. **Codebase audit régulier** → détecter la dette technique
3. **Documente les near-misses** → les bugs évités de justesse
4. **Review antigas code** → identifier les patterns d'erreur récurrents

