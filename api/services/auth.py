"""
api/services/auth.py
====================
Connexion et déconnexion.

- réponses d'échec IDENTIQUES (email inconnu vs mot de passe faux) pour ne pas
  divulguer l'existence d'un compte ;
- limitation PERSISTANTE des tentatives en base, par email ET par IP
  (5 échecs / 5 min) ;
- déconnexion = RÉVOCATION immédiate du jeton (denylist jti) ;
- audit systématique (login, login_failed, login_rate_limited, logout).

Le cookie httpOnly qui porte le jeton est posé et retiré par la route : c'est
un détail du transport HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import RevokedToken, User
from api.auth.security import (create_access_token, is_rate_limited,
                               purge_expired_security_rows,
                               register_failed_attempt, reset_attempts,
                               verify_password)
from api.services.erreurs import IdentifiantsInvalides, TropDeTentatives


def connecter(db: Session, email: str, mot_de_passe: str, ip: str) -> Tuple[User, str]:
    """Vérifie les identifiants et renvoie (utilisateur, jeton JWT)."""
    email = email.lower().strip()

    purge_expired_security_rows(db)   # hygiène : fenêtres/jetons expirés

    if is_rate_limited(email, db) or is_rate_limited(f"ip:{ip}", db):
        audit(db, user=None, email=email, action="login_rate_limited",
              detail=f"ip={ip}")
        raise TropDeTentatives("Trop de tentatives. Réessayez dans quelques minutes.")

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(mot_de_passe, user.password_hash):
        register_failed_attempt(email, db)
        register_failed_attempt(f"ip:{ip}", db)
        audit(db, user=None, email=email, action="login_failed", detail=f"ip={ip}")
        raise IdentifiantsInvalides("Identifiants invalides.")

    reset_attempts(email, db)
    reset_attempts(f"ip:{ip}", db)
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    audit(db, user=user, action="login", detail=f"ip={ip}")

    jeton = create_access_token(user_id=user.id, email=user.email,
                                role=user.role, client_code=user.client_code,
                                token_version=user.token_version or 0)
    return user, jeton


def deconnecter(db: Session, user: User, charge_jeton: Dict[str, Any]) -> bool:
    """Révoque le jeton courant ; renvoie True si un identifiant (jti) a été révoqué.

    Contrairement à un simple oubli côté client, le jeton devient inutilisable
    immédiatement, même s'il a été copié."""
    jti = charge_jeton.get("jti")
    exp = charge_jeton.get("exp")
    if jti and exp:
        try:
            db.add(RevokedToken(jti=jti, user_id=user.id,
                                expires_at=datetime.fromtimestamp(exp, tz=timezone.utc)))
            db.commit()
        except Exception:
            db.rollback()
    audit(db, user=user, action="logout", detail=f"jti={'révoqué' if jti else 'n/d'}")
    return bool(jti)
