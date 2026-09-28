"""
api/core/erreurs.py
===================
Traduction des erreurs en réponses HTTP — le seul endroit où un code de retour
est associé à une erreur métier.

Base d'authentification injoignable : 503, jamais 500
-----------------------------------------------------
Défaut observé : PostgreSQL arrêté, et `/api/auth/login` renvoyait un **500
Internal Server Error** accompagné d'une trace SQLAlchemy complète. Trois
problèmes distincts dans un seul événement :

  1. **Le mauvais code.** 500 signifie « le serveur a un bug ». Ici le serveur
     va bien : c'est une dépendance externe qui est absente. C'est un 503, et
     un client — navigateur, sonde de supervision, reverse proxy — n'a aucune
     raison de réessayer sur un 500 alors qu'il doit réessayer sur un 503.

  2. **Une fuite d'information.** La trace exposait les chemins du disque, la
     version de SQLAlchemy, le dialecte et l'hôte de la base. Rien de tout cela
     ne regarde le client.

  3. **Un défaut détecté puis ignoré.** Le démarrage affichait déjà
     « base d'auth inaccessible — le login échouera », et laissait pourtant la
     requête planter. Constater une panne sans la traiter est le motif que ce
     projet corrige partout ailleurs.

Le message renvoyé indique la cause ET la sortie, parce que c'est ce dont un
utilisateur a besoin : démarrer PostgreSQL, ou retirer `AUTH_DATABASE_URL` du
`.env` pour basculer sur SQLite.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from api.services.erreurs import (AccesRefuse, Conflit, DonneesInvalides,
                                  ErreurInterne, ErreurMetier,
                                  IdentifiantsInvalides, Introuvable,
                                  TropDeTentatives)

logger = logging.getLogger("api")

#: Erreur métier → code HTTP.
CODES_HTTP = {
    DonneesInvalides: 422,
    IdentifiantsInvalides: 401,
    AccesRefuse: 403,
    Introuvable: 404,
    Conflit: 409,
    TropDeTentatives: 429,
    ErreurInterne: 500,
}


def code_http(exc: ErreurMetier) -> int:
    for classe in type(exc).__mro__:
        if classe in CODES_HTTP:
            return CODES_HTTP[classe]
    return 400


def _erreur_metier(request: Request, exc: ErreurMetier) -> JSONResponse:
    # Même forme que HTTPException : {"detail": ...}
    return JSONResponse(status_code=code_http(exc), content={"detail": exc.detail})


def _base_indisponible(request: Request, exc: OperationalError) -> JSONResponse:
    logger.error("Base d'authentification injoignable sur %s : %s",
                 request.url.path, str(exc.orig)[:200])
    return JSONResponse(
        status_code=503,
        content={
            "detail": ("Base d'authentification injoignable. Le service ne peut "
                       "pas vérifier les identifiants."),
            "cause_probable": "le serveur PostgreSQL n'est pas démarré",
            "que_faire": [
                "démarrer PostgreSQL, ou",
                "retirer AUTH_DATABASE_URL du fichier .env pour utiliser SQLite",
            ],
            # Aucune trace, aucun chemin de disque, aucun nom d'hôte : la cause
            # technique complète reste dans les journaux du serveur.
        },
        headers={"Retry-After": "30"},
    )


def installer_gestion_erreurs(app: FastAPI) -> None:
    """À appeler sur toute application qui monte des routeurs de l'API — y
    compris une application de test qui n'en monte qu'un."""
    app.add_exception_handler(ErreurMetier, _erreur_metier)
    app.add_exception_handler(OperationalError, _base_indisponible)
