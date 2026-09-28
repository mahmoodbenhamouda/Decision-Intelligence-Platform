"""
api/schemas/filtres.py
======================
Filtres du tableau de bord, partagés par toutes les routes analytiques, et
requête du copilote (les mêmes filtres + une question et l'historique).
"""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel


class FilterRequest(BaseModel):
    selected_years: List[int] = []
    selected_clients: List[str] = []
    fidelity_filter: str = "Tous"
    date_start: str | None = None
    date_end: str | None = None
    payment_modes: List[str] = []
    risk_level: str = "Tous"
    min_amount: float | None = None
    max_amount: float | None = None


class CopilotRequest(FilterRequest):
    question: str = ""
    # Historique de conversation : liste de {role: 'user'|'assistant', text: str}
    # Les N derniers messages sont envoyés au LLM pour maintenir le contexte.
    history: List[Dict[str, str]] = []
