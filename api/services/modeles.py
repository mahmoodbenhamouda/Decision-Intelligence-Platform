"""Tableau comparatif de TOUS les modules du registre : nature, statut, métrique hors période,…"""

from __future__ import annotations

from typing import Any, Dict

from api.services.serialisation import json_safe
from ml_engine import passerelle as pw


def tableau_des_modeles() -> Dict[str, Any]:
    try:
        return json_safe({"modeles": pw.tableau_des_modeles()})
    except Exception as e:
        return {"error": f"indisponible : {e}", "modeles": []}
