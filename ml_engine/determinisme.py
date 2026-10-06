"""Reproductibilité des entraînements — une cause unique, un correctif unique."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Dict, Iterator

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
    """Borne le parallélisme numérique pendant un bloc de mesure."""
    if not threadpoolctl_disponible():
        yield
        return
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=n):
        yield


def limiter_duckdb(con, n: int = 1) -> bool:
    """Un seul thread côté entrepôt."""
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
