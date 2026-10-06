"""Cache des panels de PRÉDICTION, le temps que l'entrepôt ne change pas.

Construire le panel des devis ou des marges coûte 5 à 15 secondes. Depuis que
les panneaux des modèles suivent les filtres du tableau de bord, chaque clic sur
un filtre redemandait ce calcul, alors que les données n'avaient pas bougé : seul
le sous-ensemble de clients affiché change.

La clé contient la date de modification de l'entrepôt (toute reconstruction
invalide le cache) et l'identité des fonctions de construction (un test qui les
remplace par des données factices ne lit jamais un panel réel mis en cache).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import pandas as pd

_VERROU = threading.Lock()
_CACHE: Dict[Tuple[Any, ...], pd.DataFrame] = {}


def _date_entrepot() -> float:
    try:
        from ml_engine.analytics.kpi_engine import STORE_PATH
        return Path(STORE_PATH).stat().st_mtime
    except Exception:
        return -1.0


def panel(nom: str, fabrique: Callable[[], pd.DataFrame], *identites: Any) -> pd.DataFrame:
    """Panel `nom`, recalculé seulement si l'entrepôt ou les fonctions ont changé.

    Renvoie une copie superficielle : un appelant qui ajoute une colonne ne
    modifie pas l'exemplaire en cache."""
    cle = (nom, _date_entrepot(), *(id(x) for x in identites))
    with _VERROU:
        en_cache = _CACHE.get(cle)
    if en_cache is None:
        en_cache = fabrique()
        with _VERROU:
            for ancienne in [k for k in _CACHE if k[0] == nom]:
                del _CACHE[ancienne]
            _CACHE[cle] = en_cache
    return en_cache.copy(deep=False)


def vider() -> None:
    with _VERROU:
        _CACHE.clear()
