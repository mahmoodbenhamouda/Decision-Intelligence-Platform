"""
api/routers/portail.py
======================
Portail CLIENT (« Mon espace ») : des actions concrètes sur SES données.

GET  /api/portal/invoices         ses factures réelles, avec statut de délai
POST /api/portal/requests         déposer une demande en texte libre
GET  /api/portal/requests         suivre SES demandes et les réponses
POST /api/portal/actions          agir sur ce qu'il consulte (crée une tâche interne)
GET  /api/portal/recommandations  produits proposés, sans aucun chiffre interne

Le directeur peut consulter les factures d'un client avec `?client_code=`.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import get_current_user
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.portail import ActionCreate, RequestCreate
from api.services import portail

router = APIRouter(prefix="/api/portal", tags=["portal"])


@router.get("/invoices")
def my_invoices(client_code: Optional[str] = None, limit: int = 50,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    code = portail.code_effectif(user, client_code)
    audit(db, user=user, action="access", resource="/api/portal/invoices")
    return portail.factures(code, limit)


@router.post("/requests", status_code=201)
def create_request(body: RequestCreate,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    return portail.creer_demande(db, user, body)


@router.get("/requests")
def my_requests(user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return portail.mes_demandes(db, user)


@router.post("/actions", status_code=201)
def create_action(body: ActionCreate,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    return portail.creer_action(db, user, body)


@router.get("/recommandations")
def my_recommendations(user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    portail.exiger_code_client(user)
    audit(db, user=user, action="access", resource="/api/portal/recommandations")
    return portail.produits_proposes(db, user)
