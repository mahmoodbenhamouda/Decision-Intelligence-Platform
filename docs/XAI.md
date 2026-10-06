# Explicabilité : pourquoi ce client, ce devis, ce produit

## Le problème

Un tableau de bord qui affiche « ce client a 78 % de risque de partir » demande
un acte de foi. Le commercial ne peut ni vérifier, ni contredire, ni même savoir
quoi dire au téléphone. Et quand un directeur ne peut pas contester un
classement, il cesse de le lire.

Chaque classement de la plateforme porte donc sa justification, à l'endroit où
la décision se prend : un bouton **« Pourquoi ? »**, des faits chiffrés, et leur
poids.

## Le principe : trois éléments produits séparément

Une explication affichée se décompose en trois parties, et c'est leur séparation
qui garantit qu'elle ne peut pas être fausse :

| Élément | D'où il vient | Peut-il se tromper ? |
|---|---|---|
| **Libellé** de la variable | table `LIBELLES` — une traduction, rien d'autre | non : il n'affirme rien |
| **Sens** (aggrave / protège) | signe de la contribution, donc du **coefficient appris** | non : c'est le modèle qui parle |
| **Position** de la valeur | centile dans la distribution du parc, ou côté de la moyenne | non : c'est un calcul sur les données |

L'écran lit par exemple :

```
jours depuis la dernière commande : 6 mois — 99ᵉ centile du parc      83 %
commandes sur 12 mois : 21 — 15ᵉ centile du parc                     11 %
En sens inverse : chiffre d'affaires sur 6 mois : 138 K DT — 97ᵉ centile
→ jours depuis la dernière commande à 53 j ramène le score sous le seuil
```

### Le défaut que cette séparation a corrigé

Les trois éléments étaient auparavant fondus dans une phrase écrite à la main,
une par variable, dans `churn_model.py` :

```python
"tendance_freq": "il commande moins souvent qu'avant",
```

Or une contribution positive peut venir d'un coefficient positif avec une valeur
haute **ou** d'un coefficient négatif avec une valeur basse. La phrase, elle,
tranchait une fois pour toutes. Résultat servi en production pour le client
`CE000001` : `tendance_freq = 2.0` — c'est-à-dire `commandes récentes /
commandes antérieures = 2`, soit **deux fois plus** de commandes qu'avant — et
l'écran affichait « il commande moins souvent qu'avant ». Deux autres phrases du
même client disaient « chiffre d'affaires en retrait » devant 138 181 DT et
« seulement 21 commandes » devant un rythme de deux par mois.

Du français écrit à la main dans un fichier de modèle est toujours le signe
qu'une hypothèse non testée s'est glissée dans le pipeline.

`tests/test_explication.py::test_aucun_libelle_naffirme_une_direction` échoue
désormais si un libellé contient « faible », « en retrait », « moins souvent » ou
l'un des trente autres termes de `VERBES_DE_DIRECTION`. Et
`test_aucun_gabarit_de_phrase_dans_les_modules_de_modeles` parcourt tout
`ml_engine/` à la recherche d'une table de phrases réintroduite — après avoir
d'abord vérifié, sur le code exact qui a été retiré, qu'il sait la reconnaître.

## Une seule lecture : les raisons

Tout le monde — client, employé, directeur — voit **les mêmes raisons**, sans un
mot de technique. La mécanique du calcul n'est affichée à personne : un écran de
travail sert à décider quoi faire. Le chiffre en écarts-types existe, mais il
reste dans le champ `ecart_type` des données, pour cette documentation et les
rapports ; la phrase servie à l'écran porte un centile ou rien.

Cette mécanique n'a pas disparu pour autant : elle est **ici**, avec les chiffres
qui la vérifient. C'est là qu'elle se défend — dans un mémoire ou face à un jury
— et non dans un tableau de bord.

## Les quatre techniques, et sur quel modèle

`ml_engine/explication.py` est le seul module qui rédige. Chaque lot de raisons
porte sa méthode.

### 1. Modèles linéaires — attribution additive locale EXACTE

*Décrochage client, conversion des devis.*

```
contribution(variable) = coefficient × (valeur − moyenne) / écart-type
```

Nom exact de la méthode : **attribution additive locale**. Elle est *locale* (une
explication par client), *additive* (la somme reconstitue l'écart de logit) et
*exacte* (aucun échantillonnage). Pour un modèle linéaire à variables
indépendantes, les valeurs de Shapley valent φⱼ = βⱼ(xⱼ − E[xⱼ]) : c'est
**littéralement la formule ci-dessus**. Appeler `shap.LinearExplainer` ici
redonnerait les mêmes nombres au prix d'une dépendance.

`test_la_somme_des_contributions_reconstitue_le_score_du_modele` le vérifie au
flottant près (< 1e-9).

### Les coefficients viennent du modèle SERVI, plus d'un substitut

Le modèle de décrochage servi est un `CalibratedClassifierCV` : ses coefficients
ne sont pas directement lisibles. Une régression logistique était donc
réentraînée sur tout le panel « pour expliquer seulement », et l'accord des deux
classements était publié (Spearman 0,998).

C'était la variante faible du XAI — un **modèle de substitution** explique un
proxy, pas le modèle qui décide, et celui-ci voyait en plus la période de test.

Un calibrateur contient K estimateurs ajustés, un par pli, et sert la moyenne de
leurs sorties. **La moyenne de K fonctions linéaires est elle-même linéaire** :

```
pente*  = moyenne_k(βk / σk)        σ* = moyenne_k(σk)
β*      = pente* × σ*               μ* = moyenne_k(βk·μk/σk) / pente*
```

`extraire_pipeline_lineaire` l'extrait donc telle quelle. Plus aucun modèle n'est
entraîné pour expliquer. `test_les_coefficients_viennent_du_modele_servi_pas_dun_substitut`
vérifie que la reconstitution reproduit la moyenne des K fonctions internes à
moins de 1e-9 — mesuré à **1,8 × 10⁻¹⁵**, soit le flottant.

Ce qui est publié désormais n'est plus l'accord avec un substitut mais la
**monotonie** entre la somme des contributions et la probabilité servie : elle
vaut 1 quand la calibration ne fait que déformer l'échelle sans changer l'ordre —
c'est alors le même modèle qui est expliqué et qui décide.

### 2. Modèle d'ensemble — SHAP

*Érosion de marge (gradient boosting).*

Des centaines d'arbres n'ont pas de coefficient lisible. On calcule des **valeurs
de Shapley** (`shap.TreeExplainer`) : la seule attribution dont la somme égale
l'écart à la prédiction moyenne. Le calcul est fait à la demande, sur les seules
lignes affichées — 0,1 ms par client.

`shap` est une dépendance optionnelle. Son absence ne fait plus disparaître
l'encart en silence : `predire()` renvoie un bloc `explication` portant le motif
exact (`la librairie shap n'est pas installée`). L'`except` muet qui avalait
l'échec est supprimé.

### 3. Règles servies — le seuil lui-même

*Conditions de crédit, fin de commercialisation.*

Aucun modèle appris : l'explication est la règle. Valeur observée, seuil, écart.
Un magasinier peut vérifier chaque raison dans l'ERP.

Le seuil n'est plus écrit qu'**une fois**, dans la déclaration de la règle : les
phrases qui le recopiaient (`"règle au-delà de 90 jours"`) sont supprimées, et
`raisons_seuils` lève une `ValueError` si une règle en fournit encore une — deux
déclarations du même seuil se désynchronisent au premier changement.

Une variable qui franchit plusieurs seuils déclarés (90 jours **et** 60 jours)
n'apparaît plus qu'une fois, au seuil le plus fort : les deux lignes disaient la
même chose et chassaient une autre raison de la liste.

### 4. Recommandation de produits — les faits d'adoption

Le classement vient du modèle retenu par la mesure ; les raisons affichées sont
les grandeurs **observées** qui le fondent. C'est annoncé comme tel : elles
décrivent un contexte, elles ne décomposent pas le score du réseau.

## Ce que l'explication répond en plus : le contrefactuel

L'attribution répond « pourquoi ce score ». Un commercial se demande « que
faire ». Les **explications contrefactuelles** (Wachter et al., 2017) sont une
famille distincte de XAI, et sur un modèle linéaire la réponse est en **forme
close** : la valeur d'une variable qui ramène le score au seuil s'obtient en
résolvant une équation à une inconnue.

```
x'ⱼ = xⱼ + (cible − score) × σⱼ / βⱼ
```

Trois garde-fous, parce qu'une valeur mathématiquement correcte n'est pas
forcément une action :

- **direction réelle** — `recence_j` ne peut que baisser (en passant commande),
  `freq_3m` que monter ; l'ancienneté d'une relation ne peut pas diminuer ;
- **bornes observées** — les minima et maxima sont relevés sur le panel, jamais
  écrits en dur : un contrefactuel qui exigerait une valeur jamais vue est une
  fiction, pas un conseil ;
- **seuil relevé, non supposé** — la calibration isotonique est monotone mais non
  paramétrique, donc le score linéaire et la probabilité servie ne vivent pas sur
  la même échelle. Le seuil de score est **interpolé** sur la population pour
  correspondre à 0,5 de probabilité.

## Mesurer la fidélité, pas seulement l'accord

Un chiffre de corrélation dit que deux scores classent pareil. Il ne dit rien sur
la justesse des **raisons**. `fidelite_suppression` mesure cela directement par
une **courbe de suppression** : on remplace les k variables les plus attribuées
par leur valeur de référence, k de 1 à 5, et on mesure la chute du score moyen —
puis on recommence avec k variables tirées **au hasard**.

| | k=1 | k=2 | k=3 | k=4 | k=5 |
|---|---|---|---|---|---|
| guidée par les attributions | 0,214 | 0,249 | 0,266 | 0,274 | 0,279 |
| choix aléatoire | 0,002 | 0,015 | 0,025 | 0,038 | 0,046 |

Un écart d'aires positif signifie que les variables désignées portent réellement
le score. Un écart nul signifierait que l'explication ne désigne rien de
particulier — **quelle que soit la qualité du modèle**, ce qui est précisément ce
qu'aucune métrique de performance ne peut révéler.

Le rapport des aires n'est publié que si l'aire aléatoire est franchement
positive : remplacer des variables au hasard fait monter le score aussi souvent
qu'il le fait baisser, donc cette aire avoisine zéro et un rapport y serait
instable. L'écart, lui, se lit toujours.

Deux tests encadrent la mesure, dont un **contrôle négatif** : des attributions
tirées au hasard doivent faire *moins* bien que les vraies. Sans lui, le premier
test ne prouverait rien.

## Ce que SHAP permet de publier (et ce qu'il ne permet pas)

SHAP n'est pas une métrique de performance : il n'existe pas d'« AUC de SHAP ».
`python scripts/diagnostics_shap.py` recalcule quatre chiffres vérifiables et
écrit `reports/explicabilite_marge.json` :

| Chiffre | Valeur mesurée | Ce qu'il prouve |
|---|---|---|
| **Additivité** (erreur max) | **5,3 × 10⁻¹⁵** | `base + Σ contributions = sortie du modèle`. Propriété fondatrice des valeurs de Shapley : si elle tombait, l'attribution ne décrirait plus le modèle. |
| **Valeur de base** | **−1,73** en log-odds, soit **15,1 %** | La sortie moyenne — le client dont on ne saurait rien. Chaque contribution se lit comme un écart à cette référence. |
| **Importance globale** | marge 12 mois 19,9 %, marge 3 mois 19,8 %, délai accordé 15,1 % | Ce qui compte le plus, toutes décisions confondues (moyenne des \|contributions\|). |
| **Accord avec l'importance par permutation** | **Spearman 0,698** | Deux méthodes indépendantes classent les variables de façon comparable. |

### Une précision d'honnêteté sur le mot « approché »

Pour un modèle d'arbres, TreeSHAP calcule les valeurs de Shapley **exactement** :
l'erreur d'additivité ci-dessus est celle du flottant. L'approximation n'est pas
arithmétique, elle est dans l'**hypothèse** — SHAP suppose une manière
particulière de traiter les variables corrélées. Entre la marge à 3 mois et la
marge à 12 mois, qui varient ensemble, la répartition du mérite dépend de ce
choix.

La formule juste est donc « somme exacte, répartition dépendante d'une
hypothèse » — et c'est ce document, non l'écran, qui la porte.

## Ce que le module refuse de faire

- **Affirmer une direction.** Aucun libellé ne contient de verbe de sens ; le
  sens vient du coefficient appris.
- **Inventer une phrase pour une variable inconnue.** Une variable sans libellé
  ressort sous son nom rendu lisible — jamais avec une interprétation plausible
  mais fausse. `test_toute_variable_servie_possede_un_libelle` vérifie en outre
  que les quatre modèles servis n'en ont aucune.
- **Expliquer un modèle qui n'a pas la forme attendue.**
  `extraire_pipeline_lineaire` rend `None` plutôt qu'une décomposition
  approximative, et l'appelant publie le motif.
- **Qualifier sans seuil déclaré.** « Élevé » suppose une frontière que personne
  n'a écrite : la position est un centile ou le côté de la moyenne, pas un
  adjectif.
- **Masquer ce qui rassure.** Le facteur qui pousse le plus en sens inverse est
  affiché, avec `sens: protege` et **sans pourcentage** — lui en donner un
  laisserait croire qu'il appartient à la même somme de 100 %.

Deux défauts réels corrigés au passage. Le premier : les contributions du
décrochage étaient servies brutes, en unités de logit — l'écran affichait
« 683 % ». Le second, découvert en remaniant : `kpi_engine` renormalisait une
seconde fois des parts déjà normalisées, et transformait le `poids: None` du
facteur protecteur en `0.0` — soit une barre « 0 % » pour le seul facteur qui
n'en a pas. La normalisation n'a plus qu'un seul propriétaire.

## Où c'est visible

| Onglet | Ce qui est expliqué |
|---|---|
| **Rétention** | pourquoi ce client est signalé, **et ce qui le sortirait de la zone de risque** |
| **Devis & marge** | pourquoi ces trois devis-là, pourquoi cette rentabilité baisse, pourquoi ce produit chez ce client |
| **Stock** | pourquoi cette référence est en fin de commercialisation |
| **Priorités** | le détail d'une action reprend les raisons des clients cités |
| **Risque crédit** | quels seuils ce client franchit, et de combien |

## Vocabulaire

La table `LIBELLES` associe à chaque variable un **nom** et un **formateur
d'unité**. Sans elle, l'écran afficherait `tendance_freq = 2.0`. Avec elle, il
affiche le nom, la valeur en unités lisibles, et la position — jamais un
jugement.

| Variable | Libellé (aucune direction) | Exemple servi |
|---|---|---|
| `tendance_freq` | commandes récentes sur commandes antérieures | « × 2,00 — 88ᵉ centile du parc » |
| `recence_j` | jours depuis la dernière commande | « 6 mois — 99ᵉ centile du parc » |
| `marge_3m_pct` | marge sur 3 mois | « 18,2 % — 4ᵉ centile du parc » |
| `ratio_montant_vs_habituel` | montant rapporté à ses devis habituels | « × 3,40 — 96ᵉ centile du parc » |
| `mois_sans_vente` | mois sans aucune vente | « 9 mois — au-dessus de 6 mois » |

`tests/test_explication.py` interdit dans ces phrases le jargon, le tiret bas
(qui trahirait un nom de variable recopié tel quel) et **« écart-type »** : la
valeur en écarts-types reste dans les données, pas sur l'écran.

## Tests

`tests/test_explication.py` — **25 tests**, dont 6 marqués `vitrine` :
exactitude de la décomposition, extraction depuis le modèle servi, parts
totalisant 100 %, sens issu du coefficient et non du libellé, absence de verbe de
direction, absence de jargon, refus d'expliquer un modèle de forme inattendue,
dédoublonnage des seuils, refus d'une phrase écrite à la main, contrefactuel
atteignant exactement le seuil et refusant les valeurs non observées, fidélité
avec son contrôle négatif, et balayage de `ml_engine/` contre le retour d'une
table de phrases.

## Installation

```bash
pip install shap                          # nécessaire uniquement pour l'érosion de marge
python scripts/diagnostics_shap.py        # recalcule les quatre chiffres ci-dessus
```

Sans `shap`, tout le reste de l'explicabilité fonctionne — et l'absence est
annoncée, non subie.
