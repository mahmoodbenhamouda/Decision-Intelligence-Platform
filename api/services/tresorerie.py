"""Trésorerie : prévision d'encaissements de l'entreprise et scénarios de retard de paiement."""

from __future__ import annotations

from typing import Any, Dict

from api.schemas.filtres import FilterRequest
from api.services.filtres import filtres_moteur
from api.services.serialisation import json_safe
from ml_engine import passerelle as pw


def prevision_encaissements() -> Dict[str, Any]:
    """Prévision GLOBALE à 6 mois (LSTM, avec repli)."""
    try:
        fc = pw.prevision_encaissements(horizon=6)
        if not fc:
            return {"error": "Série d'échéances insuffisante pour la prévision."}
        return {"forecast": json_safe(fc)}
    except Exception as e:
        return {"error": str(e)}


def scenarios_paiement(req: FilterRequest) -> Dict[str, Any]:
    """Impact CHIFFRÉ d'hypothèses de retard de paiement, l'hypothèse restant explicite et modifiable."""
    try:
        from ml_engine.analytics.payment_scenario import compute_scenarios
        return compute_scenarios(filtres_moteur(req))
    except Exception as e:
        return {"error": str(e), "scenarios": []}
