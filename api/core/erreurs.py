"""Traduction des erreurs en réponses HTTP — le seul endroit où un code de retour est associé à une…"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError

from api.services.erreurs import (AccesRefuse, Conflit, DonneesInvalides,
                                  ErreurInterne, ErreurMetier,
                                  IdentifiantsInvalides, Introuvable,
                                  TropDeTentatives)

logger = logging.getLogger("api")

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
                "démarrer PostgreSQL",
                "vérifier AUTH_DATABASE_URL dans le fichier .env",
            ],
        },
        headers={"Retry-After": "30"},
    )


def _contrainte_violee(request: Request, exc: IntegrityError) -> JSONResponse:
    # Sans ce gestionnaire, l'erreur remonte en 500 HORS du middleware CORS :
    # la réponse n'a pas d'en-tête Access-Control-Allow-Origin et le navigateur
    # ne montre qu'un « Failed to fetch », sans statut ni message.
    logger.error("Contrainte d'intégrité violée sur %s : %s",
                 request.url.path, str(exc.orig)[:300])
    return JSONResponse(
        status_code=409,
        content={"detail": ("Opération refusée par la base : des données y font "
                            "encore référence.")},
    )


def installer_gestion_erreurs(app: FastAPI) -> None:
    """À appeler sur toute application qui monte des routeurs de l'API — y compris une application de…"""
    app.add_exception_handler(ErreurMetier, _erreur_metier)
    app.add_exception_handler(OperationalError, _base_indisponible)
    app.add_exception_handler(IntegrityError, _contrainte_violee)
