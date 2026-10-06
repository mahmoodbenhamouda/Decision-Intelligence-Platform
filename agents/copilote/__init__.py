"""Copilote FinBot — organisé comme la flotte : état, nœuds, graphe LangGraph."""

from agents.copilote.fichier import analyser_fichier
from agents.copilote.graph import Copilote, copilote

__all__ = ["Copilote", "copilote", "analyser_fichier"]
