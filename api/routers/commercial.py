"""GET /api/commercial/devis | marge | marge-decomposee | recommandations | ca-client.

Chaque route accepte `?filtres=<json>` : les filtres du tableau de bord, auxquels
s'applique la règle de portée des modèles (`ml_engine.portee`)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import commercial, marge
from api.services.filtres import filtres_depuis_query

router = APIRouter(tags=["commercial"])


@router.get("/api/commercial/devis")
def devis_a_relancer(limit: int = 200, filtres: str = "{}",
                     user: User = Depends(require_directeur),
                     db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/devis")
    return commercial.devis_a_relancer(limit, filtres_depuis_query(filtres))


@router.get("/api/commercial/marge-decomposee")
def marge_decomposee(limit: int = 15, filtres: str = "{}",
                     user: User = Depends(require_directeur),
                     db: Session = Depends(get_db)):
    """D'où vient la marge brute : par catégorie, par produit, dans le temps."""
    audit(db, user=user, action="access", resource="/api/commercial/marge-decomposee")
    return marge.decomposition(limit, filtres_depuis_query(filtres))


@router.get("/api/commercial/marge")
def marge_a_surveiller(limit: int = 15, filtres: str = "{}",
                       user: User = Depends(require_directeur),
                       db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/marge")
    return commercial.marge_a_surveiller(limit, filtres_depuis_query(filtres))


@router.get("/api/commercial/recommandations")
def recommandations_produits(client: Optional[str] = None,
                             limit: int = 15, filtres: str = "{}",
                             user: User = Depends(require_directeur),
                             db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/recommandations")
    return commercial.recommandations(client, limit, filtres_depuis_query(filtres))


@router.get("/api/commercial/ca-client")
def ca_client(horizon: int = 3, limit: int = 15, filtres: str = "{}",
              user: User = Depends(require_directeur),
              db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/commercial/ca-client")
    return commercial.ca_client(max(1, min(100, limit)), horizon,
                                filtres_depuis_query(filtres))
