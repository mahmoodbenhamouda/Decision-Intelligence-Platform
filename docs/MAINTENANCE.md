# Maintenir la plateforme

> Ce document s'adresse à la personne qui reprendra la plateforme. Aucune
> connaissance en programmation n'est nécessaire : tout tient en deux commandes
> et une règle de lecture.

---

## Pourquoi c'est nécessaire

Les modèles apprennent sur le passé. Quand la clientèle change, que les délais de
paiement s'allongent ou qu'une gamme de produits est remplacée, ils continuent de
répondre **avec le même aplomb** — mais leurs réponses se dégradent.

Cette dégradation est **silencieuse** : rien ne casse, aucun message d'erreur
n'apparaît, les chiffres continuent de s'afficher. C'est précisément ce qui la
rend dangereuse. La maintenance ne sert pas à réparer des pannes, elle sert à
détecter ce qui ne se voit pas.

---

## Les deux commandes

Ouvrir un terminal dans le dossier du projet, puis :

### Chaque semaine — maintenance complète

```
.venv\Scripts\python.exe scripts\maintenance.py
```

Reconstruit l'entrepôt, vérifie l'intégrité comptable, réentraîne les modèles,
surveille la dérive et recalcule les montants. **Compter dix à quinze minutes.**

### Quand vous voulez — vérification rapide

```
.venv\Scripts\python.exe scripts\maintenance.py --verifier-seulement
```

Ne réentraîne rien : contrôle simplement que tout est cohérent. **Environ trois
minutes.**

---

## Lire le résultat

Le script se termine par l'un de ces trois messages.

### « Tout est à jour. Rien ne demande votre attention. »

Rien à faire. C'est volontaire : le script **ne parle que lorsqu'il a quelque
chose à dire**. Un rapport qui énumère chaque semaine tout ce qui va bien finit
par ne plus être lu — et la première vraie alerte y passe inaperçue.

### « À VÉRIFIER »

La plateforme fonctionne, mais quelque chose a changé. Les chiffres restent
affichés. Voir le tableau ci-dessous.

### « PANNES »

Une étape n'a pas pu s'exécuter, ou un contrôle comptable est en erreur. **Les
chiffres affichés peuvent être faux.** Prévenir un informaticien avant de prendre
une décision sur la base du tableau de bord.

---

## Que faire selon le message

| Message | Ce que ça signifie | Quoi faire |
|---|---|---|
| **Contrôle d'intégrité en erreur** | Un chiffre publié est incohérent — chiffre d'affaires, marge, écarts de totaux | Ne pas utiliser le tableau de bord tant que ce n'est pas résolu. Faire appel à un informaticien. |
| **Anomalie d'intégrité signalée** | Des données douteuses existent, sans invalider les totaux (ex. factures dont l'échéance précède l'émission) | À signaler au service qui saisit les factures. Ce n'est pas urgent, mais ça se corrige à la source. |
| **Dérive détectée** | Le comportement des clients ne ressemble plus à celui sur lequel les modèles ont appris | Relancer la **maintenance complète**. Si l'alerte persiste après réentraînement, le changement est réel : les prévisions deviennent moins fiables. |
| **Modèle de décrochage non servi** | Le modèle n'atteint plus son niveau de fiabilité | La liste de relance disparaît du tableau de bord. **C'est voulu** : mieux vaut aucune liste qu'une liste fausse. Faire appel à un informaticien. |
| **Typologie non stable** | Les groupes de clients ne se distinguent plus assez | Le panneau « Types de clients » disparaît. Même principe. |
| **Une étape n'a pas pu s'exécuter** | Problème technique — fichier manquant, base inaccessible | Vérifier que les exports de l'ERP sont bien dans `data_pfe/`. |

---

## Automatiser l'exécution

Pour que la maintenance tourne sans que personne y pense, dans une invite de
commandes **administrateur** :

```
schtasks /create /tn "Overlyne - maintenance" ^
  /tr "C:\chemin\vers\.venv\Scripts\python.exe C:\chemin\vers\scripts\maintenance.py" ^
  /sc weekly /d MON /st 06:00
```

En remplaçant `C:\chemin\vers` par le dossier réel du projet. La tâche s'exécutera
chaque lundi à 6 h.

Pour vérifier qu'elle est bien créée :

```
schtasks /query /tn "Overlyne - maintenance"
```

---

## Quand les données changent

**Nouvel export de l'ERP.** Remplacer les fichiers dans `data_pfe/`, puis lancer
la maintenance complète. Rien d'autre — **les modèles se réentraînent seuls**.

### Comment la plateforme sait que les données ont changé

Chaque modèle retient une **empreinte** des données sur lesquelles il a appris :
nombre de factures, période couverte, montants totaux. Avant chaque cycle, cette
empreinte est comparée à celle des données présentes.

- Empreintes identiques → aucun réentraînement, quelques secondes suffisent.
- Empreintes différentes → seuls les modèles concernés sont réentraînés.

L'empreinte porte sur le **contenu**, pas sur la date des fichiers : recopier un
export sans le modifier ne déclenche rien.

Pour savoir où en sont les modèles sans rien lancer de lourd :

```
.venv\Scripts\python.exe -m ml_engine.synchro --verifier
```

### Si un modèle se dégrade après réentraînement

Les performances d'avant et d'après sont comparées automatiquement. Trois
situations, toutes écrites dans le rapport :

| Ce qui s'affiche | Signification |
|---|---|
| **Aucune dégradation détectée** | Le modèle est au moins aussi bon qu'avant. |
| **DÉGRADATION** | La performance a baissé de plus de 10 %. Les nouvelles données sont moins prévisibles — à surveiller au cycle suivant. |
| **REFUSÉ** | Le modèle n'atteint plus son niveau minimal : il a été **retiré du tableau de bord**. |

Le dernier cas mérite une explication, car il surprend : le module concerné
cesse simplement d'apparaître dans l'application. **C'est voulu.** Mieux vaut une
absence qu'une réponse fausse — un directeur qui ne voit plus la liste de relance
le remarquera ; un directeur à qui l'on sert une liste erronée ne le saura jamais.

**Nouvelle colonne disponible.** Trois colonnes manquent aujourd'hui et
limiteraient beaucoup moins la plateforme si elles étaient exportées :

- **la date de règlement des factures** — permettrait de savoir qui a réellement
  payé, au lieu d'en déduire une probabilité ;
- **l'inventaire physique** — permettrait de connaître le stock réel, au lieu de
  le reconstruire à partir des achats et des ventes ;
- **la famille de chaque produit** — permettrait de distinguer avec certitude un
  réactif (qui périme), un automate (qui s'amortit) et une pièce détachée (qui se
  conserve). Aujourd'hui cette distinction se fait sur les mots du libellé.

Si l'une d'elles devient disponible, le signaler : ce sont les trois améliorations
qui changeraient le plus la valeur de l'outil.

---

## Deux fichiers à faire remplir, une fois

Ils ne demandent aucune compétence technique, et ce sont les deux seules choses
que le logiciel ne peut pas produire seul.

**1. `reports/nomenclature_a_valider.csv`** — la liste des produits en stock, avec
la catégorie que la plateforme a déduite de leur nom. Les lignes marquées
`DÉFAUT` sont celles où aucun mot n'a été reconnu : ce sont les seules à corriger
en priorité. Le fichier est trié par valeur, donc les premières lignes sont les
plus rentables à vérifier — trente lignes suffisent à améliorer nettement la
fiabilité des pertes annoncées.

**2. `reports/validation_metier.csv`** — produit par
`python scripts/generer_grille_validation.py`. Chaque ligne décrit un cas réel et
ce que la plateforme en affirme ; il reste à écrire si c'est vrai ou faux.

La **dernière section** de ce second fichier est la plus importante, et la seule
entièrement vide : elle demande quels clients, créances ou produits inquiétants
**n'apparaissent pas** dans les listes. Ce que l'outil signale à tort se voit ;
ce qu'il a manqué ne se voit pas — et aucune mesure interne ne peut le révéler.

---

## Ce que la maintenance ne fait pas

Elle vérifie que les **données** n'ont pas changé de nature. Elle ne vérifie pas
que les **prédictions** étaient justes — cela demanderait de savoir, trois mois
plus tard, quels clients ont effectivement cessé de commander.

Cette vérification-là ne peut être faite que par une personne : prendre la liste
de relance d'il y a trois mois et regarder combien de ces clients sont
effectivement partis. **C'est le meilleur contrôle qui existe, et il ne coûte
qu'une heure par trimestre.** La grille de `docs/VALIDATION_METIER.md` est prévue
pour cela.
