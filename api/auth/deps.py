"""Dépendances de sécurité FastAPI : utilisateur courant (JWT en cookie httpOnly ou en Bearer) et…"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .journal import audit
from .models import ROLE_DIRECTEUR, ROLE_EMPLOYE, User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

AUTH_COOKIE_NAME = "finbot_access"


def _extract_token(request: Request,
                   creds: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    """JWT depuis l'en-tête `Authorization: Bearer` OU le cookie httpOnly."""
    if creds is not None and creds.credentials:
        return creds.credentials
    return request.cookies.get(AUTH_COOKIE_NAME)


def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Résout l'utilisateur depuis le JWT (cookie httpOnly ou Bearer)."""
    token = _extract_token(request, creds)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Authentification requise.",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Jeton invalide ou expiré.",
                            headers={"WWW-Authenticate": "Bearer"})

    jti = payload.get("jti")
    if jti:
        from .models import RevokedToken
        from sqlalchemy import select
        revoked = db.execute(select(RevokedToken.id)
                             .where(RevokedToken.jti == jti)).first()
        if revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Session terminée (jeton révoqué).")

    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Compte inconnu ou désactivé.")

    if int(payload.get("ver", 0)) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session expirée (mot de passe modifié).")

    request.state.user = user
    request.state.token_payload = payload
    return user


def require_directeur(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> User:
    """403 si l'utilisateur n'est pas directeur (ressources globales)."""
    if user.role != ROLE_DIRECTEUR:
        audit(db, user=user, action="forbidden", detail="ressource directeur")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Accès réservé au directeur.")
    return user


def require_interne(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> User:
    """403 si l'utilisateur n'est pas un compte INTERNE (directeur ou employé)."""
    if user.role not in (ROLE_DIRECTEUR, ROLE_EMPLOYE):
        audit(db, user=user, action="forbidden", detail="ressource interne")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Accès réservé à l'équipe interne.")
    return user
