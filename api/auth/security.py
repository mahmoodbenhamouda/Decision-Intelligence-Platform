"""
api/auth/security.py
====================
Primitives de sécurité : hachage bcrypt, JWT signés à expiration, politique de
mot de passe, protection anti-brute-force (rate limiting en mémoire).

Secrets : `JWT_SECRET_KEY` DOIT être fourni en variable d'environnement en
production (jamais committé). En développement, un secret aléatoire éphémère
est généré (les sessions ne survivent pas au redémarrage — comportement voulu).
"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
import bcrypt as _bcrypt

# ── Hachage : bcrypt avec sel intégré (jamais réversible) ───────────────────
# On utilise la librairie `bcrypt` DIRECTEMENT (et non passlib) : passlib fait
# une détection de version au premier appel qui est lente et incompatible avec
# bcrypt >= 4.1. Le coût de ~0,2-0,3 s par hachage est VOLONTAIRE (12 rounds,
# standard OWASP) : il rend le brute-force hors ligne impraticable.
_BCRYPT_ROUNDS = 12


def hash_password(plain: str) -> str:
    """Hache un mot de passe (bcrypt, sel aléatoire intégré au hash)."""
    return _bcrypt.hashpw(plain.encode("utf-8"),
                          _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Vérifie un mot de passe en temps quasi constant (anti-timing)."""
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


# ── Politique de mot de passe ───────────────────────────────────────────────
PASSWORD_MIN_LENGTH = 10


def password_policy_errors(plain: str) -> list[str]:
    """Retourne la liste des règles non respectées (vide = conforme)."""
    errs = []
    if len(plain) < PASSWORD_MIN_LENGTH:
        errs.append(f"au moins {PASSWORD_MIN_LENGTH} caractères")
    if not any(c.isupper() for c in plain):
        errs.append("au moins une majuscule")
    if not any(c.islower() for c in plain):
        errs.append("au moins une minuscule")
    if not any(c.isdigit() for c in plain):
        errs.append("au moins un chiffre")
    return errs


# ── JWT ─────────────────────────────────────────────────────────────────────
_ALGO = "HS256"
ACCESS_TOKEN_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))  # 8 h


def _secret() -> str:
    s = os.environ.get("JWT_SECRET_KEY", "").strip()
    if not s:
        # Dev uniquement : secret éphémère par processus.
        s = os.environ.setdefault("_JWT_DEV_SECRET", secrets.token_urlsafe(48))
    return s


def create_access_token(*, user_id: int, email: str, role: str,
                        client_code: Optional[str],
                        token_version: int = 0) -> str:
    """Émet un JWT signé, à expiration, portant l'identité et le périmètre.

    - `jti` : identifiant unique du jeton → permet la RÉVOCATION unitaire
      (logout) via la table `revoked_tokens`.
    - `ver` : version de jeton du compte → un changement de mot de passe
      incrémente la version et invalide TOUS les jetons antérieurs.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "client_code": client_code,
        "jti": secrets.token_urlsafe(24),
        "ver": int(token_version),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Décode et vérifie signature + expiration. None si invalide/expiré."""
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None


# ── Anti-brute-force : fenêtre glissante PERSISTANTE (table login_attempts) ─
# En base plutôt qu'en mémoire : le compteur survit aux redémarrages et reste
# correct en multi-instances (plusieurs workers/serveurs derrière un proxy).
# Un repli mémoire est conservé si la base est momentanément indisponible.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))  # 5 min

_attempts: Dict[str, deque] = defaultdict(deque)   # repli mémoire uniquement


def _window_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=LOGIN_WINDOW_SECONDS)


def is_rate_limited(key: str, db=None) -> bool:
    """True si `key` (email ou 'ip:…') a dépassé le quota d'échecs récents."""
    if db is not None:
        try:
            from sqlalchemy import func, select
            from .models import LoginAttempt
            n = db.execute(
                select(func.count()).select_from(LoginAttempt)
                .where(LoginAttempt.key == key, LoginAttempt.at >= _window_start())
            ).scalar_one()
            return int(n) >= LOGIN_MAX_ATTEMPTS
        except Exception:
            pass  # repli mémoire
    now = time.time()
    dq = _attempts[key]
    while dq and now - dq[0] > LOGIN_WINDOW_SECONDS:
        dq.popleft()
    return len(dq) >= LOGIN_MAX_ATTEMPTS


def register_failed_attempt(key: str, db=None) -> None:
    if db is not None:
        try:
            from .models import LoginAttempt
            db.add(LoginAttempt(key=key))
            db.commit()
            return
        except Exception:
            db.rollback()
    _attempts[key].append(time.time())


def reset_attempts(key: str, db=None) -> None:
    if db is not None:
        try:
            from sqlalchemy import delete
            from .models import LoginAttempt
            db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
            db.commit()
        except Exception:
            db.rollback()
    _attempts.pop(key, None)


def purge_expired_security_rows(db) -> None:
    """Purge opportuniste : tentatives hors fenêtre + jetons révoqués expirés."""
    try:
        from sqlalchemy import delete
        from .models import LoginAttempt, RevokedToken
        db.execute(delete(LoginAttempt).where(LoginAttempt.at < _window_start()))
        db.execute(delete(RevokedToken)
                   .where(RevokedToken.expires_at < datetime.now(timezone.utc)))
        db.commit()
    except Exception:
        db.rollback()
