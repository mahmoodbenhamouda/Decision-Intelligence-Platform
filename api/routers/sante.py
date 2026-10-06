"""GET /api/health — les deux moteurs se sont-ils chargés, et sinon pourquoi."""

from __future__ import annotations

from fastapi import APIRouter

from api.core import moteurs

router = APIRouter(tags=["santé"])


@router.get("/api/health")
def health():
    return {"engine": moteurs.MOTEUR_OK, "engine_error": moteurs.ERREUR_MOTEUR,
            "agent": moteurs.AGENT_OK, "agent_error": moteurs.ERREUR_AGENT}
