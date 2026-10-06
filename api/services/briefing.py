"""Briefing de la flotte multi-agents (LangGraph) : Recouvrement, Trésorerie, Risque client, Stock…"""

from __future__ import annotations

from typing import Any, Dict

from api.auth.models import ROLE_DIRECTEUR, User
from api.schemas.filtres import CopilotRequest
from api.services.filtres import filtres_moteur, resume_filtres


def briefing(req: CopilotRequest, user: User) -> Dict[str, Any]:
    try:
        from agents.fleet.graph import run_briefing
        from ml_engine import portee as po
        filtres = filtres_moteur(req)
        p = po.portee(filtres)
        out = run_briefing(filtres, question=(req.question or None))
        return {
            "portee_modeles": {"mode": p["mode"], "motif": p["motif"],
                               "n_clients": len(p["clients"] or [])},
            "briefing": out.get("briefing", ""),
            "findings": out.get("findings", []),
            "trace": out.get("trace", []),
            "engine": out.get("engine", ""),
            "fiabilite": out.get("fiabilite") if user.role == ROLE_DIRECTEUR else None,
            "active_filters": resume_filtres(req),
        }
    except Exception as e:
        return {"briefing": f"Erreur flotte : {e}", "findings": [], "trace": [],
                "engine": "erreur", "fiabilite": None}
