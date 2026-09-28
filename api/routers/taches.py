"""
api/routers/taches.py
=====================
Boucle d'action — toutes les routes sont réservées aux comptes internes
(`require_interne`) : un client n'y a jamais accès.

GET   /api/taches/employes  à qui confier une tâche, avec sa charge
GET   /api/taches/impact    ce que les actions ont rapporté
GET   /api/taches/boucle    ce qui est déjà reparti vers les modèles (directeur)
GET   /api/taches/confiees  alertes déjà confiées (« Confiée à … »)
GET   /api/taches           tableau de suivi (un employé : SES tâches)
POST  /api/taches           confier une tâche (directeur)
GET   /api/taches/{id}      détail et historique
PATCH /api/taches/{id}      avancer, réaffecter (directeur), clôturer avec un résultat
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur, require_interne
from api.auth.models import User
from api.schemas.taches import TacheCreate, TacheUpdate
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
