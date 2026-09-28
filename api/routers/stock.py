"""
api/routers/stock.py
====================
GET /api/stock           capital immobilisé, ruptures, non écoulable, fin de vie
GET /api/stock/risk      scoring du risque produit — retiré, répond 409
GET /api/stock/forecast  volumes à prévoir à 30, 60 et 90 jours
GET /api/supply          demande et dépendance fournisseur

Données internes d'exploitation : directeur uniquement.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import stock

router = APIRouter(tags=["stock"])


@router.get("/api/stock")
def stock_kpis(famille: str | None = None,
               client: str | None = None,
               user: User = Depends(require_directeur),
               db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock")
    return stock.indicateurs_stock()


@router.get("/api/stock/risk")
def stock_risk_scoring(client: str | None = None, limit: int = 25,
                       user: User = Depends(require_directeur),
                       db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock/risk")
    return stock.risque_produit(client, limit)


@router.get("/api/stock/forecast")
def stock_demand_forecast(produit: str | None = None, limit: int = 20,
                          user: User = Depends(require_directeur),
                          db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock/forecast")
    return stock.prevision_demande(produit, limit)


@router.get("/api/supply")
def supply_demand(user: User = Depends(require_directeur)):
    return stock.demande_et_approvisionnement()
