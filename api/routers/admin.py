"""
api/routers/admin.py
====================
Administration — toutes les routes exigent `require_directeur` (403 sinon).

GET    /api/admin/users              comptes (avec « présent dans l'ERP »)
POST   /api/admin/users              créer un compte
PATCH  /api/admin/users/{id}         modifier un compte
DELETE /api/admin/users/{id}         désactiver (défaut) ou supprimer (`permanent=true`)
GET    /api/admin/erp-clients        codes clients réels de l'entrepôt
GET    /api/admin/requests           demandes clients (filtre `status`)
PATCH  /api/admin/requests/{id}      traiter une demande
GET    /api/admin/audit              journal d'audit
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.models import User
from api.schemas.admin import RequestUpdate, UserCreate, UserOut, UserUpdate
from api.services import admin as service

router = APIRouter(prefix="/api/admin", tags=["admin"],
                   dependencies=[Depends(require_directeur)])


@router.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db),
               admin: User = Depends(require_directeur)):
    return service.lister_comptes(db)


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


@router.get("/erp-clients")
def erp_clients(admin: User = Depends(require_directeur)):
    return service.clients_erp()


@router.get("/requests")
def list_requests(status: Optional[str] = None, db: Session = Depends(get_db),
                  admin: User = Depends(require_directeur)):
    return service.lister_demandes(db, status)


@router.patch("/requests/{req_id}")
def update_request(req_id: int, body: RequestUpdate, db: Session = Depends(get_db),
                   admin: User = Depends(require_directeur)):
    return service.traiter_demande(db, admin, req_id, body)


@router.get("/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db),
               admin: User = Depends(require_directeur)):
    return service.journal_audit(db, limit)
