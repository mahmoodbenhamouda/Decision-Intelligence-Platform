"""État partagé du copilote (LangGraph), sur le modèle de celui de la flotte."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class EtatCopilote(TypedDict, total=False):
    """État circulant entre les nœuds du graphe du copilote.

    `trace` utilise le réducteur `operator.add` : chaque nœud y ajoute ses
    étapes, et la trace complète dit par où la réponse est passée.
    """
    filters: Dict[str, Any]                 # périmètre (déjà restreint par l'API)
    question: str                           # vide en mode tableau de bord
    history: List[Dict[str, str]]           # derniers échanges de la conversation
    mode: str                               # « qa » ou « dashboard »
    scope: str                              # « global » ou « client »
    kpis: Dict[str, Any]                    # indicateurs du périmètre + prévision + radar
    themes: List[str]                       # thèmes financiers de la question
    documentaire: bool                      # la base documentaire doit-elle être consultée ?
    requete_documentaire: str               # question sans le préfixe « doc: »
    texte: Optional[str]                    # réponse retenue
    via: str                                # « rag », « llm » ou « regles »
    trace: Annotated[List[Dict[str, Any]], operator.add]
