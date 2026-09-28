"""
api/routers/commercial.py
=========================
GET /api/commercial/devis            devis à relancer (directeur)
GET /api/commercial/marge            marge à surveiller (directeur)
GET /api/commercial/recommandations  produits à proposer (un client : les siens)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import get_current_user, require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import commercial

router = APIRouter(tags=["commercial"])


@router.get("/api/commercial/devis")
def devis_a_relancer(limit: int = 20,
                     user: User = Depends(require_directeur),
                     db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/devis")
    return commercial.devis_a_relancer(limit)


@router.get("/api/commercial/marge")
def marge_a_surveiller(limit: int = 15,
                       user: User = Depends(require_directeur),
                       db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/marge")
    return commercial.marge_a_surveiller(limit)


@router.get("/api/commercial/recommandations")
def recommandations_produits(client: Optional[str] = None,
                             limit: int = 15,
                             user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/recommandations")
    return commercial.recommandations(client, limit, user)
