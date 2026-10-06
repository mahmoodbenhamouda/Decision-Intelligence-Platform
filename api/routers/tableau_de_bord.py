"""POST /api/dashboard indicateurs, options de filtre, trace de l'agent POST /api/ai_insight…"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.filtres import FilterRequest
from api.services import tableau_de_bord

router = APIRouter(tags=["tableau de bord"])


@router.post("/api/dashboard")
def get_dashboard_data(req: FilterRequest,
                       user: User = Depends(require_directeur),
                       db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/dashboard")
    return tableau_de_bord.indicateurs(req, user)


@router.post("/api/ai_insight")
def get_ai_insight(req: FilterRequest,
                   user: User = Depends(require_directeur),
                   db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/ai_insight")
    return tableau_de_bord.synthese(req)
