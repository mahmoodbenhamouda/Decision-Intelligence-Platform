"""
agents/copilote/fichier.py
==========================
Réponse sur un fichier joint (CSV, PDF textuel), croisée avec les indicateurs
de la plateforme. La lecture du fichier est faite par l'API
(`api/services/fichiers.py`) ; ici, seulement le contexte et le modèle.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from agents.copilote import llm
from agents.copilote.contexte import build_thematic_context
from agents.copilote.intention import detect_theme
from agents.copilote.prompt import prompt_fichier


def analyser_fichier(question: str, extension: str, resume_fichier: str, texte: str,
                     kpis: Dict[str, Any]) -> Optional[str]:
    """Réponse du modèle de langage, ou None (aucun modèle : l'API répond alors
    par un résumé du fichier)."""
    try:
        contexte = build_thematic_context(detect_theme(question), kpis)
    except Exception:
        return None
    return llm.interroger(prompt_fichier(question, extension, resume_fichier, texte, contexte))
