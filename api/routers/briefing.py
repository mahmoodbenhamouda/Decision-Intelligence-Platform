"""
api/routers/briefing.py
=======================
POST /api/fleet/briefing — briefing priorisé de la flotte multi-agents.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import get_current_user
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.filtres import CopilotRequest
from api.services import briefing as service
from api.services.perimetre import restreindre

router = APIRouter(tags=["briefing"])


@router.post("/api/fleet/briefing")
def fleet_briefing(req: CopilotRequest,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    req = restreindre(req, user)
    audit(db, user=user, action="access", resource="/api/fleet/briefing")
    return service.briefing(req, user)
