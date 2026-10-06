"""Boucle d'action — toutes les routes sont réservées aux comptes internes (`require_interne`) : un…"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur, require_interne
from api.auth.models import User
from api.schemas.taches import DelegationReglages, TacheCreate, TacheUpdate
from api.services import delegation
from api.services import taches as service

router = APIRouter(prefix="/api/taches", tags=["taches"],
                   dependencies=[Depends(require_interne)])


@router.get("/employes")
def liste_employes(db: Session = Depends(get_db),
                   user: User = Depends(require_interne)):
    return service.employes(db)


@router.get("/impact")
def impact(db: Session = Depends(get_db), user: User = Depends(require_interne)):
    return service.impact(db, user)


@router.get("/boucle")
def boucle(db: Session = Depends(get_db), user: User = Depends(require_directeur)):
    return service.boucle(db)


@router.get("/confiees")
def confiees(db: Session = Depends(get_db), user: User = Depends(require_interne)):
    return service.confiees(db)


@router.get("/delegation")
def delegation_etat(db: Session = Depends(get_db),
                    user: User = Depends(require_directeur)):
    return delegation.etat(db)


@router.put("/delegation")
def delegation_reglages(body: DelegationReglages, db: Session = Depends(get_db),
                        user: User = Depends(require_directeur)):
    return delegation.modifier_reglages(db, user, body.active, body.heure)


@router.post("/delegation/lancer")
def delegation_lancer(db: Session = Depends(get_db),
                      user: User = Depends(require_directeur)):
    return delegation.lancer(db, user)


@router.get("")
def lister(statut: Optional[str] = None, client_code: Optional[str] = None,
           assigne_id: Optional[int] = None, limit: int = 300,
           db: Session = Depends(get_db), user: User = Depends(require_interne)):
    return service.lister(db, user, statut, client_code, assigne_id, limit)


@router.post("", status_code=201)
def creer(body: TacheCreate, db: Session = Depends(get_db),
          user: User = Depends(require_directeur)):
    return service.creer(db, user, body)


@router.get("/{tache_id}")
def detail(tache_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_interne)):
    return service.detail(db, user, tache_id)


@router.patch("/{tache_id}")
def modifier(tache_id: int, body: TacheUpdate, db: Session = Depends(get_db),
             user: User = Depends(require_interne)):
    return service.modifier(db, user, tache_id, body)
