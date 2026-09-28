"""
ml_engine/determinisme.py
==========================
Reproductibilité des entraînements — une cause unique, un correctif unique.

Le symptôme
-----------
Deux exécutions strictement identiques donnaient des résultats différents :

    lightgbm   AUC 0.8172  écart train/valid +0.1316      exécution A
    lightgbm   AUC 0.8169  écart train/valid +0.1319      exécution B

    segmentation  k=3 · stabilité 0.9283                  exécution A
    segmentation  k=3 · stabilité 0.9754                  exécution B

Aucune donnée n'avait changé, aucune graine n'était absente : `random_state=42`
est fixé partout, et le générateur de la stabilité est explicitement semé.

La cause, unique
----------------
**L'addition flottante n'est pas associative.** `(a+b)+c` et `a+(b+c)` diffèrent
au dernier bit. Dès qu'une bibliothèque somme en parallèle, l'ordre des
contributions dépend de l'ordonnancement des threads, donc du système — pas du
code.

Trois familles de calculs en dépendent dans ce projet :

  * **le gradient boosting** — LightGBM, XGBoost, HistGradientBoosting somment
    gradients et hessiennes par blocs. L'effet se compose sur 250 à 300
    itérations d'arbres construits gloutonnement : une différence au dernier bit
    déplace un point de coupure, qui déplace tous les suivants ;
  * **KMeans** — les centroïdes sont des moyennes parallélisées. Un client à
    égale distance de deux centres bascule, et la stabilité mesurée avec lui ;
  * **les agrégations DuckDB** — `sum()` et `avg()` sont parallélisés. Une
    variable d'entrée qui change au quinzième chiffre suffit à propager tout le
    reste.

Pourquoi ce n'est pas un détail cosmétique
------------------------------------------
Dans `stock_risk`, la sélection se joue à **0,003 d'AUC** entre candidats et la
disqualification pour sur-apprentissage à **0,10 d'écart**. Une décision de
déploiement pouvait donc basculer selon la charge de la machine. Un résultat qui
change sans que rien ne change n'est pas un résultat, et une décision qu'on ne
peut pas reproduire n'est pas auditable.

Ce que ce module garantit — et ce qu'il ne garantit pas
------------------------------------------------------
Il **borne** le parallélisme numérique à un thread pendant les phases de mesure.
Il ne prétend pas rendre toute bibliothèque bit-reproductible sur toute
plateforme : cela dépend de versions et de compilations hors de notre contrôle.

C'est pourquoi la reproductibilité est **mesurée** plutôt qu'affirmée :
`scripts/verif_reproductibilite.py` exécute un module deux fois dans deux
processus distincts et compare les rapports champ par champ. Affirmer sans
mesurer est précisément ce que ce projet s'interdit ailleurs.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator

# Variables d'environnement lues par les bibliothèques de calcul AU CHARGEMENT.
# Les poser ici n'a donc d'effet complet que si ce module est importé avant
# numpy/sklearn. Ce n'est pas toujours le cas, d'où le verrou `threadpool_limits`
# ci-dessous, qui agit lui à chaud.
_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")


def poser_variables_environnement() -> Dict[str, str]:
    """Force un thread par bibliothèque de calcul, sans écraser un choix explicite."""
    poses = {}
    for v in _VARIABLES:
        if v not in os.environ:
            os.environ[v] = "1"
            poses[v] = "1"
    return poses


def threadpoolctl_disponible() -> bool:
    try:
        import threadpoolctl  # noqa: F401
        return True
    except Exception:
        return False


@contextmanager
def limiter_threads(n: int = 1) -> Iterator[None]:
    """Borne le parallélisme numérique pendant un bloc de mesure.

    Le contexte s'ouvre même si `threadpoolctl` est absent : il est alors
    simplement inopérant. Une absence silencieuse serait le pire cas — on
    croirait mesurer dans des conditions contrôlées sans l'être — d'où `etat()`,
    que les modules d'entraînement inscrivent dans leur rapport.
    """
    if not threadpoolctl_disponible():
        yield
        return
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=n):
        yield


def limiter_duckdb(con, n: int = 1) -> bool:
    """Un seul thread côté entrepôt.

    `sum()` et `avg()` sont parallélisés par DuckDB : deux exécutions peuvent
    donner des totaux différant au dernier bit. Sur des variables comme le coût
    unitaire ou la valeur de stock, cela suffit à déplacer un point de coupure
    d'arbre — et la conclusion avec lui.
    """
    try:
        con.execute(f"SET threads TO {n}")
        return True
    except Exception:
        return False


def etat() -> Dict[str, Any]:
    """Ce qui est réellement actif — destiné à être publié dans les rapports."""
    dispo = threadpoolctl_disponible()
    return {
        "threadpoolctl": ("actif — parallélisme borné à 1 thread" if dispo
                          else "ABSENT — le parallélisme numérique n'est PAS "
                               "borné, les résultats peuvent varier d'une "
                               "exécution à l'autre"),
        "reproductible": dispo,
        "variables_environnement": {v: os.environ.get(v, "(non posée)")
                                    for v in _VARIABLES},
        "cause_traitee": (
            "l'addition flottante n'est pas associative : dès qu'une somme est "
            "parallélisée, son résultat dépend de l'ordonnancement des threads. "
            "Le gradient boosting compose cet effet sur des centaines "
            "d'itérations gloutonnes."),
        "comment_le_verifier": "python scripts/verif_reproductibilite.py",
    }
