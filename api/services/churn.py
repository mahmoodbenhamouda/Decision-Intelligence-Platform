"""Rétention : clients à risque de décrochage dans les 90 jours, classés par enjeu."""

from __future__ import annotations

from typing import Any, Dict

from ml_engine import passerelle as pw
from ml_engine import portee as po


def clients_a_risque(limite: int, filtres: Dict[str, Any] | None = None) -> Dict[str, Any]:
    p = po.portee(filtres)
    cache = po.pour_analyse_par_client(p)
    if cache:
        return cache
    try:
        data = pw.decrochage_servi(limite=max(1, min(limite, 100)), clients=p["clients"])
    except Exception as e:
        return {"servi": False, "motif": f"indisponible : {e}"}
    return po.annoter(data, p)
