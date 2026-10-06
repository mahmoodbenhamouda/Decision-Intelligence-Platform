# Module Stock — données simulées

> 🟢 **STATUT ACTUEL : ce module n'est plus la source des chiffres servis.**
>
> Les quantités figurent dans les lignes de facture d'**achat** et de **vente** :
> la position de stock est donc **reconstructible par différence des flux**, et
> c'est `ml_engine/stock/flux_reels.py` qui alimente désormais le capital
> immobilisé, les ruptures et le stock non écoulable — **sans aucune simulation**
> (§3 quater de `reports/METRICS_REPORT.md`).
>
> Ce module subsiste pour deux raisons précises, et aucune autre :
>
> 1. **repli** — si la table `stock_flux_reel` n'a pas été matérialisée, l'interface
>    retombe sur lui, en le marquant comme estimé ;
> 2. **variables de position** des deux modèles de risque produit (§3 ter), qui
>    hiérarchisent le risque sans produire de montant affiché.
>
> Tout ce qui suit décrit donc un mécanisme de repli, et non la chaîne principale.
> Le reste du document reste exact et conservé : il documente la démarche qui a
> précédé la reconstruction.

> ⚠️ **Avertissement méthodologique, à lire avant tout.**
> Les exports de l'ERP du distributeur ne contiennent **aucune donnée de stock** — vérifié par recherche systématique sur les 32 fichiers (motifs `STOCK`, `QTESTOCK`, `DISPO`, `INVENTAIRE`, `REAPPRO`, `SEUIL` : zéro colonne).
> Ce module **simule** un stock, il ne le mesure pas. Aucun chiffre produit ici ne décrit une réalité observée.

## Pourquoi simuler plutôt que renoncer

Renoncer aurait laissé un trou fonctionnel : sans stock, impossible de démontrer la chaîne de gestion (réapprovisionnement, couverture, péremption) qui est pourtant le cœur métier d'un distributeur de réactifs.

Simuler est une pratique d'ingénierie **légitime — à condition d'être irréprochable sur trois points** :

1. **Calibrage sur le réel** — chaque paramètre dérive de la demande réellement observée (6 ans, 1 973 produits), aucune valeur n'est inventée sans ancrage.
2. **Modèle explicite** — la génération suit des formules standard de la gestion des stocks, documentées ci-dessous et vérifiables arithmétiquement.
3. **Marquage systématique** — base de données, API, interface, briefing d'agent : le caractère simulé est signalé partout, et **testé**.

Ce qui serait de la fraude : présenter ces chiffres comme des observations. Ce qui est de l'ingénierie : démontrer une chaîne fonctionnelle sur un jeu de données maîtrisé, en le disant.

---

## Le modèle de génération

Pour chaque produit, tout part de la **demande réelle** (`product_sales`).

### 1. Demande et variabilité (issues du réel)

```
d      = quantité annuelle moyenne ÷ 365          (demande journalière)
σ      = écart-type des volumes annuels ÷ 365     (variabilité)
σ_min  = 0,15 × d                                  (plancher de variabilité)
```

### 2. Paramètres par famille de produit

| Famille | Délai fournisseur `L` | Couverture cible | Durée de vie | Périssable |
|---|---|---|---|---|
| **RÉACTIF** | 45 j | 60 j | 18 mois | oui |
| **ÉQUIPEMENT** | 75 j | 90 j | — | non |
| **CONSOMMABLE** | 30 j | 45 j | 24 mois | oui |
| *défaut* | 40 j | 60 j | 18 mois | oui |
| SERVICE | — | — | — | **exclu** (pas de stock physique) |

Les délais reflètent la réalité du distributeur : réactifs importés d'un fournisseur unique dominant (Biomérieux, 84,6 % des achats — donnée réelle), équipements fabriqués à la commande.

### 3. Politique de réapprovisionnement (s, S)

Formules standard de la gestion des stocks :

```
Stock de sécurité    SS = z × σ × √L          avec z = 1,65 (service 95 %)
Point de commande    s  = d × L + SS
Niveau cible         S  = s + d × couverture
```

Ces trois relations sont **vérifiées par test** sur 500 produits (`test_politique_s_S_respectee`) : les colonnes stockées doivent permettre de recalculer exactement `s` et `SS`.

### 4. Situation de stock

Le niveau actuel est tiré selon un profil réaliste — la plupart des références sont correctement approvisionnées, une minorité est en tension :

| Situation | Part | Niveau tiré |
|---|---|---|
| Sain | 62 % | entre `s` et `S` |
| À commander | 18 % | entre 35 % de `s` et `s` |
| Rupture | 8 % | entre 0 et 20 % de `s` |
| Surstock | 12 % | entre `S` et 1,9 × `S` |

### 5. Péremption (spécifique au diagnostic in vitro)

Un réactif périmé est une **perte sèche** — c'est un enjeu majeur du secteur, absent d'une gestion de stock générique. La date de péremption du lot en cours est tirée en cohérence avec la rotation : un produit qui tourne lentement porte un lot plus ancien.

```
usure_du_lot   = 25 % à 85 % de la durée de vie (plus forte si rotation < 2/an)
jours_restants = durée_de_vie × (1 − usure)
```

### 6. Valorisation

Le coût unitaire dérive du **prix de vente réel** corrigé de la **marge réelle mesurée** (28 %) : `coût = prix × 0,72`. La valorisation du stock reste ainsi cohérente avec la comptabilité observée.

### 7. Reproductibilité

Graine fixée (`SIMULATION_SEED = 42`) **et** ordre de traitement strictement déterministe (`ORDER BY qte_totale DESC, produit ASC` — sans le tri secondaire, les ex-aequo changeaient l'ordre des tirages et la simulation n'était pas reproductible : défaut détecté par `test_reproductibilite_de_la_graine`).

---

## Indicateurs calculés

| Indicateur | Formule | Décision éclairée |
|---|---|---|
| Couverture (jours) | `stock ÷ d` | combien de temps je tiens |
| Taux de rotation | `coût annuel écoulé ÷ valeur du stock` | mon stock tourne-t-il ? |
| Taux de service estimé | part des produits au-dessus de `SS` | risque de rupture client |
| Valeur immobilisée | `Σ stock × coût_unitaire` (surstock) | trésorerie bloquée |
| Jours avant rupture | `(stock − SS) ÷ d` | urgence de la commande |
| Quantité à commander | `S − stock` si `stock ≤ s` | combien commander |
| Perte par péremption | `stock − d × jours_restants` valorisé | perte sèche à venir |

**Résultats sur la simulation actuelle** (graine 42, 1 914 références) :

| | Valeur |
|---|---|
| Valorisation du stock | 7,09 M DT |
| Couverture moyenne | 160 j |
| Taux de rotation | 5,7 ×/an |
| Taux de service estimé | 96,5 % |
| À commander | 325 références |
| En rupture | 163 références |
| Trésorerie immobilisée (surstock) | ~1,6 M DT |
| Perte par péremption prévisionnelle | ~45 K DT |

---

## Le marquage : où le caractère simulé est signalé

| Emplacement | Marquage |
|---|---|
| Base de données | colonne `is_simulated BOOLEAN` sur **chaque ligne** de `stock_simule` |
| Traçabilité | table `stock_simule_meta` : graine, date, modèle, avertissement |
| API `/api/stock` | champ `is_simulated: true` + `avertissement` dans chaque réponse |
| Interface | **bandeau orange non masquable**, en tête de l'onglet Stock |
| Agent de la flotte | ne lit **jamais** la simulation, même en repli : sans flux réels, le volet stock se tait ; avec, son constat porte `is_simulated: false` et l'origine des chiffres (les factures) |
| Documentation | ce fichier, référencé depuis le README et le rapport de métriques |

Quatre tests vérifient ce marquage (`test_stock.py`) — dont `test_chaque_ligne_est_marquee_en_base` et `test_agent_stock_ne_presente_jamais_la_simulation_comme_reelle`. **Ce sont les tests les plus importants du fichier** : leur échec signalerait un risque de présenter du synthétique comme du réel.

---

## Ce qui change le jour où le stock réel arrive

L'architecture est prête. Il suffirait de remplacer la table `stock_simule` par les données ERP réelles en conservant le schéma :

| Colonne | Source réelle attendue |
|---|---|
| `stock_actuel` | état des stocks ERP |
| `demande_jour` | déjà calibré sur le réel — inchangé |
| `lead_time_jours` | délais contractuels fournisseurs |
| `date_peremption` | numéros de lot et DLC |
| `is_simulated` | passe à `FALSE` |

Les indicateurs, alertes, agent et interface fonctionneraient **sans modification** : seul le drapeau change, et le bandeau disparaît.

---

## Commandes

```bash
python -m ml_engine.stock.generator            # génère (idempotent)
python -m ml_engine.stock.generator --force    # régénère
python -m ml_engine.stock.generator --stats    # répartition par situation
python -m ml_engine.stock.stock_engine         # indicateurs en console
python -m pytest tests/test_stock.py -v        # 18 tests
```

---

## Ce qu'il faut dire au jury

> « L'ERP ne contient aucune donnée de stock — je l'ai vérifié sur les 32 fichiers. Plutôt que de laisser un trou fonctionnel ou d'inventer des chiffres en silence, j'ai construit un simulateur calibré sur la demande réelle, avec une politique (s,S) classique, et je l'ai marqué comme simulé partout : en base, dans l'API, à l'écran, dans le briefing de l'agent — avec des tests qui vérifient ce marquage. Le jour où l'entreprise fournit ses stocks, je remplace une table et le module fonctionne à l'identique. »
