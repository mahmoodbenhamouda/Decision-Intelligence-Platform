"""Crée les bases PostgreSQL du projet, sans outils clients.

`createdb` fait partie des outils clients PostgreSQL, souvent absents du PATH sur
Windows même quand le serveur tourne. Ce script fait la même chose via psycopg2,
déjà installé avec l'API.

    python scripts/preparer_bases.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

SUFFIXE_TEST = "_test"


def _charger_env() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv(RACINE / ".env", override=False)
    except Exception:
        pass
    import os
    url = os.environ.get("AUTH_DATABASE_URL", "").strip()
    if not url:
        print("  AUTH_DATABASE_URL n'est pas défini.")
        print("  Copiez .env.example vers .env et renseignez-le.")
        raise SystemExit(2)
    if not url.startswith("postgresql"):
        print(f"  AUTH_DATABASE_URL n'est pas une URL PostgreSQL : {url[:60]}")
        raise SystemExit(2)
    return url


def _parametres(url: str) -> dict:
    """Paramètres de connexion psycopg2, en visant la base d'administration."""
    p = urlsplit(url)
    options = dict(parse_qsl(p.query))
    return {
        # Un `host` en paramètre de requête l'emporte : c'est la forme utilisée
        # pour une connexion par socket Unix, où la partie hôte de l'URL est vide.
        "host": options.get("host") or p.hostname or "localhost",
        "port": p.port or 5432,
        "user": p.username or "postgres",
        "password": p.password or "",
        # On se connecte à `postgres` : on ne peut pas créer une base depuis
        # elle-même, et `postgres` existe sur toute installation.
        "dbname": "postgres",
    }


def _nom_base(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


def creer(params: dict, nom: str) -> str:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    con = psycopg2.connect(connect_timeout=4, **params)
    con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nom,))
            if cur.fetchone():
                return "existe déjà"
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nom)))
            return "créée"
    finally:
        con.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    url = _charger_env()
    params = _parametres(url)
    principale = _nom_base(url)
    de_test = principale + SUFFIXE_TEST

    print("=" * 70)
    print("  BASES POSTGRESQL DU PROJET")
    print("=" * 70)
    print(f"\n  Serveur : {params['user']}@{params['host']}:{params['port']}")

    try:
        for nom in (principale, de_test):
            print(f"  {nom:<32} {creer(params, nom)}")
    except Exception as e:
        motif = str(e).strip().splitlines()[0][:120]
        print(f"\n  ÉCHEC : {motif}")
        print("\n  Le serveur PostgreSQL ne répond pas. Au choix :")
        print("    docker compose -f docker-compose.postgres.yml up -d")
        print("    ou démarrez le service PostgreSQL installé sur la machine")
        print("\n  Vérifiez aussi que les identifiants de AUTH_DATABASE_URL")
        print("  correspondent à ceux du serveur.")
        print("=" * 70)
        return 1

    print(f"\n  La base de test « {de_test} » est utilisée par pytest.")
    print("  Chaque module de test y reçoit son propre schéma, recréé à vide.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
