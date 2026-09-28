"""
api/main.py
===========
Assemblage de l'application : configuration, CORS, gestion des erreurs,
routeurs, cycle de vie. Aucune route n'est définie ici — voir `api/routers/`,
et docs/ARCHITECTURE_API.md pour l'organisation en couches.

Lancement :
    python api/main.py                          (port 9000, rechargement automatique)
    API_RELOAD=0 python api/main.py             (démarrage unique, pour une démo)
    python -m uvicorn api.main:app --port 9000
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# `python api/main.py` place `api/` en tête du chemin d'import : on y ajoute la
# racine du projet pour que `api.*`, `ml_engine.*` et `agents.*` se résolvent.
_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.append(str(_RACINE))

from api.core.demarrage import journal, verifier_modeles  # noqa: E402

journal("démarrage… chargement des librairies (30-60 s au premier lancement)")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.core import config, moteurs  # noqa: E402,F401  (charge .env, puis les moteurs)
from api.core.erreurs import installer_gestion_erreurs  # noqa: E402
from api.auth.database import init_db  # noqa: E402
from api.routers import (admin, auth, briefing, churn, commercial,  # noqa: E402
                         copilote, modeles, portail, sante, stock,
                         tableau_de_bord, taches, tresorerie)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application (remplace `@app.on_event`, déprécié)."""
    verifier_modeles(config.RACINE_PROJET)
    yield


app = FastAPI(title="Finance Dashboard API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.origines_cors(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
installer_gestion_erreurs(app)

# ── Routeurs, par domaine (un par fonctionnalité du frontend) ──────────────
for module in (
    sante,             # état des moteurs
    auth,              # connexion, déconnexion, profil
    tableau_de_bord,   # indicateurs et synthèse
    tresorerie,        # prévision d'encaissements, scénarios de paiement
    briefing,          # flotte multi-agents
    copilote,          # FinBot : questions et fichiers joints
    churn,             # rétention
    commercial,        # devis, marge, recommandations
    stock,             # stock, approvisionnement, demande
    modeles,           # registre des modèles
    taches,            # boucle d'action (équipe interne)
    portail,           # espace client
    admin,             # administration (directeur)
):
    app.include_router(module.router)

# Service OCR : ses dépendances (Tesseract, LayoutLMv3) sont optionnelles ;
# s'il ne se charge pas, le reste de l'API fonctionne.
try:
    from api.routers import ocr
    app.include_router(ocr.router)
except Exception as e:  # pragma: no cover
    print(f"[ocr] router non chargé : {e}")

journal("connexion à la base d'authentification…")
try:
    init_db()
    journal("base d'authentification prête ✓")
except Exception as e:  # pragma: no cover
    print(f"[auth] ATTENTION : base d'auth inaccessible ({e}) — "
          "le login échouera. PostgreSQL est-il démarré ? (ou retirez "
          "AUTH_DATABASE_URL du .env pour utiliser SQLite)", flush=True)


if __name__ == "__main__":
    print(f"[api] écoute sur http://{config.hote()}:{config.port()}")
    uvicorn.run("api.main:app", host=config.hote(), port=config.port(),
                reload=config.rechargement(), app_dir=str(_RACINE))
