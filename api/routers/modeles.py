"""GET /api/models/metrics — tableau comparatif des modules du registre (directeur)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import modeles

router = APIRouter(tags=["modèles"])


@router.get("/api/models/metrics")
def models_metrics(user: User = Depends(require_directeur),
                   db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/models/metrics")
    return modeles.tableau_des_modeles()
