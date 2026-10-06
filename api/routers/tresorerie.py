"""POST /api/forecast prévision d'encaissements de l'entreprise (directeur) POST…"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.filtres import FilterRequest
from api.services import tresorerie

router = APIRouter(tags=["trésorerie"])


@router.post("/api/forecast")
def get_forecast(req: FilterRequest, user: User = Depends(require_directeur)):
    """Réservée au directeur : il s'agit de la trésorerie de la société, pas des données d'un client."""
    return tresorerie.prevision_encaissements()


@router.post("/api/payment-scenarios")
def payment_scenarios(req: FilterRequest,
                      user: User = Depends(require_directeur),
                      db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/payment-scenarios")
    return tresorerie.scenarios_paiement(req)
