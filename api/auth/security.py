"""Primitives de sécurité : hachage bcrypt, JWT signés à expiration, politique de mot de passe,…"""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
import bcrypt as _bcrypt

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


_ALGO = "HS256"
ACCESS_TOKEN_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "480"))

# RFC 7518 §3.2 : une clé HMAC-SHA256 doit faire au moins 256 bits. En dessous,
# la résistance de la signature tombe à la taille de la clé, pas à celle du
# condensat.
LONGUEUR_MIN_SECRET = 32

_GENERER = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'

_SANS_SECRET = (
    "JWT_SECRET_KEY n'est pas défini. Aucun secret n'est généré à la volée : un "
    "secret tiré au démarrage est différent dans chaque processus, donc un jeton "
    "émis par un worker est rejeté par les autres (401 intermittents, sans "
    "message), et tout redémarrage invalide les sessions en cours.\n"
    f"  Générer : {_GENERER}\n"
    "  Puis renseigner JWT_SECRET_KEY dans .env (voir .env.example)."
)

_SECRET_TROP_COURT = (
    "JWT_SECRET_KEY fait {n} octets, en dessous du minimum de "
    "{minimum} exigé par la RFC 7518 §3.2 pour HS256.\n"
    f"  Générer un remplacement : {_GENERER}\n"
    "  La rotation invalide les jetons en circulation : reconnexion nécessaire."
)


class ConfigurationSecuriteInvalide(RuntimeError):
    """Secret de signature absent ou trop court."""


def verifier_secret() -> None:
    """Valide JWT_SECRET_KEY, ou échoue avec un message actionnable.

    Appelée au démarrage. La vérification vit dans une fonction et non à
    l'import : importer le module ne doit rien exiger, démarrer doit tout exiger.
    """
    s = os.environ.get("JWT_SECRET_KEY", "").strip()
    if not s:
        raise ConfigurationSecuriteInvalide(_SANS_SECRET)
    n = len(s.encode("utf-8"))
    if n < LONGUEUR_MIN_SECRET:
        raise ConfigurationSecuriteInvalide(
            _SECRET_TROP_COURT.format(n=n, minimum=LONGUEUR_MIN_SECRET))


def _secret() -> str:
    """Secret de signature. Aucun repli : une clé absente est une erreur."""
    verifier_secret()
    return os.environ["JWT_SECRET_KEY"].strip()


def create_access_token(*, user_id: int, email: str, role: str,
                        token_version: int = 0) -> str:
    """Émet un JWT signé, à expiration, portant l'identité et le périmètre."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "jti": secrets.token_urlsafe(24),
        "ver": int(token_version),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TOKEN_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Décode et vérifie signature + expiration."""
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None


LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))

_attempts: Dict[str, deque] = defaultdict(deque)


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
            pass
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
