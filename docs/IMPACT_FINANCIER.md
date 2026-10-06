# Ce que la plateforme vaut, en dinars

> **Le chiffre à citer est celui que produit la commande, jamais celui de ce
> document.**
>
> ```bash
> python -m ml_engine.analytics.impact      # affiche et réécrit reports/impact_metrics.json
> ```
>
> C'est la même règle que pour les métriques ML : le calcul décide, le rapport
> raconte. Les montants ci-dessous sont l'état mesuré le **5 octobre 2026** ; ils
> bougent à chaque reconstruction de l'entrepôt.

## 1. Ce que ce document n'est pas

La plateforme **ne génère aucun encaissement**. Elle identifie et elle priorise.
Tout montant qualifié de « récupérable » suppose qu'une action soit menée par
quelqu'un, et le taux qui en calcule la part est une **hypothèse déclarée**, pas
une mesure.

C'est pourquoi chaque poste publie quatre choses, et pas seulement un chiffre :

1. le **montant identifié** — une requête sur l'entrepôt, reproductible ;
2. le **taux supposé** de conversion en argent réel ;
3. la **justification** de ce taux ;
4. la **réserve** : ce que le chiffre ne dit pas.

Un lecteur qui juge un taux inadapté peut le changer dans `HYPOTHESES`
(`ml_engine/analytics/impact.py`) et relancer le calcul. C'est le but : les
hypothèses sont au même endroit, nommées, et modifiables en une ligne.

## 2. Les postes

| Poste | Identifié | Hypothèse | Récupérable | Source du chiffre |
|---|---:|---:|---:|---|
| Créances à terme long priorisées | 10 948 315 DT | 15 % | 1 642 247 DT | échéances réelles des factures |
| Chiffre d'affaires menacé par le décrochage | 4 895 100 DT | 20 % | 979 020 DT | churn — AUC 0,9224 hors période |
| Trésorerie immobilisée en stock excédentaire | 5 943 821 DT | 10 % | 594 382 DT | achats − ventes, au coût réel |
| Marge menacée par la dégradation de la rentabilité | 2 875 835 DT | 25 % | 718 959 DT | marge_client — AUC 0,7969 |
| Ventes probables en attente de relance | *(voir §5)* | 10 % | — | conversion_devis — lift 2,49 |
| Stock qui ne sera pas écoulé avant péremption | 212 117 DT | 40 % | 84 847 DT | rotation lue sur les factures |
| **Total** | **24 875 188 DT** | — | **4 019 455 DT** | — |

Le total exclut le poste des devis, absent de cette mesure pour une raison
d'environnement expliquée au §5 — pas pour une raison de méthode.

### Pourquoi ces taux, et pas d'autres

| Poste | Taux | Ce qui le justifie |
|---|---:|---|
| Recouvrement | 15 % | Bas **volontairement** : aucune date de règlement n'est enregistrée (`docs/DONNEES_MANQUANTES.md`), donc l'effet réel d'une relance n'est pas mesurable. Le gain porte sur l'**anticipation** de l'encaissement, pas sur une perte récupérée. |
| Rétention | 20 % | Le modèle signale des clients **encore actifs**, donc joignables. Mais un client s'éloigne souvent pour des raisons qu'un appel ne règle pas : prix, concurrent, réorganisation. |
| Surstock | 10 % | Seule une part du stock excédentaire est déstockable à court terme ; un automate ne se revend pas comme un consommable. |
| Marge | 25 % | AUC 0,797 contre 0,762 pour la marge des trois derniers mois seule : le classement informe, modestement. Et la cause dominante — la montée de la part d'équipement — n'est pas toujours corrigeable. |
| Devis | 10 % | **Le seul taux appuyé sur une mesure directe** : sur les 10 % de devis les mieux classés hors période, le taux de signature observé est **2,49 fois** celui du taux de base. 10 % reste bas parce que la base est déjà une espérance. |
| Péremption | 40 % | Le plus élevé, parce que le **constat** ne repose sur aucune estimation : la référence détient plus de deux ans de consommation, ce qui se lit sur les factures. L'incertitude ne porte que sur la capacité à écouler. |

## 3. Le montant qui ne s'additionne à rien : 15 800 000 DT

Le chiffre d'affaires publié était surévalué de **5,44 %**. Deux causes, toutes
deux corrigées :

- les **avoirs étaient additionnés** au lieu d'être déduits — la colonne TTC
  n'est pas signée, seule `MONTANTSIGNE_DEV` porte le signe ;
- **1 324 factures** étaient comptées deux fois.

Ce montant est **isolé du total, et doit le rester**. Rien n'est à encaisser :
c'est une décision faussée qui ne le sera plus. Un objectif commercial, une
prime, une prévision bâtis sur 5,44 % de trop.

Mais c'est **le seul chiffre de ce document qui ne dépende d'aucune hypothèse**.
Il est vérifié par des invariants comptables : CA net = ventes − avoirs,
marge = CA − coût de revient. Si un jury ne devait retenir qu'un montant, c'est
celui-là.

## 4. Ce qui n'est pas chiffré, et pourquoi

Trois apports réels qu'aucune requête ne sait mesurer. Les chiffrer aurait été
facile et malhonnête.

- **Temps d'analyse épargné** — le briefing agrège en quelques secondes ce qu'un
  contrôleur de gestion assemblerait en heures. Le mesurer exigerait de connaître
  le temps réellement passé avant la plateforme. Nous ne l'avons pas.
- **Fiabilité des indicateurs** — neuf contrôles d'intégrité tournent à chaque
  calcul et détecteraient une régression comme celle des 5,44 %. La valeur d'une
  erreur évitée ne se mesure qu'après coup.
- **Refus documentés** — trois modèles ont été écartés faute de gain confirmé
  (`reports/METRICS_REPORT.md`). Le coût évité — des décisions prises sur des
  prédictions non fiables — n'est pas observable, par construction.

## 5. Le poste des devis, et pourquoi il manque à cette mesure

Le modèle de conversion des devis est sérialisé avec **scikit-learn 1.8.0**.
Chargé depuis une version antérieure, il lève une exception, et le module fait
alors ce qu'il doit faire : **il retire le poste au lieu de l'estimer**, et la
phrase correspondante disparaît avec lui.

Pour le faire apparaître :

```bash
python scripts/retrain_all.py              # réaligne les modèles sur la version installée
python -m ml_engine.analytics.impact       # le poste et sa phrase reviennent
```

Ce comportement est testé (`test_un_poste_dont_le_modele_n_est_pas_servi_disparait`)
parce qu'il vaut mieux qu'un total manque un poste que de le voir complété par
une valeur plausible.

## 6. Le détail par client

Un total ne se décide pas : il faut savoir **sur qui appeler demain matin**.
Chaque poste attribuable publie donc ses dix comptes les plus lourds
(`par_client`), avec le même taux que le poste — aucun client n'est supposé
convertir mieux qu'un autre, sans quoi le total ne serait plus la somme de ses
parts, et c'est testé.

Deux postes n'ont pas de détail par client, et ne peuvent pas en avoir : le
surstock et la péremption portent sur des **références de stock**, le
recouvrement sur l'ensemble des factures à terme long.

## 7. Les phrases

Le module produit aussi des **phrases prêtes à citer** (`phrases`), affichées
dans l'onglet *Enjeu financier*. Elles sont **entièrement dérivées** des montants
calculés : aucune n'est écrite en dur, et aucune ne survit à la disparition du
poste qui la fonde. Deux tests le garantissent
(`test_les_phrases_citent_les_montants_calcules`,
`test_une_phrase_ne_survit_pas_au_poste_qui_la_fonde`).

C'est la condition pour qu'on puisse les répéter sans les vérifier : elles ne
peuvent pas rester vraies dans le texte et fausses dans les données.

## 8. Où tout cela vit

| Quoi | Où |
|---|---|
| Calcul et hypothèses | `ml_engine/analytics/impact.py` |
| Accès des agents et de l'API | `ml_engine/passerelle.py` → `impact_financier()` |
| Route | `GET /api/impact` (directeur seul) |
| Écran | onglet **Enjeu financier**, `frontend/src/features/impact/` |
| Tests | `tests/test_impact.py` — 20 tests |
| Sortie machine | `reports/impact_metrics.json` |

## 9. Ce qu'il manque pour que ces chiffres soient autre chose qu'un calcul

Tout ce qui précède est **interne** : des requêtes sur nos propres données,
pondérées par nos propres hypothèses. Rien n'y prouve qu'un dinar a été gagné.

Deux choses le prouveraient, et une seule dépend de nous :

1. **La grille de validation métier** (`docs/VALIDATION_METIER.md`), remplie par
   un responsable commercial : sur dix clients signalés, combien le sont à juste
   titre ? C'est ce qui transforme un taux supposé en taux observé.
2. **Les dates de règlement** (`docs/DONNEES_MANQUANTES.md`), que l'entreprise
   seule peut fournir : sans elles, le poste de recouvrement restera une
   anticipation non mesurable.

Tant que la première n'est pas remplie, le mot juste pour ce document est
**« ce que la plateforme identifie »** — jamais « ce qu'elle rapporte ».
