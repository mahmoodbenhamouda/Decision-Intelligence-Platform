"""Administration — toutes les routes exigent `require_directeur` (403 sinon)."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.models import User
from api.schemas.admin import UserCreate, UserOut, UserUpdate
from api.services import admin as service

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_directeur)])


@router.get("/users", response_model=List[UserOut])
def list_users(inclure_retires: bool = False, db: Session = Depends(get_db),
               admin: User = Depends(require_directeur)):
    """Comptes de l'équipe. `inclure_retires` n'existe que pour l'inspection."""
    return service.lister_comptes(db, inclure_retires=inclure_retires)


@router.get("/roles-retires")
def compter_roles_retires(db: Session = Depends(get_db),
                          admin: User = Depends(require_directeur)):
    """Combien de comptes d'un rôle que la plateforme ne sert plus subsistent en base."""
    return {"n": service.compter_roles_retires(db)}


@router.post("/purger-roles-retires")
def purger_roles_retires(db: Session = Depends(get_db),
                         admin: User = Depends(require_directeur)):
    """Efface définitivement ces comptes. Journal d'audit préservé (anonymisé)."""
    return service.purger_roles_retires(db, admin)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db),
                admin: User = Depends(require_directeur)):
    return service.creer_compte(db, admin, body)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_directeur)):
    return service.modifier_compte(db, admin, user_id, body)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, permanent: bool = False,
                db: Session = Depends(get_db),
                admin: User = Depends(require_directeur)):
    return service.supprimer_compte(db, admin, user_id, definitif=permanent)


@router.get("/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db),
               admin: User = Depends(require_directeur)):
    return service.journal_audit(db, limit)
