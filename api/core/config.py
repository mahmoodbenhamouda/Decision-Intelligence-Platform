"""
api/core/config.py
==================
Configuration de l'API, lue dans l'environnement (et le fichier `.env`).

    FRONTEND_ORIGINS  origines autorisées par CORS, séparées par des virgules
    API_HOST          adresse d'écoute               (défaut 127.0.0.1)
    API_PORT          port d'écoute                  (défaut 9000)
    API_RELOAD        rechargement automatique       (défaut 1 ; 0 en démonstration)

Le port 9000 est l'adresse que le frontend appelle (`NEXT_PUBLIC_API_URL`,
défaut http://localhost:9000).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()

RACINE_PROJET = Path(__file__).resolve().parents[2]

_ORIGINES_PAR_DEFAUT = (
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:4000,http://127.0.0.1:4000,"
    "http://localhost:5173,http://127.0.0.1:5173"
)


def origines_cors() -> List[str]:
    """CORS restreint aux adresses du frontend."""
    brut = os.environ.get("FRONTEND_ORIGINS", _ORIGINES_PAR_DEFAUT)
    return [o.strip() for o in brut.split(",") if o.strip()]


def hote() -> str:
    return os.environ.get("API_HOST", "127.0.0.1")


def port() -> int:
    return int(os.environ.get("API_PORT", "9000"))


def rechargement() -> bool:
    """`reload=True` est pratique en développement mais relance tout le
    chargement à chaque sauvegarde : API_RELOAD=0 pour une démonstration."""
    return os.environ.get("API_RELOAD", "1") not in ("0", "false", "False")
