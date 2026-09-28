"""
api/core/moteurs.py
===================
Chargement des deux moteurs dont dépendent les services, sans jamais empêcher
l'API de démarrer.

* le moteur KPI DuckDB (`ml_engine.analytics.kpi_engine`) ;
* le copilote FinBot, chef d'orchestre à outils (`agents.copilote`).

Si l'un d'eux ne se charge pas, l'API démarre quand même : les services
basculent sur leur repli (moteur direct, puis calcul pandas), et
`GET /api/health` expose la cause. Les services lisent ces attributs au moment
de l'appel (`moteurs.copilote`), jamais par copie à l'import.
"""

from __future__ import annotations

from api.core.demarrage import journal

journal("chargement du moteur KPI (DuckDB)…")
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
