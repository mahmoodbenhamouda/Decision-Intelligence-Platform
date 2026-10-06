"""POST /api/auth/login connexion : JWT remis en cookie httpOnly ET dans le corps POST…"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import AUTH_COOKIE_NAME, get_current_user
from api.auth.models import User
from api.auth.security import ACCESS_TOKEN_MINUTES
from api.schemas.auth import LoginRequest, LoginResponse, MeResponse
from api.services import auth as service

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes")


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)):
    """Connexion : vérifie bcrypt, émet un JWT (cookie httpOnly + corps), journalise."""
    ip = request.client.host if request.client else "?"
    user, token = service.connecter(db, body.email, body.password, ip)
    response.set_cookie(
        AUTH_COOKIE_NAME, token,
        httponly=True, samesite="lax", secure=_COOKIE_SECURE,
        max_age=ACCESS_TOKEN_MINUTES * 60, path="/",
    )
    return LoginResponse(access_token=token, role=user.role, email=user.email,
                         full_name=user.full_name)


@router.post("/logout")
def logout(request: Request, response: Response,
           user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    """Déconnexion : le jeton devient inutilisable immédiatement, même copié."""
    charge = getattr(request.state, "token_payload", None) or {}
    revoque = service.deconnecter(db, user, charge)
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    return {"ok": True, "revoked": revoque}


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    """Profil de l'utilisateur authentifié (pour l'UI : rôle + périmètre)."""
    return MeResponse(email=user.email, role=user.role, full_name=user.full_name,
                      last_login=user.last_login.isoformat() if user.last_login else None)
