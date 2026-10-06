"""État partagé de la flotte d'agents (LangGraph)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class FleetState(TypedDict, total=False):
    """État circulant entre les agents du graphe."""
    question: str
    filters: Dict[str, Any]
    kpis: Dict[str, Any]
    modeles: Dict[str, Any]
    findings: Annotated[List[Dict[str, Any]], operator.add]
    trace: Annotated[List[Dict[str, Any]], operator.add]
    fiabilite: Dict[str, Any]
    briefing: str
