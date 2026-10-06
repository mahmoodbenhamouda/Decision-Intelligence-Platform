"""Journal d'audit : qui a fait quoi, quand."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from .models import AuditLog, User

logger = logging.getLogger("auth")


def audit(db: Session, *, user: Optional[User], action: str,
          resource: Optional[str] = None, detail: Optional[str] = None,
          email: Optional[str] = None) -> None:
    """Écrit une entrée d'audit (best-effort : ne bloque jamais la requête)."""
    try:
        db.add(AuditLog(user_id=user.id if user else None,
                        email=email or (user.email if user else None),
                        action=action, resource=resource, detail=detail))
        db.commit()
    except Exception:  # pragma: no cover
        db.rollback()
        logger.exception("audit_log en échec")
