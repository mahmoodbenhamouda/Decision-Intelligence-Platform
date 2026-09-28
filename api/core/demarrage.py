"""
api/core/demarrage.py
=====================
Journal de démarrage, affiché UNE SEULE FOIS, et contrôle des modèles.

Le module principal est chargé plusieurs fois : `python api/main.py` l'exécute
comme `__main__`, puis `uvicorn.run("api.main:app")` le RÉIMPORTE ; en mode
reload, un processus superviseur et un worker le chargent chacun. Sans
garde-fou, le journal s'affiche 2 à 4 fois. La marque passe par
l'environnement, partagé entre le réimport et les processus enfants.

Ce module n'importe rien de lourd : il doit pouvoir écrire avant le chargement
des librairies, qui prend 30 à 60 s au premier lancement.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEJA_AFFICHE = os.environ.get("_API_BOOT_LOGGED") == "1"
os.environ["_API_BOOT_LOGGED"] = "1"


def journal(message: str) -> None:
    """Écrit une ligne du journal de démarrage (au premier chargement seulement)."""
    if not _DEJA_AFFICHE:
        print(f"[api] {message}", flush=True)


def verifier_modeles(racine: Path) -> None:
    """Alerte si un modèle a été entraîné avec une AUTRE version de
    scikit-learn : le rechargement peut alors produire des résultats invalides.
    Silencieux si tout est conforme."""
    try:
        import warnings
        import joblib
        from sklearn.exceptions import InconsistentVersionWarning
        for relatif in ("models/credit_risk_model.joblib",):
            chemin = racine / relatif
            if not chemin.exists():
                continue
            with warnings.catch_warnings(record=True) as captures:
                warnings.simplefilter("always")
                joblib.load(chemin)
            if any(issubclass(c.category, InconsistentVersionWarning) for c in captures):
                journal(f"ATTENTION : {Path(relatif).name} a été entraîné avec une autre "
                        "version de scikit-learn → résultats potentiellement invalides. "
                        "Corrigez avec : python scripts/retrain_all.py")
    except Exception:
        pass
