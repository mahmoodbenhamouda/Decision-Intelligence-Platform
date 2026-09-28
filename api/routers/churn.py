"""
api/routers/churn.py
====================
GET /api/churn — clients à risque de décrochage (un client ne voit que le sien).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import get_current_user
from api.auth.journal import audit
from api.auth.models import User
from api.services import churn

router = APIRouter(tags=["rétention"])


@router.get("/api/churn")
def churn_risque(limite: int = 20,
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/churn")
    return churn.clients_a_risque(limite, user)
