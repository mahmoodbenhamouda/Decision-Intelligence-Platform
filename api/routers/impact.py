"""GET /api/impact — l'enjeu financier identifié, en dinars.

Réservé au directeur : c'est la lecture consolidée de l'entreprise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import impact as service

router = APIRouter(tags=["impact"])


@router.get("/api/impact")
def impact_financier(user: User = Depends(require_directeur),
                     db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/impact")
    return service.impact_financier()
