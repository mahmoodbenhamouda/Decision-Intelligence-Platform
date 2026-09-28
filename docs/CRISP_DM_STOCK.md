# Modélisation du domaine Stock — méthodologie CRISP-DM

Deux modèles ont été construits sur le domaine stock :

| Modèle | Fichier | Type | Question métier |
|---|---|---|---|
| Prévision de demande multi-horizon | `ml_engine/models/demand_forecast.py` | Régression, 3 horizons (30/60/90 j) | *Combien vais-je vendre de cette référence d'ici 1, 2, 3 mois ?* |
| Risque de stock | `ml_engine/models/stock_risk.py` | Classification binaire calibrée | *Quelles références vont me coûter de l'argent, et combien ?* |

Ce document suit les **six phases de CRISP-DM**, dans l'ordre, sans en omettre
aucune. Les chiffres cités proviennent de `reports/demand_forecast_ml_metrics.json`
et `reports/stock_risk_metrics.json`, régénérés à chaque entraînement.

> **Avertissement de périmètre.** Les *ventes* sont réelles (6 ans d'ERP,
> 18 782 observations produit × mois). Les *positions de stock* sont simulées par
> un modèle (s,S) calibré sur ces ventes réelles — l'ERP d'Overlyne n'expose
> aucune table de stock (voir `docs/STOCK_SIMULE.md`). Les métriques valident
> donc la chaîne de modélisation et la partie « demande » ; elles ne constituent
> pas une mesure de performance sur des stocks observés.

---

## Phase 1 — Compréhension du métier

### Contexte

Overlyne distribue des réactifs et automates de diagnostic in vitro à des
hôpitaux publics, cliniques privées et laboratoires tunisiens. Deux coûts
s'opposent :

* **Rupture** — un laboratoire sans réactif arrête une série d'analyses. Le coût
  n'est pas le manque à gagner sur une commande, mais le risque de perdre le
  client au profit d'un concurrent.
* **Surstock et péremption** — les réactifs ont une durée de vie courte (12 à
  24 mois). Un lot non écoulé avant sa date est une **perte sèche** : il ne peut
  ni être vendu, ni être retourné.

### Objectifs métier traduits en objectifs de fouille de données

| Objectif métier | Traduction data science | Critère de succès |
|---|---|---|
| Anticiper les commandes à passer | Prévoir la demande cumulée à 30 / 60 / 90 jours | Battre les prévisions naïves sur période inédite |
| Éviter les pertes financières | Classer chaque référence en risque / non-risque et chiffrer l'exposition | AUC nettement > 0,5, probabilités calibrées |
| Prioriser l'action du directeur | Ordonner par **perte attendue** = probabilité × exposition | Le classement doit être stable et explicable |

### Critère d'arrêt posé *avant* la modélisation

> Un modèle appris n'est déployé que si son gain, mesuré en validation croisée
> temporelle, **se confirme sur une période finale jamais utilisée** pour
> quelque décision que ce soit. Sinon, la référence naïve est servie et
> l'interface l'annonce.

Cette règle est implémentée dans le code (`train_demand_models`), pas seulement
énoncée : c'est elle qui a conduit au résultat de la phase 5.

---

## Phase 2 — Compréhension des données

### Sources

| Source | Nature | Volume |
|---|---|---|
| `ZZ_Facture_vente_mouv.csv` | Lignes de facturation réelles (ERP) | 6 ans, 2021-01 → 2026-03 |
| `stock_simule` (DuckDB) | Positions de stock simulées (s,S) | 44 843 lignes, 1 131 clients |
| `sales`, `dim_client` (DuckDB) | Entrepôt analytique dérivé | — |

### Constats de l'exploration

* **328 produits** ont un historique suffisant (≥ 12 mois d'activité).
* Les séries sont **courtes, bruitées et à zéros fréquents** : la MAPE y est
  indéfinie (division par zéro). La métrique de sélection retenue est la **MAE**,
  complétée par la **WAPE** (erreur rapportée au volume total), interprétable.
* La demande est **fortement concentrée** : quelques références (VIDAS TSH,
  D-Dimer, Troponine) portent l'essentiel du volume.
* La typologie de clientèle structure la saisonnalité : les **hôpitaux publics**
  commandent par marchés annuels, les **laboratoires privés** au fil de l'eau.
  D'où les variables `part_public`, `part_labo`, `hhi_clients`.
* **Limite documentée** : aucune date de règlement dans l'ERP (voir
  `docs/DONNEES_MANQUANTES.md`) — sans impact sur le domaine stock.

### Qualité des données

Contrôles passés : aucune quantité négative, aucun doublon produit × mois,
aucune valeur manquante dans les variables servies au modèle (vérifié par le
test `test_dataset_sans_valeur_manquante`).

---

## Phase 3 — Préparation des données

Implémentation : `ml_engine/models/demand_features.py`.

Agrégation en séries **produit × mois**, puis construction de **23 variables**,
toutes strictement rétrospectives :

| Famille | Variables | Intuition |
|---|---|---|
| Mémoire courte | `lag_1`, `lag_2`, `lag_3` | dynamique récente |
| Mémoire longue / saisonnière | `lag_6`, `lag_12` | cycle annuel des marchés hospitaliers |
| Tendance et niveau | `ma_3`, `ma_6`, `ma_12`, `tendance_3m`, `ratio_3_12` | accélération ou décélération |
| Volatilité | `std_3`, `std_6` | régularité de la consommation |
| Calendrier | `mois`, `trimestre` | saisonnalité |
| Structure client | `n_clients`, `part_public`, `part_labo`, `hhi_clients` | qui achète, et à quel point c'est concentré |
| Maturité | `anciennete_mois`, `mois_actifs`, `taux_activite` | référence installée ou nouvelle |
| Prix | `prix_moyen`, `variation_prix` | effet tarifaire |

La typologie d'établissement est dérivée par `classer_etablissement()` :
`HOPITAL_PUBLIC`, `CLINIQUE_PRIVEE`, `LABORATOIRE`, `PHARMACIE`, `AUTRE`. La règle
« hôpital public » est commune au projet (`ml_engine/typologie.py`) : le radar
financier l'utilise aussi.

**Cibles** : `y_h1`, `y_h2`, `y_h3` = demande **cumulée** des 1, 2 et 3 mois
suivants. Cumulée et non ponctuelle, parce qu'une décision d'achat porte sur une
quantité à couvrir sur une période, pas sur un mois isolé.

**Jeu final** : 328 produits · 18 782 observations · 23 variables · 0 valeur
manquante.

### Découpage — antidatation interdite

```
2021-01 ─────────────── développement (17 101 obs) ──────────── 2025-09 │ hold-out 2025-10 → 2026-03
                        ↑ 4 plis de validation temporelle                 ↑ 6 mois, jamais touchés
```

La validation croisée est **temporelle par blocs glissants** : on entraîne sur
tout le passé, on valide sur le bloc suivant. Un `KFold` aléatoire aurait laissé
le modèle apprendre le futur pour prédire le passé.

Les plis sont **pondérés géométriquement** (poids ∝ 2ⁱ) : le comportement récent
compte davantage que celui de 2021.

---

## Phase 4 — Modélisation

### 4.1 Prévision de demande

**Candidats** : LightGBM, XGBoost, HistGradientBoosting, Ridge — comparés à
trois **références naïves** obligatoires : `naif_lag1` (dernier mois × h),
`naif_saisonnier` (même mois l'an dernier × h), `moyenne_mobile_3`.

**Apprentissage résiduel.** Les modèles n'apprennent pas la demande, mais
l'**écart à un socle de référence**, transformé par un `log1p` signé :

```python
def _to_residual(y, base):
    r = y - base
    return np.sign(r) * np.log1p(np.abs(r))
```

Trois raisons : le modèle part d'une prévision déjà correcte ; la cible devient
centrée et à variance stable ; et surtout, un modèle qui n'apprend rien retombe
sur la baseline au lieu de produire n'importe quoi. Le **socle est adaptatif** —
la meilleure baseline mesurée sur l'horizon considéré.

**Contre le surapprentissage** : arbres peu profonds (`max_depth=4`), feuilles
peuplées (`min_child_samples=60`), échantillonnage lignes et colonnes (0,7),
pénalités L1/L2, et **arrêt précoce** sur le pli de validation.

**Reproductibilité.** LightGBM est forcé en mode `deterministic=True`,
`force_row_wise=True`, `n_jobs=1`. Sans cela, l'ordre de sommation multi-thread
des histogrammes fait varier le modèle d'une exécution à l'autre — écart
suffisant pour faire basculer la règle d'acceptation, donc pour rendre la
conclusion du mémoire non reproductible. Ce point a été **découvert
expérimentalement** : deux entraînements successifs donnaient +3,8 % puis
−14,0 % sur le même horizon.

### 4.2 Risque de stock

**Itération n°1 — abandonnée pour fuite de cible.** La première formulation
définissait le risque de rupture par `stock / demande < délai`, alors que
`stock`, `demande` et `délai` étaient tous trois des variables explicatives. Le
modèle atteignait **AUC = 1,0000**. Une AUC parfaite sur un problème métier n'est
pas une réussite : c'est le signe que la cible est déductible des entrées.

**Itération n°2 — cible prospective.** Le risque est désormais **constaté a
posteriori** à partir de la demande réellement observée sur les 3 mois suivants
(`y_h3`), qui n'est jamais une variable explicative :

```python
# rupture : la demande réelle des 3 mois suivants dépasse le stock
df["risque_rupture"] = ((df["y_h3"].notna()) & (df["y_h3"] > df["stock_actuel"])).astype(int)

# péremption : expiration proche ET stock non écoulé par la demande réelle
conso_futur = df["y_h3"].fillna(0)
df["risque_peremption"] = ((horizon_perem <= 120) & (df["stock_actuel"] > conso_futur)
                           & (df["stock_actuel"] > 0)).astype(int)

# surstock : couverture excessive ET demande future faible devant le stock
df["risque_surstock"] = ((df["couverture_actuelle_j"] > SEUIL_SURSTOCK_JOURS)
                         & (conso_futur < df["stock_actuel"] * 0.5)).astype(int)
```

**Candidats** : LightGBM, XGBoost, HistGradientBoosting, RandomForest, régression
logistique (référence linéaire). Validation `StratifiedKFold` à 5 plis, hold-out
stratifié de 20 %.

**Calibration.** Le score doit être une probabilité, pas un rang : il est
multiplié par une exposition financière. Le modèle est enveloppé dans un
`CalibratedClassifierCV` (isotonique, cv=3).

**Sorties du contrat** : `risk_score` (0-100), `risk_category`
(Faible / Moyen / Élevé / Critique), `risk_type` (péremption / rupture /
surstock / aucun), `financial_impact_dt`, `days_to_stockout`.

---

## Phase 5 — Évaluation

### 5.1 Prévision de demande — le modèle est refusé, et c'est le résultat

**Validation croisée temporelle (MAE, plus bas = meilleur) :**

| Horizon | naif_lag1 | naif_saisonnier | moyenne mobile 3 | LightGBM | XGBoost | HistGB | Ridge |
|---|---|---|---|---|---|---|---|
| 30 j | 12,13 | 13,77 | **10,35** | 10,03 | **9,86** | 10,02 | 10,37 |
| 60 j | 21,68 | 24,86 | **17,11** | 16,33 | **16,24** | 16,28 | 18,04 |
| 90 j | 31,25 | 36,12 | **23,79** | 22,36 | **22,34** | 22,58 | 25,87 |

Les modèles appris gagnent **4,7 % à 6,1 %** sur la meilleure baseline. Le
surapprentissage est maîtrisé : l'écart train → validation est **négatif** à tous
les horizons (l'erreur de validation est inférieure à celle d'apprentissage).

**Hold-out final — 6 mois jamais utilisés :**

| Horizon | Meilleure baseline hold-out | MAE baseline | Gain du modèle | Décision |
|---|---|---|---|---|
| 30 j | `naif_saisonnier` | 16,57 | **−2,3 %** | modèle **refusé** |
| 60 j | `naif_saisonnier` | 27,82 | **−27,7 %** | modèle **refusé** |
| 90 j | `naif_saisonnier` | 37,23 | **−14,0 %** | modèle **refusé** |

**Interprétation — pourquoi le gain disparaît.** Sur les plis de développement,
la meilleure référence est toujours la **moyenne mobile 3 mois** ; c'est donc
elle que les modèles ont prise pour socle. Sur les 6 derniers mois, la
hiérarchie s'inverse nettement :

| Référence | MAE hold-out à 90 j |
|---|---|
| `naif_saisonnier` (valeur d'il y a 12 mois) | **37,23** |
| `moyenne_mobile_3` | 43,72 |
| `naif_lag1` | 66,12 |

La demande y suit son profil de l'an passé plutôt que sa moyenne récente. Les
modèles, entraînés sur le socle « moyenne récente », héritent de sa faiblesse.
Aucune information disponible avant le hold-out ne permettait de l'anticiper.

**Ce qui est déployé** : la référence saisonnière aux trois horizons — et
l'interface l'affiche explicitement, avec le gain CV et sa non-confirmation.

Une piste testée et écartée : borner le résidu prédit à l'amplitude maximale
observée en apprentissage (l'inverse `expm1` est explosif). Sans effet ici, les
modèles à base d'arbres n'extrapolant pas au-delà de leur plage d'entraînement.
La contrainte est conservée car elle protège l'inférence en production.

### 5.2 Risque de stock

**Validation croisée (AUC) :**

| Modèle | AUC CV | Écart train/valid |
|---|---|---|
| **LightGBM** | **0,8450** | +0,051 |
| HistGradientBoosting | 0,8427 | +0,046 |
| XGBoost | 0,8414 | +0,046 |
| RandomForest | 0,8294 | +0,048 |
| Régression logistique | 0,7632 | +0,004 |

L'écart de 0,082 d'AUC entre le modèle linéaire et les modèles à arbres montre
que le problème est **franchement non linéaire** : ce n'est pas un seuil sur une
variable, ce sont des interactions.

**Hold-out (3 615 observations, 63,7 % de positifs) :**

| Indicateur | Valeur | Lecture |
|---|---|---|
| AUC | **0,8594** | discrimination solide, sans être suspecte |
| Average precision | 0,9174 | tient sur la classe positive |
| Précision | 0,8313 | 83 % des alertes sont justifiées |
| Rappel | 0,8446 | 84 % des risques réels sont détectés |
| F1 | 0,8379 | équilibre précision/rappel |
| Brier | 0,146 | qualité probabiliste |
| Écart de calibration moyen | **0,0202** | une probabilité annoncée de 70 % se réalise ~70 % du temps |

Matrice de confusion : `[[916, 395], [358, 1946]]` — 395 fausses alertes et
358 risques manqués. Le compromis est volontairement centré : une fausse alerte
coûte une vérification, un risque manqué coûte un lot périmé.

**Test d'ablation** — retirer `prix_moyen`, `couverture_actuelle_j` et
`ma_12` fait chuter l'AUC de **0,8594 à 0,7729** (perte 0,0865). Le modèle
apprend donc bien de ces variables et ne se contente pas d'un a priori sur la
classe majoritaire.

**Variables les plus contributives :**

| Variable | Importance |
|---|---|
| `prix_moyen` | 12,7 % |
| `couverture_actuelle_j` | 10,6 % |
| `ma_12` | 7,5 % |
| `taux_activite` | 6,9 % |
| `hhi_clients` | 5,7 % |
| `std_6` | 5,1 % |

Cohérent avec le métier : la couverture domine, le prix pondère l'enjeu, et le
rapport tendance courte / tendance longue capte les décrochages.

### 5.3 De la probabilité à la décision

```
perte attendue (DT) = probabilité calibrée × exposition financière
```

C'est cette grandeur, et non le score brut, qui ordonne les priorités affichées.
Une référence à 60 % de risque sur 300 000 DT passe avant une référence à 95 %
sur 2 000 DT — parce que le directeur arbitre de l'argent, pas des probabilités.

---

## Phase 6 — Déploiement

### Points d'entrée API

| Route | Rôle | Contenu |
|---|---|---|
| `GET /api/stock/risk` | directeur | scoring par référence, agrégats par catégorie et par type, périmètre, performance du modèle servi |
| `GET /api/stock/forecast` | directeur | prévisions 30/60/90 j + estimateur retenu et gains CV/hold-out par horizon |

Le paramètre `client` restreint la **liste affichée** aux références détenues par
l'établissement ; il ne re-score pas par client. Le modèle raisonne au niveau
produit sur le stock central — prétendre le contraire serait une extrapolation
non validée. Le champ `perimetre` de la réponse l'indique explicitement.

### Interface

Onglet **Stock**, trois vues :

1. **Pilotage opérationnel** — situation du stock, familles, réapprovisionnements
   représentés en « course contre la montre » (jours de stock restants vs délai
   fournisseur : quand la barre grise dépasse la colorée, la commande arrivera
   après la rupture), péremptions. Chaque ligne porte une **pastille de score ML**.
2. **Risque ML** — nuage score × impact financier (l'argent à risque),
   répartitions par type et par criticité, classement actionnable par perte
   attendue.
3. **Prévision de demande** — estimateur retenu par horizon avec son erreur,
   trajectoire cumulée du produit sélectionné, volumes attendus à 90 jours.

**Aucune métrique n'est écrite en dur dans l'interface** : l'AUC, le F1 et le nom
du modèle sont lus dans les rapports d'évaluation et transmis par l'API. Un
réentraînement ne peut donc pas rendre l'affichage mensonger.

### Copilote

Le thème `risque_stock` est reconnu par mots-clés (péremption, rupture, surstock,
days to stockout, réappro urgent…) et déclenche l'appel au scoring. La question
type — *« Quels sont les 5 réactifs présentant le plus fort risque de perte par
péremption le trimestre prochain ? »* — est traitée avec repli déterministe si le
LLM est indisponible : les chiffres viennent du modèle, jamais du LLM.

### Surveillance et réentraînement

```bash
python -m ml_engine.models.demand_forecast train   # régénère bundle + rapport
python -m ml_engine.models.stock_risk train
python -m pytest tests/test_ml_stock.py -v         # garde-fous
```

Les tests de `tests/test_ml_stock.py` sont conçus pour **échouer** si une
régression méthodologique se réintroduit :

| Test | Ce qu'il empêche |
|---|---|
| `test_auc_non_parfaite` | le retour d'une fuite de cible |
| `test_cible_absente_des_features` | l'ajout d'une variable qui construit la cible |
| `test_modele_deploye_uniquement_si_gain_confirme` | déployer un modèle non confirmé sur période inédite |
| `test_rapport_coherent_avec_le_modele_charge` | un rapport qui annonce autre chose que ce qui est servi |
| `test_pas_de_surapprentissage_grossier` | retenir un modèle qui mémorise |
| `test_calibration_du_risque` | des probabilités décoratives |
| `test_ablation_le_modele_apporte_quelque_chose` | un modèle qui n'apprend rien |
| `test_perimetre_client_est_un_sous_ensemble` | un score qui changerait selon le filtre d'affichage |

Deux défauts réels ont été détectés par ces tests :

1. **`predict_demand()` ignorait le modèle entraîné** et servait systématiquement
   une moyenne mobile, sans appliquer la reconstruction résiduelle. Le bundle
   stocke désormais le socle et la borne de résidu, et l'inférence trace
   l'estimateur réellement utilisé (`modele_30j`, `modele_60j`, `modele_90j`).
2. **La simulation de stock n'était pas reproductible** malgré `SIMULATION_SEED`.
   La requête de collecte de la demande par client triait par
   `client_name, ca_total DESC` sans départage final : à chiffre d'affaires égal
   — cas systématique sur les petites lignes — DuckDB ne garantit pas l'ordre.
   Les tirages aléatoires étant consommés ligne à ligne, **28 % des positions de
   stock changeaient d'une génération à l'autre**, ce qui déplaçait ensuite le
   taux de risque du jeu d'entraînement (58,9 % → 63,7 %). Corrigé par l'ajout de
   `produit ASC` au tri (`test_reproductibilite_de_la_graine`).

---

## Ce que ce travail établit, et ce qu'il n'établit pas

**Établi :**

* une chaîne CRISP-DM complète et reproductible sur 6 ans de ventes réelles ;
* un classifieur de risque calibré, AUC 0,859 sur période inédite, dont la
  contribution est prouvée par ablation ;
* une méthodologie de validation qui a détecté quatre défauts réels : une fuite
  de cible (AUC 1,0), une source de non-reproductibilité dans l'entraînement
  (sommation multi-thread de LightGBM), un défaut d'inférence (`predict_demand`
  ignorait le modèle entraîné) et une **non-reproductibilité de la simulation de
  stock** (départage d'ex æquo manquant dans le tri SQL : 28 % des lignes
  changeaient d'une génération à l'autre malgré la graine fixée).

**Non établi :**

* aucune performance sur des **positions de stock observées** — elles sont
  simulées, faute de données ERP ;
* aucun gain de prévision confirmé hors échantillon : la référence saisonnière
  reste le meilleur estimateur disponible à ce jour sur ce jeu.

Le second point n'est pas un échec de la démarche, c'en est le produit : la
valeur d'un protocole de validation se mesure à sa capacité de refuser un modèle
qui paraissait gagnant.
