"""Assemblage de l'application : configuration, CORS, gestion des erreurs, routeurs, cycle de vie."""

import asyncio
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.append(str(_RACINE))

from api.core.demarrage import journal, verifier_modeles  # noqa: E402

journal("démarrage… chargement des librairies (30-60 s au premier lancement)")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.core import config, moteurs, planificateur  # noqa: E402,F401  (charge .env, puis les moteurs)
from api.core.erreurs import installer_gestion_erreurs  # noqa: E402
from api.auth.database import init_db, verifier_connexion  # noqa: E402
from api.auth.security import verifier_secret  # noqa: E402
from api.routers import (admin, auth, briefing, churn, commandes,  # noqa: E402
                         commercial, copilote, impact, modeles, sante, stock,
                         tableau_de_bord, taches, tresorerie)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application (remplace `@app.on_event`, déprécié).

    La base est contactée ICI, au démarrage du serveur, et non à l'import du
    module. Deux raisons :

      * importer `api.main` ne doit pas exiger une base en marche — sinon l'outillage
        (tests d'architecture, génération d'OpenAPI, inspection des routes) devient
        impossible sans PostgreSQL ;
      * une exception levée ici empêche réellement le serveur de servir, alors
        qu'un simple avertissement laissait l'application annoncer
        « startup complete » puis renvoyer 500 au premier login.

    Le secret de signature est validé selon la même règle : une configuration
    d'authentification incomplète doit arrêter le démarrage, pas se découvrir à
    la première requête.
    """
    journal("connexion à PostgreSQL…")
    init_db()
    verifier_connexion()
    verifier_secret()
    journal("base d'authentification prête ✓")

    verifier_modeles(config.RACINE_PROJET)
    tache_fond = None
    if planificateur.actif():
        tache_fond = asyncio.create_task(planificateur.boucle())
    yield
    if tache_fond is not None:
        tache_fond.cancel()
        with suppress(asyncio.CancelledError):
            await tache_fond


app = FastAPI(title="Finance Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.origines_cors(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
installer_gestion_erreurs(app)

for module in (
    sante,
    auth,
    tableau_de_bord,
    tresorerie,
    briefing,
    copilote,
    churn,
    commercial,
    impact,
    stock,
    commandes,
    modeles,
    taches,
    admin,
):
    app.include_router(module.router)

try:
    from api.routers import ocr
    app.include_router(ocr.router)
except Exception as e:  # pragma: no cover
    print(f"[ocr] router non chargé : {e}")



if __name__ == "__main__":
    print(f"[api] écoute sur http://{config.hote()}:{config.port()}")
    uvicorn.run("api.main:app", host=config.hote(), port=config.port(),
                reload=config.rechargement(), app_dir=str(_RACINE))
