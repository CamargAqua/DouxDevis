# 📖 Guide Utilisateur — DouxDevis

Bienvenue dans **DouxDevis**, l'outil de génération automatique de devis pour DOUX Joaillier.

---

## Vue d'ensemble

DouxDevis est un outil simple et intelligent qui **convertit les devis reçus des partenaires en devis clients professionnels**.

### Ce que DouxDevis fait :
✅ **Extrait automatiquement** les données du devis partenaire (PDF, email, etc.)  
✅ **Traduit en français** si le devis d'origine est en anglais  
✅ **Applique votre marge commerciale** via des coefficients  
✅ **Arrondit les montants** au multiple de 5 supérieur pour une présentation professionnelle  
✅ **Génère un devis final** prêt à envoyer au client  

---

## Workflow complet

### **Étape 1️⃣ : Importer le devis du partenaire**

Allez sur la page d'accueil et importez le devis du partenaire. Vous avez deux options :

**Option A - Uploader un fichier PDF**
- Cliquez sur "📄 Fichier" ou glissez-déposez un fichier
- Formats acceptés : PDF, email (.eml), message Outlook (.msg)
- Taille max : 25 Mo

**Option B - Coller un email**
- Cliquez sur "✉️ Coller un email"
- Collez le contenu de l'email directement

Ensuite, cliquez sur **"Extraire les informations"** et attendez 10-20 secondes.

---

### **Étape 2️⃣ : Vérifier et ajuster les données**

L'outil vous affiche une page "**Vérification & ajustement**" où vous pouvez revoir et modifier toutes les informations extraites.

#### **En-tête du devis**
- **Marque partenaire** : Sélectionnez la marque (Chanel, Tag Heuer, Breitling, Rolex, Autre)
- **Numéro SAV** : Le numéro de réparation
- **Date** : Date du devis (auto-remplie par défaut)
- **Lieu** : Ville où s'effectue la réparation (Avignon, Nîmes, etc.)
- **Nom du client** : Nom de qui recevra le devis

#### **Informations de la montre**
- **Modèle** : Modèle de la montre (ex: J12, Datejust)
- **Référence** : Référence technique
- **N° de série** : Numéro de série de la montre
- **État constaté** : Description de l'état (rayures, usure, etc.)
- **Photo** (facultatif) : Vous pouvez ajouter une photo

#### **Travail nécessaire**
- Liste de toutes les **interventions obligatoires**
- Chaque intervention a :
  - Un intitulé (ex: "REVISION COMPLETE")
  - Un prix (en €)
  - Une option : Normal / INCL (inclus) / OFFERT (gratuit)

Vous pouvez :
- ✏️ Modifier les prix
- ➕ Ajouter une intervention
- ❌ Supprimer une intervention

#### **Tarification — Les coefficients**

C'est ici que **vous appliquez votre marge commerciale**.

- Chaque marque a un **coefficient par défaut** (ex: Chanel = ×2,10)
- Le coefficient est appliqué au prix partenaire HT
- Vous pouvez :
  - Utiliser un coefficient rapide (×1,30 à ×1,80)
  - Entrer un coefficient **personnalisé**

**Exemple :**
```
Prix partenaire HT : 1 000 €
Coefficient appliqué : ×2,10
Prix client TTC : 2 200 €
Marge : +1 200 €
```

#### **Travail optionnel**

- Liste des **services optionnels** proposés au client
- Chaque option a un prix
- Vous pouvez marquer une option comme OFFERT si vous le souhaitez

---

### **Étape 3️⃣ : Générer le devis final**

Une fois vérifié et ajusté, cliquez sur **"Générer"** (bouton en bas à droite).

DouxDevis va :
1. **Traduire en français** tout contenu anglais
2. **Arrondir le total** au multiple de 5 supérieur (voir exemple ci-dessous)
3. **Générer un PDF** professionnel au format DOUX
4. **Envoyer le PDF par email** (ou vous permettre de le télécharger)

**Exemple d'arrondi appliqué :**
- Total calculé : 2 217,50 € → **Arrondi à 2 220 €**
- Total calculé : 1 846 € → **Arrondi à 1 850 €**
- Total calculé : 923,25 € → **Arrondi à 925 €**

---

## Règles métier principales

### 🇫🇷 Traduction automatique en français

Si vous importez un devis en **anglais** (ex: PDF d'un fournisseur international), l'outil traduit automatiquement :
- Les titres des interventions
- Les descriptions
- Les termes techniques

Le devis final est **100% en français**.

### 💶 Arrondi du total au multiple de 5

Le montant final est **toujours arrondi au multiple de 5 supérieur** pour une présentation plus propre :

| Montant calculé | Montant final |
|---|---|
| 847,50 € | **850 €** |
| 323 € | **325 €** |
| 1 046,25 € | **1 050 €** |
| 2 217,80 € | **2 220 €** |

---

## FAQ — Questions fréquentes

### ❓ **Que se passe-t-il si l'extraction échoue ?**
L'outil s'efforce d'extraire les données automatiquement, mais si le PDF est très complexe ou mal formaté, l'extraction peut être incomplète. Dans ce cas, vous pouvez remplir manuellement la page "Vérification & ajustement".

### ❓ **Puis-je modifier le coefficient après la génération ?**
Non, une fois généré. Si vous avez besoin de changer le coefficient, revenir à la page "Vérification & ajustement", modifiez le coefficient, et régénérez.

### ❓ **Le devis final est-il signable électroniquement ?**
Oui, le PDF généré peut être envoyé au client qui peut le signer électroniquement via un lien fourni.

### ❓ **Puis-je ajouter mon logo / mes conditions générales ?**
Le devis généré inclut déjà le logo DOUX et les conditions générales. Si vous avez besoin de modifications spéciales, contactez l'équipe technique.

### ❓ **Quels formats de fichier sont acceptés ?**
✅ **PDF** — Les devis partenaires en PDF  
✅ **Email (.eml)** — Les emails exportés au format .eml  
✅ **Message Outlook (.msg)** — Les messages Outlook exportés  

**Taille max : 25 Mo**

### ❓ **L'outil fonctionne-t-il en offline ?**
Non, DouxDevis nécessite une connexion Internet (pour l'extraction et la traduction).

---

## Support & Assistance

### 📧 Vous avez une question ?
Contactez l'équipe technique : [email de support à insérer]

### 🐛 Vous avez trouvé un bug ?
Décrivez-le détaillé et envoyez une capture d'écran à : [email de support à insérer]

### 💡 Vous avez une suggestion d'amélioration ?
Nous aimons vos retours ! Écrivez-nous : [email de support à insérer]

---

## Conseils & bonnes pratiques

✅ **Avant d'importer**, vérifiez que le devis partenaire est lisible et complet  
✅ **Vérifiez deux fois** le coefficient avant de générer  
✅ **Testez avec un client moins important** avant de déployer  
✅ **Gardez trace** des coefficients utilisés pour chaque marque  
✅ **Mettez à jour les coefficients** régulièrement selon votre stratégie commerciale  

---

**Version:** 1.0  
**Dernière mise à jour:** Juin 2026  
**Support:** [email à insérer]
