"""GET /api/churn — clients à risque de décrochage (directeur)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import churn
from api.services.filtres import filtres_depuis_query

router = APIRouter(tags=["rétention"])


@router.get("/api/churn")
def churn_risque(limite: int = 20, filtres: str = "{}",
                 user: User = Depends(require_directeur),
                 db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/churn")
    return churn.clients_a_risque(limite, filtres_depuis_query(filtres))
