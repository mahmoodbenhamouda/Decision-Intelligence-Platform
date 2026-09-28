"""
api/routers/tableau_de_bord.py
==============================
POST /api/dashboard   indicateurs, options de filtre, trace de l'agent
POST /api/ai_insight  synthèse écrite (LLM, sinon règles)

Tout utilisateur authentifié ; le périmètre d'un client est forcé côté serveur.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import get_current_user
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.filtres import FilterRequest
from api.services import tableau_de_bord
from api.services.perimetre import restreindre

router = APIRouter(tags=["tableau de bord"])


@router.post("/api/dashboard")
def get_dashboard_data(req: FilterRequest,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    req = restreindre(req, user)
    audit(db, user=user, action="access", resource="/api/dashboard")
    return tableau_de_bord.indicateurs(req, user)


@router.post("/api/ai_insight")
def get_ai_insight(req: FilterRequest,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    req = restreindre(req, user)
    audit(db, user=user, action="access", resource="/api/ai_insight")
    return tableau_de_bord.synthese(req)
