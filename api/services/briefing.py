"""
api/services/briefing.py
========================
Briefing de la flotte multi-agents (LangGraph) : Recouvrement, Trésorerie,
Risque client, Stock & Approvisionnement, Commercial → arbitre → briefing
priorisé.

Directeur : briefing global et volet fiabilité des modèles. Client : briefing
restreint à son périmètre, sans volet fiabilité (méthodologie interne).
"""

from __future__ import annotations

from typing import Any, Dict

from api.auth.models import ROLE_DIRECTEUR, User
from api.schemas.filtres import CopilotRequest
from api.services.filtres import filtres_moteur, resume_filtres


def briefing(req: CopilotRequest, user: User) -> Dict[str, Any]:
    try:
        from agents.fleet.graph import run_briefing
        out = run_briefing(filtres_moteur(req), question=(req.question or None))
        return {
            "briefing": out.get("briefing", ""),
            "findings": out.get("findings", []),
            "trace": out.get("trace", []),
            "engine": out.get("engine", ""),
            # Réservé au directeur : les motifs de refus décrivent la
            # méthodologie interne. Sur un périmètre client la flotte ne le
            # produit déjà pas ; ce filtre est une seconde garde.
            "fiabilite": out.get("fiabilite") if user.role == ROLE_DIRECTEUR else None,
            "active_filters": resume_filtres(req),
        }
    except Exception as e:
        return {"briefing": f"Erreur flotte : {e}", "findings": [], "trace": [],
                "engine": "erreur", "fiabilite": None}
