"""Journal de démarrage, affiché UNE SEULE FOIS, et contrôle des modèles."""

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
    """Alerte si un modèle a été entraîné avec une AUTRE version de scikit-learn : le rechargement peut…"""
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
