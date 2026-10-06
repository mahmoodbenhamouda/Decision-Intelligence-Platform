# Demande par référence — méthodologie CRISP-DM

| | |
|---|---|
| Question métier | *Combien de chaque réactif vais-je vendre dans 1, 2 et 3 mois — donc combien commander ?* |
| Module servi | `ml_engine/forecasting/demande_reference.py` |
| Étude complète | `evaluation_demande/comparer_modeles.py` → `reports/demande_reference_comparaison.json` |
| Rapport lu par le registre | `reports/demande_reference_metrics.json` |
| Consommé par | l'agent **Stock & Approvisionnement** (volet stock), via la passerelle |

Ce document suit les six phases de CRISP-DM dans l'ordre. Les chiffres cités sont
ceux des rapports ; ils se régénèrent avec les commandes indiquées en fin de page.

---

## Phase 1 — Compréhension du métier

### Le besoin

L'entreprise dont l'ERP alimente le projet — un client d'Overlyne — distribue
des réactifs de diagnostic à des hôpitaux publics, des cliniques et des
laboratoires. Deux erreurs coûtent :

* **commander trop peu** : un laboratoire sans réactif arrête une série
  d'analyses, et se tourne vers un concurrent ;
* **commander trop** : un réactif vit 12 à 24 mois ; ce qui n'est pas vendu à
  temps est une perte sèche.

La plateforme savait déjà prévoir le **volume total** du mois prochain
(`demande_hybride`, MAPE 15,71 %). Son propre rapport en dit la limite : *« le
volume agrégé n'est pas un plan de réapprovisionnement, il ne dit rien de la
répartition par référence »*. On ne commande pas 8 290 articles ; on commande 40
kits d'un test et 12 d'un autre.

### Ce qui avait déjà été tenté — et pourquoi cela avait échoué

Un premier modèle par produit existe (`ml_engine/models/demand_forecast.py`,
`docs/CRISP_DM_STOCK.md`) : LightGBM, XGBoost, HistGB et Ridge sur 328 produits.
Ils gagnaient 5 à 6 % en validation croisée, puis **perdaient** sur un bloc final
de six mois ; le naïf saisonnier est servi. Trois causes, qui dictent le
protocole de cette étude :

| Cause de l'échec précédent | Ce que fait cette étude |
|---|---|
| Un seul bloc de test de 6 mois : un verdict à la merci d'une période | **18 origines mensuelles** en walk-forward |
| Les modèles apprenaient l'écart à un socle choisi en validation (moyenne mobile), et héritaient de sa faiblesse quand le saisonnier a gagné sur le test | Modèles **globaux** qui apprennent la demande elle-même, saisonnalité en variable |
| Ni méthodes de demande intermittente, ni test de significativité, décision hors registre | Croston, SBA, TSB ; **IC95 bootstrap** apparié ; entrée au **registre central** |

### Objectif de fouille de données et critère de succès

Prévoir, pour chaque référence régulière, la quantité vendue à 1, 2 et 3 mois, et
son cumul sur 3 mois (la quantité à commander), avec une borne haute pour le
stock de sécurité.

> **Critère de déploiement, posé avant toute modélisation.** Le meilleur candidat
> — choisi sur la validation seule — n'est servi que s'il bat la meilleure règle
> simple, elle aussi choisie sur la validation, **d'au moins 2 points de WAPE à
> 1 mois sur le test**, avec un intervalle de confiance à 95 % de l'écart
> **entièrement positif** (bootstrap par rééchantillonnage des références).
> Sinon la règle simple est servie, et le rapport dit pourquoi.

Le seuil de 2 points a le même rôle que les 0,02 d'AUC exigés des classifieurs
du registre : en dessous, un modèle n'apporte rien qu'une règle d'une ligne ne
fasse déjà, et il coûte en maintenance et en explicabilité.

---

## Phase 2 — Compréhension des données

### Source

Lignes de facture réelles de l'entrepôt (`sales_lines`), agrégées par
référence × client × mois ; noms de clients (`dim_client`) ; achats et positions
reconstruits des factures (`stock_position_mensuelle`) ; devis par client et par
mois (`devis`). Aucune donnée simulée n'entre dans l'étude.

### Constats de l'exploration

| Constat | Mesure | Conséquence |
|---|---|---|
| Rupture d'historique | ventes 2017-2018, puis rien jusqu'à 2020-12 (bascule d'ERP) | période exploitable **2021-01 → 2026-03**, comme `demande_hybride` |
| Dernier mois incomplet | export arrêté au 29/04/2026 | avril 2026 écarté |
| Familles | REACTIF = 90,1 % du CA, 830 références ; services, SAV, formation et équipements à part | périmètre **REACTIF** : on ne réapprovisionne ni un service ni un automate sur prévision |
| Retours | 7 630 lignes négatives ; 158 mois-référence où les retours dépassent les ventes | demande nette **ramenée à 0** quand elle serait négative |
| Activité | ≥ 12 mois actifs : 410 références = 98,6 % du volume ; ≥ 24 mois : 295 = 96,1 % | éligibilité par un seuil d'activité, décidé à l'origine |
| Concentration | 20 références = 48,9 % du volume ; 100 = 85,9 % | la WAPE, pondérée par le volume, reflète ce qui compte en achats |
| Intermittence (Syntetos-Boylan) | régulière 135 réf. / 70,7 % du volume ; erratique 72 / 22,4 % ; irrégulière 103 / 5,5 % ; intermittente 100 / 1,4 % | méthodes spécialisées (Croston, SBA, TSB) au programme ; résultats par classe |
| Zéros | 37 % des mois-référence (références ≥ 12 mois actifs) | **MAPE indéfinie** → WAPE |
| Pics | pic / médiane des mois actifs : 3,6 en médiane, 9 au 9e décile, 182 au maximum | une erreur absolue est optimisée par la **médiane**, pas la moyenne |
| Saisonnalité | décembre 1,37 × la moyenne ; octobre-novembre 1,14-1,17 ; janvier 0,77 | fin d'exercice budgétaire des hôpitaux ; mois de la cible en variable |
| Tendance | +8,2 % en 2024, +7,9 % en 2025 | niveau récent et croissance 12 mois en variables |
| Clientèle | 16 clients par référence en médiane ; premier client = 24 % ; 30 références à plus de 80 % sur un seul client | structure client par type d'établissement en variable |

### Qualité

* 0 référence vide dans la famille retenue ; une référence « fourre-tout »
  (`1200`, 139 libellés de réparations) appartient aux services, donc exclue ;
* une même référence porte plusieurs libellés (`PRL`, `PROLACTINE 60 Tests`…) :
  **la référence est l'unité**, pas le libellé ;
* la table de stock est indexée par libellé : chaque libellé est rattaché à la
  référence qui l'a le plus vendu.

---

## Phase 3 — Préparation des données

Implémentation : `construire_panel()` et `variables()`.

La demande est mise sous forme de **matrice référence × mois** (830 × 63). Toute
variable à l'origine `o` se calcule par une tranche des colonnes `≤ o` : un
test (`test_aucune_variable_ne_lit_le_futur`) remplace tous les mois postérieurs
par des valeurs aléatoires et vérifie que rien ne change.

| Famille | Variables |
|---|---|
| Mémoire | `lag_0` … `lag_11` ; même mois il y a 1 et 2 ans (`saison_1`, `saison_2`) |
| Niveau | moyennes et médianes sur 3, 6, 12, 24 mois ; moyenne des 12 mois précédents ; croissance 12 mois |
| Forme | écart-type, maximum, part de mois à zéro, ADI, CV², mois depuis la dernière vente, ancienneté, mois actifs sur 24 |
| Clientèle | part des hôpitaux publics, cliniques, laboratoires, autres ; HHI ; clients acheteurs |
| Prix | prix moyen sur 12 mois |
| Approvisionnement | achats sur 3 et 12 mois ; position de fin de mois (minorant) |
| Marché | demande totale du dernier mois, du même mois l'an dernier, moyenne 12 mois |
| Calendrier | mois de la cible, horizon ; **gamme** (premier mot du libellé : VIDAS, LIAISON…) |

48 variables. Pour les modèles globaux, une variante **normalisée** divise les
quantités par le niveau de la référence (moyenne 12 mois) : le modèle apprend des
formes de demande communes à des références de tailles très différentes.

Deux variables construites au niveau du **client** ont été testées puis
**écartées** sur la validation : le *rachat attendu* (ce qu'achetaient l'an
dernier les clients qui n'ont pas encore racheté) et l'*activité de devis*
récente des clients de la référence. WAPE à 1 mois 31,82 avec, 31,46 sans. Le
code reste, testé, pour rejouer l'hypothèse quand l'historique s'allongera.

**Éligibilité**, décidée à l'origine avec le seul passé : au moins 6 mois de
vente sur les 24 derniers et au moins une vente sur les 12 derniers. 363 à 388
références selon le mois, **95 à 99,7 % du volume**.

### Découpage

```
2021-01 ──────────── apprentissage ───────────── 2023-09 │ validation 2023-10 → 2024-09 │ test 2024-10 → 2026-03
                                                          │  12 origines — TOUT s'y choisit │  18 origines — lu une fois
```

Le test couvre **exactement** la fenêtre du modèle agrégé. Les modèles appris sont
réentraînés tous les 3 mois sur le seul passé, et interrogés chaque mois avec des
variables à jour.

---

## Phase 4 — Modélisation

Implémentation : `evaluation_demande/comparer_modeles.py`. **31 méthodes**, toutes
évaluées dans le même walk-forward, sur les mêmes couples référence × mois.

| Famille | Méthodes | Réglage |
|---|---|---|
| Règles simples (19) | zéro, naïf, naïf saisonnier, saisonnier ajusté au niveau, moyennes et médianes 3/6/12 mois, **Croston, SBA, TSB** (α = 0,1 / 0,2 / 0,3) | aucun |
| Statistiques par série (4) | **ETS** (AutoETS), **Theta** (AutoTheta), **ADIDA**, **IMAPA** — `statsforecast` | estimés série par série |
| Apprentissage global (5) | régression de **Poisson**, **LightGBM**, **XGBoost**, **CatBoost**, **MLP** (PyTorch) | **Optuna** (TPE) : 15, 80, 50, 30 et 20 essais |
| Réseaux de séries (2) | **N-HiTS**, **DeepAR** (loi binomiale négative) — `neuralforecast` | 2 configurations chacun |
| Combinaison (1) | médiane des trois meilleurs candidats de la validation | membres choisis en validation |

**199 configurations** de modèles appris ont été mesurées, toutes sur la seule
validation. Les modèles appris sont globaux : un modèle pour toutes les
références, qui apprend de l'une pour l'autre.

### La perte : le choix qui a le plus compté

La WAPE est une erreur **absolue** : la prévision qui la minimise est la
**médiane** de la demande future, pas sa moyenne. Or les pertes Tweedie et
Poisson — celles qu'on recommande habituellement pour la demande — apprennent une
moyenne. Sur une demande en pics, l'écart est grand. La perte a donc été laissée
au choix d'Optuna (Tweedie, Poisson, L1, quantile 0,5, Huber) : **les trois
familles de gradient boosting ont convergé vers la perte absolue (L1 / MAE) sur
données normalisées**.

### Deux corrections faites en cours d'étude

* **Point de départ d'Optuna.** 60 essais n'avaient pas retrouvé pour LightGBM
  un réglage aussi bon qu'un réglage standard (32,52 contre 31,69 %) : la
  recherche dépensait ses essais sur des pertes inadaptées. Chaque recherche
  démarre désormais depuis un réglage par défaut mis en file, jugé comme les
  autres sur la validation.
* **Adaptateur CatBoost.** Une exponentielle était appliquée deux fois aux
  prévisions Poisson et Tweedie (CatBoost la fait déjà), ce qui donnait des WAPE
  absurdes (176 %, 188 %). Corrigé, CatBoost entièrement re-réglé.

### Reproductibilité

LightGBM en mode `deterministic`, un seul thread ; graines fixées pour XGBoost,
CatBoost, PyTorch et Optuna. Le module de production rejoue le duel final et
retrouve **exactement** les chiffres de l'étude (38,31 / 39,87 / −1,57).

---

## Phase 5 — Évaluation

### Validation (12 mois) — ce qui a été choisi

| Méthode | WAPE 1 mois | cumul 3 mois |
|---|---|---|
| **LightGBM** (L1) — *challenger désigné* | **31,46** | 20,5 |
| Combinaison LightGBM + XGBoost + CatBoost | 31,48 | 20,4 |
| XGBoost (L1) | 31,61 | 20,5 |
| CatBoost (MAE) | 31,79 | 20,7 |
| **Médiane des 12 derniers mois** — *règle de référence* | **31,99** | 21,8 |
| MLP | 32,33 | 21,2 |
| N-HiTS | 32,40 | 22,0 |
| Régression de Poisson | 33,86 | 20,6 |
| TSB (α 0,2) · Croston (α 0,2) | 34,32 · 34,63 | 21,7 · 22,1 |
| IMAPA · ADIDA · Theta · ETS | 35,27 · 35,29 · 35,48 · 38,81 | |
| DeepAR | 36,47 | 27,2 |
| Naïf saisonnier (servi jusqu'ici par `/api/stock/forecast`) | 48,31 | 25,3 |

Écart challenger − règle en validation : **+0,54 point**, IC95 [−0,34 ; +1,47].

### Test (18 mois) — le verdict

| Méthode | WAPE 1 mois | cumul 3 mois | biais |
|---|---|---|---|
| **Médiane des 12 derniers mois** | **38,31** | 29,3 | −13,2 % |
| N-HiTS | 38,48 | 30,1 | −13,4 % |
| XGBoost | 38,95 | 28,8 | −10,2 % |
| Combinaison | 39,30 | 29,0 | −10,5 % |
| CatBoost | 39,33 | 29,4 | −11,8 % |
| **LightGBM** (challenger) | **39,87** | 29,2 | −10,2 % |
| Moyenne 12 mois | 40,65 | 29,8 | −4,2 % |
| MLP | 41,29 | 30,0 | −12,6 % |
| Régression de Poisson | 41,61 | 30,4 | +0,9 % |
| Theta · ETS | 42,14 · 42,16 | 31,4 · 32,0 | |
| DeepAR | 44,18 | 35,9 | −19,5 % |
| Naïf saisonnier | 49,38 | 34,0 | −5,6 % |

**Décision : LightGBM fait −1,57 point face à la médiane, IC95 [−2,29 ; −0,73].
Il est significativement moins bon. La règle simple est servie.**

### Pourquoi le modèle appris perd

Il gagne 9 mois de test sur 18 — autant que la règle. L'écart tient presque
entièrement à **janvier 2026** : 62,8 % d'erreur contre 32,5 % pour la médiane.

Décembre 2025 a été exceptionnel : **18 861 articles**, contre 11 341 en novembre
et 8 017 en janvier. Le modèle, qui a appris que le dernier mois compte, a
reporté ce pic sur janvier : il a prévu 11 478 articles pour 7 629 vendus
(+50 %). La médiane des douze derniers mois, par construction, l'a ignoré.
**Hors janvier 2026, les deux font jeu égal : 38,68 % contre 38,61 %.**

C'est la conclusion honnête : sur ces données, le modèle appris n'a pas
d'avantage à faire valoir, et il a un point de rupture que la règle n'a pas.
C'est aussi, à peu de chose près, ce qu'avait trouvé l'étude précédente : le gain
de validation ne survit pas à la période suivante.

N-HiTS, septième en validation, finit deuxième au test (38,48) : il n'a pas été
retenu, et c'est voulu. Choisir le challenger en regardant le test aurait rendu
le verdict optimiste.

### Par classe de demande (test, classe calculée à l'origine)

| Classe | Part du volume | Médiane 12 | LightGBM |
|---|---|---|---|
| Régulière | 81,6 % | **29,19** | 30,56 |
| Erratique | 9,8 % | **75,02** | 82,42 |
| Intermittente | 4,5 % | 77,04 | **75,43** |
| Irrégulière | 4,2 % | 88,91 | **84,10** |

Le modèle ne gagne que là où il y a peu de volume.

### Ce que la WAPE ne dit pas : le biais

Toutes les méthodes optimisées pour une erreur absolue **sous-estiment** le
volume total : −13 % pour la médiane au test. C'est mécanique — la médiane d'une
demande en pics est sous sa moyenne — et aggravé par la croissance (+8 % par an).
**On ne commande donc jamais la prévision ponctuelle** : on commande la borne
haute.

### La borne haute P80

Borne = prévision + q × niveau de la référence, où q est le quantile 80 % de
l'écart normalisé mesuré sur la validation (calibration conforme).

Un quantile unique couvrait 95 % des mois des références régulières (marge
inutilement large, sur 83 % du volume) et 67 % des autres — mesuré en calibrant
sur la première moitié de la validation et en vérifiant sur la seconde. La borne
servie est donc calibrée **par groupe** (régulière / autre). Au test :

| | Global | Régulières | Autres |
|---|---|---|---|
| Couverture à 1 mois | **80,3 %** | 79,4 % | 80,9 % |
| Couverture du cumul 3 mois | **78,9 %** | 77,0 % | 80,3 % |

Pour VIDAS TSH, la marge sur trois mois passe de +75 % (quantile unique) à +31 %.

### Pont avec le modèle agrégé

Sommées sur le périmètre prévu (95 à 99,7 % du volume réactif), les prévisions de
la médiane donnent le total mensuel avec **14,1 %** d'erreur moyenne, contre
15,71 % pour `demande_hybride` sur le total de tous les articles. Indicatif : les
périmètres diffèrent.

---

## Phase 5 bis — Diagnostic : d'où viennent les 6 à 8 points perdus au test ?

Toutes les méthodes perdent entre la validation (≈ 31-32 %) et le test
(≈ 38-39 %). Avant de toucher au pipeline, trois questions : les valeurs
extrêmes sont-elles des erreurs ? l'écart vient-il du modèle ou des données ?
reste-t-il une information exploitable ? Scripts : `evaluation_demande/diagnostic.py`,
`propagation.py`, `pipeline_robuste.py` ; résultats dans `resultats/diagnostic.json`,
`propagation.json`, `pipeline_robuste_*.json`, `preenregistrement.json`.

### 1. Décembre 2025 est un événement réel, pas une erreur

18 183 unités (≈ 2,5 × la médiane du marché). Qualifié avant tout traitement :

* **pas une erreur d'export** : les lignes répétées sont des mouvements distincts
  (`mouv_id` chronologiques), l'en-tête des factures concorde avec les lignes ;
* **un événement administratif** : +7 813 unités sur la hausse viennent des
  hôpitaux publics, dont les achats d'octobre 2025 se sont effondrés (15 unités,
  contre 2 100 à 2 650 les autres années) ; 8 595 unités facturées entre le 21 et
  le 31 décembre (1 864 en 2024) ; milieux de culture, groupage sanguin, troponine ;
* **un rattrapage de budget** plus qu'une hausse de consommation : les vingt clients
  du pic achètent 1 144 unités au 1er trimestre 2026 contre 2 202 un an plus tôt ;
* **imprévisible dans son ampleur** : aucun devis en octobre-novembre, table des
  bons de livraison vide ; l'effondrement d'octobre est le seul indice. Analogue
  historique : octobre 2022 (7 282 unités publiques).

Décision : décembre reste dans les données et dans la cible. Rien n'est écrêté ni
supprimé. La cible est une série de **facturation**, déformée par le calendrier
budgétaire des hôpitaux publics : c'est une propriété des données, pas un défaut à
corriger.

### 2. L'écart validation → test vient des données

Deux plafonds « oracles », qui lisent le futur et qu'aucune méthode n'atteint :

| | Validation | Test | Dégradation |
|---|---|---|---|
| Médiane 12 mois | 31,99 | 38,31 | +6,32 |
| LightGBM | 31,46 | 39,87 | +8,41 |
| Oracle : **meilleure constante par référence**, connue d'avance | 29,15 | 34,99 | +5,84 |
| Oracle : médiane des 3 mois avant et 3 mois après | 33,95 | 38,51 | +4,56 |
| Volatilité pondérée autour de la médiane | 0,351 | 0,441 | |
| Part du volume dans des pics (> 2 × niveau) | 11 % | 18 % | |
| WAPE médiane, références « hôpitaux publics » | 48,4 | 63,8 | |

* **≈ 92 % de la dégradation de la médiane (5,84 sur 6,32 pts) est une hausse du
  plancher irréductible** : même en connaissant d'avance le niveau exact de chaque
  référence sur la période, on perdrait presque autant.
* **La marge maximale de toute prévision « de niveau » est de 3 à 5 points** (29,9 et
  35,8 % pour la constante clairvoyante sur les 12 premiers et 12 derniers mois du
  test, contre 34,4 et 40,5 % pour la médiane). Le reste est le calendrier mois par
  mois des commandes, que l'oracle de voisinage lui-même n'explique pas.
* **Les 2,09 points supplémentaires de LightGBM sont un optimisme de sélection** :
  sur les 12 mois qui précèdent la validation (2022-09 → 2023-08, jamais utilisés
  jusque-là), LightGBM perdait déjà contre la médiane (38,87 contre 37,54). Son
  avantage de validation (−0,53 pt) n'était pas stable.

### 3. Décomposition de la WAPE du test (médiane contre LightGBM, mêmes 6 792 observations)

* **Concentration** : les 10 mois les plus coûteux font 67,8 % de l'erreur de
  LightGBM ; décembre 2025 seul pèse 18 % ; 10 références font 27,9 %, 50 en font 61,6 %.
* **Biais** : la médiane sous-prévoit de 13,2 %, LightGBM de 10,2 %. Sous-prévision
  sur 9 mois (dont les pics d'octobre-novembre 2024 et de novembre-décembre 2025),
  sur-prévision sur 5 (juillet-octobre 2025 et **janvier 2026 : +50,5 %**).
* **Par type d'observation** : les pics (18 % du volume) font 34-37 % de l'erreur ;
  les creux (2,8 % du volume) en font 11-12 %.
* **Par clientèle** : les références majoritairement publiques font 20 % du volume
  et un tiers de l'erreur.
* **Duel par observation** (tolérance max(1 ; 5 %)) : 64 % d'observations
  **similaires** ; LightGBM meilleur sur 17,9 %, médiane meilleure sur 17,9 %.
  LightGBM gagne les pics (194 contre 38) mais perd les mois normaux
  (−2 231 unités nettes) et les creux : il réagit trop.

### 4. Comment le pic s'est propagé (TreeSHAP, prévision de janvier 2026 reproduite à l'unité près)

| Contribution à la prévision de janvier 2026 | Unités |
|---|---|
| Marché total du dernier mois (`marche_dernier_mois`) | **+3 520** |
| Ancienneté (`anciennete`, qui croît chaque mois : une horloge) | **+1 182** |
| Moyennes et médianes glissantes | +1 022 (≈ +1 365 à une origine normale) |
| Retards `lag_0..lag_11` | +156 |
| Croissance (`croissance_12`, `moy_12_precedente`) | +21 |

1. **Ni les retards ni la croissance** : ce sont deux variables **non stationnaires**,
   le marché en unités absolues et l'ancienneté. Le marché de décembre (2,5 × sa
   médiane) était hors de tout ce que le modèle avait vu (maximum historique : 1,96
   en octobre 2022) ; l'arbre l'a rangé avec l'exemple d'entraînement le plus
   récent — novembre → décembre 2025, marché déjà haut et cible record — et en a
   déduit un **élan** (forme × 1,32 contre ≈ 1,00 d'habitude).
2. **L'échelle** (moyenne 12 mois) n'explique que 26 % du surcroît.
3. **Contrefactuel** : le seul mois de décembre neutralisé dans les variables, la
   prévision tombe de 11 478 à 7 907 unités (réel 7 629) et la WAPE de 62,8 à 33,2 %.
4. **Pics historiques** : après octobre 2022, le même modèle n'a pas extrapolé
   (marché : −662 unités) — et novembre 2022 est resté haut (8 807). Après
   décembre 2025, janvier est retombé. **Avec deux événements de sens opposé,
   l'après-pic n'est pas apprenable.**
5. **Détection** : une règle robuste (« marché du dernier mois > 1,3 × sa médiane
   12 mois ») ne se déclenche qu'une fois avant le test. Trop rare pour calibrer un
   traitement ; utile comme **alerte** (« mois atypique : prévisions à lire avec
   prudence »), pas comme variable.

### 5. Reste-t-il une information exploitable ? Test pré-enregistré

Sept candidats **motivés par le diagnostic**, fixés avant la phase de test, sans
nouvelle recherche de réglages et **sans jamais toucher la cible** : marché en
ratios et ancienneté plafonnée (`lightgbm_stationnaire`), plus échelle robuste
sans le mois maximal (`lightgbm_robuste`), combinaison ½ médiane + ½ LightGBM
robuste, quantiles 55 % et 60 % (correction du biais), hybride par classe.

**Période de développement** : les 12 origines de validation + 12 origines de
pré-validation (2022-09 → 2023-08), pour ne plus décider sur 12 mois seulement.
**Règle écrite avant le test** (`preenregistrement.json`, horodaté, empreintes
SHA-256) : battre la médiane dans les deux sous-périodes et IC95 bootstrap du gain
entièrement positif sur les 24 origines.

| Développement (WAPE à 1 mois) | Pré-validation | Validation | 24 origines | Gain vs médiane [IC95] |
|---|---|---|---|---|
| Médiane 12 mois | 37,54 | 31,99 | 34,78 | — |
| Combinaison 50/50 | 37,75 | 31,49 | 34,63 | +0,14 [−0,19 ; +0,48] |
| Quantile 55 % | 37,53 | 32,07 | 34,81 | −0,03 [−0,26 ; +0,16] |
| LightGBM actuel | 38,87 | 31,46 | 35,18 | −0,40 [−1,13 ; +0,26] |
| Hybride par classe | 38,66 | 31,90 | 35,29 | −0,52 [−1,20 ; +0,01] |
| LightGBM stationnaire | 39,20 | 32,22 | 35,73 | −0,95 [−1,74 ; −0,25] |
| LightGBM robuste | 40,13 | 32,44 | 36,31 | −1,53 [−2,23 ; −0,81] |

**Aucun candidat ne passe. La décision pré-enregistrée est la médiane 12 mois.**

### 6. Tableau final (test de 18 mois inchangé, lu pour confirmation)

| Modèle | Validation | Test 18 mois | Δ Test vs médiane | Biais (test) | MAE (test) | WAPE cumul 3 mois (test) |
|---|---|---|---|---|---|---|
| Médiane 12 mois | 31,99 | 38,31 | — | −13,2 % | 8,66 | 29,31 |
| LightGBM actuel | 31,46 | 39,87 | +1,57 (IC95 [+0,73 ; +2,29]) | −10,2 % | 9,01 | 29,20 |
| **Nouveau pipeline (décision pré-enregistrée) = médiane 12 mois** | 31,99 | 38,31 | 0 | −13,2 % | 8,66 | 29,31 |
| *Non retenu* — Combinaison 50/50 | 31,49 | 37,67 | −0,63 (IC95 [−1,05 ; −0,25]) | −10,3 % | 8,52 | 27,74 |
| *Non retenu* — LightGBM stationnaire | 32,22 | 38,04 | −0,27 (IC95 [−0,97 ; +0,35]) | −8,7 % | 8,60 | 27,10 |

Δ négatif = meilleur que la médiane.

Les deux dernières lignes font mieux au test ; elles ne sont **pas** retenues. Le
stationnaire perdait en développement : son gain au test tient surtout au fait
que le test contient l'extrapolation de janvier 2026 qu'il corrige. La combinaison
perdait en pré-validation. Les choisir maintenant, ce serait choisir sur le test.
Et même la meilleure (−0,63 pt) reste loin du seuil de déploiement de la
plateforme (−2 points).

**Avril 2026** (jamais utilisé, un seul mois, 29 jours sur 30) : tout le monde
sous-prévoit d'environ 30 %. Médiane 39,6, LightGBM actuel 40,2, combinaison 38,7.
Indicatif seulement.

### Conclusion

**Le plafond vient de la prédictibilité des données, pas du modèle.** La série est
une série de facturation dont environ 20 % du volume suit le calendrier budgétaire
des hôpitaux publics. Un oracle qui connaîtrait d'avance le niveau de chaque
référence ferait encore 35 % au test. Aucune variable disponible au moment de
prévoir n'annonce l'ampleur ni l'après-coup d'un pic. Le LightGBM a une vraie
faiblesse (des variables non stationnaires qui extrapolent), mais la corriger ne
rapporte rien de stable hors de l'épisode qui l'a révélée.

Pistes qui ne dépendent pas du test déjà lu :

1. **Évaluation prospective** : les mois d'avril à septembre 2026 existent
   désormais dans l'entrepôt. En réexportant l'extrait, la décision
   pré-enregistrée — et, en « ombre », la combinaison 50/50 sur le cumul de 3 mois
   (meilleure que la médiane dans les deux sous-périodes de développement en
   post-hoc : 23,44 contre 24,13 et 20,57 contre 21,80) — se jugent sur des mois
   que personne n'a vus.
2. **Une donnée nouvelle, pas un modèle nouveau** : calendrier des appels d'offres
   et des marchés publics, dates de commande (et non de facture), bons de
   livraison. C'est là qu'est l'information manquante.
3. **Décider sur 3 mois, pas sur un mois** : l'erreur cumulée (≈ 29 %) est bien
   plus faible que l'erreur mensuelle (≈ 38 %), parce que les décalages de
   facturation se compensent. C'est déjà la quantité que l'agent Stock &
   Approvisionnement présente.

---

## Phase 6 — Déploiement

| Élément | Où |
|---|---|
| Prévision servie, duel et décision | `ml_engine/forecasting/demande_reference.py` (`train`, `prevoir`) |
| Registre | entrée `demande_reference` : servie si le rapport existe ; nature lue dans le rapport (`methode_statistique` tant que la règle gagne) |
| Passerelle | `passerelle.demande_par_reference()` — aucun agent n'importe le module |
| Agent | **Stock & Approvisionnement**, volet stock : pour les ruptures en tête de liste, la demande attendue sur trois mois et la quantité qui la couvre dans 8 cas sur 10 (borne − stock encore positif) |
| Interface | `/api/stock/forecast` (onglet Stock) sert désormais cette prévision, contrat de réponse inchangé ; l'ancien chemin reste en repli |
| Réentraînement | `ml_engine.synchro` (`demande_reference`) et `scripts/retrain_all.py` |

**Surveillance.** Chaque `train()` rejoue le duel règle / LightGBM sur les 18
derniers mois avec les réglages figés. Le jour où le modèle appris bat la règle
de 2 points avec un intervalle entièrement positif, il est servi automatiquement,
son artefact est écrit, et le registre le déclare `modele_appris`. Le choix des
réglages, lui, ne se rouvre qu'en relançant l'étude complète.

### Ce que ce travail établit, et ce qu'il n'établit pas

* Il établit qu'une **règle robuste — la médiane des 12 derniers mois — est la
  meilleure prévision disponible** sur ces données, devant 30 autres méthodes,
  dont le gradient boosting et le deep learning, et qu'elle fait 11 points de
  mieux que le naïf saisonnier servi jusqu'ici (38,31 contre 49,38 %).
* Il établit que la borne P80 tient sa promesse hors de l'échantillon qui l'a
  calibrée.
* Il n'établit pas une **quantité optimale** : l'ERP ne porte ni délai
  fournisseur ni coût de rupture ; « couvrir trois mois dans 8 cas sur 10 » est
  une convention explicable, pas un optimum.
* La position de stock est un **minorant** (le stock antérieur à 2017 est
  inconnu) : la quantité à commander est donc prudente par excès.
* **Modèles de fondation** (Chronos, TimesFM) : non testés, leurs poids ne sont
  pas téléchargeables depuis cet environnement. Les ajouter maintenant serait un
  essai *a posteriori* — le test a été lu. Ils devront attendre une nouvelle
  fenêtre de test pour concourir.

---

## Rejouer l'étude

```bash
python evaluation_demande/comparer_modeles.py --phase validation   # ≈ 60 min
python evaluation_demande/comparer_modeles.py --phase test         # ≈ 15 min, refuse de tourner sans validation figée
python -m ml_engine.forecasting.demande_reference                  # duel de production + rapport lu par le registre
python evaluation_demande/diagnostic.py                            # écart validation/test, décomposition du test
python evaluation_demande/propagation.py                           # TreeSHAP, contrefactuel, pics historiques
python evaluation_demande/pipeline_robuste.py --phase dev          # sélection + pré-enregistrement
python evaluation_demande/pipeline_robuste.py --phase test         # refuse de tourner sans pré-enregistrement
python -m pytest tests/test_demande_reference.py -v
```
