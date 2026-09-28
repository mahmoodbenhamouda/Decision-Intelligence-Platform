# Explicabilité : pourquoi ce client, ce devis, ce produit

## Le problème

Un tableau de bord qui affiche « ce client a 78 % de risque de partir » demande
un acte de foi. Le commercial ne peut ni vérifier, ni contredire, ni même savoir
quoi dire au téléphone. Et quand un directeur ne peut pas contester un
classement, il cesse de le lire.

Chaque classement de la plateforme porte donc sa justification, à l'endroit où
la décision se prend : un bouton **« Pourquoi ? »**, trois phrases chiffrées en
français, et leur poids.

## Une seule lecture : les raisons

Tout le monde — client, employé, directeur — voit **les mêmes raisons**, en
français, sans un mot de technique.

La mécanique du calcul n'est affichée à personne. Un écran de travail sert à
décider quoi faire, pas à expliquer comment un score a été obtenu : le directeur
qui prépare un appel n'a pas plus besoin de lire « valeurs de Shapley » que le
client. C'est la même règle que pour les métriques de modèles, retirées des
écrans.

Cette mécanique n'a pas disparu pour autant : elle est **ici**, dans la
documentation du projet, avec les chiffres qui la vérifient
(`scripts/diagnostics_shap.py`). C'est là qu'elle se défend — dans un mémoire ou
face à un jury — et non dans un tableau de bord.

## Trois familles de modèles, trois techniques

Le module `ml_engine/explication.py` ne connaît qu'une seule manière de mentir :
présenter une approximation comme une certitude. Chaque lot de raisons porte
donc sa méthode et son drapeau `exacte`.

### 1. Modèles linéaires — décomposition EXACTE

*Décrochage client, conversion des devis.*

```
contribution(variable) = coefficient × (valeur − moyenne) / écart-type
```

Sur une régression logistique, `ordonnée à l'origine + Σ contributions` redonne
**exactement** le logit du modèle. Ce n'est pas une façon de parler :
`test_la_somme_des_contributions_reconstitue_le_score_du_modele` le vérifie au
flottant près (< 1e-9). C'est ce qui autorise le mot « exacte » à l'écran.

Le modèle de décrochage servi est *calibré* : ses coefficients ne sont pas
directement lisibles. Une régression logistique simple est donc ajustée sur les
mêmes données **pour expliquer seulement**, et l'accord entre les deux
classements est publié : **0,998** (Spearman). Une valeur basse signifierait que
l'explication décrit un autre modèle que celui qui décide — l'interface affiche
ce chiffre au directeur.

### 2. Modèle d'ensemble — SHAP

*Érosion de marge (gradient boosting).*

Des centaines d'arbres n'ont pas de coefficient lisible. On calcule des
**valeurs de Shapley** (`shap.TreeExplainer`) : la seule attribution dont la
somme égale l'écart à la prédiction moyenne. Le calcul est fait **à la demande,
sur les seules lignes affichées** — expliquer 1 100 clients pour un écran qui en
montre quinze serait du gaspillage.

`shap` est une dépendance **optionnelle** : si elle manque, le classement sort
sans justification plutôt qu'avec une approximation silencieuse.

### 3. Règles servies — le seuil lui-même

*Conditions de crédit, fin de commercialisation.*

Aucun modèle appris : l'explication est la règle. Valeur observée, seuil, écart.
Un magasinier peut vérifier chaque raison dans l'ERP — ce qu'aucune attribution
statistique ne permet.

Le poids affiché suit le **poids métier** de la règle, modulé (jamais renversé)
par l'ampleur du dépassement : un stock vingt fois supérieur à son seuil ne
passe pas devant « six mois sans la moindre vente ».

### 4. Recommandation de produits — les faits d'adoption

Le classement vient du modèle retenu par la mesure ; les raisons affichées sont
les grandeurs **observées** qui le fondent (adoption chez les établissements
comparables, nombre d'acheteurs, montant annuel médian). C'est annoncé comme
tel : ces raisons décrivent un contexte, elles ne décomposent pas le score du
réseau.

## Ce que SHAP permet de publier (et ce qu'il ne permet pas)

SHAP n'est **pas une métrique de performance** : il n'existe pas d'« AUC de
SHAP ». C'est une méthode d'attribution. Quatre chiffres sont néanmoins
mesurables et vérifiables — `python scripts/diagnostics_shap.py` les recalcule
et écrit `reports/explicabilite_marge.json` :

| Chiffre | Valeur mesurée | Ce qu'il prouve |
|---|---|---|
| **Additivité** (erreur max) | **5,3 × 10⁻¹⁵** | `base + Σ contributions = sortie du modèle`. C'est la propriété fondatrice des valeurs de Shapley : si elle tombait, l'attribution ne décrirait plus le modèle. |
| **Valeur de base** | **−1,73** en log-odds, soit **15,1 %** | La sortie moyenne du modèle — le client dont on ne saurait rien. Chaque contribution se lit comme un écart à cette référence. |
| **Importance globale** | marge 12 mois 19,9 %, marge 3 mois 19,8 %, délai accordé 15,1 % | Ce qui compte le plus dans le modèle, toutes décisions confondues (moyenne des \|contributions\|). |
| **Accord avec l'importance par permutation** | **Spearman 0,698** | Deux méthodes indépendantes classent les variables de façon comparable. Un accord faible signalerait que l'une des deux décrit mal le modèle. |

S'y ajoute le **coût** : 0,09 s pour les 993 clients du parc, soit 0,1 ms par
client. C'est ce qui autorise un calcul à la demande, sans précalcul ni fichier
à maintenir.

### Une précision d'honnêteté sur le mot « approché »

Pour un modèle d'arbres, TreeSHAP calcule les valeurs de Shapley **exactement** :
l'erreur d'additivité ci-dessus est celle du flottant. L'approximation n'est pas
arithmétique, elle est dans l'**hypothèse** — SHAP suppose une manière
particulière de traiter les variables corrélées. Entre la marge à 3 mois et la
marge à 12 mois, qui varient ensemble, la répartition du mérite dépend de ce
choix. C'est cette limite que l'interface annonce, et non une prétendue
imprécision de calcul.

La formule juste est donc « somme exacte, répartition dépendante d'une
hypothèse » — et c'est ce document, non l'écran, qui la porte.

## Ce que le module refuse de faire

- **Inventer une phrase pour une variable inconnue.** Une variable sans libellé
  métier ressort sous un nom neutre — jamais avec une interprétation plausible
  mais fausse.
- **Expliquer un modèle qui n'a pas la forme attendue.** `extraire_pipeline_lineaire`
  rend `None` plutôt qu'une décomposition approximative.
- **Afficher des poids incohérents.** Les parts publiées totalisent 100 % des
  facteurs qui poussent dans le sens du signalement. Le facteur en sens inverse
  est écrit **sans pourcentage** : lui en donner un laisserait croire qu'il
  appartient à la même somme.

Un défaut réel corrigé au passage : le modèle de décrochage enregistrait des
contributions brutes, en unités de logit. L'écran affichait « 683 % ». Elles
sont désormais converties en parts au moment d'être servies.

## Où c'est visible

| Onglet | Ce qui est expliqué |
|---|---|
| **Rétention** | pourquoi ce client est signalé, sur chaque ligne de la liste d'appels |
| **Devis & marge** | pourquoi ces trois devis-là, pourquoi cette rentabilité baisse, pourquoi ce produit chez ce client |
| **Stock** | pourquoi cette référence est en fin de commercialisation |
| **Priorités** | le détail d'une action reprend les raisons des clients cités |
| **Risque crédit** | quels seuils ce client franchit, et de combien |

## Vocabulaire

Le cœur du module est une table de phrases, une par variable. Sans elle,
l'écran afficherait `tendance_freq = 2.0`, qui n'explique rien à personne.

| Variable | Ce que lit l'utilisateur |
|---|---|
| `tendance_freq` | « il commande moins souvent qu'avant » |
| `recence_j` | « dernière commande il y a 7 mois » |
| `marge_3m_pct` | « marge tombée à 18,2 % sur 3 mois » |
| `ratio_montant_vs_habituel` | « devis 3,4 fois plus gros que ses devis habituels » |
| `mois_sans_vente` | « 9 mois sans la moindre vente sur les 12 derniers » |

`tests/test_explication.py` interdit le jargon **et le tiret bas** dans ces
phrases : un tiret bas trahirait un nom de variable recopié tel quel.

## Tests

`tests/test_explication.py` (10 tests, dont 2 marqués `vitrine`) contrôle les
promesses affichées : exactitude de la décomposition, parts totalisant 100 %,
absence de jargon, refus d'expliquer un modèle de forme inattendue, et ordre des
raisons d'une règle.

## Installation

```bash
pip install shap                          # nécessaire uniquement pour l'érosion de marge
python scripts/diagnostics_shap.py        # recalcule les quatre chiffres ci-dessus
```

Sans `shap`, tout le reste de l'explicabilité fonctionne.
