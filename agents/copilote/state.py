"""État partagé du copilote (LangGraph), sur le modèle de celui de la flotte."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class EtatCopilote(TypedDict, total=False):
    """État circulant entre les nœuds du graphe du copilote."""
    filters: Dict[str, Any]
    question: str
    history: List[Dict[str, str]]
    mode: str
    scope: str
    kpis: Dict[str, Any]
    themes: List[str]
    documentaire: bool
    requete_documentaire: str
    texte: Optional[str]
    via: str
    trace: Annotated[List[Dict[str, Any]], operator.add]
