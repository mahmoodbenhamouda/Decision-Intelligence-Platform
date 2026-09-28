"""
api/auth/database.py
====================
Connexion SQLAlchemy à la base d'authentification.

- PRODUCTION : PostgreSQL, via la variable d'environnement `AUTH_DATABASE_URL`
  (ex. `postgresql+psycopg2://finance:***@localhost:5432/finance_auth`).
- DÉMO / TESTS : repli automatique sur SQLite (`output/auth.db`) si l'URL n'est
  pas définie — le schéma est identique (SQLAlchemy portable), la migration vers
  PostgreSQL se fait en changeant uniquement l'URL.

La base d'authentification est volontairement SÉPARÉE de l'entrepôt analytique
DuckDB : les identités/rôles d'un côté, les données métier de l'autre.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("auth.db")

_BASE_DIR = Path(__file__).resolve().parents[2]
_DEFAULT_SQLITE = f"sqlite:///{(_BASE_DIR / 'output' / 'auth.db').as_posix()}"


def _database_url() -> str:
    # Charge .env (utile quand on lance `python -m api.auth.seed` directement)
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:  # pragma: no cover
        pass
    url = os.environ.get("AUTH_DATABASE_URL", "").strip()
    if url:
        return url
    logger.warning(
        "AUTH_DATABASE_URL non défini — repli SQLite (%s). "
        "En production, utilisez PostgreSQL.", _DEFAULT_SQLITE)
    return _DEFAULT_SQLITE


class Base(DeclarativeBase):
    """Base déclarative des modèles d'authentification."""


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    """Moteur SQLAlchemy paresseux (créé au premier accès)."""
    global _engine, _SessionLocal
    if _engine is None:
        url = _database_url()
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            (_BASE_DIR / "output").mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False}
        elif url.startswith("postgresql"):
            # Échec RAPIDE si le serveur PostgreSQL n'est pas joignable
            # (sinon la connexion TCP peut bloquer le démarrage sans message).
            kwargs["connect_args"] = {"connect_timeout": 4}
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def init_db() -> None:
    """Crée les tables si absentes (idempotent) + micro-migration additive :
    les colonnes ajoutées aux modèles (ex. `full_name`, `phone`) sont créées
    par ALTER TABLE sur une base existante (SQLite et PostgreSQL)."""
    from . import models  # noqa: F401 — enregistre les modèles
    engine = get_engine()
    Base.metadata.create_all(engine)
    _ensure_columns(engine)


def _ensure_columns(engine) -> None:
    """Ajoute les colonnes manquantes des tables déclarées (migration additive)."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(engine)
        with engine.begin() as con:
            for table in Base.metadata.sorted_tables:
                if table.name not in insp.get_table_names():
                    continue
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in existing:
                        continue
                    ctype = col.type.compile(engine.dialect)
                    con.execute(text(
                        f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ctype}'))
                    logger.info("migration: %s.%s ajoutée", table.name, col.name)
    except Exception:  # pragma: no cover — best effort
        logger.exception("micro-migration en échec (colonnes)")


def get_db() -> Iterator[Session]:
    """Dépendance FastAPI : une session par requête, toujours refermée."""
    get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_for_tests(url: str) -> None:
    """Ré-initialise le moteur sur une URL donnée (utilisé par la suite de tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    os.environ["AUTH_DATABASE_URL"] = url
    _engine = None
    _SessionLocal = None
    init_db()
