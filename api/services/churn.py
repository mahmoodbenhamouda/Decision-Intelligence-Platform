"""
api/services/churn.py
=====================
Rétention : clients à risque de décrochage dans les 90 jours, classés par enjeu.

Le modèle n'est interrogé que si le registre le déclare servi : la décision de
déploiement est appliquée ici, pas seulement documentée ailleurs. Un compte
`client` ne reçoit que SON propre score ; le filtrage est fait côté serveur.
"""

from __future__ import annotations

from typing import Any, Dict

from api.auth.models import ROLE_DIRECTEUR, User
from ml_engine import passerelle as pw


def clients_a_risque(limite: int, user: User) -> Dict[str, Any]:
    try:
        data = pw.decrochage_servi(limite=max(1, min(limite, 100)))
    except Exception as e:
        return {"servi": False, "motif": f"indisponible : {e}"}

    if not data.get("servi"):
        return data

    if user.role == ROLE_DIRECTEUR:
        return {**data, "scope": "global"}

    code = (user.client_code or "").strip().lower()
    mien = [c for c in data.get("top", [])
            if str(c.get("code") or "").strip().lower() == code]
    return {
        "servi": True, "scope": "client",
        "top": mien,
        "n_clients_scores": len(mien),
        "lecture": data.get("lecture"),
    }
