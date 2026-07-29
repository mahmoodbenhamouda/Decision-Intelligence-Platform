"""État partagé de la flotte d'agents (LangGraph)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class FleetState(TypedDict, total=False):
    """État circulant entre les agents du graphe.

    `findings` et `trace` utilisent le réducteur `operator.add` : quand plusieurs
    agents s'exécutent en parallèle, leurs listes sont concaténées automatiquement.
    """
    question: str
    filters: Dict[str, Any]
    kpis: Dict[str, Any]                                   # données internes (ERP)
    intel: Dict[str, Any]                                  # signaux externes (veille)
    findings: Annotated[List[Dict[str, Any]], operator.add]   # constats des agents
    trace: Annotated[List[Dict[str, Any]], operator.add]      # journal d'exécution
    briefing: str                                         # synthèse finale (rédacteur)
