# Note de soutenance — chiffres et objections

> À connaître par cœur. Un jury pardonne une fonctionnalité manquante ; il ne
> pardonne pas une hésitation sur un chiffre que tu affiches à l'écran.

## L'histoire en un paragraphe

J'ai construit un tableau de bord d'intelligence financière sur les données ERP
réelles d'un distributeur pharmaceutique. En cours de projet, j'ai audité
l'intégrité de ces données et découvert que **le chiffre d'affaires affiché était
surévalué de 15 809 779 DT, soit 5,44 %**. Deux causes : les avoirs étaient
ajoutés au CA au lieu d'en être retranchés, et 1 324 factures figuraient en
double. J'ai corrigé les deux, étendu la correction à treize autres indicateurs
qu'elles contaminaient, et mis en place un contrôle d'intégrité automatique pour
qu'une telle erreur ne puisse plus passer inaperçue.

C'est le cœur de ta soutenance. **Ne le présente pas comme un incident : c'est ta
contribution la plus solide.**

## Les chiffres à connaître

### Le CA et sa correction

| | |
|---|---|
| CA affiché avant | 290 506 268 DT |
| **CA net corrigé** | **274 696 489 DT** |
| Écart | 15 809 779 DT (**5,44 %**) |
| dont double comptage des avoirs | 14 755 841 DT (93 % de l'erreur) |
| dont factures dupliquées | 1 053 938 DT |

### La volumétrie

| | |
|---|---|
| Factures de vente | 121 763 |
| Avoirs | 5 761 (4,7 % des ventes) |
| Lignes de facture | 336 651 |
| Clients | 1 137 |
| **Historique exploitable** | **2021 → 2026** (92,5 % du CA) |

### La croissance — ton récit business

```
2021   47,6 M DT
2022   47,8 M DT      +0,3 %
2023   49,6 M DT      +3,7 %
2024   53,9 M DT      +8,7 %
2025   62,1 M DT     +15,4 %
```

**+30,5 % en quatre ans, et une accélération nette en 2025.** C'est la lecture
métier à mettre en avant.

### Le contrôle qualité

| | |
|---|---|
| Tests automatisés | **371** |
| Invariants vérifiés à chaque calcul | ~30 |
| Rapprochement des deux exports ERP | **écart 0,08 %** |
| TVA implicite | 3,21 % (cohérent : diagnostic in vitro largement exonéré) |

## Les objections probables

### « Comment savez-vous que vos chiffres sont justes maintenant ? »

**La réponse la plus forte du dossier.** L'ERP exporte les factures à deux
niveaux : les en-têtes et les lignes de détail, dans deux fichiers distincts. Je
somme le HT des deux côtés indépendamment :

```
HT lignes  : 266 012 496 DT
HT entêtes : 266 235 708 DT
écart      : 0,08 %
```

Deux fichiers produits séparément décrivant le même argent concordent à huit
points de base. Si ma correction du signe ou de ma déduplication était fausse,
cet écart exploserait. C'est une vérification qui ne repose sur **aucune
hypothèse interne à mon code**.

Second contrôle : la somme des CA annuels vaut 282 074 410 DT, moins les
7 377 921 DT d'avoirs = **274 696 489 DT**. La décomposition annuelle et le total
global concordent au dinar.

### « Pourquoi personne ne l'avait vu avant ? »

Parce qu'un montant faux ne se voit pas. 290 M et 275 M sont **aussi plausibles
l'un que l'autre** — aucune relecture, aucun coup d'œil au tableau de bord ne
pouvait faire la différence.

L'exemple qui le prouve : le **panier moyen était juste par compensation**.
2 255 DT avant correction, 2 256 DT après. Numérateur et dénominateur étaient
faux dans la même proportion. Aucun contrôle de vraisemblance ne l'aurait
signalé.

Ce qui a révélé l'erreur, c'est d'avoir relu le fichier source **colonne par
colonne**, pas un contrôle automatique.

### « Quelle était l'erreur exactement ? »

`TTC_DEV` est **toujours positif**, y compris sur un avoir. Le sens comptable est
porté par une autre colonne, `MONTANTSIGNE_DEV`. Sommer le TTC ajoutait donc les
avoirs au chiffre d'affaires au lieu de les en retrancher : chaque avoir comptait
**deux fois**.

Pour les doublons : `ENT_ID` est un identifiant de ligne d'export, **unique par
construction**. Contrôler l'unicité sur cette colonne est *structurellement*
incapable de révéler un doublon. La clé métier est `PIECENOFULL`.

### « Combien d'années d'historique ? »

**2021 à 2026.** Cinq ans et demi, dont 2026 partielle.

Les dates brutes vont de janvier 2017 à avril 2026, mais c'est trompeur : 2019 et
2020 sont **absentes de toutes les sources** — ventes, lignes, achats, devis.
Aucun fichier ne contient quoi que ce soit, ce qui exclut un défaut d'export et
désigne une bascule d'ERP ou une reprise de dossier. 2017 et 2018 ne portent que
1 329 factures, **1,1 % du total**, contre 20 333 pour la seule année 2021 : des
résidus de migration.

*Ne dis jamais « 2017–2026 ».* Tu revendiquerais neuf ans là où il y en a cinq et
demi, et un jury qui creuse te prendrait en défaut.

### « Vos modèles ne sont pas déployés. C'est un échec ? »

Non — c'est un protocole de validation qui **fonctionne**. Un projet qui ne refuse
jamais rien n'a pas de critère de refus.

Exemple concret : le garde-fou « AUC > 0,98 ⇒ fuite suspectée » a révélé que
`MODEREGL` **épelle la réponse** — `C060` signifie « chèque 60 jours » et vaut
61 jours de délai médian. Cette seule variable donne 0,93.

Pour le risque de crédit :

| | v2 (données sales) | v3 (données propres) |
|---|---|---|
| GroupKFold par client | 0,8116 | **0,8007** |
| Hors-période | 0,5664 | **0,5973** |
| Meilleure baseline triviale | — | 0,6651 |

Sur un client **réellement nouveau**, le modèle fait moins bien qu'une régression
logistique. Le risque de crédit en cold-start n'est pas prédictible à partir de
ces variables. C'est un résultat, pas un échec.

**Point d'honnêteté à assumer :** j'ai réentraîné ce modèle après la correction
des données. La version précédente s'entraînait sur les avoirs et les doublons —
son refus de déploiement était donc juste **par accident**. La conclusion est
identique, mais elle repose maintenant sur une mesure valide.

### « Vos données de stock sont simulées ? »

Oui, et c'est documenté sans ambiguïté. L'ERP ne contient **aucune** donnée de
stock. La simulation suit une politique (s, S) calibrée sur la demande réelle par
produit ; elle démontre la chaîne de gestion, elle ne mesure rien.

Elle est **reproductible par construction** : chaque produit dérive son propre
flux aléatoire de la graine et de sa clé, ce qui rend le résultat insensible à
l'ordre de parcours.

### « Et les retards de paiement ? »

Limite fondamentale, à énoncer avant qu'on te la trouve : **l'ERP ne contient
aucune date de paiement réelle.** Les colonnes de règlement sont absentes de
l'export, `ETAT` est constante, `SOLDEACOMPTE_DEV` vaut zéro partout.

Tout indicateur de « retard » est donc un **proxy du délai accordé**, jamais un
retard *constaté*. Mon DSO est un DSO **contractuel**. Un test vérifie cette
absence — s'il échoue un jour, ce sera une bonne nouvelle.

### « Quelle est l'accuracy de vos modèles ? »

Réponds avec la **barre à dépasser** dans la même phrase, jamais le chiffre seul :

| Modèle | Accuracy | Classe majoritaire | Balanced accuracy |
|---|---|---|---|
| Décrochage | 93,0 % | 90,8 % | 72,2 % |
| Règle de crédit | 90,4 % | 59,2 % | 91,9 % |
| Érosion de marge | 77,7 % | 78,3 % | 67,6 % |
| Conversion des devis | 77,5 % | 90,6 % | 64,0 % |

« Sur une cible rare, un modèle qui répond toujours *non* atteint déjà 90,8 % d'accuracy. C'est
pour ça que je publie la balanced accuracy et le MCC à côté, et que le déploiement se décide
sur l'AUC hors période face à une référence triviale. » Tableau complet :
`python scripts/tableau_metriques.py`, et §0 bis du rapport.

### « Vos agents calculent juste des formules ? »

Non : **les douze modules de gestion du registre sont consommés par les agents**, via une
passerelle unique qui consulte le registre ; le treizième, la lecture de factures (LayoutLMv3),
est consommé par la chaîne OCR. Recouvrement → règle de crédit ; Trésorerie → échéancier ;
Risque client → décrochage × segmentation ; Commercial → conversion des devis, érosion de
marge, recommandation ; Stock & Approvisionnement → demande, demande par référence (la médiane
des 12 derniers mois, qui a battu LightGBM, XGBoost, CatBoost, N-HiTS et DeepAR au test), et
réappro / fin de vie refusés (il le dit : cet agent est déterministe et statistique) ; le volet
fiabilité → registre, accuracy, dérive. Détail : `docs/CRISP_DM_DEMANDE_REFERENCE.md`.
Chaque constat affiche le modèle qui l'a produit et sa fiabilité mesurée. Un test échoue si un
module du registre n'atteint aucun agent métier, ou si un agent importe un modèle sans passer
par le registre.

### « Où est le deep learning ? »

Recommandation de produits par un réseau **Wide & Deep** (PyTorch, embeddings produit /
famille / type d'établissement). Walk-forward sur 3 origines, 1 472 évaluations client :
NDCG@10 **0,350**, Recall@10 **0,510**, HitRate@10 **72 %** — meilleur que toutes les autres
méthodes. **Mais** son avance sur LightGBM (+0,006, IC95 [−0,004 ; +0,016]) n'est pas
significative : par parcimonie, LightGBM est servi et le réseau reste challenger, réévalué à
chaque réentraînement. « J'ai appliqué au deep learning la même règle qu'au gradient boosting
du décrochage : un modèle plus complexe doit prouver qu'il fait mieux. » Détail :
`docs/DEEP_LEARNING.md`.

## Ce que tu ne dois PAS affirmer

| Ne dis pas | Dis plutôt |
|---|---|
| « Mes données sont sans erreur » | « J'ai une méthode pour détecter les erreurs, et elle en a trouvé une de 15,8 M DT » |
| « 2017–2026 » | « Historique exploitable 2021–2026 » |
| « Le modèle prédit le risque client » | « Sur les clients connus, une règle déterministe suffit ; en cold-start, aucune variable disponible n'est prédictive » |
| « Je mesure les retards de paiement » | « Je mesure le délai accordé — l'ERP n'a pas les dates de paiement » |
| « Mon modèle a 93 % d'accuracy » | « 93 % contre 90,8 % pour la classe majoritaire ; balanced accuracy 72 % » |
| « Le deep learning est en production » | « Le Wide & Deep est le meilleur mesuré, mais pas significativement : LightGBM est servi par parcimonie » |

## Les limites de mon contrôle — à assumer d'emblée

Un contrôle d'intégrité vérifie la **cohérence**. Il ne peut pas attraper :

- une **erreur systématique** qui préserve les égalités — si un coefficient était
  appliqué uniformément, `CA = ventes − avoirs` resterait vrai ;
- une **erreur d'interprétation** d'un champ dont la sémantique est mal comprise —
  c'est exactement ce qui est arrivé avec `MONTANTSIGNE_DEV`.

C'est pourquoi j'ai ajouté un second niveau, les **ancrages externes** : `TTC ≥ HT`
sur chaque pièce (contrainte fiscale, pas une moyenne), le ratio TVA dans une
bande plausible, et le rapprochement des deux exports. Ce second niveau manquait,
et son absence explique pourquoi l'erreur a survécu si longtemps.

Dire cela toi-même, avant qu'on te le demande, vaut mieux que de le concéder sous
la question.

## Pour aller chercher les détails

| Sujet | Fichier |
|---|---|
| Sémantique vérifiée de chaque colonne | `docs/SEMANTIQUE_COLONNES.md` |
| Formules de chaque indicateur | `docs/KPI_FORMULES.md` |
| Ce que l'ERP ne contient pas | `docs/DONNEES_MANQUANTES.md` |
| Reproduire l'audit du CA | `scripts/audit_ca_corrige.py` |
| Reproduire l'audit des autres sources | `scripts/audit_toutes_sources.py` |
| Diagnostic du trou temporel | `scripts/audit_trou_temporel.py` |
| Contrôle d'intégrité | `ml_engine/analytics/data_quality.py` |
| Tests de cohérence financière | `tests/test_coherence_financiere.py` |
| Tests de sémantique ERP | `tests/test_semantique_erp.py` |
