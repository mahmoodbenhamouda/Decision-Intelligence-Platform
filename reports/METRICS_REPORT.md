# Rapport de métriques ML — plateforme d'intelligence décisionnelle Overlyne

*Sources : `reports/credit_risk_metrics.json`, `reports/churn_metrics.json`,
`reports/segmentation_metrics.json`, `reports/demande_hybride_metrics.json`,
`reports/cashflow_carnet_metrics.json`, `reports/stock_risk_metrics.json`,
`reports/stock_flux_metrics.json`, `reports/encours_metrics.json`,
`reports/impact_metrics.json`, `reports/derive_metrics.json`,
`reports/synchro.json`. État consolidé exécutable : `python -m ml_engine.registre`.*

## Ce que la plateforme sert, et sous quelle forme

Onze modules ont été construits et mesurés ; **huit sont servis** — dont **quatre
modèles supervisés et un non supervisé**, un **réseau de neurones Wide & Deep**
mesuré en challenger (§8) — les trois autres servant une règle ou une
statistique. Des trois écartés, **deux sont refusés** parce qu'une règle d'une
variable les égalait, et **un est retiré** pour une raison qu'aucune métrique ne
peut voir : sa cible dépend de dates simulées.

Le décompte exact se lit à l'exécution (`python -m ml_engine.registre`) et non
dans ce document : c'est le registre qui décide, pas le rapport.

Cette proportion est un résultat, pas un manque. Lorsqu'une grandeur est
contractuelle, déjà inscrite dans les données, ou que sa variation n'est que du
bruit, l'apprentissage n'ajoute que de l'opacité — et chacun de ces trois cas a
été **mesuré** avant d'être conclu, jamais supposé.

| Module | Nature | Métrique hors période | Référence à battre |
|---|---|---|---|
| **Décrochage client** | modèle appris | AUC **0,9224** | 0,9002 (fréquence seule) |
| **Érosion de marge client** | modèle appris | AUC **0,7969** | 0,7620 (marge des 3 derniers mois) |
| **Conversion des devis** | modèle appris | AUC **0,7165** | 0,6823 (montant inverse) |
| **Risque produit** | mesuré puis **retiré** | AUC 0,8562 groupé par produit | cible partiellement simulée — retiré du service |
| **Typologie de clientèle** | modèle non supervisé | silhouette **0,468–0,473** · stabilité **0,942–0,964** | seuils 0,25 / 0,60 |
| **Conditions de crédit** | règle déterministe | AUC **0,9200** | 0,5 (hasard) |
| **Échéancier à 1 mois** | lecture du carnet | MAPE **1,27 %** | 11,91 % (dernier mois) |
| **Demande mensuelle** | statistique robuste | MAPE **15,71 %** | écart non significatif |
| **Recommandation de produits** | modèle appris (LightGBM) · **Wide & Deep challenger** | NDCG@10 **0,3439** (Wide & Deep **0,3501**) | 0,2872 (item-kNN) — §8 |
| **Réapprovisionnement 3 mois** | mesuré puis **refusé** | AUC **0,9297** hors période | 0,9178 (nombre d'achats sur 12 mois) — gain +0,0119 sous le seuil de 0,02 |

La dernière ligne est le résultat dont ce projet est le plus content, et c'est le
seul refus d'un modèle **bon**. 0,93 d'AUC, aucune fuite décelable, et pourtant
écarté : compter les achats de l'année atteint déjà 0,9178, et un point d'AUC
d'AUC ne paie pas un modèle à maintenir. Détail en §3 quinquies.

Le décompte à citer en soutenance est celui que produit
`python -m ml_engine.registre`, jamais celui de ce document.

Quatre autres formulations ont été mesurées puis **refusées** : la prédiction de
crédit en cold start, le correcteur appris sur la demande, l'échéancier au-delà
de deux mois, et la pertinence des appels d'offres. Le détail de chaque refus
figure dans les sections correspondantes.

**Deux mesures déterministes complètent ces modules**, et aucune n'aurait gagné à
porter un modèle : la **position de stock reconstruite** des factures d'achat et
de vente (§3 quater) et l'**encours contractuel par client** (§3 sexies). Prédire
une grandeur qui se calcule exactement n'ajouterait que de l'opacité — les deux
fournissent pourtant les montants les plus utilisés du tableau de bord.

**Un septième module a été rendu possible par cette reconstruction** : les
positions étant désormais calculables mois par mois, le **besoin de
réapprovisionnement à 3 mois** (§3 quinquies) s'apprend sur une cible
entièrement observée — un achat a eu lieu, ou non — et sur des variables toutes
issues des factures. Ses seuils de déploiement sont déclarés avant la mesure, et
le registre les applique : le tableau de bord ne l'affiche que s'il les atteint.

Le registre (`ml_engine/registre.py`) rend ces décisions **exécutables** : un
module dont les seuils ne sont pas atteints est inaccessible à l'API et au
tableau de bord, et non simplement déconseillé dans un document.

## 0 bis. Accuracy et métriques complètes de chaque classifieur (`ml_engine/metriques.py`)

*Tableau régénérable : `python scripts/tableau_metriques.py`. Tous les chiffres sont hors
période ; le seuil de décision est choisi **sur l'entraînement seul** (maximisation du F1),
jamais sur le test.*

| Module | Statut | AUC | **Accuracy** | Classe majoritaire | **Balanced accuracy** | Précision | Rappel | F1 | MCC |
|---|---|---|---|---|---|---|---|---|---|
| Décrochage client | servi | 0,9224 | **93,0 %** | 90,8 % | **72,2 %** | 0,671 | 0,466 | 0,550 | 0,523 |
| Conditions de crédit (règle) | servi | 0,9200 | **90,4 %** | 59,2 % | **91,9 %** | 0,812 | 0,996 | 0,894 | 0,823 |
| Érosion de marge | servi | 0,7969 | **77,7 %** | 78,3 % | **67,6 %** | 0,485 | 0,498 | 0,492 | 0,349 |
| Conversion des devis | servi | 0,7165 | **77,5 %** | 90,6 % | **64,0 %** | 0,203 | 0,473 | 0,284 | 0,197 |
| Réapprovisionnement 3 mois | refusé | 0,9297 | **83,5 %** | 65,1 % | **84,5 %** | 0,713 | 0,881 | 0,788 | 0,665 |
| Fin de commercialisation | refusé | 0,8346 | **95,9 %** | 97,0 % | **57,3 %** | 0,224 | 0,163 | 0,188 | 0,170 |
| Risque produit (seuil 0,5) | retiré | 0,8562 | **89,0 %** | 88,0 % | **55,2 %** | 0,892 | 0,997 | 0,941 | 0,271 |
| Crédit cold start (hors période) | refusé | 0,5973 | 41,9 % | 82,4 % | 56,4 % | — | — | 0,323 | 0,104 |

### Pourquoi l'accuracy seule tromperait — et pourquoi elle est publiée quand même

Sur une cible rare, l'accuracy est dominée par la classe majoritaire. Le décrochage concerne
9,2 % des observations de test : un classifieur qui répondrait « ne décroche pas » à tout le
monde atteindrait **90,8 %** sans détecter un seul départ. Les **93,0 %** du modèle ne valent
donc que par leur écart à cette barre, et c'est la **balanced accuracy (72,2 %)** et le **MCC
(0,52)** qui mesurent la détection réelle.

Trois lectures en découlent, toutes publiées plutôt que masquées :

* **La conversion des devis a une accuracy (77,5 %) inférieure à la classe majoritaire
  (90,6 %)**, et c'est voulu : au seuil optimisé, le modèle signale 217 devis pour en trouver 44
  signés sur 93 — il troque de l'accuracy contre du rappel, parce que la décision réelle est
  « quels devis relancer », pas « quel devis sera signé ». Au seuil conventionnel de 0,5, il
  atteindrait 90,5 % d'accuracy… en ne prédisant **aucune** signature (balanced accuracy 49,9 %).
* **La marge (77,7 % contre 78,3 %)** suit la même logique : balanced accuracy 67,6 %, MCC 0,35.
* **La règle de crédit** est la seule dont l'accuracy (90,4 %) domine largement sa classe
  majoritaire (59,2 %) : sa cible est une clause contractuelle, stable par client.

L'accuracy n'est donc jamais un critère de déploiement dans ce projet ; elle est publiée
**avec sa référence**, parce qu'un jury la demandera et qu'un chiffre sans sa barre est trompeur.

## 0 ter. Tous les modèles sont branchés sur les agents (`ml_engine/passerelle.py`)

Jusqu'ici, un seul agent consommait un modèle appris. Les agents calculaient surtout des
indicateurs, et le copilote importait `score_stock_risk` — un modèle **retiré** — sans passer
par le registre.

Une **passerelle unique** relie désormais agents, copilote et API aux modèles. Elle interroge
le registre, renvoie la méthode de repli désignée par la mesure quand un modèle est refusé, et
joint à chaque sortie sa **carte d'identité** (nature, statut, métrique hors période, accuracy,
balanced accuracy). Détail et schéma : `docs/ARCHITECTURE_AGENTS.md`.

| Agent | Modèles |
|---|---|
| Recouvrement | conditions de crédit |
| Trésorerie | échéancier à 1 mois |
| Risque client | décrochage × segmentation |
| Approvisionnement | demande mensuelle, réapprovisionnement (refusé → repli) |
| Stock | fin de commercialisation (règle servie), risque stock (retiré, jamais utilisé) |
| **Commercial** (nouveau) | conversion des devis, érosion de marge, recommandation |
| **Data Scientist** (nouveau) | registre, métriques de classification, dérive PSI |

Le croisement qui en résulte n'existait pas : dès la première exécution, l'arbitre a relevé
qu'un même hôpital cumulait **une créance à relancer et une marge en érosion** (agents
Recouvrement + Commercial) — un compte sur lequel négocier les délais et les prix en même temps.

Garanties testées (`tests/test_passerelle_agents.py`) : chaque module du registre atteint un
agent métier ; aucun agent n'importe un modèle directement ; un modèle refusé ou retiré n'est
jamais présenté comme servi ; le périmètre client ne voit ni les autres clients, ni le stock,
ni les fournisseurs, ni le registre.

## 1. Conditions de crédit client (`ml_engine/analytics/credit_risk_model.py`) — v3

> **v3 — réentraîné sur données nettoyées.** La v2 s'entraînait sur le CSV brut,
> donc sur les 5 761 avoirs traités comme des ventes et les 1 324 factures
> dupliquées. Un avoir n'est pas un événement de crédit : c'est l'annulation d'un
> précédent, et son délai `DATEPIECE → DATEECHEANCE` n'a aucun sens comme cible.
> Les deux biais gonflaient les métriques, **y compris celles qui justifiaient le
> refus de déploiement**. Il fallait donc refaire la mesure pour que la
> conclusion, quelle qu'elle soit, ait une valeur.
>
> | | v2 (données brutes) | **v3 (nettoyées)** |
> |---|---|---|
> | Factures | 128 835 | **121 754** |
> | Régime A — AUC | 0,9264 | **0,9243** |
> | Régime B — GroupKFold | 0,8116 ± 0,0185 | **0,8007 ± 0,0121** |
> | Régime B — hors période | 0,5664 | **0,5973** |
> | Référence : régression logistique | 0,6729 | **0,6651** |
> | Décision | non déployé | **non déployé** |
>
> L'AUC intra-plis a **baissé** : c'est la signature du nettoyage. L'AUC hors
> période a monté, mais reste **sous la référence triviale**. La décision est
> inchangée, et désormais fondée sur une mesure valide.

> **Ce modèle a été réfuté puis reconstruit.** La v1 affichait AUC 0,9975. Ce
> n'était pas une performance mais une **tautologie**, démontrée ci-dessous.
> Aucun modèle n'est aujourd'hui déployé sur ce domaine, et c'est le résultat
> le plus solide de cette section.

### a) Réfutation de la v1 (AUC 0,9975)

La v1 prédisait « délai accordé > 60 j » en utilisant, entre autres variables, la
**moyenne des délais passés du même client**. Trois mesures suffisent à l'invalider :

| Mesure | Valeur | Lecture |
|---|---|---|
| Écart-type du délai **intra-client** (médian) | **1,05 j** | le délai ne varie pas à l'intérieur d'un client |
| Écart-type du délai **global** | 20,72 j | toute la variance est **entre** clients |
| AUC d'une **règle à un seul seuil** (`moyenne passée > 60 j`) | **0,9183** | atteinte sans aucun apprentissage |
| Concordance de cette règle avec la cible | 86,5 % | la cible est quasi déterminée par l'historique |

Le délai de crédit est une **constante contractuelle par client**. La v1 mesurait
la mémorisation de cette constante. Formulation abandonnée.

### b) Deuxième fuite : `MODEREGL` épelle la cible

Après reformulation, l'AUC est remontée à **0,9998** — le garde-fou
`fuite_suspectee` (AUC > 0,98) a bloqué le déploiement et permis de trouver la
cause : le code de règlement **contient le délai en toutes lettres**.

| Code | Libellé | Délai médian |
|---|---|---|
| `C030` | CHÈQUE 30 JOURS | 31 j |
| `C060` | CHÈQUE 60 JOURS | 61 j |
| `V090` | Virement 90 jours | 90 j |
| `C120` | CHÈQUE 120 JOURS | 122 j |

Seul, ce champ atteint **AUC 0,9340**. Il ne prédit pas le délai, il le transcrit.
Variable versée à `_FEATURES_INTERDITES`.

### c) Formulation v2 : deux régimes

**Régime A — client connu : aucun modèle.** Le délai étant contractuel, la norme
historique du client est la meilleure estimation possible. Règle déterministe,
auditable, sans entraînement : **AUC 0,9243, accuracy 0,9048** sur 118 565 factures.
Le score publié pour ces clients est un **fait mesuré**, pas une prédiction.

Cette AUC était toutefois calculée sur l'ensemble de l'historique — le reproche
même adressé à la v1. Or « la norme passée prédit le délai futur » est une
affirmation temporelle, qui doit être vérifiée dans le sens du temps. La norme a
donc été recalculée sur les seules factures **antérieures** au 2025-05-16, puis
confrontée aux factures **postérieures** des mêmes clients :

| Protocole | AUC | Accuracy | n |
|---|---|---|---|
| Sur tout l'historique | 0,9243 | 0,9048 | 118 565 |
| **Hors période** (norme d'avant, factures d'après) | **0,9200** | 0,9043 | 23 698 |

La perte est de **0,004**. À comparer aux 0,214 perdus par le modèle cold start
entre ses deux protocoles : la règle généralise, le modèle non. C'est cette mesure
qui autorise à servir la règle.

**Régime B — client nouveau (cold start) : le seul endroit où le ML aurait un rôle.**
Variables limitées à ce qui est connu au premier contact (commercial, dépôt,
établissement, code tarif, RIB, montant, calendrier) — **aucun agrégat du client**.

| Protocole | AUC | Ce qu'il autorise |
|---|---|---|
| **GroupKFold par client** (5 plis, n=121 754, 1 136 clients) | **0,8007 ± 0,0121** | client de test jamais vu, mais **périodes brassées** |
| **Cold start hors période** (94 clients arrivés après 2025-05-16) | **0,5973** | client jamais vu **et** postérieur — la situation réelle |
| Référence : régression logistique | 0,6651 | |
| Ablation (sans `month` + `commercial`) | 0,7609 | perte 0,0398 → le signal est localisé |

Plis individuels : 0,7804 · 0,7952 · 0,8074 · 0,8160 · 0,8045.

**Décision : modèle NON déployé.** Le gain de +0,1356 AUC sur la meilleure
référence disparaît sur le seul protocole qui reproduit l'usage : sur des clients
réellement nouveaux et postérieurs, le modèle tombe à **0,5973**, sous la
régression logistique (0,6651). L'écart 0,8007 → 0,5973 **mesure une fuite
temporelle** : en GroupKFold, le modèle apprenait l'usage d'une période sur
d'autres clients de la même période.

Les clients sans historique reçoivent donc le **taux de base** (39,8 %), seule
information honnête à leur sujet — et `source` accompagne chaque score dans
`output/client_risk.json` (`regle_historique` / `taux_de_base`). Sur 1 136
clients, **969 sont scorés par la règle** et 167 par le taux de base.

C'est la **même règle d'acceptation** que celle appliquée à la prévision de
demande 30/60/90 j : un gain non confirmé hors échantillon n'est pas servi.

**Reproductibilité.** Tri SQL totalement déterministe (`date, client, piece`) :
sans le numéro de pièce en départage, l'ordre des factures d'un même client au
même jour variait, déplaçait la médiane glissante et faisait bouger toutes les
métriques — le même défaut que celui corrigé dans `stock/generator.py`. Deux
exécutions consécutives donnent désormais des métriques identiques au bit près.

**Garde-fous automatisés.** `tests/test_ml_credit.py` (17 tests) échoue si une
variable interdite réapparaît, si l'AUC redevient quasi parfaite, si le protocole
hors période disparaît du rapport, si un modèle refusé sert malgré tout ses
probabilités, ou si le bundle diverge du rapport.

**Reproduction.** `python -m ml_engine.analytics.credit_risk_model` · `python -m pytest tests/test_ml_credit.py -v`

## 1 bis. Décrochage client (`ml_engine/analytics/churn_model.py`)

> **Le premier modèle appris déployé de la plateforme.** Il existe parce que le
> précédent a échoué : aucune optimisation ne pouvait sauver la prédiction de
> crédit, dont la cible est une clause contractuelle. Il fallait changer de
> question, pas d'algorithme.

### Pourquoi cette cible plutôt que l'autre

Le délai de paiement a un écart-type de **1,07 jour à l'intérieur d'un client**
contre 20,79 jours au global. Il ne varie donc pas : il se lit. Le comportement
d'achat, lui, varie fortement chez un même client — il y a quelque chose à
apprendre.

| Critère | Délai de crédit | **Décrochage** |
|---|---|---|
| Observable sans interprétation | oui | **oui** — le client commande, ou non |
| Non trivial | non (constante contractuelle) | **oui** |
| Actionnable | non (le contrat est signé) | **oui** — une relance change l'issue |

**Cible.** Aucune commande dans les 90 jours suivant l'observation.
**Panel.** 36 601 observations (client × fin de mois), 945 clients, taux de
décrochage 8,0 %, période 2022-01 → 2026-01.

### Absence de fuite — par construction

Les variables se calculent sur `]-∞, t]`, la cible se lit sur `]t, t+90j]`.
Fenêtres disjointes : aucune variable ne peut contenir la cible.
`tests/test_ml_churn.py` le vérifie en modifiant le **futur** d'un client et en
exigeant qu'aucune variable ne bouge.

Le protocole hors période impose en outre une **marge** : une observation n'entre
à l'entraînement que si `t + 90 j ≤ coupure`. Sans elle, les dernières
observations du train verraient le début du test.

### Résultats

| Protocole | AUC |
|---|---|
| **Hors période** (entraînement passé, test futur) | **0,9224** |
| GroupKFold par client — *indicatif* | 0,9450 |
| **Écart entre les deux** | **+0,0226** |

L'écart est la mesure décisive. Il valait **+0,214** pour le modèle de crédit
(0,8116 → 0,5973), signature d'une fuite temporelle. Ici 0,023 : le modèle
généralise dans le temps.

**Références triviales** — une seule variable, aucun apprentissage :

| Référence | AUC |
|---|---|
| Fréquence de commande sur 12 mois (inversée) | 0,9002 |
| Récence seule | 0,8458 |
| Tendance du chiffre d'affaires (inversée) | 0,6527 |
| Rapport récence / intervalle habituel | 0,6162 |
| **Gain du modèle** | **+0,0222** |

### Choix de l'algorithme par parcimonie

Deux candidats voient exactement les mêmes variables : régression logistique
**0,9224**, gradient boosting **0,9243**. Deux millièmes d'écart. La régression
logistique est retenue — plus simple, interprétable par ses coefficients, plus
rapide et moins sujette à la dérive.

La distinction est méthodologique et elle décide de tout : une **référence
triviale** mesure la valeur ajoutée du modèle et fonde le déploiement ; un
**modèle candidat** répond à une autre question — la non-linéarité est-elle
nécessaire ? Les confondre ferait rejeter un bon modèle au motif qu'un autre bon
modèle existe.

### Honnêteté sur la portée

Le gain de 2,2 points s'obtient sur une référence déjà forte : « combien de
commandes sur douze mois ? » explique l'essentiel du risque. Le modèle apporte la
combinaison de plusieurs signaux, donc une meilleure robustesse — pas une
révélation.

Le classement servi suit **l'enjeu financier** (probabilité × CA 12 mois) et non
la probabilité seule : 0,9 sur un compte à 2 000 DT ne mérite pas l'attention
qu'exige 0,6 sur un compte à 2 M DT.

**Reproduction.** `python -m ml_engine.analytics.churn_model` · `python -m pytest tests/test_ml_churn.py -v`

## 1 ter. Typologie de clientèle (`ml_engine/analytics/segmentation.py`)

> **Apprentissage non supervisé.** Il n'existe aucune étiquette « type de
> client » à prédire : la typologie est à découvrir, pas à reproduire. Un modèle
> supervisé exigerait qu'un expert étiquette d'abord 938 clients à la main.

### La question posée

Le tableau de bord répond déjà à « quels clients ? » — les plus gros, ceux qui
décrochent, ceux qui paient tard. Il ne répondait pas à **« quels TYPES de
clients servons-nous ? »**. La différence est opérationnelle : une liste de 938
comptes ne se pilote pas, une poignée de segments oui.

**Données.** 938 clients, 278,4 M DT, profil comportemental à 7 variables
(récence, fréquence, montant, régularité, panier, ancienneté, étendue de gamme).
Montants et fréquences passés au **logarithme** : sans cette transformation,
quelques hôpitaux pesant mille fois un petit laboratoire réduiraient la
segmentation à « gros contre petits » — ce que le classement par chiffre
d'affaires dit déjà.

### Trois exigences, sans lesquelles une segmentation reste décorative

Un clustering produit **toujours** un résultat : c'est précisément son danger.

| Critère | Seuil posé a priori | Mesuré |
|---|---|---|
| Séparation (silhouette) | ≥ 0,25 | **0,468 à 0,473** |
| Stabilité (Rand ajusté) | ≥ 0,60 | **0,942 à 0,964** |
| Unicité des noms | vérifiée par test | ✅ |

**Les deux grandeurs sont données en fourchette, et c'est volontaire.** Elles
fluctuent d'une exécution à l'autre — bruit résiduel de KMeans, documenté et
mesuré au §5. Publier « silhouette 0,4733 » laisserait croire à une précision de
quatre décimales qui n'existe pas. Les deux critères restent très au-dessus de
leurs seuils sur toute la plage observée.

La **stabilité** est le test décisif, et le plus rarement fait. On resegmente huit
fois sur 80 % des clients tirés au hasard, puis on compare les affectations. Un
client retombe dans le même groupe dans plus de 94 % des cas : ces segments
décrivent la clientèle, non le hasard du tirage.

### Le choix de k, et une marge plus mince que je ne l'ai d'abord écrit

| k | Silhouette | Stabilité |
|---|---|---|
| 3 | 0,459 à 0,460 | 0,968 à 0,971 |
| 4 | 0,4536 | 0,959 à 0,985 |
| **5** | **0,468 à 0,473** | 0,942 à 0,964 |
| 6 | 0,315 à 0,324 | 0,831 à 0,835 |

k=5 devance k=3 de **0,008 à 0,015** de silhouette selon l'exécution. Une première
version de cette section annonçait 0,0149 — le chiffre d'un seul run, présenté
comme une marge confortable. Sur plusieurs exécutions, l'avance descend à 0,008,
soit l'ordre de grandeur de la dérive mesurée sur cette même grandeur (jusqu'à
0,0075 pour k=6).

**La conclusion honnête est donc plus prudente** : k=5 gagne à chaque exécution
observée, mais la marge n'est pas confortable, et un jeu de données légèrement
différent pourrait faire basculer le choix vers k=3. Le dire vaut mieux que de
citer le run le plus flatteur.

Sans la mesure de reproductibilité (§5), cette vérification aurait été impossible :
on aurait comparé un écart à rien — et on aurait conclu à tort qu'il était solide.

### Les cinq segments

| Profil | Clients | Part du CA | Part menacée par le décrochage |
|---|---|---|---|
| Comptes stratégiques réguliers | 605 | 84,9 % | 0,7 % — 3 468 K DT |
| Comptes stratégiques actifs | 77 | 10,0 % | **10,3 % — 3 355 K DT** |
| Comptes intermédiaires réguliers | 104 | 4,1 % | 2,2 % — 198 K DT |
| Petits comptes occasionnels — encore actifs | 96 | 0,6 % | **15,0 %** — 55 K DT |
| Petits comptes occasionnels — en sommeil | 56 | 0,4 % | — |

Les deux derniers noms portent la trace du défaut corrigé au §5 : ils sont
**tous deux qualifiés**, par récence, et non plus l'un nu et l'autre suffixé selon
un ordre de cluster arbitraire.

**Les noms sont dérivés des mesures, jamais écrits en dur.** Chaque segment est
positionné par RANG face aux autres, et l'unicité est forcée par l'ajout du trait
le plus distinctif. Un nom codé en dur deviendrait faux au premier
réentraînement sans que rien ne le signale.

*Défaut corrigé.* La première version comparait chaque segment à la médiane
**globale**. Celle-ci étant tirée par le segment majoritaire — 611 clients sur
938 — un segment pesant 10 % du chiffre d'affaires se retrouvait qualifié de
« petits comptes », et **trois segments distincts portaient le même nom**. Un nom
porté par deux groupes ne désigne plus rien. `tests/test_segmentation.py` (12
tests) verrouille l'unicité sur données synthétiques ET réelles.

### Le croisement qui justifie le module

Segmentation et décrochage se répondent : le premier dit *qui sont* les clients,
le second *lesquels partent*. Ensemble ils répondent à une troisième question —
**quel type de clientèle perdons-nous ?**

| Segment | Part menacée | Enjeu |
|---|---|---|
| Petits comptes occasionnels | 15,0 % | 55 K DT |
| **Comptes stratégiques actifs** | **10,6 %** | **3 355 K DT** |
| Comptes intermédiaires réguliers | 2,4 % | 198 K DT |
| **Comptes stratégiques réguliers** | **0,7 %** | **3 468 K DT** |

**Les deux lignes en gras sont le résultat le plus exploitable du projet.** Poids
financier quasi identique, **risque quinze fois supérieur**. La seule différence
entre ces groupes est la régularité des commandes : chez les gros comptes, **la
régularité protège**, et un compte stratégique dont le rythme se dérègle est en
danger réel.

Ni la segmentation ni le modèle de décrochage ne produisent cette lecture seuls.
Elle se traduit en règle de suivi : surveiller la régularité des grands comptes,
pas seulement leur volume.

**Reproduction.** `python -m ml_engine.analytics.segmentation` · `python -m pytest tests/test_segmentation.py -v`

## 1 quater. Conversion des devis (`ml_engine/analytics/conversion_devis.py`)

*Source : `reports/conversion_devis_metrics.json`*

**Le taux de conversion réel est de 9,0 %** — plus de neuf devis sur dix ne se
transforment jamais. Un commercial qui relance dans l'ordre d'arrivée passe donc
l'essentiel de son temps sur des dossiers morts.

C'est une question de **comportement**, pas de volume. Toutes les formulations de
volume de ce projet ont échoué, et pour une raison mesurée trois fois : la série de
demande n'a pas de signal exploitable au-delà des méthodes naïves. On ne retente
pas une prévision ; on cherche une rupture de régime, comme pour le décrochage
client.

### Le censurage à droite, et pourquoi il décide de tout

`ETATPIECE` est un **état lu aujourd'hui**, pas un événement observé sur une
fenêtre. Un devis émis la semaine dernière est encore en négociation : il porte
l'étiquette « non transformé » alors que rien n'est joué.

L'inclure apprendrait au modèle que **« récent ⇒ perdu »** — vrai dans les
données, faux dans le monde. Le modèle afficherait une AUC flatteuse en ayant
surtout appris à lire un calendrier.

| Cohortes | Taux de conversion |
|---|---|
| mûres (> 6 mois) | **10,19 %** |
| récentes (≤ 6 mois) | **7,09 %** |
| chute relative | **−30,4 %** |

La maturation déclarée de six mois est donc **confrontée à la mesure**, pas
supposée. Les devis plus récents sont écartés de l'apprentissage — et conservés
pour la prédiction, puisque ce sont les seuls encore relançables.

### Résultats

*3 956 devis mûrs · 647 clients · 2020-05 → 2025-10 · taux de base 9,3 %*

| Métrique (hors période, coupure 2024-12) | Valeur |
|---|---|
| **AUC** | **0,7165** |
| Average precision | 0,1921 |
| Brier | 0,0819 |
| **Sur-apprentissage** *(même période des deux côtés)* | **−0,0059** |
| Dérive temporelle | +0,0040 |
| **Au décile : précision / rappel / lift** | **0,2347 / 0,2473 / 2,49** |

**Lecture métier du lift.** Un commercial qui suit la liste convertit **23,5 %** au
lieu de 9,4 % : il travaille 2,5 fois mieux à effort constant.

**Le sur-apprentissage est négatif** — le modèle fait légèrement mieux en
validation qu'en entraînement. Aucune mémorisation. Et le boosting a été
**disqualifié** à +0,21 d'écart malgré trois réglages de plus en plus bridés : sur
3 000 lignes et 19 variables, le modèle simple n'est pas un compromis, c'est le bon
outil, et la mesure permet de le dire.

### Trois résultats contre-intuitifs, laissés tels quels

| Référence triviale | AUC | Ce que cela dit |
|---|---|---|
| `inverse_montant` | 0,6823 | un gros devis est plus dur à signer |
| `est_deja_client` | **0,5147** | être déjà client n'aide presque pas |
| `taux_conversion_passe` | **0,4876** | **sous le hasard** — le passé d'un client ne prédit pas ses signatures |

Les deux dernières contredisent l'intuition commerciale. Aucun signe n'a été
inversé après mesure : retoucher une référence au vu de son résultat reviendrait à
l'entraîner, et elle cesserait d'être une référence.

### Prévention de fuite, par construction et non par relecture

Les variables sont calculées **en Python et non par une agrégation SQL par
client** : une agrégation aurait donné le même profil à tous les devis d'un client,
y compris les plus anciens — fuite temporelle classique et invisible. Chaque devis
voit l'historique tronqué **strictement** avant sa date : il ne peut voir ni
lui-même, ni une facture du même jour, laquelle pourrait être sa propre
transformation.

Et `taux_conversion_passe` vaut **−1** pour un client sans devis antérieur, valeur
hors domaine. Mettre 0 aurait appris à confondre « je ne sais pas » avec « ce
client ne signe jamais ».

## 1 quinquies. Érosion de marge client (`ml_engine/analytics/marge_client.py`)

*Source : `reports/marge_client_metrics.json`*

### Pourquoi la marge d'un TRIMESTRE et non celle d'une facture

Au moment de facturer, l'entreprise **connaît son coût de revient** : prédire la
marge d'une facture existante ne prédirait rien. La cible porte donc sur les trois
mois à venir, dont ni le mix ni les négociations ne sont encore joués.

**Ce module n'existe que grâce à une colonne réputée absente.** `MTCRSIGNE`, le
coût de revient, a corrigé la marge affichée de 77 % à **28,3 %** — la vraie. Sans
lui, on ne modélise pas une marge qu'on ne sait pas calculer.

### Résultats

*31 924 observations client × mois · 898 clients actifs · seuil de marge basse
25,55 %, quantile 0,20 calculé sur le **seul** jeu d'entraînement*

| Métrique (hors période, coupure 2025-01, marge 3 mois) | Valeur |
|---|---|
| **AUC** | **0,7969** |
| Average precision | 0,4801 |
| Brier | 0,1440 |
| Sur-apprentissage | +0,0174 |
| Dérive temporelle | +0,0054 |
| **Au décile : précision / lift** | **0,5361 / 2,47** |
| **Écart apparié agrégé, IC95** | **[+0,0321 ; +0,0449]** sur 4 008 positifs |

La référence à battre était dure et c'est ce qui rend le résultat solide :
`inverse_marge_3m` atteint **0,7620**. La marge d'hier prédit donc beaucoup de
celle de demain — mais pas tout, et l'écart de +0,0349 est significatif sur un test
de quatre mille cas.

### Une hypothèse de départ réfutée, et la règle qui l'a tranchée

Ce module postulait que le **mix produit** portait le mécanisme : un client qui
glisse de l'équipement vers le réactif voit sa rentabilité changer sans qu'aucun
prix ne bouge. La famille ERP le rendait mesurable.

**C'est faux.** Le jeu complet devançait le jeu sans mix de **+0,0035** d'AUC
interne — sous le seuil de parcimonie de 0,01 du projet — et `part_equipement`
seule atteint **0,5117**, à peine mieux que le hasard. La référence triviale le
disait déjà.

*Et cela a révélé une incohérence du projet lui-même.* La règle de parcimonie
n'était appliquée qu'à la **famille d'algorithme**, jamais au **jeu de variables**.
Un jeu de variables est pourtant de la complexité au même titre : plus de colonnes
à produire, à surveiller et à voir dériver. La règle est désormais appliquée aux
deux, dans les deux nouveaux modules, et dans cet ordre — jeu le plus petit
d'abord, puis famille la plus simple.

**Coût de cette correction : 0,0071 d'AUC** (0,8040 → 0,7969), pour cinq variables
de moins et une hypothèse honnêtement réfutée.

### Deux précautions de construction

**Les marges sont des ratios de sommes, jamais des moyennes de ratios.** Un mois à
300 DT pèserait autant qu'un mois à 300 000 DT, et la marge d'un client serait
dictée par ses plus petits mois.

**Le seuil de marge basse est calculé sur le train seul**, et refixé dans chaque
pli du walk-forward. Le déduire de l'ensemble ferait entrer dans l'entraînement une
information sur la distribution du test — une fuite discrète, invisible dans toute
matrice de confusion.

## 2. Veille externe et pertinence des appels d'offres — **RETIRÉES DU PROJET**

Un modèle de pertinence d'appels d'offres (TF-IDF + régression logistique,
accuracy 0,95) et un agent de veille externe (appels d'offres TUNEPS, taux
EUR/TND, budget santé) figuraient dans les versions précédentes. **Les deux ont
été retirés**, et la raison est méthodologique.

Le reste de la plateforme s'appuie exclusivement sur l'ERP, dont chaque colonne a
été vérifiée (`docs/SEMANTIQUE_COLONNES.md`) et dont chaque indicateur est
contrôlé par des invariants comptables (`ml_engine/analytics/data_quality.py`).
La veille externe échappait à cette discipline :

- son **corpus était écrit à la main** en imitant la formulation TUNEPS — le
  modèle pouvait apprendre les régularités d'écriture de son auteur plutôt que
  celles des avis réels ;
- son hold-out ne comptait que **63 exemples** : chaque erreur pesait 1,6 point,
  et l'intervalle de confiance à 95 % autour de 0,952 s'étendait d'environ 0,87 à
  0,99. Le troisième chiffre décimal était du bruit ;
- le **taux de change** provenait d'une source en ligne dont la qualité ne
  pouvait être auditée, alors qu'il alimentait un chiffrage d'exposition ;
- aucune des deux sources n'était **reproductible** hors connexion.

Conserver un chiffre flatteur de 95 % obtenu sur un corpus auto-produit aurait
contredit la démarche suivie partout ailleurs. Le périmètre est désormais
**entièrement interne à l'ERP** : tout ce que la plateforme affiche vient de
données auditables. La flotte comptait alors 5 agents spécialistes au lieu de 6 (7 depuis §0 ter), et un
collecteur au lieu de deux.

Un test (`tests/test_auth_rbac.py::test_route_opportunites_bien_supprimee`)
vérifie que la route correspondante renvoie bien 404 : une route retirée du code
mais restée accessible rendrait la suppression incomplète sans que rien ne le
signale.

## 3. Prévision de demande (`ml_engine/forecasting/demande_hybride.py`)

> **Aucun modèle appris n'est servi ici, et ce n'est pas un défaut de réglage.**
> Le correcteur a été mis à l'épreuve à chaque pas et désactivé à chaque fois.

**Cible.** Volume mensuel d'articles facturés — *proxy assumé* : l'ERP n'expose
aucun stock, c'est donc la demande **servie**, non la demande latente.
**Série.** 63 mois exploitables, 2021-01 → 2026-03. Le début est fixé à 2021 : le
trou de 27 mois (2018-08 → 2020-10) est une bascule d'ERP, et une série qui le
traverse contient une fausse rampe. Le dernier mois est écarté car presque
toujours partiel.

### Architecture : socle statistique + correcteur de résidu

`prévision = socle(t+h) × (1 + résidu appris)`. Si le résidu est nul, la prévision
**est** celle du socle : le modèle ne peut donc pas faire structurellement pire
que la méthode dont il part. C'est la structure qui domine les compétitions de
prévision — un socle corrigé, jamais un modèle appris de zéro sur soixante points.

### Résultats — walk-forward strict, 18 pas

| Méthode | MAPE |
|---|---|
| `mediane_mobile_6` | **14,65 %** |
| **`mediane_mobile_12`** — servie | **15,71 %** |
| Hybride (socle + correcteur) | 15,71 % |
| Socle re-choisi à chaque pas | 15,78 % |
| Naïf saisonnier | 18,54 % |
| Dernier mois | 20,29 % |
| `moyenne_mobile_3` | 23,89 % |
| Saisonnier × croissance | 26,52 % |

**Trois enseignements, tous mesurés.**

*Le correcteur n'apporte rien.* Hybride et socle nu donnent **la même MAPE au
centième**. La validation interne — entraînement sur le passé, contrôle sur les
6 derniers mois connus — l'a désactivé à chaque pas. Le résidu de cette série ne
contient pas de signal apprenable.

*Re-sélectionner la méthode à chaque pas nuit.* 15,78 % contre 15,71 % pour un
socle fixe : la sélection ajoute sa propre variance sur un échantillon court.

*Moyenne et médiane divergent de 9 points* (23,89 % contre 14,65 %). C'est la
signature d'une série à valeurs extrêmes : la moyenne se laisse tirer par les mois
exceptionnels, la médiane les ignore.

### L'incertitude, mesurée plutôt que tue

Intervalle de confiance à 95 % de la MAPE, par bootstrap : **[10,06 % ; 22,57 %]**.

Sur 18 observations, la MAPE n'est pas mesurable plus finement. L'écart apparié
entre la méthode servie et `mediane_mobile_6` a un intervalle **contenant zéro** :
les deux méthodes sont statistiquement équivalentes, et le classement observé
relève du bruit d'échantillonnage.

### Pourquoi ce n'est pas la meilleure du test qui est servie

`mediane_mobile_6` obtient 14,65 %, soit 1,06 point de mieux. Elle n'est pourtant
**pas** servie : la choisir reviendrait à sélectionner une méthode en regardant le
résultat qu'on cherche à annoncer. La méthode servie est celle élue sur les seuls
mois d'entraînement, avant d'avoir vu la période de test.

Les prévisions sont accompagnées d'un **intervalle à 80 %** construit sur les
écarts réellement observés — pas sur une hypothèse de loi normale — et cet
intervalle s'élargit avec l'horizon, les pas au-delà du premier se nourrissant de
leur propre prévision.

*Dépendance fournisseur* (même module) : HHI = 7 177 (**critique**), Biomérieux
84,6 % des achats, top 3 = 89,9 %.

**Reproduction.** `python -m ml_engine.forecasting.demande_hybride`

## 3 bis. Prévision d'encaissements / trésorerie (`ml_engine/forecasting/`)

**Méthodologie.** Série mensuelle des encaissements attendus (somme TTC par mois d'échéance). Évaluation **out-of-sample walk-forward** sur les 12 derniers mois (`evaluate_cashflow.py`) : à chaque pas, ré-entraînement sur le seul passé (log1p + standardisation recalculées sur le train — aucune fuite), prédiction h=1 et h=3, comparaison à trois baselines naïves. Seed 42.

> **Le problème était mal posé.** Les modèles de série temporelle plafonnaient à
> 23-30 % de MAPE parce qu'ils tentaient de *prédire* une grandeur largement
> *observable* : une facture émise porte déjà sa date d'échéance. Deux défauts
> supplémentaires invalidaient cette première évaluation — la série interpolait
> les 27 mois absents de 2019-2020 (une fausse rampe de 447 k à 47,6 M DT), et
> incluait des mois d'échéance encore partiellement constitués.
>
> La reformulation par **carnet d'échéances** (facteurs de développement) est
> dans `carnet_echeances.py`. À l'origine T, l'encaissement de T+h se décompose
> en une part déjà inscrite au carnet — connue exactement — et un reste à
> facturer, seule part estimée.

### Résultat, toutes méthodes sur la MÊME cible et les MÊMES origines

| Horizon | Carnet | Meilleure référence triviale | Gain | Maturité du carnet |
|---|---|---|---|---|
| **h=1** | **1,3 %** | naïf dernier mois — 11,9 % | **+10,6 pts** | **99,2 %** |
| h=2 | 14,1 % | moyenne mobile 3 — 14,9 % | +0,8 pt | 52,9 % |
| h=3 | *refusé* | — | — | ~1 % (structurel) |

### Pourquoi h=1 fonctionne, et pourquoi h=3 est impossible

Distribution mesurée des délais accordés :

| Délai | Part |
|---|---|
| 0 mois (comptant) | 1,47 % |
| 1 mois | 50,60 % |
| 2 mois | 46,94 % |
| **cumul à 2 mois** | **99,01 %** |
| 3 mois | 0,97 % |

**L'horizon utile est borné par les conditions de paiement, pas par la méthode.**
À h=1 le carnet est constitué à 99,2 %, et le résidu de 1,3 % correspond aux
1,47 % de ventes au comptant émises dans le mois même : les deux mesures
concordent. À h=2 la maturité tombe à 52,9 % — conforme aux 47,9 % de factures à
délai ≥ 2 mois — et le demi-mois visible ne suffit plus à battre une moyenne
mobile. Le module **déclare lui-même l'absence de gain**.

À h=3, seules 0,98 % des factures ont un délai suffisant : le carnet est
structurellement aveugle. Un premier essai avait donné 9,3 % de MAPE, mais en
s'appuyant sur **trois factures atypiques de 425 000 DT** — une coïncidence, pas
une méthode. L'horizon est désormais **refusé explicitement** plutôt que servi.

### Un modèle appris a-t-il sa place ici ? Mesuré, puis écarté

La prévision vaut `acquis / taux de maturité`. Le taux est une **médiane
constante** — c'est la seule grandeur estimée de la formule, tout le reste étant
lu dans les factures émises. À h=2 il reste 47 % du mois à estimer : un modèle
apprenant ce taux selon le contexte pourrait, en principe, améliorer les 14,1 %.

Le diagnostic (`scripts/diag_maturite.py`) a été mené **avant** toute
modélisation, sur 61 origines.

| Estimateur du taux (walk-forward) | Erreur absolue moyenne |
|---|---|
| **Médiane globale** — actuel | **0,0587** |
| Médiane des 6 dernières origines | 0,0630 |
| Médiane du même mois calendaire | 0,0712 |

Les deux estimateurs contextuels **dégradent** l'estimation. Le taux est
dispersé (écart-type 0,087) mais ne varie pas *systématiquement* : sa variation
est du bruit. Aucun modèle ne peut exploiter du bruit — il ne peut que le
mémoriser.

**Une corrélation tautologique évitée de justesse.** Une seule variable
corrélait fortement au taux : `acquis_relatif`, avec rho = 0,533 et p < 0,0001.
Signal apparemment solide. Mais :

```
taux           = acquis / total
acquis_relatif = acquis / niveau
```

Les deux partagent le **même numérateur**. La corrélation est mécanique. Un
modèle construit dessus aurait affiché un excellent score sans valeur — la faute
exacte qui avait produit l'AUC de 0,9975 de la première version du modèle de
crédit. C'est le troisième piège de ce type rencontré sur ce projet, et le seul
qui ait été détecté **avant** d'écrire le modèle plutôt qu'après.

### Portée — limite irréductible

Cette cible est un **échéancier contractuel**, pas de la trésorerie encaissée :
l'ERP ne contient aucune date de paiement réelle (§6). Le module dit quand les
créances deviennent **exigibles**, jamais quand le client paiera. Il alimente un
plan de recouvrement, pas un plan de trésorerie.

**Reproduction.** `python -m ml_engine.forecasting.carnet_echeances` ·
vérifications : `scripts/verif_carnet_h3.py`, `scripts/verif_pic_echeances.py`

## 3 ter. Domaine Stock — deux modèles construits selon CRISP-DM (`ml_engine/models/`)

*Détail complet des six phases : `docs/CRISP_DM_STOCK.md`. Sources : `reports/demand_forecast_ml_metrics.json`, `reports/stock_risk_metrics.json`.*

**Données.** Ventes RÉELLES (6 ans d'ERP) agrégées en séries produit × mois : **328 produits, 18 782 observations, 23 variables, 0 valeur manquante**, 2021-01 → 2026-03. Découpage temporel strict : 4 plis glissants pondérés géométriquement sur le développement, **6 mois de hold-out final jamais utilisés** pour aucune décision.

> **Périmètre de ces deux modèles, après la reconstruction des flux (§3 quater).**
> Ils apprennent sur la demande réelle, mais leurs variables de position
> (`couverture_actuelle_j`, `stock`) proviennent du module (s,S) simulé. Ils
> restent donc des modèles de **hiérarchisation du risque produit**, et non la
> source des montants affichés : le capital immobilisé, les ruptures et le stock
> non écoulable servis au tableau de bord viennent désormais de §3 quater, qui ne
> contient aucune valeur simulée.

### a) Prévision de demande multi-horizon 30/60/90 j (`demand_forecast.py`)

Apprentissage **résiduel** (le modèle prédit l'écart à un socle naïf adaptatif, transformé en `log1p` signé) contre trois références naïves obligatoires.

| Horizon | Meilleure baseline CV | Meilleur modèle CV | Gain CV | Gain hold-out | Décision |
|---|---|---|---|---|---|
| 30 j | moy. mobile 3 — MAE 10,35 | XGBoost — MAE 9,86 | +4,7 % | **−2,3 %** | modèle **refusé** |
| 60 j | moy. mobile 3 — MAE 17,11 | XGBoost — MAE 16,24 | +5,1 % | **−27,7 %** | modèle **refusé** |
| 90 j | moy. mobile 3 — MAE 23,79 | XGBoost — MAE 22,34 | +6,1 % | **−14,0 %** | modèle **refusé** |

**Lecture honnête.** Les modèles gagnent 5 à 6 % en validation croisée, écart train→validation **négatif** (aucune mémorisation). Mais sur les 6 derniers mois la hiérarchie des références s'inverse : le naïf **saisonnier** (37,23 de MAE à 90 j) devance nettement la moyenne mobile (43,72), sur laquelle les modèles ont appris. Aucune information antérieure au hold-out ne permettait de l'anticiper. La règle d'acceptation — posée avant la modélisation — refuse donc le déploiement, et **c'est la baseline saisonnière qui est servie, annoncée comme telle dans l'interface**.

**Reproductibilité.** LightGBM forcé en `deterministic=True`, `force_row_wise=True`, `n_jobs=1` : sans cela l'ordre de sommation multi-thread faisait varier le gain à 90 j de +3,8 % à −14,0 % entre deux exécutions identiques.

### b) Risque de stock — péremption / rupture / surstock (`stock_risk.py`)

**Trois fuites, trouvées l'une après l'autre.** C'est le module qui a le plus
résisté, et son historique est plus instructif que sa métrique finale.

**Fuite n°1 — la cible était une formule sur les features.** La première
formulation définissait la rupture par `stock / demande < délai`, alors que ces
trois grandeurs étaient des variables explicatives : **AUC = 1,0000**. La cible a
été reformulée de manière **prospective**, constatée a posteriori sur la demande
réellement observée des 3 mois suivants (`y_h3`, jamais une feature).

**Fuite n°2 — un tiers de la cible restait un seuil sur une feature.** La
correction précédente avait laissé passer `risque_surstock`, défini par
`couverture_actuelle_j > 180 jours ET demande future < 50 % du stock`. Or
`couverture_actuelle_j` **est** une variable explicative. Un tiers de la cible —
9 876 lignes sur 18 071 — n'était donc qu'un seuil posé sur une entrée du modèle.

*Pourquoi le garde-fou ne l'a pas vu.* `test_cible_absente_des_features`
comparait les features à une **liste nommée** de colonnes interdites. Un seuil sur
une variable autorisée ne figurait dans aucune liste. La leçon est celle des
tautologies précédentes : un test qui vérifie une liste ne protège que contre ce
qu'on avait déjà prévu. Le nouveau test lit le **code** qui construit la cible et
vérifie qu'aucun nom de feature n'y apparaît — il ne dépend d'aucune liste à
maintenir.

*Correction.* La condition sur la couverture est retirée. Le surstock se définit
désormais par la seule demande future observée face à `stock_actuel`, qui n'est
pas une feature. Prédire « la demande des 3 mois suivants ne consommera pas la
moitié du stock » exige alors de **prévoir cette demande** : c'est un vrai
problème.

**Fuite n°3 — le découpage plaçait le même produit des deux côtés.** Le hold-out
était stratifié **aléatoirement**. Or le jeu compte ~18 000 lignes pour quelques
centaines de produits, et l'instantané de stock (`stock_actuel`,
`date_peremption`, donc `couverture_actuelle_j`) est joint à **toute la série
temporelle** d'un produit : ces variables sont constantes par produit.

Un découpage aléatoire donnait donc au modèle le même produit, avec les mêmes
valeurs de stock, en apprentissage et en test. Il n'avait plus qu'à mémoriser
l'identité du produit. **Fuite par duplication** — et la plus difficile à voir,
parce qu'elle est invisible dans l'écart train/validation : les deux côtés en
profitent également, l'écart reste petit, et tout paraît sain.

*Correction.* `GroupShuffleSplit` et `GroupKFold` par produit. Un produit
appartient entièrement au développement ou entièrement au hold-out.

*Et l'écart est conservé et publié.* Le bloc `audit_fuite` du rapport mesure le
même modèle avec les deux découpages. Cet écart **est** la preuve chiffrée du
défaut ; l'effacer effacerait la trace de la correction. Le registre n'accepte
que la mesure groupée, et refuse désormais aussi **par le haut** — toute AUC
≥ 0,99 est traitée comme un symptôme, non comme une réussite.

### Ce que les corrections ont coûté — et c'est le chiffre le plus parlant du rapport

| | Avant | Après | Écart |
|---|---|---|---|
| **AUC validation croisée** | 0,9200 *(StratifiedKFold)* | **0,8190** *(GroupKFold produit)* | **−0,1010** |
| **AUC hold-out** | 0,9209 *(stratifié)* | **0,8562** *(groupé)* | **−0,0647** |
| Écart train/validation, LightGBM | +0,0351 | **+0,1320** | ×3,8 |

**Dix points d'AUC en validation croisée.** C'est ce que le découpage aléatoire
offrait gratuitement au modèle. Ce chiffre n'est pas une régression : c'est la
mesure de la fuite, et l'ancien 0,92 n'a jamais correspondu à une capacité
réelle.

**Et la troisième ligne est la plus instructive.** Les écarts train/validation
ont **triplé ou quadruplé** en passant aux groupes disjoints — de +0,035 à +0,132
pour LightGBM. C'est la même fuite vue d'un autre angle : tant que train et
validation partageaient des produits, les deux côtés mémorisaient les mêmes
références, et l'écart paraissait sain. Un indicateur de sur-apprentissage cesse
de fonctionner dès que le découpage est contaminé — **il mesurait deux jeux
également fuités**.

Conséquence : trois des cinq candidats sont désormais **disqualifiés pour
sur-apprentissage**, et la contrainte a été déplacée dans la sélection plutôt que
laissée à un test qui échoue après coup (cf. ci-dessous).

### Métriques servies — protocole groupé par produit

*18 071 références · 66 produits de hold-out jamais vus à l'entraînement*

| Candidat (GroupKFold 5 plis) | AUC | Écart train/valid | Statut |
|---|---|---|---|
| random_forest | **0,8190** ± 0,0310 | +0,0979 | **retenu** |
| lightgbm | 0,8168 ± 0,0268 | +0,1320 | **disqualifié** |
| xgboost | 0,8153 ± 0,0268 | +0,1167 | **disqualifié** |
| hist_gb | 0,8124 ± 0,0285 | +0,1243 | **disqualifié** |
| regression_logistique | 0,7649 ± 0,0355 | **+0,0166** | éligible, non retenu |

| Métrique (hold-out groupé) | Valeur |
|---|---|
| **AUC** | **0,8562** |
| Précision / Rappel | 0,8916 / 0,9967 |
| F1 | 0,9412 |
| Brier | 0,0845 |
| Écart de calibration moyen | 0,0406 |
| **Audit de fuite** : même modèle, découpage aléatoire | 0,8622 *(écart +0,0060)* |
| **Ablation** sans `couverture_actuelle_j`, `hhi_clients`, `n_clients` | 0,7343 *(perte 0,1219)* |

Le modèle linéaire plafonne à 0,7649 : l'écart de 0,0913 justifie un modèle
d'ensemble plutôt qu'une règle. La calibration isotonique rend le score utilisable
comme probabilité, ce qui autorise le calcul de la **perte attendue =
probabilité × exposition** — la grandeur qui ordonne les priorités affichées.

**Marge étroite, assumée.** `random_forest` passe à +0,0979 pour un seuil à 0,10.
C'est serré, et volontairement non retouché : si un réentraînement le fait
franchir la limite, il sera disqualifié à son tour et la régression logistique
sera servie à 0,7649. Déplacer le seuil pour protéger le modèle en place serait
exactement l'inverse de ce que ce seuil sert à faire.

### Le taux de base de 88 % — ce que l'AUC ne dit pas

**88,1 % des références sont positives** (péremption 11 576, rupture 1 044,
surstock 12 369). À ce niveau, le drapeau binaire n'apprend rien : répondre
« oui » partout donne déjà 88 % de justesse, et le rappel de **0,9967** dit
précisément que le modèle fait à peu près cela. Publier l'AUC seule serait
trompeur **même en l'absence totale de fuite**.

La question utile change donc de sens :

> Ce n'est pas *« quelles références sont à risque ? »* — presque toutes. C'est
> *« lesquelles puis-je ignorer sans risque ? »*

C'est la seule direction qui produit une décision : ramener 18 000 lignes à ce qui
mérite un examen.

| Décile du score | Résultat réel | Lift | Ce que ça vaut |
|---|---|---|---|
| **le plus bas** | **44,8 %** réellement sans risque | **3,74** | la mesure qui décide |
| le plus haut | 100 % à risque | 1,14 | rien — c'est le plafond |

**Le décile bas est le seul résultat exploitable de ce modèle.** Le taux de base
négatif est de 12 % : dans le groupe que le modèle désigne comme le plus sûr,
**44,8 %** le sont effectivement, soit **3,74 fois mieux que le hasard**. C'est
une décision concrète — écarter d'emblée une partie de la liste à examiner.

**Et le décile haut est publié précisément parce qu'il ne démontre rien.** 100 %
de positifs paraît excellent ; avec 88 % de positifs partout, le lift maximal
atteignable est de **1,14**, et l'atteindre ne prouve aucune compétence. Un
rapport qui aurait mis ce 100 % en avant aurait maquillé un plafond arithmétique
en performance.

**D'où vient ce taux de base ?** Du stock **simulé**, généreux par construction :
la position médiane couvre plus de six mois de demande. Ce n'est pas la définition
de la cible qui gonfle le taux. La preuve : sur les positions **réelles**
reconstruites (§3 quater), la même question donne **22 références** au-delà de
deux ans sur 1 501. Un facteur trente entre le simulé et le réel — et c'est le
meilleur argument pour avoir reconstruit les flux.

**Ce qui est réellement servi.** Le tableau de bord n'affiche pas ce drapeau. Il
classe par perte attendue. C'est un **ordre de priorité**, pas une alerte oui/non,
et c'est la seule sortie qu'un taux de base de 88 % permette d'exploiter.

**Garde-fous automatisés.** `tests/test_ml_stock.py` échoue si une AUC redevient
quasi parfaite, si une variable construisant la cible entre dans les features, si
un **nom de feature apparaît dans le code qui construit la cible**, si le hold-out
n'est pas groupé par produit, si le modèle **servi** sur-apprend, si un candidat
au-dessus du seuil n'est pas marqué disqualifié, si un modèle non confirmé est
déployé, si le rapport diverge du modèle réellement chargé, ou si le score d'un
produit dépend du filtre d'affichage.

**Reproduction.** `python -m ml_engine.models.demand_forecast train` · `python -m ml_engine.models.stock_risk train` · `python -m pytest tests/test_ml_stock.py -v`

### c) Une simulation qui trahissait son propre profil

Défaut détecté en relisant un briefing généré, non par un test.

Le générateur déclare viser **8 % de références en rupture** (`PROFIL_SITUATION`).
Il en produisait **856 sur 1 892, soit 45 %**. Le briefing annonçait donc une
pénurie généralisée, et recommandait d'écouler des produits… manquants.

*Cause.* La situation « rupture » tire un stock entre 0 et 20 % du point de
commande — un stock bas, pas nul. Mais `round()` ramène à zéro toute valeur
inférieure à 0,5, ce qui arrive systématiquement pour les références à faible
rotation dont le point de commande vaut moins d'une unité. **Même les produits
tirés comme « sains » finissaient à zéro.**

*Correction.* Toute référence qui n'est pas explicitement en rupture porte au
moins une unité — « sain » et « stock nul » étant contradictoires par définition.
Résultat : **141 ruptures, soit 7,5 %**, conforme au profil.

*Effet de bord assumé.* Le stock dormant passe de 2,12 à 4,51 M DT. Ce n'est pas
une régression : les références à faible rotation, auparavant invisibles car
ramenées à zéro, sont désormais comptées. Un automate immobilisé pour une demande
quasi nulle **est** du capital gelé, même à une seule unité. L'ancien chiffre
sous-estimait l'immobilisation.

Deux tests verrouillent la cohérence : le taux de ruptures doit rester dans le
triple du profil visé, et aucune référence ne peut être à la fois « saine » et
vide.

## 3 quater. Du stock simulé au stock reconstruit (`ml_engine/stock/flux_reels.py`)

*Source : `reports/stock_flux_metrics.json` — `python -m ml_engine.stock.flux_reels`*

### L'objection qui a rendu le module inutilisable

Un stock simulé est honnête tant qu'il est marqué — et inutilisable pour décider.
Aucun directeur ne déstocke sur une estimation, et la première question d'un jury
comme d'un dirigeant est la même : *ce chiffre, il vient d'où ?*

### Ce qui a été trouvé dans les données

Les lignes de facture d'**achat** portent les quantités reçues, les lignes de
**vente** les quantités livrées. Le stock n'était donc pas absent : il était
**reconstructible**.

    position(référence) = Σ quantités achetées − Σ quantités vendues

**Trois vérifications avant d'exploiter ce calcul.**

| Vérification | Résultat |
|---|---|
| Rapprochement achat ↔ vente | **1 218 références** communes, **94,9 % du volume** couvert |
| Sémantique de `INDICMVTSTOCK` (champ non documenté) | déduite empiriquement : valeur `"1"` = **95,6 %** de libellés de prestation (contrat, maintenance, formation), valeur `"2"` = **0,46 %** → **`"2"` retenue** comme mouvement de stock |
| Services exclus | **129 références** écartées — un contrat de maintenance ne génère aucun mouvement |

La deuxième ligne est la plus importante méthodologiquement : plutôt que de
supposer le sens d'un code ERP, on a mesuré laquelle de ses valeurs se comporte
comme un mouvement de marchandise. Un contrat ne bouge pas de stock, un réactif
si.

### Résultats servis

| Indicateur | Valeur | Origine |
|---|---|---|
| Références suivies | **2 792** dont 1 218 rapprochées | factures réelles |
| Prestations écartées | **560** | famille produit ERP (§3 quater bis) |
| Positions positives | **1 386** | — |
| Capital immobilisé | **5 943 821 DT** | positions positives × coût d'achat réel |
| Stock non écoulable | **212 117 DT** sur 15 références | rotation > 24 mois |
| Ruptures d'approvisionnement | détectées sans niveau de stock | référence encore vendue, achats interrompus |

### La limite énoncée avant qu'on la pose

**Une variation cumulée n'est pas un inventaire.** Le stock détenu avant la
première facture connue reste inconnu. Conséquence directe : **650 références
ressortent en position négative**, ce qui ne signifie pas un stock négatif mais
qu'un stock préexistait à l'historique. Les 5 943 821 DT sont donc un
**minorant** du capital immobilisé — jamais une surestimation, ce qui est le sens
d'erreur acceptable pour un chiffre présenté à une direction.

### La péremption, sans date de péremption

L'ERP ne porte **aucune** date d'expiration, et ce module refuse d'en simuler
une. Un raisonnement donne pourtant une certitude équivalente :

> Un consommable dont le stock dépasse **deux ans** de consommation constatée
> périmera avant d'être vendu. On perd la date exacte, on gagne un signal
> mesuré.

| Paramètre | Choix | Statut |
|---|---|---|
| Seuil de perte quasi certaine | 24 mois de couverture | **déclaré**, ordre de grandeur du diagnostic in vitro |
| Seuil de rotation lente | 12 mois | **déclaré** |
| Base de calcul | l'**excédent** au-delà du seuil | mesuré — un produit à 30 mois perd 6 mois de stock, pas 30 |
| Équipements | exclus | un automate ne périme pas, il s'amortit |

**Résultat : 213 771 DT de perte quasi certaine sur 16 références**, et 54 803 DT
en rotation lente sur 34 références.

> Ces deux montants sont ceux de la dernière exécution. Le classement produit
> ayant été repris dans un module dédié (ci-dessous), ils doivent être relus dans
> `reports/stock_flux_metrics.json` après régénération : un motif de libellé
> ajouté déplace la frontière consommable / pièce détachée, donc le montant. Le
> chiffre à citer est celui du fichier, jamais celui d'un document.

### Un faux positif corrigé, et ce qu'il enseigne

La première exécution comptait parmi les pertes un *Seals kit vidas range*
(47 351 DT), un *VIDAS NSH UPGRADE KIT* (29 027 DT) et un *P.M. KIT* (14 333 DT).
Ce sont des **pièces détachées** : elles ne périment pas davantage qu'un automate,
et une pièce de rechange se détient précisément *parce que* sa rotation est lente.

**90 711 DT de faux positifs retirés** par un filtre de libellé, et
**18 références écartées sont listées nommément** dans la sortie du module —
un chiffre corrigé sans trace vérifiable ne vaut pas mieux que le chiffre faux.

**C'est aussi le maillon faible du module, et il est énoncé comme tel :** le tri
entre consommable et pièce détachée repose sur des **mots-clés de libellé**,
faute de nomenclature produit dans l'export. C'est la troisième demande de
données adressée à l'entreprise, après les dates de règlement et l'inventaire.

### Ce qui borne la confiance, calculé au même endroit que le chiffre

Deux annexes sont produites par le module lui-même, dans le même fichier de
métriques. Les reléguer ailleurs laisserait circuler la perte sans sa marge
d'interprétation.

**a) Sensibilité au seuil de deux ans.** Le seuil est déclaré, donc contestable.
Plutôt que de le défendre, le module mesure comment la conclusion se déplace sur
toute la plage plausible — 18, 24, 30 et 36 mois — et compare les dix premières
références de chaque liste.

> Le **montant** dépend du seuil. L'**ordre** des références beaucoup moins. Or
> une direction n'agit pas sur un total : elle traite les premières lignes d'une
> liste. Tant que ces lignes sont les mêmes, l'incertitude sur le seuil ne change
> aucune décision — elle ne change que le chiffre qu'on annonce.

Un test verrouille le sens de variation : la perte doit **décroître** quand le
seuil augmente, puisqu'elle porte sur l'excédent au-delà du seuil. L'inverse
signalerait une erreur de calcul.

**b) Fiabilité du classement produit** (`ml_engine/stock/nomenclature.py`). Les
motifs de libellé vivaient auparavant en deux expressions régulières au milieu de
`flux_reels.py`. Ce qui pilote la perte annoncée a désormais un module à soi,
**autorité unique** — un test échoue si `flux_reels` porte à nouveau ses propres
motifs, parce que deux jeux de motifs en parallèle divergent toujours : l'un est
corrigé, pas l'autre, et le résultat dépend alors du chemin d'appel.

## 3 quater bis. La nomenclature existait — et deux erreurs l'ont masquée

C'est la section la plus instructive de ce rapport, et elle raconte deux fautes de
méthode successives, la seconde plus coûteuse que la première.

### Faute n°1 — conclure à une absence sans avoir cherché

Ce document a longtemps annoncé, comme une limite structurelle, qu'aucune famille
produit n'existait dans l'export. Le classement consommable / pièce / équipement
reposait donc sur des **mots-clés de libellé**, avec **2 781 137 DT — 43,3 % du
stock valorisé** — classés « consommable » par défaut, faute d'avoir reconnu quoi
que ce soit.

`ARTICLE_LIBELLE_FAM_STAT1` est renseignée pour **340 912 lignes sur 340 913,
soit 99,9 %**. La colonne était même déjà lue par `kpi_engine`. Personne n'avait
interrogé son contenu.

### Faute n°2 — un `except` muet qui fabrique une conclusion

Le chemin de lecture ajouté ensuite renvoyait « 0 désignation », et cette section
a donc été réécrite une deuxième fois pour affirmer que la colonne était vide.

La cause n'était pas dans les données. L'amorçage du cache se faisait **après le
`finally` qui ferme la connexion** ; l'exception était avalée par un `except` sans
trace, et le classement retombait silencieusement sur les mots-clés.

> Un `except` muet n'a pas seulement dégradé un chiffre : il a produit une
> **conclusion fausse sur les données**, inscrite dans ce rapport. C'est la leçon
> la plus utile du projet.

Le `except` imprime désormais ce qu'il avale, et les métriques portent un champ
`echec_de_chargement`. La question est tranchée à tout moment par
`python scripts/diag_famille_produit.py`, qui mesure au lieu d'affirmer.

### Ce que la correction a donné

| | Avant | Après |
|---|---|---|
| Classé par la famille ERP | 0 % | **62,1 %** de la valeur |
| Classé par défaut | 43,3 % | **29,2 %** |
| Valeur exposée à une erreur | 2 781 137 DT | **1 873 978 DT** |
| Couverture en valeur | 56,7 % | **70,8 %** |

**907 159 DT d'incertitude supprimés.** Et le signe le plus rassurant est ailleurs :
la perte quasi certaine passe de 213 771 à **212 117 DT**, soit −0,8 %. Les
mots-clés approchaient donc correctement — l'ERP le **confirme** au lieu de le
supposer, et deux exclusions qu'aucun mot-clé ne voyait apparaissent
(*5 ML SYRINGE XLP*, *AIGUILLE ECHANTILLON*).

### Et une erreur de fond que cette lecture a révélée

L'ERP identifie **560 références de prestation** contre 129 pour l'expression
régulière : contrats de maintenance, `SERVICE SAV`, `SERVICE DIVERS`, frais. Un
contrat ne se stocke pas.

Le capital immobilisé en portait **445 957 DT**. Il passe de 6 389 778 à
**5 943 821 DT**. Le chiffre le plus mis en avant du domaine était faux de 7 %,
et aucune métrique de modèle ne pouvait le signaler — seule une autorité de
classement correcte pouvait le faire.

### Ce qui reste, et pourquoi

**1 873 978 DT (29,2 %) sont encore classés par défaut.** Cause identifiée : ces
références n'apparaissent que dans les **factures d'achat**, jamais dans les
ventes, et la famille produit ne vit que du côté ventes. Aucun code ne peut lever
cela — c'est une demande de donnée, désormais précise au lieu d'être générale :
*la famille produit sur les lignes d'ACHAT*.

### Une hiérarchie à trois niveaux, et une exception justifiée

| Priorité | Source | Part de la valeur |
|---|---|---|
| 1 | famille ERP | 62,1 % |
| 2 | famille ERP **précisée** par un mot-clé de pièce | 0,0 % |
| 3 | mot-clé de libellé seul | 8,7 % |
| 4 | défaut — aucun signal | 29,2 % |

Le niveau 2 mérite sa justification. La famille ERP n'offre **aucune valeur
« pièce détachée »** : un kit de joints saisi en `REACTIF` n'affirme pas qu'il
périme, il constate qu'aucune case ne lui convient. Le mot-clé est alors **plus
spécifique** que la famille, non concurrent — il subdivise une classe que l'ERP ne
subdivise pas. Et l'exception ne joue que dans ce sens : un `EQUIPEMENT` ou un
`SERVICE` déclarés sont respectés sans discussion. Mesurée à 0,0 % de la valeur,
elle s'avère d'ailleurs presque inutile — l'ERP classait déjà correctement les
pièces en `SERVICE SAV`.

Quatre catégories, dans un ordre d'évaluation qui n'est pas interchangeable :

| Ordre | Catégorie | Pourquoi à cette place |
|---|---|---|
| 1 | prestation | « CONTRAT DE MAINTENANCE TOUS RISQUE VIDAS » contient « VIDAS » |
| 2 | pièce détachée | « VIDAS NSH UPGRADE KIT » contient un mot d'équipement |
| 3 | équipement | « Hb NEXT Analyzer » est un instrument |
| 4 | **consommable, par défaut** | seule classe qui périme, donc jamais attribuée par un motif positif |

Le module mesure une grandeur que rien ne mesurait : la **valeur classée
« consommable » par défaut**, c'est-à-dire faute d'avoir reconnu quoi que ce soit.
C'est la seule classe qui déclenche une perte, et ce montant borne donc
honnêtement la fiabilité de tout le volet obsolescence. Une désignation vide n'y
entre jamais — classer une absence de donnée dans la classe qui périme serait la
pire des conventions par défaut.

En sortie, `reports/nomenclature_a_valider.csv`, **trié par valeur décroissante** :
si l'entreprise ne corrige que les trente premières lignes, ce sont celles qui
portent le plus d'argent. Une grille d'audit doit être rentable à remplir
partiellement.

## 3 quinquies. Réapprovisionnement à 3 mois — le seul modèle du domaine entraîné sur des positions réelles (`ml_engine/stock/reappro_model.py`)

*Sources : `reports/positions_metrics.json`, `reports/reappro_metrics.json`*

### L'objection à laquelle ce module répond

Les deux modèles de §3 ter apprennent leurs variables de position sur le module
**simulé**. L'objection est légitime et arrive vite : *votre modèle de risque
tourne sur quoi, au fait ?*

### Ce que la reconstruction a débloqué

`flux_reels.py` calcule une position **finale** : une photo, un chiffre par
référence. C'est assez pour constater un surstock, et inutilisable pour apprendre
— un modèle supervisé a besoin d'un historique d'états, pas d'un état. Or le même
calcul fonctionne **à chaque date de coupure** :

    position(référence, fin du mois m) = Σ entrées ≤ m − Σ sorties ≤ m

`positions_historiques.py` matérialise cette grille référence × mois. Le produit
cartésien est volontaire : un mois **sans** mouvement est une information — la
position ne bouge pas, la couverture se consomme. Ne garder que les mois
mouvementés donnerait une série à trous où « rien ne s'est passé » deviendrait
invisible.

### La question posée, et pourquoi celle-là

> À la fin du mois *m*, cette référence sera-t-elle réapprovisionnée au cours des
> trois mois suivants ?

Trois propriétés rendent cette formulation défendable là où d'autres ont échoué
dans ce projet :

1. **La cible est observée, jamais construite.** Un achat a eu lieu, ou non.
   Aucun seuil déclaré, aucune simulation, aucune formule mêlant des variables
   explicatives. C'est l'exact opposé de la première formulation du risque de
   stock, dont la cible « rupture » était définie par `stock / demande < délai`
   alors que ces trois grandeurs étaient des features — et qui affichait pour
   cette raison **AUC = 1,0000**.
2. **Aucune variable ne peut contenir la cible.** Toutes se calculent sur les mois
   ≤ *m*, la cible se lit sur *]m, m+3]*. La séparation est temporelle, donc
   vérifiable **mécaniquement** plutôt que par relecture — un test refuse toute
   variable corrélée à plus de 0,98 avec la cible.
3. **La question a un usage réel.** Savoir quelles références seront à commander
   au prochain trimestre, c'est préparer les négociations fournisseur et lisser la
   trésorerie. C'est la décision que le service achat prend effectivement.

### Le biais du stock initial, isolé et mesuré

La position reconstruite porte un décalage inconnu mais **constant par
référence** : le stock antérieur à l'historique. Ce décalage s'annule dans toute
variable de **variation** et subsiste dans toute variable de **niveau**. Les
variables sont donc déclarées en deux familles, et une **ablation** mesure ce que
les variables de niveau apportent réellement.

Si le modèle tient sans elles, sa performance ne repose pas sur la partie biaisée
de la reconstruction. C'est la réponse directe à l'objection la plus légitime
qu'on puisse opposer au module, et elle est chiffrée plutôt qu'argumentée.

### Références triviales — direction fixée avant la mesure

| Référence | Signal | A priori |
|---|---|---|
| `achat_recent` | − mois depuis le dernier achat | une référence activement réapprovisionnée le reste |
| `frequence_achat_12m` | nombre d'achats sur 12 mois | un acheteur régulier rachète |
| `ratio_attente` | attente / intervalle habituel | retard sur le rythme habituel |
| `couverture_faible` | − couverture en mois | une couverture faible appelle une commande |
| `consommation_3m` | consommation récente | un fort volume se recommande |

Le sens de chacune est posé **a priori** et jamais révisé au vu de l'AUC :
inverser un signe après avoir vu le résultat reviendrait à entraîner la référence
elle-même.

### Seuils de déploiement, déclarés avant toute mesure

    AUC hors période ≥ 0,70   ET   gain ≥ 0,02 sur la meilleure référence triviale

### Résultat mesuré — et **refusé**

*46 677 observations · 1 105 références · 2017-12 → 2026-01 · taux de base 32,9 %*
*Coupure 2025-02-01 · marge anti-fuite 3 mois · train 32 045 · test 11 621*

| | AUC hors période |
|---|---|
| régression logistique | **0,9297** ← retenue par parcimonie |
| gradient boosting | 0,9336 |
| `frequence_achat_12m` (trivial) | **0,9178** |
| `achat_recent` (trivial) | 0,9020 |
| `consommation_3m` (trivial) | 0,8496 |
| `couverture_faible` (trivial) | 0,5922 |
| `ratio_attente` (trivial) | 0,1631 |

**Gain : +0,0140. Seuil exigé : 0,02. → REFUSÉ.**

Le modèle est bon dans l'absolu — 0,93 d'AUC, Brier 0,098, écart au GroupKFold de
seulement +0,0046, donc aucune fuite décelable. Il perd malgré tout, et pour la
raison la plus simple : **compter les achats des douze derniers mois atteint
déjà 0,9178**. Un distributeur qui a commandé quatre fois cette année
recommandera. Ajouter un modèle pour gagner un point et demi d'AUC introduirait
une dépendance, un réentraînement et une opacité pour un bénéfice qu'une requête
d'une ligne procure presque entièrement.

C'est exactement ce que les seuils déclarés à l'avance sont censés produire : une
décision qui ne dépend pas de l'envie d'avoir un modèle de plus.

### Deux résultats que ce refus a produits par ailleurs

**L'ablation ferme l'objection du stock initial inconnu.** Sans les trois
variables de niveau, l'AUC passe de 0,9297 à **0,9307** — soit une perte de
−0,0007, autrement dit rien. Le modèle ne repose donc **pas** sur la partie
biaisée de la reconstruction. C'est la réponse chiffrée, et non argumentée, à
l'objection la plus légitime qu'on puisse opposer au module.

**Un a priori faux, laissé tel quel.** `ratio_attente` — l'attente rapportée à
l'intervalle d'achat habituel — affiche **0,1631**, c'est-à-dire fortement
*inversé* : plus une référence est « en retard » sur son rythme, moins elle est
recommandée. C'est contre-intuitif, et l'interprétation métier est nette : une
référence qui dépasse son intervalle habituel est en général une référence
**abandonnée**, pas une référence en retard.

Le signe n'a **pas** été corrigé après la mesure. L'inverser aurait porté cette
référence triviale à 0,8369 et changé le classement — mais retoucher une
référence au vu de son résultat revient à l'entraîner, et elle cesserait alors
d'être une référence.

### En cas de refus, ce que le code fait réellement

Aucun artefact n'est écrit et l'ancien est **supprimé** — un fichier présent finit
toujours par être chargé par quelqu'un. Le tableau de bord continue de servir la
détection de rupture arithmétique de §3 quater, qui ne dépend d'aucun
apprentissage, et le panneau d'anticipation n'apparaît pas.

### La limite qu'il faut énoncer soi-même

Ce modèle apprend le **comportement d'achat historique**, pas le besoin optimal.
Si l'entreprise a jusqu'ici surcommandé une référence, le modèle reproduira cette
habitude. Il prévoit ce que le service achat **va** faire, non ce qu'il
**devrait** faire.

C'est la faute la plus grave qu'on pourrait commettre en présentant ce module,
parce qu'elle est **invisible dans les métriques** : un modèle qui reproduit
fidèlement une mauvaise habitude affiche une excellente AUC. D'où son
positionnement dans l'interface, à côté du constat d'obsolescence qui dit
l'inverse — là où les deux se contredisent, il y a une décision à revoir.

Le classement affiché suit le **budget à prévoir** — probabilité × trois mois de
consommation × coût d'achat réel — et non la probabilité seule : une référence
quasi certaine à 40 DT n'appelle aucune décision, une référence probable à
80 000 DT en appelle une.

## 3 sexies. Encours contractuel par client (`ml_engine/analytics/encours.py`)

*Source : `reports/encours_metrics.json` — `python -m ml_engine.analytics.encours`*

Répond à la question la plus directe d'un dirigeant — *qui me doit de l'argent ?* —
sans jamais prétendre y répondre au-delà de ce que les données permettent.

| Indicateur | Valeur |
|---|---|
| Montant échu à la date de référence (fenêtre 18 mois) | **77 855 115 DT** sur 922 clients |
| **Comptes à vérifier en priorité** | **117 clients · 4 619 469 DT** — soit **5,9 %** du total |
| Critère | échéance dépassée de plus de 90 jours **ET** aucune commande depuis 90 jours |

**Ce que ce chiffre n'est pas.** Ce n'est **pas** un montant d'impayés. L'ERP
n'enregistre aucune date de règlement : une grande partie de ces factures a
certainement été payée, et rien dans les données ne permet de le vérifier. Le
module mesure donc ce qui **aurait dû être encaissé**, puis désigne les comptes
dont la vérification est la plus rentable. Le passage de 77,8 M DT à 4,6 M DT est
tout l'apport du module : il transforme un agrégat inexploitable en une liste de
117 appels à passer.

**Le défaut qui invalidait tout, et sa cause exacte.** La première version
signalait **100 % des clients**. Le silence commercial était mesuré depuis la
dernière **échéance** connue (2026-09-11), alors qu'il doit l'être depuis la
dernière **facture émise** (2026-04-29) — une facture d'avril échoit en
septembre. Ce décalage de 135 jours s'ajoutait au silence de chaque client. Deux
dates de référence distinctes sont désormais calculées séparément, et le fichier
de sortie porte le champ `pourquoi_deux_dates` pour que l'erreur ne puisse pas
être réintroduite silencieusement.

## 4. Robustesse de la flotte multi-agents (`agents/fleet/`)

Chaque nœud est enveloppé par `_safe_node` : une exception dans un agent produit une trace `erreur` et un briefing dégradé, **jamais un crash** (testé par injection de panne). Orchestration LangGraph (fan-out/fan-in parallèle) avec **repli séquentiel déterministe** si LangGraph est absent.

### Une lecture croisée assumée : trésorerie ↔ stock

Les spécialistes s'exécutent en parallèle et ne se parlent pas. L'agent Stock
annonçait un montant immobilisé, l'agent Trésorerie un besoin de financement, et
**personne ne rapprochait les deux** — alors que du stock dormant *est* de la
trésorerie gelée.

L'agent Trésorerie consulte donc directement le module de stock. Il convertit le
cycle en dinars — `(DSO − DPO) / 365 × CA des 12 derniers mois` — puis calcule la
part de ce besoin immobilisée en marchandise excédentaire. L'annualisation porte
sur les douze derniers mois et non sur l'historique cumulé : sept ans de
facturation additionnés donneraient un besoin sans rapport avec l'exercice.

La lecture va dans un seul sens, donc aucune boucle n'est créée et l'ordre
d'exécution reste sans importance. Le constat distingue le **surstock**
(récupérable) de la **péremption** (perte sèche), et rappelle que les quantités
sont estimées — un test vérifie que cette réserve survit.

### L'arbitre : hiérarchiser entre des domaines incomparables

Chaque spécialiste déclare la sévérité de son propre constat, selon ses critères
métier. Un « haute » de l'agent Stock et un « haute » de l'agent Recouvrement ne
mesurent donc pas la même chose : le rédacteur les triait à égalité, et l'ordre
entre eux était **arbitraire**.

Or l'arbitrage inter-domaines — relancer un débiteur ou déstocker ? — est
précisément la question qu'aucun agent ne peut trancher, puisqu'aucun ne voit les
constats des autres. Elle ne se pose qu'après le fan-in.

**Comment les montants deviennent comparables.** Les montants bruts ne le sont
pas : 100 000 DT de créance en retard et 100 000 DT de marchandise périmée ne
pèsent pas pareil, le premier étant récupérable et le second perdu. Chacun est
pondéré par la nature économique de ce qu'il représente.

| Catégorie | Nature | Coefficient |
|---|---|---|
| Recouvrement, Trésorerie | décalage de trésorerie | 0,15 |
| Rétention | revenu récurrent menacé | 0,20 |
| Stock | capital immobilisé | 0,10 |
| Approvisionnement | risque opérationnel | 0,05 |

Les coefficients reprennent ceux de `impact.py` : les deux doivent dire la même
chose, sinon le tableau de bord et le briefing hiérarchiseraient différemment les
mêmes faits.

**Ce que l'arbitre ne fait pas, volontairement.** Aucun score global de santé.
Agréger créances, stock et décrochage en un chiffre unique produirait un
indicateur que personne ne saurait interpréter ni actionner. Il **ordonne**, il
ne résume pas — et un test le vérifie.

### Le croisement que seul l'arbitre peut faire

Un même client apparaissait en tête des débiteurs **et** parmi ceux qui
décrochent, sans que rien ne le signale. Le recouvrement ignore le décrochage, le
risque client ignore les impayés : chacun voit son domaine.

Or la conjonction change la nature du risque. **Une créance sur un client qui
s'éloigne devient douteuse**, puisque le levier commercial qui permettrait de
négocier un échéancier disparaît avec la relation.

Les agents publient donc une liste structurée `clients_concernes`, et l'arbitre
détecte les intersections. Le cas s'est produit dès la première exécution — un
client cumulait 300 K DT de créance et 400 K DT de chiffre d'affaires menacé — et
il est désormais placé en tête avec son explication.

C'est la justification opérationnelle de l'architecture multi-agents : cette
lecture n'existe **ni dans les données brutes, ni dans aucun agent isolé**.

### Une contradiction entre deux agents, corrigée

L'agent Trésorerie utilisait `montant_risque_ttc`, que le moteur KPI documente
pourtant comme « un comportement de paiement, PAS un encours dû aujourd'hui » :
il additionne cinq ans de factures réglées avec retard.

Il annonçait donc **133,77 M DT** de créances échues quand l'agent Recouvrement
annonçait **10,95 M DT** pour la même réalité — soit 48 % du chiffre d'affaires
total en prétendus impayés. Deux agents qui se contredisent sur un même fait
ruinent la crédibilité de l'ensemble du briefing.

Corrigé, avec deux tests : l'un vérifie que les deux agents annoncent la même
exposition, l'autre interdit le vocabulaire de l'impayé — l'ERP n'enregistrant
aucune date de règlement, seule la date d'échéance contractuelle est connue.

### Le rédacteur fabriquait des chiffres

Le prompt demandait des actions « chiffrées ». Cela suffisait à faire produire des
remises de 2 % et 5 %, un objectif de 2,8 M DT à transférer, des accords de
consignation — **aucun de ces nombres ne figurait dans les constats**. Le briefing
recommandait en outre des « ventes flash » sur des produits en rupture.

Sept règles absolues encadrent désormais la génération : aucun nombre absent des
constats, aucun levier commercial inventé, jamais d'écoulement proposé sur une
rupture, l'action de l'agent reprise et non remplacée, les réserves sur les
données estimées conservées, aucun calendrier ni répartition de responsabilités
fabriqués, et les clients multi-signaux placés en tête.

Les deux dernières règles ont été ajoutées après une seconde dérive : privé de
chiffres à inventer, le modèle s'était mis à produire un **planning** — « Semaine
1 : équipe Recouvrement », « Semaine 3 : Finance / Logistique » — et des leviers
comme les « dons à des structures publiques ». Il ne connaît ni l'organisation de
l'entreprise ni ses capacités.

Un briefing contenant un seul élément inventé perd toute valeur, puisque le
lecteur ne peut plus distinguer le mesuré de l'imaginé.

## 4 bis. Registre de modèles (`ml_engine/registre.py`)

Un modèle refusé mais présent sur le disque est un piège : rien n'empêchait de
charger son artefact et de servir ses probabilités. **Le refus n'existait que dans
un JSON que personne n'était obligé de lire.**

Le cas s'est produit : le radar financier a servi une projection LSTM à six mois,
modèle jamais validé, sur un horizon que les données ne soutiennent pas — 99 % des
factures ayant un délai de 0 à 2 mois, les encaissements au-delà proviennent de
factures non encore émises.

Le registre rend la décision **exécutable**. Chaque module déclare où lire sa
décision ; l'API et le tableau de bord interrogent le registre avant de servir. En
l'absence de rapport, le module est refusé — **un doute se résout toujours dans le
sens du refus**.

Il déclare aussi la **nature** de chaque module — modèle appris, règle
déterministe, statistique robuste, lecture du carnet. Confondre ces natures
conduirait à présenter comme un échec un module utile au seul motif qu'il ne
contient pas de réseau de neurones.

`tests/test_modules_branches.py` (6 tests) vérifie le **câblage** et non la
qualité : qu'aucun module refusé n'alimente une sortie, que le LSTM ne revienne
pas, qu'aucun horizon de six mois ne soit annoncé, et que les intervalles de
prévision s'élargissent avec l'horizon. Ces tests comblent un angle mort — les
293 tests précédents vérifiaient chaque module **isolément**, ce qui est sans
rapport avec la question de savoir s'il est branché. Un module correct mais
débranché est invisible pour l'utilisateur, et la panne est silencieuse.

**État consolidé.** `python -m ml_engine.registre`

## 4 ter. Un test qui a failli enterrer un bon modèle (`ml_engine/validation.py`)

C'est l'épisode le plus instructif de ce projet sur le plan méthodologique, et il
s'est joué en trois temps.

### Temps 1 — le modèle passe

La conversion des devis atteint **AUC 0,7165**, soit **+0,0341** sur la meilleure
référence triviale. Les deux seuils déclarés — 0,70 et +0,02 — sont atteints.
Décision : déployé.

### Temps 2 — un contrôle manquant refuse le modèle

Le registre appliquait déjà une exigence de **significativité** à la prévision de
demande, dont il affiche « écart non significatif » au lieu d'un gain. Elle
manquait aux nouveaux modules. Ajoutée — **après** un premier résultat positif, en
sachant qu'elle pouvait l'invalider :

```
écart médian +0,0350 · IC95 [-0,0290 ; +0,0948]  ->  NON SIGNIFICATIF
le modèle gagne dans 86,4 % des tirages
```

Le modèle passe en REFUSÉ. C'est précisément pour cela qu'il fallait ajouter le
test : un contrôle qu'on n'ajoute que lorsqu'il ne risque rien ne contrôle rien.

### Temps 3 — le diagnostic, et le remède qui n'est pas un assouplissement

Lecture exacte du verdict : **le modèle n'est pas mauvais, le test est trop
petit**. 988 devis dont **92 signés**. À cette taille, l'intervalle sur l'écart
mesure surtout notre ignorance — retirer trois signatures suffirait à en changer le
signe.

Une coupure unique 75/25 n'utilise qu'un quart de l'historique, et toujours le
même. Le remède n'est donc pas de desserrer un seuil, c'est de **mesurer sur plus
d'observations avec la même exigence** : le walk-forward avance la coupure quatre
fois et met en commun les prédictions hors période.

| Protocole | Devis de test | Signatures | IC95 de l'écart | Verdict |
|---|---|---|---|---|
| Coupure unique | 988 | 92 | [−0,0290 ; +0,0948] | non significatif |
| **Walk-forward, 4 origines** | **2 370** | **210** | **[+0,0126 ; +0,0964]** | **significatif** |

Le modèle gagne dans **99,6 %** des tirages. Déployé — sur une mesure plus fiable,
pas sur une règle plus souple.

### Pourquoi agréger n'est pas tricher

Chaque prédiction est produite par un modèle entraîné **exclusivement** sur des
observations antérieures à sa propre coupure. Mettre les prédictions en commun
agrège donc des **mesures hors période**, pas des modèles : la garantie anti-fuite
est identique, seul le nombre de cas disponibles change.

Deux détails séparent une implémentation correcte d'une implémentation fausse :

* **la sélection du modèle est refaite dans chaque pli**, sur son seul train.
  Réutiliser le réglage choisi globalement ferait entrer dans un pli une
  information issue de périodes qu'il ne doit pas connaître ;
* **le score de la référence est accumulé pendant la boucle**, jamais reconstitué
  après coup en rejouant les bornes. Un décalage d'une ligne casserait
  l'appariement, et rien ne le signalerait.

### Et la conclusion peut rester négative

C'est ce qui rend le procédé honnête. **Un écart qui disparaît sur un test élargi
n'a jamais existé.** Le walk-forward a confirmé la conversion des devis ; il aurait
pu l'enterrer, et l'érosion de marge y est passée avec un intervalle quatre fois
plus étroit — [+0,0321 ; +0,0449] sur 4 008 positifs.

Le test est **apparié** : chaque tirage rééchantillonne les mêmes observations pour
les deux scores. Comparer deux intervalles calculés séparément serait plus faible —
ils peuvent se chevaucher alors que la différence, elle, est stable.

## 5. Reproductibilité

- Seeds fixées : `random_state=42` (conditions de crédit, décrochage client, prévision de demande, risque de stock), backtests déterministes.
### Le déterminisme était affirmé, pas mesuré — et il était faux

La ligne ci-dessus disait « backtests déterministes ». Personne ne pouvait le
vérifier, car rien ne le vérifiait. Deux exécutions strictement identiques :

```
lightgbm      AUC 0.8172   écart train/valid +0.1316      exécution A
lightgbm      AUC 0.8169   écart train/valid +0.1319      exécution B

segmentation  k=3 · stabilité 0.9283                      exécution A
segmentation  k=3 · stabilité 0.9754                      exécution B
```

Aucune donnée n'avait changé, et `random_state=42` était bien fixé partout.

**Une cause unique : l'addition flottante n'est pas associative.** Dès qu'une
somme est parallélisée, l'ordre des contributions dépend de l'ordonnancement des
threads — donc du système, pas du code. Trois familles de calculs en dépendent
ici : le gradient boosting (gradients sommés par blocs, effet composé sur 250 à
300 itérations gloutonnes), KMeans (centroïdes = moyennes parallélisées), et les
agrégations DuckDB (`sum()`, `avg()`).

**Pourquoi ce n'était pas cosmétique.** Dans `stock_risk`, la sélection se joue à
**0,003 d'AUC** entre candidats et la disqualification à **0,10 d'écart** : une
décision de déploiement pouvait basculer selon la charge de la machine.

**Et la conséquence la plus grave était visible par l'utilisateur.** Deux
segments de tailles voisines **échangeaient leur nom** entre deux exécutions —
« Petits comptes occasionnels » et « … en sommeil » permutaient. Le tableau de
bord renommait donc des segments sans qu'aucune donnée ait changé.

*Correctif, centralisé dans `ml_engine/determinisme.py`* : la cause étant unique,
le traitement l'est aussi — `threadpool_limits(1)` pendant les phases de mesure
(risque produit et segmentation, y compris la segmentation **servie**, sans quoi
elle différerait de celle qui a été mesurée), `deterministic=True,
force_row_wise=True, n_jobs=1` pour LightGBM, et `SET threads TO 1` sur les
connexions DuckDB d'entraînement.

*Et surtout, la propriété est désormais mesurée* :
`python scripts/verif_reproductibilite.py` exécute un module **deux fois dans
deux processus distincts** — jamais dans le même interpréteur, qui réutiliserait
pools de threads et caches et masquerait précisément ce qu'on cherche — puis
compare les rapports champ par champ. Chaque écart est jugé non pas contre zéro
mais contre **la marge de la décision qu'il pourrait faire basculer** : 0,0003
sur une AUC est sans conséquence, sauf si un choix se joue à 0,003.

Le rapport de chaque modèle porte un champ `determinisme` qui **dit si
`threadpoolctl` est absent** au lieu de le taire : croire mesurer dans des
conditions contrôlées sans l'être serait le pire des cas.

#### Ce que la mesure a donné — et pourquoi la réponse n'est pas « zéro »

| Module | Valeurs comparées | Différentes | Écart maximal | Verdict |
|---|---|---|---|---|
| Risque produit | 82 | 9 | **0,0010** *(`lightgbm.cv_auc`)* | aucune marge de décision atteinte |
| Segmentation *(avant correction)* | 99 | 17 | 0,0731 *(`stabilite` à k=6)* | 7 écarts sur l'**identifiant** de segment |
| Segmentation *(après)* | 99 | **7** | **0,0280** *(`stabilite` à k=6)* | plus aucun écart d'identifiant |

**La reproductibilité parfaite n'est pas atteinte, et le rapport le dit.** Ce qui
est garanti est plus précis, et c'est ce qui compte : **aucune décision de
déploiement ne bascule**. Pour le risque produit, les trois candidats instables
sont tous **disqualifiés** à +0,12 ou +0,13 d'écart train/validation, soit à plus
de 0,02 du seuil de 0,10 ; et le modèle **retenu** — `random_forest`, 0,8190 avec
un écart de +0,0979 — est ressorti **bit à bit identique** à chaque exécution.
L'instabilité résiduelle porte donc exclusivement sur des candidats écartés.

Prétendre à un déterminisme parfait aurait été une deuxième affirmation non
vérifiée après la première. Mesurer, puis énoncer la garantie exacte, est le seul
traitement honnête.

#### Le défaut que cette mesure a fait apparaître, et qui était visible par l'utilisateur

Parmi les 17 écarts de la segmentation, sept portaient sur le champ `segment` —
l'**identifiant de cluster**. KMeans numérote ses groupes dans l'ordre où ses
centroïdes convergent, ordre qui varie au dernier bit. Le même segment portait
l'identifiant 3 puis 0.

Conséquence observée dans le tableau de bord : deux segments partageant la base
« Petits comptes occasionnels » étaient nommés selon leur **ordre d'arrivée** — le
premier gardait le nom nu, le second héritait du suffixe « — en sommeil ». L'ordre
changeant, **le suffixe changeait de segment** :

```
exécution A :  Petits comptes occasionnels — en sommeil    95 clients
               Petits comptes occasionnels                 57 clients

exécution B :  Petits comptes occasionnels                 95 clients
               Petits comptes occasionnels — en sommeil    57 clients
```

Aucune donnée n'avait changé. C'est le seul de ces défauts qu'un directeur aurait
remarqué, et donc le plus grave.

*Correction en deux temps, aucun des deux ne dépendant du hasard d'étiquetage.*

1. **Les étiquettes sont canonisées à la source**, juste après le clustering :
   0 = le groupe au plus fort chiffre d'affaires cumulé, puis par ordre
   décroissant, ex æquo départagés par l'effectif puis la récence. Tout ce qui est
   en aval — nommage, jointure du croisement avec le décrochage, export client —
   hérite d'une numérotation déduite des données. La table de correspondance est
   **sauvegardée avec le modèle** : `km.predict()` renvoie les étiquettes brutes,
   et un client scoré plus tard aurait reçu le nom d'un autre segment.
2. **Dans un groupe en collision, aucun segment ne garde le nom nu.** Tous
   reçoivent un qualificatif, attribué par récence croissante — « encore actifs »
   au plus récent, « en sommeil » au plus dormant. La question « lequel est le
   premier ? » disparaît au lieu d'être seulement stabilisée, ce qui est
   préférable : une question supprimée ne peut pas se reposer.

*Résultat après correction* : les **sept écarts d'identifiant ont disparu**. Il ne
reste que sept écarts, tous sur des mesures de qualité (`stabilite`, `silhouette`,
`inertie`), aucun n'atteignant une marge de décision.

Deux tests verrouillent la propriété : permuter l'ordre des profils d'entrée ne
doit rien changer aux noms, et aucun membre d'une collision ne doit conserver le
nom nu — ni aucun segment sans homonyme être décoré inutilement.

**Et ces deux tests ont d'abord échoué pour une raison instructive.** Leur première
version ne fournissait que **deux** profils. Or les qualificatifs sont attribués
par RANG entre segments : avec deux segments, les rangs valent nécessairement 0 et
1 sur chaque axe, aucune collision n'est possible, et le test ne pouvait rien
vérifier. Il fallait **cinq** profils pour que deux tombent dans la même tranche de
chiffre d'affaires *et* la même tranche de régularité. Un test qui ne construit pas
la situation qu'il prétend couvrir passe pour de mauvaises raisons — c'est la même
famille d'erreur que le garde-fou anti-fuite qui vérifiait une liste de noms au
lieu de la construction réelle de la cible.
- **Tout artefact sérialisé est réaligné, où qu'il soit.** `rag/index/tfidf.pkl` sérialise un `TfidfVectorizer` hors de `models/` : aucune commande ne le réalignait, et c'était le dernier avertissement de version émis par la suite de tests pendant que le script de maintenance annonçait « Terminé ». Un index de recherche désaligné est le cas le plus sournois — il ne lève aucune erreur, il renvoie de mauvais passages. Un test balaie désormais **tout le dépôt** à la recherche de `.joblib` et `.pkl` orphelins, au lieu d'inspecter un dossier choisi d'avance.
- **Départage explicite des ex æquo dans tous les tris SQL** (`credit_risk_model.py` : `date, client, piece` ; `stock/generator.py` : `client_name, ca_total DESC, produit`). Sans dernier critère, l'ordre des lignes varie d'une exécution à l'autre et déplace tout ce qui en dépend (médianes glissantes, consommation du générateur aléatoire).
- **Déterminisme forcé** sur LightGBM (`deterministic=True`, `force_row_wise=True`, `n_jobs=1`) : le multi-threading rendait sinon les conclusions de sélection non reproductibles d'une exécution à l'autre.
- Tests : **371** au total — `python -m pytest tests/ -v` (intégrité des données, sémantique ERP, crédit, décrochage, segmentation, flotte, demande, échéancier, stock simulé, flux réels, encours, câblage des modules, auth, RBAC, portail).
- Chaîne de régénération complète, **dans cet ordre** :

  ```
  python -m ml_engine.stock.flux_reels             # table stock_flux_reel + nomenclature
  python -m ml_engine.stock.positions_historiques  # table stock_position_mensuelle
  python -m ml_engine.stock.reappro_model          # modèle appris sur positions réelles
  python -m ml_engine.analytics.encours
  python scripts/retrain_all.py --force
  python -m ml_engine.analytics.impact
  python -m ml_engine.derive
  python scripts/generer_grille_validation.py
  python -m ml_engine.analytics.conversion_devis   # cycle commercial
  python -m ml_engine.analytics.marge_client       # rentabilité
  python -m ml_engine.registre                     # état consolidé
  python scripts/verif_reproductibilite.py         # deux exécutions, comparées
  ```

  L'ordre n'est pas indifférent : chaque étape matérialise une table ou un rapport que les suivantes lisent. Inverser les deux premières laisse le modèle de réapprovisionnement sans panneau ; lancer `impact` avant `flux_reels` produit des postes calculés sur le repli simulé. `python -m ml_engine.synchro` exécute la même chaîne automatiquement quand l'empreinte des données a changé.
- Environnement : `pip install -r requirements.txt` ; figer l'environnement exact de soutenance avec `pip freeze > requirements.lock.txt`.

## 6. Limites des données — quatre annoncées à tort

Pour chaque limite, la donnée a été cherchée avant de conclure qu'elle manquait.
**Quatre fois, elle s'y trouvait** — la marge par client, la conversion des devis,
les quantités permettant de reconstruire le stock, et la famille produit. Une
cinquième a été **contournée par un raisonnement mesurable** faute d'exister.

Ce compte est le résultat le plus embarrassant et le plus utile du projet : **les
deux tiers des « limites de données » annoncées étaient des limites de
recherche.** Chacune avait été écrite avec assurance dans ce rapport avant d'être
réfutée par une requête de trois lignes. La règle qui en sort : une absence de
donnée ne se déclare qu'après avoir interrogé la donnée — jamais après avoir lu un
schéma, un commentaire de code, ou un rapport antérieur.

Détail : `docs/DONNEES_MANQUANTES.md`.

| Limite | Statut | Résultat |
|---|---|---|
| **Marge par client** | ✅ **résolue** | coût de revient `MTCRSIGNE` trouvé dans les lignes → marge réelle **28,3 %** (au lieu de 77 %), désormais **attribuable par client** |
| **Conversion devis** | ✅ **résolue** | statut ERP `ETATPIECE=8` décodé et validé empiriquement (89,4 % d'appariement contre 37,4 %) → taux réel **9,0 %** au lieu de 94,8 % |
| **Date de paiement** | ❌ absente de l'export | `REG` et `REGTYP` sont **absents du schéma** de `Facture_vente_ent_v.csv` — pas « présents mais vides », comme l'énonçait imprécisément la version précédente de ce rapport ; `SOLDEACOMPTE_DEV` existe et vaut 0 partout, `ETAT` est constante. Vérifié par `tests/test_semantique_erp.py`, qui interroge le schéma au lieu de le supposer → module de scénarios paramétrés (jamais de prédiction inventée) + demande technique rédigée |
| **Validation métier** | ⬜ **grille pré-remplie, verdicts à recueillir** | tous les indicateurs de ce rapport sont INTERNES : une AUC compare des prédictions à des étiquettes calculées sur les mêmes données, et ne dit rien de la pertinence terrain. `python scripts/generer_grille_validation.py` produit `reports/validation_metier.csv` où **chaque ligne est déjà instruite** — le cas réel, ce que la plateforme en affirme — et où seule la colonne de verdict reste vide. Un protocole qui demande à un directeur de recopier trente noms depuis une application ne sera jamais rempli ; celui-ci se coche. La section 6 du fichier réclame ce que le code ne peut pas produire : les **faux négatifs**, un cas inquiétant ABSENT des listes |
| **Niveau de stock** | ✅ **résolue** | aucune colonne d'inventaire, mais les **quantités** figurent dans les lignes d'achat et de vente → position reconstruite par différence des flux (§3 quater), **94,9 % du volume couvert**, capital immobilisé **6 389 778 DT** mesuré. Les chiffres servis ne contiennent plus aucune valeur simulée ; le module (s,S) ne subsiste qu'en repli et pour alimenter les variables des deux modèles de §3 ter |
| **Date de péremption** | ⚠️ **contournée, non obtenue** | aucune date d'expiration dans les 32 fichiers, et le module refuse d'en simuler une → détection par **rotation** : un consommable au-delà de deux ans de consommation périmera (§3 quater). Seuils 24 / 12 mois **déclarés** et révisables |
| **Nomenclature produit** | ✅ **résolue à 62 %, et le reste est précisé** | la famille `ARTICLE_LIBELLE_FAM_STAT1` est renseignée à **99,9 %** — l'annonce d'absence était fausse (§3 quater bis). Elle gouverne désormais **62,1 %** de la valeur classée ; la part « par défaut » tombe de 43,3 % à **29,2 %**, soit 907 159 DT d'incertitude supprimés, et 445 957 DT de prestations sortent du capital immobilisé. Le reliquat s'explique : ces références n'existent que dans les factures d'ACHAT, où la famille est absente → demande de donnée désormais précise |
| **Corpus appels d'offres** | ⬛ **hors périmètre** | module retiré du projet (§2) — un corpus écrit à la main ne pouvait être audité comme l'est l'ERP |

## 6 bis. Impact financier — ce qui est identifié, ce qui est récupérable

*Source : `reports/impact_metrics.json` — `python -m ml_engine.analytics.impact`*

> **La plateforme ne génère aucun encaissement.** Elle identifie et priorise ;
> c'est l'action qui produit le gain. Additionner les montants détectés pour
> annoncer plusieurs millions de gain serait démontable en une phrase :
> identifier une créance en retard ne la recouvre pas.

Trois catégories, volontairement séparées.

| Poste | Identifié | Hypothèse | Récupérable | Origine du montant |
|---|---|---|---|---|
| Créances à terme long priorisées | 10 948 315 DT | 15 % | 1 642 247 DT | échéances réelles |
| Chiffre d'affaires menacé par le décrochage | 4 895 100 DT | 20 % | 979 020 DT | modèle, AUC 0,9224 |
| Trésorerie immobilisée en stock excédentaire | 5 943 821 DT | 10 % | 594 382 DT | **flux réels** (§3 quater) |
| Stock qui ne sera pas écoulé avant péremption | 212 117 DT | 40 % | 84 847 DT | **flux réels** (§3 quater) |
| **Total** | **21 999 353 DT** | | **3 300 496 DT** | |

**Le poste de surstock a BAISSÉ de 445 957 DT, et c'est une correction.** La
famille produit de l'ERP, une fois réellement lue (§3 quater bis), a identifié
**560 références de prestation** au lieu de 129 : contrats de maintenance,
services SAV, frais. Un contrat ne se stocke pas. Ces 445 957 DT n'avaient rien à
faire dans un capital immobilisé, et le chiffre le plus mis en avant du domaine
les portait.

Deux postes sur quatre ont changé de nature depuis la reconstruction des flux
(§3 quater), et le tableau est plus solide bien que le total varie peu :

* le **surstock** passe de 4 510 000 à 6 389 778 DT, mais cesse d'être une
  quantité simulée pour devenir une différence entre factures d'achat et de
  vente — le montant augmente et sa contestabilité disparaît ;
* la **péremption** chute de 838 059 à 213 771 DT. La baisse n'est pas une
  régression : l'ancien montant reposait sur des dates d'expiration **inventées
  par le générateur**. Le nouveau ne retient que les références dont le stock
  excède deux ans de ventes constatées, équipements et pièces détachées exclus.
  **Un chiffre quatre fois plus petit et entièrement défendable valait mieux.**

**Les taux de conversion sont des hypothèses, pas des mesures.** Chacun est
déclaré et justifié dans `HYPOTHESES` (`impact.py`), et volontairement bas : mieux
vaut un chiffre défendable entièrement qu'un chiffre à réviser à la baisse devant
un interlocuteur sceptique. Un lecteur qui les juge inadaptés peut relancer le
calcul avec les siens.

Le taux le plus élevé — 40 % sur la péremption — l'est pour une raison précise :
le constat ne repose sur **aucune estimation**. Détenir 187 mois de consommation
d'un contrôle qualité se lit directement sur les factures. L'incertitude ne porte
que sur la capacité commerciale à écouler, jamais sur la détection.

### À part : la correction du chiffre d'affaires — 15,8 M DT

Ce montant **ne s'additionne pas** aux précédents : rien n'est à encaisser. Le
chiffre d'affaires publié était surévalué de 5,44 % — les avoirs étaient
additionnés au lieu d'être déduits, et 1 324 factures comptées deux fois.

C'est pourtant l'apport le plus certain du projet, car **le seul qui ne dépende
d'aucune hypothèse**. Un objectif commercial, une prime ou une prévision bâtis
sur 5,44 % de trop ne le seront plus.

### Ce qui n'est pas chiffré, et pourquoi

Trois apports résistent à la quantification honnête, et le rapport les nomme
plutôt que de laisser un silence passer pour un zéro : le **temps d'analyse
épargné** (chiffrer exigerait de mesurer le temps passé avant la plateforme), la
**fiabilité des indicateurs** (la valeur d'une erreur évitée ne se mesure
qu'après coup), et les **refus documentés** (le coût des décisions qu'on aurait
prises sur des prédictions non fiables n'est pas observable par construction).

## 6 ter. Surveillance de la dérive (`ml_engine/derive.py`)

*Source : `reports/derive_metrics.json` — `python -m ml_engine.derive`*

Un hold-out ne protège qu'une fois, au moment de l'entraînement. Ce module fait
la même vérification **en continu** : les conditions dans lesquelles le modèle
répond aujourd'hui ressemblent-elles à celles où il a appris ?

Trois surveillances, mesurées par l'indice de stabilité de population (PSI), dont
les seuils sont ceux du scoring bancaire — **non ajustés pour ce projet**, un
seuil taillé sur mesure étant toujours suspect.

| Surveillé | État mesuré |
|---|---|
| Variables du modèle de décrochage | PSI max **0,084** — stable (15 variables) |
| Taux de décrochage | 7,6 % → 9,2 % |
| Structure des délais de paiement | PSI **0,188** — modéré |
| Part des factures à délai ≤ 2 mois | **99,3 % → 95,6 %** |

**La dernière ligne est le signal à suivre.** Le seuil d'alerte est à 95 %, donc
rien ne se déclenche — mais la tendance va dans le mauvais sens, et c'est
exactement l'hypothèse sur laquelle repose l'échéancier. Si cette part continue
de baisser, l'horizon à un mois perdra sa fiabilité.

Ce cas illustre la raison d'être du module : la règle de crédit et l'échéancier
**ne contiennent aucun modèle appris**. Aucune métrique d'apprentissage ne
signalerait leur obsolescence. Cette surveillance joue ce rôle à leur place.

### Un faux positif écarté, et pourquoi il est instructif

La première exécution a produit une alerte spectaculaire : PSI de **2,62** sur
`anciennete_j`. Signal apparemment massif — et strictement vide de sens.
L'ancienneté d'un client augmente d'un jour par jour : son déplacement est
arithmétique, pas comportemental.

Une alerte qui se déclenche par construction est **pire qu'une absence
d'alerte** : elle épuise l'attention et fait ignorer les vraies. La variable est
donc exclue du déclenchement, mais **reste affichée** avec son motif — masquer une
mesure gênante serait une autre forme de malhonnêteté.

**Portée assumée.** La dérive mesure un déplacement des DONNÉES, jamais la
performance du modèle. Cette dernière exigerait la vérité terrain, qui n'arrive
qu'après le délai de la cible — 90 jours pour le décrochage. Le signal dit « les
conditions ont changé, vérifiez », pas « le modèle s'est trompé ».

## 6 ter bis. Réentraînement automatique (`ml_engine/synchro.py`)

*Source : `reports/synchro.json`, `reports/empreintes.json` — `python -m ml_engine.synchro`*

Un modèle entraîné une fois devant un jury reste juste le jour de la soutenance.
La question qu'un dirigeant pose ensuite est différente : *et quand j'ajoute les
données du trimestre ?*

**Détection par empreinte de contenu, pas par date de fichier.** Une date de
modification change dès qu'un fichier est ouvert ou recopié, sans qu'une seule
ligne diffère. L'empreinte est donc calculée sur le **contenu agrégé** de
l'entrepôt — nombre de factures, période couverte, chiffre d'affaires, nombre de
clients, lignes de vente, achats :

| Champ de l'empreinte | Valeur au dernier contrôle |
|---|---|
| Factures | 127 524 |
| Période | 2017-01-17 → 2026-04-29 |
| Chiffre d'affaires | 274 696 488,80 DT |
| Clients | 1 137 |
| Lignes de vente · achats | 336 651 · 1 844 |
| **Empreinte** | `f80c750eacb83ab2` |

**Trois garanties, et c'est ce qui distingue ce mécanisme d'un simple script.**

1. **Rien ne se relance sans raison.** Empreinte identique → aucun
   réentraînement, et la trace le dit explicitement.
2. **Aucune défaillance n'est masquée.** Un modèle qui n'atteint plus ses seuils
   après réentraînement est refusé par le registre (§4 bis) et **disparaît du
   tableau de bord**. Mieux vaut une absence qu'une réponse fausse.
3. **Une dégradation est signalée même sans refus.** Seuil `SEUIL_DEGRADATION =
   0,10` : une perte de performance supérieure à 10 % produit une alerte, quand
   bien même le modèle resterait au-dessus de son seuil de déploiement.

**Deux dépendances d'ordre, déclarées plutôt que subies.** Le réapprovisionnement
apprend sur `stock_position_mensuelle`, que le domaine stock doit avoir
reconstruite ; et `scripts/retrain_all.py` lance les modèles dans l'ordre de sa
table plutôt que dans l'ordre où il détecte les écarts de version — un ordre
dépendant du hasard serait une source de panne intermittente.

**Un défaut de ce script, corrigé.** `retrain_all.py` ne ré-entraînait que le
modèle de crédit alors que **cinq artefacts** vivent dans `models/`, et affichait
« Terminé ». Un script de maintenance qui certifie un état qu'il n'a pas vérifié
est pire que pas de script. Il couvre désormais les cinq, déclare pour chacun le
nom réel de sa fonction d'entraînement — `stock_risk` expose `train_stock_risk`,
pas `train` — et un test échoue si un `.joblib` apparaît dans `models/` sans
entrée correspondante, ou si une entrée désigne une fonction inexistante.

**Vérification réelle.** Dernière exécution : **1 modèle resynchronisé**
(échéancier, MAPE h1 = 1,27 %, servi), 0 échec, 0 refus, 0 dégradation, état
`ok`. L'échéancier a d'ailleurs exigé un traitement à part — il n'expose aucune
fonction `train()`, mais un `evaluer()` suivi d'une écriture de métriques ; le
mécanisme appelle donc chaque module par son interface réelle, pas par une
interface supposée uniforme.

## 6 quater. Ancrage méthodologique

Les méthodes employées ne sont pas improvisées ; chacune répond à un problème
documenté dans la littérature, et c'est ce qui a permis d'éviter plusieurs
impasses.

**Prévision — combiner plutôt que sélectionner.** Le résultat de Bates et Granger
(1969) sur la combinaison de prévisions, confirmé par les compétitions M
successives (Makridakis, Spiliotis et Assimakopoulos, 2018 et 2020), établit
qu'une moyenne de méthodes bat généralement la meilleure méthode sélectionnée —
particulièrement quand la sélection porte sur un échantillon court. C'est ce qui
a motivé le passage d'un socle élu à un socle-ensemble (§3 ter), et la mesure a
confirmé l'apport : l'ensemble se dégrade de 76 % hors échantillon contre 84 %
pour la moyenne mobile qu'il remplace. L'architecture socle statistique +
correction apprise est celle du modèle hybride vainqueur de la M4 (Smyl, 2020).

**Échéancier — facteurs de développement.** La décomposition « part déjà acquise
/ part restant à venir » est la méthode chain-ladder de la provision actuarielle
(Mack, 1993). Elle s'applique ici pour la même raison qu'en assurance : une part
substantielle de la grandeur cible est **déjà observable** au moment de la
prévision, et l'estimer serait moins précis que la lire.

**Attrition — RFM et évaluation temporelle.** Les variables de récence,
fréquence et montant sont le socle établi de la prédiction de défection
(Hughes, 1994 ; Neslin et al., 2006). Le choix de classer par **enjeu financier**
plutôt que par probabilité suit l'approche profit-driven de Verbeke et al.
(2012) : un score sans montant ne permet pas de hiérarchiser l'action.

**Validation temporelle.** Le protocole hors période, distinct de la validation
croisée, répond au problème analysé par Bergmeir et Benítez (2012) : sur données
temporelles, une validation croisée classique brasse les périodes et surestime la
performance. L'écart de 0,214 mesuré sur le modèle de crédit en est une
illustration directe.

**Fuites de données.** Les trois tautologies rencontrées (§7) relèvent du
phénomène formalisé par Kaufman et al. (2012) : une variable explicative qui
contient déjà la cible. Leur typologie — fuite par construction de la cible, par
proxy, par variable dérivée — recouvre exactement les trois cas observés.

**Calibration.** La régression isotonique (Zadrozny et Elkan, 2002) rend les
scores utilisables comme probabilités, condition nécessaire au calcul d'une
espérance de perte — la grandeur qui ordonne les priorités affichées.

**Dérive.** L'indice de stabilité de population et ses seuils (0,10 / 0,25) sont
la pratique établie du scoring de crédit (Siddiqi, 2006).

## 7. Ce que ce projet a mesuré puis refusé

Cette section est délibérée. Un dossier qui n'expose que ses succès ne se
distingue pas d'un dossier où rien n'a été vérifié.

| Formulation | Mesure qui l'a écartée | Ce qui est servi à la place |
|---|---|---|
| Crédit pour un client inconnu | AUC **0,5973** hors période, sous la référence 0,6651 | la règle historique, AUC 0,9200, couvrant 85,3 % du portefeuille |
| Correcteur appris sur la demande | MAPE **identique** au socle nu (15,71 %) | une médiane mobile, avec son intervalle |
| Échéancier au-delà de 2 mois | **0,98 %** des factures ont un délai suffisant | rien — l'horizon est refusé explicitement |
| Pertinence des appels d'offres | 0,952 sur **63** exemples d'un corpus auto-produit | rien — module retiré |
| Projection de trésorerie à 6 mois | modèle jamais validé, horizon non soutenu | l'échéancier à 1 mois, 1,27 % |
| Modèle sur le taux de maturité (h=2) | tout estimateur contextuel **dégrade** l'estimation (0,063 et 0,071 contre 0,059) | la médiane constante |
| Réapprovisionnement à 3 mois | AUC **0,9297** contre **0,9178** pour le simple nombre d'achats sur 12 mois — gain +0,0119, seuil 0,02 | la détection de rupture arithmétique, sans apprentissage |
| Fin de commercialisation à 6 mois | AUC **0,8346** contre **0,8474** pour le seul nombre de mois actifs sur 12 — gain **négatif** | cette règle même, servie et mesurée : lift 4,77 au décile |
| Wide & Deep pour la recommandation | NDCG@10 **0,3501** contre **0,3439** pour LightGBM — écart +0,006, IC95 [−0,004 ; +0,016], **non significatif** | LightGBM, par parcimonie ; le Wide & Deep reste challenger (§8) |

La dernière ligne est la plus significative de ce tableau : c'est le seul refus
d'un modèle **sans défaut**. Les six autres formulations ont été écartées parce
qu'elles ne marchaient pas ; celle-ci marche, et ne paie simplement pas son coût
de maintenance. Refuser un mauvais modèle est de l'hygiène ; refuser un bon
modèle superflu est une décision d'ingénierie.

### Cinq tautologies rencontrées, dont une évitée avant d'écrire le modèle

Le même piège s'est présenté cinq fois sous des formes différentes : la cible
déductible de ce que le modèle voit déjà.

| Où | Forme prise | AUC / signal apparent | Détection |
|---|---|---|---|
| Crédit v1 | moyenne des délais passés, alors que le délai est constant par client | AUC 0,9975 | après entraînement |
| Crédit v2 | `MODEREGL` épelle le délai (« CHÈQUE 60 JOURS ») | AUC 0,9340 seul | par le garde-fou `fuite_suspectee` |
| Maturité h=2 | `acquis_relatif` partage son numérateur avec la cible | rho 0,533, p < 0,0001 | **avant** d'écrire le modèle |
| Risque produit — seuil | `risque_surstock` défini par `couverture_actuelle_j > 180`, une **feature** | 9 876 cibles sur 18 071 | en relisant la construction de la cible, pas par un test |
| Risque produit — duplication | instantané de stock constant par produit + découpage **aléatoire** | **+0,1010 d'AUC** en validation croisée | en se demandant *de quoi* le hold-out était composé |

Les deux dernières ont résisté le plus longtemps, et pour deux raisons
différentes qui valent d'être nommées.

La première a franchi le garde-fou parce que celui-ci comparait les features à
une **liste nommée** de colonnes interdites : un seuil posé sur une variable
autorisée n'y figurait pas. Un test qui vérifie une liste ne protège que contre
ce qu'on avait déjà prévu. Le test l'a remplacée par une lecture du **code** de
construction de la cible.

La seconde est d'une autre nature : elle ne laisse **aucune signature dans les
métriques habituelles**. L'écart train/validation reste normal, la validation
croisée est stable, la calibration est correcte — parce que les deux côtés de la
coupure bénéficient de la même duplication. Aucun indicateur ne pouvait la
révéler ; seule la question « de quoi ce hold-out est-il fait ? » y menait.

Et la correction l'a démontré à rebours : une fois les groupes disjoints, l'écart
train/validation de LightGBM est passé de **+0,035 à +0,132**. Le garde-fou
anti-sur-apprentissage n'était pas trop permissif — il était **aveugle**, parce
qu'il comparait deux jeux également contaminés. C'est la leçon la plus utile de
tout ce document : *un indicateur de généralisation ne vaut rien tant que le
découpage n'a pas été vérifié*.

La progression est l'enseignement : le premier cas a coûté un modèle complet, le
deuxième a été arrêté par un garde-fou automatique, le troisième par un
diagnostic préalable. C'est cette étape de diagnostic — mesurer qu'il y a
quelque chose à apprendre avant de tenter de l'apprendre — qui avait manqué sur
la prévision de demande, où quatre familles de modèles ont été entraînées avant
de découvrir un changement de régime.

### Six défauts trouvés en confrontant une sortie à ce qu'elle prétendait être

Aucun n'était visible à l'œil, aucun ne faisait échouer un test existant.

**Une fuite temporelle**, révélée par l'écart entre deux protocoles : 0,8116 en
validation croisée contre 0,5973 hors période. Sans le second protocole, un
modèle inutilisable aurait été déployé avec un chiffre flatteur.

**Un correcteur qui se désactive lui-même.** Sa validation interne l'a écarté à
chaque pas. Sans elle, l'affirmation « le modèle ne peut pas faire pire » aurait
été fausse — un correcteur appris sur un signal faible dégrade.

**Une simulation infidèle à son propre profil** : 45 % de ruptures pour 8 %
déclarés, à cause d'un arrondi. Détectée en relisant un briefing, pas par un test.

**Un rédacteur qui fabriquait des chiffres** — remises, objectifs, volumes — dont
aucun ne figurait dans les données, et qui proposait d'écouler des produits en
rupture.

**Un encours qui signalait 100 % des clients** : le silence commercial était
compté depuis la dernière échéance connue, postérieure de 135 jours à la dernière
facture émise. Une alerte universelle ne dit rien — c'est sa propre réfutation.

**Des pièces détachées comptées comme périmables** : 90 711 DT de perte annoncée
sur un kit de joints, un kit d'upgrade et un kit de maintenance préventive. Une
pièce de rechange se détient précisément *parce que* sa rotation est lente. Le
raisonnement par rotation était bon, son périmètre d'application ne l'était pas.

### Et un angle mort de la démarche de test elle-même

Deux modules validés — l'échéancier à 1,27 % et la demande hybride — n'étaient
**appelés par aucune partie de l'application**. Les 293 tests d'alors vérifiaient
que chaque module fonctionne isolément, ce qui est vrai et sans rapport avec la
question de savoir s'il est branché.

Un module correct mais débranché n'existe pas pour l'utilisateur, et la panne est
silencieuse : rien ne casse, l'ancienne valeur continue de s'afficher. Six tests
de câblage comblent désormais cet angle mort.

## 8. Deep learning — recommandation de produits (`ml_engine/deep/recommandation.py`)

*Source : `reports/recommandation_metrics.json` · détail complet : `docs/DEEP_LEARNING.md`*

**Question** : quels produits, jamais achetés par ce client, adoptera-t-il dans les 6 mois ?
Cible observée (première facture du couple client × produit), rachats et prestations exclus.
289 093 couples client × date × produit, 1 053 clients, 904 produits.

**Architecture** : Wide & Deep (PyTorch) — partie linéaire + perceptron 64-32 sur 15 variables
et trois embeddings appris (produit, famille ERP, type d'établissement), dropout d'identifiant.
Nombre d'époques choisi en validation interne, jamais sur le test.

**Protocole** : walk-forward à 3 origines (2024-09, 2025-03, 2025-09), classement sur le
catalogue entier, 1 472 évaluations client.

| Méthode | NDCG@10 | Recall@10 | HitRate@10 |
|---|---|---|---|
| Popularité 12 mois | 0,2837 | 0,3939 | 57,5 % |
| Item-kNN (meilleure référence) | 0,2872 | 0,4184 | 61,8 % |
| Régression logistique | 0,3181 | 0,4581 | 66,4 % |
| **LightGBM — servi** | **0,3439** | 0,4827 | 69,6 % |
| **Wide & Deep — challenger** | **0,3501** | **0,5101** | **72,2 %** |

**Décision.** Le Wide & Deep est le meilleur sur toutes les métriques et bat significativement
les références triviales (+0,063, IC95 [+0,050 ; +0,076]) et la régression logistique. Mais son
avance sur LightGBM — +0,006, IC95 [−0,004 ; +0,016] — n'est pas distinguable du bruit. La
règle de parcimonie, appliquée partout ailleurs dans ce projet, sert donc LightGBM ; le réseau
reste challenger et est réévalué à chaque réentraînement (`python -m ml_engine.synchro`).

C'est la même décision que pour le décrochage, où la régression logistique (0,9224) a été
préférée au gradient boosting (0,9243) : un modèle plus complexe doit prouver qu'il fait mieux,
pas seulement l'afficher.

