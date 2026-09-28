# Données manquantes — analyse et demande technique

## Résumé

L'export ERP fourni ne contient **aucune date de règlement**. Cette page documente la recherche menée pour l'établir, ses conséquences exactes sur les indicateurs, la solution mise en place en attendant, et la demande technique précise à adresser à Overlyne.

---

## 1. Ce qui a été cherché, et ce qui a été trouvé

Recherche systématique sur les **32 fichiers CSV** de `data_pfe/`, sur les motifs `REGLEMENT`, `PAIEMENT`, `PAYE`, `ENCAISS`, `LETTRAGE`, `SOLDE`, `RESTE`, `DATEREGL`, `MONTANTREGLE`.

| Champ trouvé | Fichier | Contenu réel |
|---|---|---|
| `SOLDEACOMPTE_DEV` | `Facture_vente_ent_v.csv` | **0 sur les 128 848 lignes** — une seule valeur distincte, colonne jamais alimentée |
| `REG` | `Ms_Bl_facture_ent_actif.csv` | **totalement vide** (0 ligne remplie sur 128 938) |
| `REGTYP` | `Ms_Bl_facture_ent_actif.csv` | **totalement vide** |
| `ETAT` | `Ms_Bl_facture_ent_actif.csv` | constante `'NR'` — une seule valeur distincte, non exploitable |
| `MT`, `MTR3` | `Ms_Bl_facture_ent_actif.csv` | constantes à `0` |
| `EFFDT`, `EMIDT`, `ECHDT` | `Ms_Bl_facture_ent_actif.csv` | constantes `1/1/1999` (valeur sentinelle « non renseigné ») |
| `NATUREPAIEMENT` | `table_nature_paiement_vcsv.csv` | référentiel des **natures** de paiement (agios, virement…), sans aucun mouvement |
| `MODEREGLLIBELLE` | `Facture_vente_ent_v.csv` | mode de règlement **convenu** (ex. « Virement 60 jours ») — exploité pour l'analyse du mix, mais ne dit rien du paiement effectif |

**Conclusion factuelle** : les champs de règlement **existent dans le schéma de l'ERP** — ils sont simplement vides ou remplis de valeurs sentinelles dans l'export transmis. Ce n'est donc pas une impossibilité technique, mais un **périmètre d'extraction**.

---

## 2. Conséquence exacte sur les indicateurs

`payment_delay_days = échéance − date de facture` mesure le **délai de crédit accordé**, pas le retard constaté.

| Indicateur | Statut | Lecture correcte |
|---|---|---|
| `dso_jours` | ⚠️ proxy | délai **accordé** moyen, pas le délai d'encaissement |
| `exposition_recente_dt` | ⚠️ proxy | CA **facturé à délai long**, pas un impayé |
| `retards_30j/60j/90j` | ⚠️ proxy | factures à délai **accordé** long |
| `montant_risque_ttc` | ⚠️ proxy | comportement contractuel cumulé, **pas un encours dû** |
| Modèle de risque crédit | ⚠️ cible proxy | prédit `P(délai accordé > 60 j)`, pas `P(défaut)` |
| `cash_forecast` | ✅ correct | encaissements attendus **à l'échéance** — c'est bien ce qui est calculé |
| CA, marge, concentration, produits, fournisseurs, demande | ✅ correct | aucun lien avec la date de paiement |

> **Point important** : les jauges de santé qui apparaissent vides en vue client (marge, conversion devis) ne viennent **pas** de cette limite, mais d'un problème d'**attribution** (les achats et les devis ne sont pas rattachés aux clients dans l'ERP).

---

## 3. Pourquoi on ne « prédit » pas la date de paiement

Prédire, en apprentissage supervisé, suppose d'avoir observé la cible pour apprendre. Il n'existe **aucune** date de paiement dans les données : le problème est **sans étiquettes**.

Un modèle entraîné sans cible ne prédit rien — il restitue l'hypothèse qu'on lui a injectée, sous une apparence savante. Afficher « paiement prévu le 12/06 » alors que ce serait le simple résultat d'un paramètre codé en dur reviendrait à **fabriquer une donnée** : c'est précisément ce qu'un travail d'ingénieur data science doit refuser.

---

## 4. La solution retenue : des scénarios, pas une prédiction

Module `ml_engine/analytics/payment_scenario.py`, exposé par `POST /api/payment-scenarios` et affiché dans l'onglet **Risque crédit**.

Le principe est inversé : au lieu de cacher une hypothèse dans un modèle, on la rend **explicite, visible et modifiable**.

```
Hypothèse assumée + calcul exact  ≠  prédiction inventée présentée comme un fait
```

| Scénario | Hypothèse | DSO simulé | Encours estimé |
|---|---|---|---|
| Optimiste | paiement à l'échéance, 5 % de retards | 44,3 j | 0 DT |
| Central | +30 j sur 20 % des factures | 50,3 j | 818 K DT |
| Pessimiste | +75 j sur 35 % des factures | 70,6 j | 6,34 M DT |

*(valeurs sur le périmètre complet, observation au 29/04/2026)*

**Formule** : `DSO simulé = délai accordé + (retard moyen × part concernée)`. L'encours estimé retient les factures dont l'échéance, augmentée du retard supposé, dépasse la date d'observation.

**La sensibilité est le vrai livrable** : 26,3 jours de DSO et 6,34 M DT d'écart entre l'hypothèse la plus douce et la plus dure. C'est la mesure chiffrée de l'incertitude — et l'argument économique pour obtenir les données manquantes.

Un avertissement accompagne systématiquement les chiffres, dans l'API comme à l'écran. Douze tests (`tests/test_payment_scenario.py`) vérifient la cohérence arithmétique et la présence de ces garde-fous.

---

## 5. Demande technique à adresser à Overlyne

> **Objet : complément d'export ERP — données de règlement**
>
> Dans le cadre du projet d'intelligence décisionnelle, l'export actuel permet de calculer les délais de paiement **accordés** (date de pièce → date d'échéance), mais pas les délais **constatés**, faute de données de règlement.
>
> Les champs concernés existent dans le schéma de l'ERP mais sont vides dans l'extraction transmise. Nous demandons un export complémentaire contenant, **pour les factures de vente** :
>
> | Champ | Table d'origine | Usage |
> |---|---|---|
> | `REG` | `Ms_Bl_facture_ent_actif` | référence / date du règlement |
> | `REGTYP` | `Ms_Bl_facture_ent_actif` | type de règlement (espèces, virement, traite…) |
> | `ETAT` | `Ms_Bl_facture_ent_actif` | statut réel de la facture (réglée / partiellement / non réglée) |
> | `MTR3` | `Ms_Bl_facture_ent_actif` | montant réglé |
> | `EFFDT` | `Ms_Bl_facture_ent_actif` | date d'effet du règlement |
> | `SOLDEACOMPTE_DEV` | `Facture_vente_ent_v` | solde restant dû |
>
> **À défaut**, l'un de ces éléments suffirait :
> - la table des **écritures de règlement** (journal de banque / caisse) avec le lettrage vers les factures ;
> - la **balance âgée client** à une date donnée (encours par tranche d'ancienneté) ;
> - un simple export `numéro_facture ; date_règlement ; montant_réglé`.
>
> **Bénéfice attendu** : DSO réel constaté, taux d'impayés effectif, encours client exact, et un modèle de risque crédit ciblant le **défaut de paiement réel** au lieu du délai accordé.

---

## 6. Ce qui change le jour où les données arrivent

| Aujourd'hui | Avec les règlements |
|---|---|
| DSO = délai accordé (44,3 j) | DSO réel constaté |
| Encours = 3 scénarios (0 → 6,3 M DT) | Encours exact à date |
| Modèle : `P(délai > 60 j)`, AUC 0,997 | Modèle : `P(défaut de paiement)`, métriques à réévaluer |
| Priorité de recouvrement = score × exposition facturée | Priorité = score × **encours réellement dû** |
| Onglet « Scénarios » | Remplacé par les chiffres constatés |

L'architecture est prête : le champ `payment_delay_days` est calculé à un seul endroit (la vue `sales`, `etl/presentation.py`) ; le remplacer par `date_règlement − date_échéance` suffirait à propager la correction à l'ensemble des indicateurs.

---

## 7. Les autres limites — deux résolues, deux irréductibles

Une exploration systématique des 32 fichiers a été menée pour chacune. Résultat : **deux limites sur quatre reposaient sur une donnée que nous n'exploitions pas** — elles sont corrigées.

### ✅ RÉSOLUE — Marge par client (coût de revient trouvé dans les lignes)

Les lignes de vente (`ZZ_Facture_vente_mouv.csv`) portent **`MTCRSIGNE`** = coût de revient signé, **rempli sur 340 709 lignes**. La marge est donc calculable ligne à ligne, donc **attribuable par client**.

| | Avant (v7) | Après (v8) |
|---|---|---|
| Formule | `CA HT − achats TTC` | `Σ CA lignes − Σ coût de revient` |
| Taux global | 77,2 % (invraisemblable) | **28,3 %** (plausible pour un distributeur) |
| Vue client | `None` — « non attribuable » | **25,7 %** pour l'Hôpital Militaire |
| Marge mensuelle | approximation | réelle, par client |

**Nettoyage documenté** : 318 lignes portent un coût > 10× le prix de vente (erreurs de saisie manifestes — panel vendu 28 300 DT, coût déclaré 665 450 DT). Le moteur écarte `coût > 5 × CA` (387 lignes, 0,12 %) et **expose ce nombre** dans les KPI. Les 3 208 lignes à montant nul mais coût réel (2,2 M DT) sont des consommables offerts, comptabilisés séparément.

### ✅ RÉSOLUE — Taux de conversion des devis (statut ERP décodé)

Le champ `ETATPIECE` des devis porte 3 valeurs (1, 8, 2) sans référentiel. L'hypothèse « 8 = transformé en facture » a été **validée empiriquement** : on vérifie, pour chaque devis, s'il existe une facture du même client au même montant (± 1 %).

| État | Devis appariés à une facture |
|---|---|
| **8** | **371 / 415 → 89,4 %** |
| 1 | 1 567 / 4 189 → 37,4 % |

L'écart est sans ambiguïté. Le taux de conversion passe de **94,8 %** (heuristique « ce client a-t-il facturé quelque chose ? », dénuée de sens commercial) à **9,0 %** (415 devis transformés sur 4 621). Un test re-vérifie cette interprétation à chaque exécution de la suite.

### ⚠️ ABSENTE — Données de stock → traitée par SIMULATION marquée

Recherche sur les 32 fichiers (`STOCK`, `QTESTOCK`, `DISPO`, `INVENTAIRE`, `REAPPRO`, `SEUIL`) : **aucune colonne**. La donnée n'existe pas et ne peut pas être déduite.

**Traitement retenu** : plutôt que de laisser un trou fonctionnel, un module de gestion de stock a été construit sur des **données simulées explicitement marquées** — politique (s,S) calibrée sur la demande réelle (6 ans, 1 973 produits), péremption, réapprovisionnement, agent dédié dans la flotte. Le caractère simulé est signalé en base (`is_simulated`), dans l'API, à l'écran (bandeau non masquable), dans le briefing de l'agent — et **quatre tests vérifient ce marquage**.

Ce n'est pas une résolution de la limite : c'est une démonstration de la chaîne fonctionnelle sur un jeu maîtrisé, sans jamais faire passer du synthétique pour de l'observé. Détail complet : `docs/STOCK_SIMULE.md`.

La prévision de demande, elle, reste sur la **demande servie** (volumes facturés) — la demande latente demeure invisible.

### ⬛ HORS PÉRIMÈTRE — Corpus d'appels d'offres

Le modèle de pertinence des appels d'offres reposait sur 312 libellés écrits à la main par imitation des avis TUNEPS : aucun historique réel étiqueté n'existe publiquement. Il a été **retiré du projet** avec la veille externe, parce qu'un corpus auto-produit ne pouvait pas être audité comme l'est l'ERP (`reports/METRICS_REPORT.md`, §2). La limite ne s'applique donc plus à la plateforme livrée.

---

## 8. Récapitulatif de l'honnêteté du projet

| Limite | Statut | Preuve |
|---|---|---|
| Date de paiement | ❌ absente de l'export, présente dans le schéma | scénarios paramétrés + demande technique (§ 5) |
| Marge par client | ✅ **résolue** | coût de revient ERP, 11 tests |
| Conversion devis | ✅ **résolue** | statut ERP validé à 89,4 % |
| Stock | ❌ irréductible | aucune colonne dans les 32 fichiers |
| Corpus AO | ⬛ hors périmètre | module retiré du projet (`METRICS_REPORT.md`, §2) |

**La démarche compte autant que le résultat** : pour chaque limite, la donnée a été cherchée dans les fichiers bruts avant de conclure. Deux fois sur quatre, elle s'y trouvait.
