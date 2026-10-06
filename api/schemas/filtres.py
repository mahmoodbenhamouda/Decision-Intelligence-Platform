"""Filtres du tableau de bord, partagés par toutes les routes analytiques, et requête du copilote…"""

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
    # Période de référence des indicateurs quand aucune année ni date n'est
    # choisie : « 12m » (défaut), « annee » (année en cours), « tout ».
    periode: str = "12m"


class CopilotRequest(FilterRequest):
    question: str = ""
    history: List[Dict[str, str]] = []
