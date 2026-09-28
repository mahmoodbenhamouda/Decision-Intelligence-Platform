# Deep learning — recommandation de produits (Wide & Deep, PyTorch)

*Code : `ml_engine/deep/recommandation.py` · Rapport : `reports/recommandation_metrics.json` ·
Sortie servie : `output/recommandations.json` · Reproduction : `python -m ml_engine.deep.recommandation`*

## La question

> Quels produits, **jamais achetés** par ce client, va-t-il adopter dans les **6 prochains mois** ?

C'est la vente croisée. La cible est **observée** (première facture du couple client × produit
dans la fenêtre), jamais construite. Les rachats sont exclus : prédire qu'un laboratoire
rachète son réactif habituel n'apprend rien au service commercial. Les prestations
(`SERVICE SAV`, `SERVICE DIVERS`) et les avoirs sont exclus.

**Données** : 289 093 couples client × date × produit, 1 053 clients, 904 produits,
2021-01 → 2026-04 (dernier mois complet : 2026-03).

## Pourquoi du deep learning ici

Les autres modules scorent un client ou un produit. Celui-ci classe **des centaines de produits
pour chacun des clients** : plus de 400 000 couples candidats par date. La similarité entre
produits et entre profils d'établissement s'apprend par des **embeddings** — c'est le terrain
naturel des réseaux de neurones de recommandation.

## Architecture — Wide & Deep (Cheng et al., Google, 2016)

```
score = wide(x) + deep( x ⊕ E_produit(16) ⊕ E_famille(16) ⊕ E_type_établissement(4) )
deep  = Linear(51→64) → ReLU → Dropout(0,2) → Linear(64→32) → ReLU → Linear(32→1)
```

* **15 variables** : popularité 12 mois et 3 mois, tendance, adoption par les établissements du
  même type, similarité de co-achat (item-kNN) avec l'historique du client, ancienneté et CA du
  produit, taille et récence du client, poids de la famille du produit chez ce client.
* **Perte** : entropie croisée binaire pondérée (`pos_weight`), Adam (lr 3e-3, weight decay 1e-5).
* **Dropout d'identifiant** : 30 % des produits remplacés par un vecteur « inconnu » pendant
  l'entraînement, pour recommander aussi un produit récent.
* **Nombre d'époques** choisi par **validation interne** (entraînement jusqu'à T−12 mois,
  validation en T−6 mois) parmi {3, 6, 9, 12} — jamais sur le test.
* Déterminisme : graines fixées, `torch.use_deterministic_algorithms(True)`.

## Protocole

Walk-forward à **3 origines** (2024-09-30, 2025-03-31, 2025-09-30). Exemples d'entraînement
trimestriels dont la fenêtre cible se termine **au plus tard à l'origine**. Test sur le
**catalogue entier** (pas d'échantillon de négatifs qui faciliterait la tâche).
1 472 évaluations client au total.

## Résultats agrégés (3 origines, 1 472 évaluations client)

| Méthode | Famille | NDCG@10 | Recall@10 | HitRate@10 | Precision@10 | MAP@10 |
|---|---|---|---|---|---|---|
| Popularité 12 mois | référence triviale | 0,2837 | 0,3939 | 57,5 % | 0,110 | 0,203 |
| Popularité par type | référence triviale | 0,2799 | 0,3903 | 58,0 % | 0,107 | 0,199 |
| Item-kNN (co-achat) | référence triviale | 0,2872 | 0,4184 | 61,8 % | 0,111 | 0,199 |
| Régression logistique | non profond | 0,3181 | 0,4581 | 66,4 % | 0,123 | 0,224 |
| **LightGBM** | non profond — **servi** | **0,3439** | 0,4827 | 69,6 % | 0,134 | 0,243 |
| **Wide & Deep** | **deep learning** — challenger | **0,3501** | **0,5101** | **72,2 %** | **0,135** | **0,245** |

**Lecture métier** : sur 10 produits proposés à un client, le Wide & Deep en fait adopter au
moins un dans **72 % des cas** (contre 58 % pour la simple popularité), et retrouve **51 %** des
produits que le client adoptera réellement.

## Décision — règles déclarées avant la mesure

| Duel (bootstrap apparié sur les clients) | Écart NDCG@10 | IC95 | Verdict |
|---|---|---|---|
| Wide & Deep − item-kNN | +0,0629 | [+0,050 ; +0,076] | significatif |
| Wide & Deep − régression logistique | +0,0319 | [+0,022 ; +0,042] | significatif |
| **Wide & Deep − LightGBM** | **+0,0062** | **[−0,004 ; +0,016]** | **non significatif** |
| LightGBM − item-kNN (règle 1) | +0,0566 | [+0,044 ; +0,069] | significatif, gain ≥ 0,02 |

1. **L'apprentissage est utile** : le modèle retenu bat la meilleure référence triviale de
   +0,057 de NDCG@10, au-delà du seuil de 0,02, avec un écart significatif.
2. **Parcimonie** : le Wide & Deep est le meilleur sur **toutes** les métriques, mais son avance
   sur LightGBM n'est pas distinguable du bruit (il gagne dans 87,8 % des tirages). Le modèle le
   plus simple non significativement inférieur est servi : **LightGBM**.

Le Wide & Deep reste **challenger** : il est réentraîné et réévalué à chaque passage de
`python -m ml_engine.synchro` ; il sera servi automatiquement le jour où son avance devient
significative. Le volet fiabilité de la flotte publie ce duel à chaque briefing (réservé au directeur).

## Ce que le modèle ne dit pas

* Une adoption **probable**, pas une commande : le « potentiel » affiché est la dépense annuelle
  médiane des clients qui achètent déjà ces produits — un ordre de grandeur observé.
* Il apprend le comportement d'achat **passé** : il recommande ce que des clients comparables ont
  adopté, pas ce qui serait optimal cliniquement ou commercialement.

## Intégration

* **Agent Commercial** : constat « Opportunités de vente croisée », clients nommés pour l'arbitre.
* **Copilote** : thème `recommandation` (« quels produits proposer à… »), périmètre client respecté.
* **API** : `GET /api/commercial/recommandations` (client forcé côté serveur pour un compte client).
* **PyTorch n'est pas requis par l'API** : les recommandations sont précalculées.
