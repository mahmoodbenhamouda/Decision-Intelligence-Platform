"""Les filtres du tableau de bord, sous les deux formes dont les moteurs ont besoin : le…"""

from __future__ import annotations

from typing import Any, Dict

from api.schemas.filtres import FilterRequest


def filtres_moteur(req: FilterRequest) -> Dict[str, Any]:
    """Convertit la requête en dictionnaire de filtres pour le moteur DuckDB."""
    return {
        "selected_years": req.selected_years,
        "selected_clients": req.selected_clients,
        "fidelity_filter": req.fidelity_filter,
        "date_start": req.date_start,
        "date_end": req.date_end,
        "payment_modes": req.payment_modes,
        "risk_level": req.risk_level,
        "min_amount": req.min_amount,
        "max_amount": req.max_amount,
        "periode": req.periode,
    }


def filtres_depuis_query(texte: str | None) -> Dict[str, Any]:
    """Filtres transmis en JSON dans la query `?filtres=` des routes des modèles.

    Un JSON illisible vaut « aucun filtre » : la route répond sur tout le
    portefeuille plutôt que d'échouer."""
    import json
    try:
        brut = json.loads(texte or "{}")
        return filtres_moteur(FilterRequest(**(brut if isinstance(brut, dict) else {})))
    except Exception:
        return {}


def resume_filtres(req: FilterRequest) -> Dict[str, Any]:
    return {
        "years": req.selected_years or "Toutes",
        "clients": req.selected_clients or "Tous",
        "client_count": len(req.selected_clients),
        "fidelity": req.fidelity_filter,
        "periode": req.periode,
    }
