"""Connexion SQLAlchemy à la base d'authentification."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("auth.db")

_BASE_DIR = Path(__file__).resolve().parents[2]

_SANS_URL = (
    "AUTH_DATABASE_URL n'est pas défini. Cette application exige PostgreSQL ; "
    "il n'existe aucun repli.\n"
    "  Exemple : AUTH_DATABASE_URL="
    "postgresql+psycopg2://finance:MOTDEPASSE@localhost:5432/finance_auth\n"
    "  Renseignez-le dans le fichier .env (voir .env.example)."
)

_MAUVAIS_MOTEUR = (
    "AUTH_DATABASE_URL vaut « {url} », qui n'est pas une URL PostgreSQL.\n"
    "  Seul PostgreSQL est supporté : les types, les contraintes et le "
    "comportement transactionnel diffèrent d'un moteur à l'autre, et une "
    "application validée sur un autre moteur n'est pas validée.\n"
    "  Attendu : postgresql://… ou postgresql+psycopg2://…"
)


class ConfigurationBaseInvalide(RuntimeError):
    """Configuration de base de données absente ou incompatible."""


def _database_url() -> str:
    """URL PostgreSQL de la base d'authentification, ou erreur explicite.

    Aucun repli SQLite. L'ancien comportement démarrait sur un fichier local
    quand la variable manquait : l'application semblait fonctionner, sur une base
    vide et un moteur différent de celui de production.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(override=False)
    except Exception:  # pragma: no cover
        pass

    url = os.environ.get("AUTH_DATABASE_URL", "").strip()
    if not url:
        raise ConfigurationBaseInvalide(_SANS_URL)
    if not url.startswith("postgresql"):
        raise ConfigurationBaseInvalide(_MAUVAIS_MOTEUR.format(url=url))
    return url


class Base(DeclarativeBase):
    """Base déclarative des modèles d'authentification."""


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    """Moteur SQLAlchemy paresseux (créé au premier accès)."""
    global _engine, _SessionLocal
    if _engine is None:
        url = _database_url()
        _engine = create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 4})
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False,
                                     expire_on_commit=False)
    return _engine


def init_db() -> None:
    """Crée les tables si absentes (idempotent) + micro-migration additive : les colonnes ajoutées aux…"""
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
    """Ré-initialise le moteur sur une URL PostgreSQL donnée.

    Refuse toute URL non PostgreSQL, y compris depuis les tests : des tests qui
    passent sur un autre moteur ne disent rien du moteur réellement servi.
    """
    if not url.startswith("postgresql"):
        raise ConfigurationBaseInvalide(_MAUVAIS_MOTEUR.format(url=url))
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    os.environ["AUTH_DATABASE_URL"] = url
    _engine = None
    _SessionLocal = None
    init_db()


def verifier_connexion() -> None:
    """Ouvre une connexion et échoue bruyamment si PostgreSQL est injoignable.

    Appelée au démarrage : une application qui annonce « startup complete » puis
    renvoie 500 au premier login n'a pas démarré, elle a différé son échec.
    """
    from sqlalchemy import text
    with get_engine().connect() as con:
        con.execute(text("SELECT 1"))
