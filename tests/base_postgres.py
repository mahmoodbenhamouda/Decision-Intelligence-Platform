"""Base PostgreSQL de test, partagée par les tests qui touchent l'authentification.

Aucun repli : les tests s'exécutent sur PostgreSQL, ou ils sont sautés avec un
motif explicite. Les faire passer sur un autre moteur ne dirait rien du moteur
réellement servi — types, contraintes et comportement transactionnel diffèrent.

Isolation : chaque module de test reçoit son propre SCHÉMA, recréé à vide au
démarrage. Les fichiers SQLite temporaires donnaient cette isolation
gratuitement ; sur une base partagée il faut la rétablir, sans quoi les modules
se polluent et les échecs dépendent de l'ordre d'exécution.

La cible est déduite de `AUTH_DATABASE_URL` en suffixant le nom de base par
`_test` : les identifiants ne sont déclarés qu'une fois.

Création de la base, une fois : python scripts/preparer_bases.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import pytest

SUFFIXE = "_test"

# 47 octets : au-delà du minimum RFC 7518 exigé par `api.auth.security`.
SECRET_DE_TEST = "secret-de-test-uniquement-assez-long-pour-hs256"


def _charger_env() -> None:
    """Charge `.env` avant toute lecture de l'environnement.

    Sans cela, `AUTH_DATABASE_URL` paraissait absent et les cinq modules de test
    d'authentification étaient SAUTÉS — pendant que la suite affichait « 570
    passed ». Un saut compte comme un succès : c'est la pire forme d'échec.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    except Exception:
        pass


_charger_env()

# URL telle qu'elle était AVANT toute modification par ce module.
#
# `preparer()` écrit dans AUTH_DATABASE_URL une URL décorée d'un `search_path`.
# Relire la variable d'environnement au module suivant renvoyait donc une URL
# DÉJÀ décorée, et y ajouter un second `options` faisait recevoir à PostgreSQL
# deux arguments de ligne de commande — qu'il refuse. Pytest important tous les
# modules avant d'en exécuter aucun, l'erreur ne touchait que le deuxième module
# et suivants : invisible fichier par fichier.
_URL_ORIGINE = os.environ.get("AUTH_DATABASE_URL", "").strip()


def url_de_base() -> str:
    """URL de la base de test, sans schéma dédié.

    Déduite de `AUTH_DATABASE_URL` en suffixant le nom de base, afin que les
    identifiants ne soient déclarés qu'UNE fois. `AUTH_TEST_DATABASE_URL` force
    une autre cible si besoin.
    """
    forcee = os.environ.get("AUTH_TEST_DATABASE_URL", "").strip()
    principale = forcee or _URL_ORIGINE
    if not principale:
        pytest.skip(
            "AUTH_DATABASE_URL non défini : impossible de déduire la base de "
            "test. Renseignez-le dans .env (voir .env.example).",
            allow_module_level=True)

    parties = urlsplit(principale)
    # Tout `options` déjà présent est retiré : c'est ce module qui le pose, et
    # en empiler deux fait refuser la connexion.
    requete = [(k, v) for k, v in parse_qsl(parties.query) if k != "options"]
    base = parties.path.lstrip("/")
    if not base.endswith(SUFFIXE):
        base += SUFFIXE
    return urlunsplit(parties._replace(path=f"/{base}",
                                       query=urlencode(requete)))


def _nom_schema(nom_module: str) -> str:
    """Nom de schéma déduit du module : stable d'une exécution à l'autre.

    Un nom aléatoire laisserait un schéma orphelin à chaque exécution.
    """
    court = nom_module.rsplit(".", 1)[-1]
    return "t_" + re.sub(r"[^a-z0-9_]", "_", court.lower())[:50]


def _avec_schema(url: str, schema: str) -> str:
    """Ajoute `search_path` aux options libpq de l'URL."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote(f'-csearch_path={schema}')}"


def preparer(nom_module: str) -> str:
    """Crée un schéma vide pour ce module et renvoie l'URL qui l'utilise.

    Saute le module entier si PostgreSQL est injoignable, plutôt que de laisser
    chaque test échouer sur une trace de connexion illisible.
    """
    base = url_de_base()
    schema = _nom_schema(nom_module)

    try:
        from sqlalchemy import create_engine, text
        moteur = create_engine(base, connect_args={"connect_timeout": 3})
        with moteur.begin() as con:
            con.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            con.execute(text(f'CREATE SCHEMA "{schema}"'))
        moteur.dispose()
    except Exception as e:
        pytest.skip(
            f"PostgreSQL injoignable pour {nom_module} — {type(e).__name__}. "
            f"Base attendue : {base}. "
            "Aucun repli : voir tests/base_postgres.py.",
            allow_module_level=True)

    url = _avec_schema(base, schema)
    os.environ["AUTH_DATABASE_URL"] = url
    # Affectation ferme, pas `setdefault` : avec un défaut, la clé réelle de
    # production présente dans `.env` l'emportait et servait à signer tous les
    # jetons de test. Les tests n'ont aucune raison de connaître ce secret.
    os.environ["JWT_SECRET_KEY"] = SECRET_DE_TEST
    return url
