"""Chargement des deux moteurs dont dépendent les services, sans jamais empêcher l'API de démarrer."""

from __future__ import annotations

from api.core.demarrage import journal

journal("chargement du moteur d'indicateurs…")
try:
    from ml_engine.analytics import kpi_engine
    MOTEUR_OK = True
    ERREUR_MOTEUR = ""
except Exception as exc:  # pragma: no cover
    kpi_engine = None
    MOTEUR_OK = False
    ERREUR_MOTEUR = str(exc)

journal("chargement du copilote (LLM/RAG)…")
try:
    from agents.copilote import copilote
    AGENT_OK = True
    ERREUR_AGENT = ""
except Exception as exc:  # pragma: no cover
    copilote = None
    AGENT_OK = False
    ERREUR_AGENT = str(exc)


def moteur_disponible() -> bool:
    return MOTEUR_OK and kpi_engine is not None


def agent_disponible() -> bool:
    return AGENT_OK and copilote is not None
