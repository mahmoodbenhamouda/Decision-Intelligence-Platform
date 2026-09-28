"""
tests/test_architecture_api.py
==============================
Les règles de l'architecture en couches de l'API (docs/ARCHITECTURE_API.md),
vérifiées sur le code plutôt que seulement décrites :

1. une route ne calcule rien et n'interroge aucune base ;
2. un service ne connaît pas FastAPI ;
3. l'API n'importe aucun module de modèle ni aucun nom privé du moteur :
   elle passe par la passerelle, qui applique les décisions du registre ;
4. toute erreur métier a un code HTTP ;
5. l'application expose les routes attendues, chacune une seule fois.
"""

from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Si ce module importe l'application le premier, la base d'authentification
# est temporaire : la vraie (output/auth.db) n'est jamais ouverte.
os.environ.setdefault("AUTH_DATABASE_URL",
                      f"sqlite:///{Path(tempfile.mkdtemp()).as_posix()}/auth.db")
os.environ.setdefault("JWT_SECRET_KEY", "secret-de-test-uniquement")

API = Path(__file__).resolve().parents[1] / "api"


def _fichiers(dossier: str):
    return sorted((API / dossier).glob("*.py"))


def _imports(chemin: Path):
    """Modules importés par un fichier (import x / from x import y)."""
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for a in noeud.names:
                yield a.name, [a.name]
        elif isinstance(noeud, ast.ImportFrom) and noeud.module:
            yield noeud.module, [a.name for a in noeud.names]


# ── 1. Routes ───────────────────────────────────────────────────────────────
_INTERDITS_ROUTES = ("ml_engine", "duckdb", "pandas", "agents", "connectors", "sqlalchemy")


@pytest.mark.parametrize("fichier", _fichiers("routers"), ids=lambda p: p.name)
def test_une_route_ne_calcule_rien(fichier):
    fautifs = [m for m, noms in _imports(fichier)
               if m.split(".")[0] in _INTERDITS_ROUTES
               # la session de base est un paramètre transmis au service
               and not (m == "sqlalchemy.orm" and noms == ["Session"])]
    assert not fautifs, f"{fichier.name} accède directement à : {fautifs}"


# ── 2. Services ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fichier", _fichiers("services") + _fichiers("donnees"),
                         ids=lambda p: p.name)
def test_un_service_ne_connait_pas_fastapi(fichier):
    fautifs = [m for m, _ in _imports(fichier)
               if m.split(".")[0] in ("fastapi", "starlette") or m.startswith("api.routers")]
    assert not fautifs, f"{fichier.name} dépend de la couche HTTP : {fautifs}"


# ── 3. Chemin unique vers les modèles ───────────────────────────────────────
# Même liste que pour les agents (tests/test_passerelle_agents.py), plus la
# prévision d'encaissements et le registre, consultés par la passerelle.
_MODULES_DE_MODELE = re.compile(
    r"^ml_engine\.(models|analytics\.(churn_model|conversion_devis|marge_client|"
    r"credit_risk_model|segmentation)|stock\.(reappro_model|fin_de_vie)|deep|"
    r"forecasting\.lstm_cashflow|registre)\b")


def test_l_api_passe_par_la_passerelle():
    fautifs = []
    for chemin in sorted(API.rglob("*.py")):
        for module, noms in _imports(chemin):
            if _MODULES_DE_MODELE.match(module):
                fautifs.append(f"{chemin.relative_to(API)} : {module}")
            if module.startswith("ml_engine") and any(n.startswith("_") for n in noms):
                fautifs.append(f"{chemin.relative_to(API)} : nom privé {noms} de {module}")
    assert not fautifs, "l'API contourne la passerelle :\n" + "\n".join(fautifs)


# ── 4. Erreurs métier ───────────────────────────────────────────────────────
def test_toute_erreur_metier_a_un_code_http():
    from api.core.erreurs import CODES_HTTP
    from api.services import erreurs
    classes = [c for c in vars(erreurs).values()
               if isinstance(c, type) and issubclass(c, erreurs.ErreurMetier)
               and c is not erreurs.ErreurMetier]
    assert classes and all(c in CODES_HTTP for c in classes)


def test_une_erreur_metier_garde_la_forme_de_fastapi():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.core.erreurs import installer_gestion_erreurs
    from api.services.erreurs import Conflit, Introuvable

    app = FastAPI()
    installer_gestion_erreurs(app)

    @app.get("/texte")
    def texte():
        raise Introuvable("Tâche introuvable.")

    @app.get("/objet")
    def objet():
        raise Conflit({"statut_client": "doublon"})

    c = TestClient(app)
    r = c.get("/texte")
    assert r.status_code == 404 and r.json() == {"detail": "Tâche introuvable."}
    r = c.get("/objet")
    assert r.status_code == 409 and r.json() == {"detail": {"statut_client": "doublon"}}


# ── 5. Table des routes ─────────────────────────────────────────────────────
def test_chaque_route_est_declaree_une_seule_fois():
    from api.main import app
    ops = [(m, p) for p, d in app.openapi()["paths"].items() for m in d]
    assert len(ops) == len(set(ops))
    chemins = {p for _, p in ops}
    for attendu in ("/api/health", "/api/auth/login", "/api/dashboard", "/api/copilot",
                    "/api/copilot/upload", "/api/fleet/briefing", "/api/churn",
                    "/api/commercial/devis", "/api/stock", "/api/models/metrics",
                    "/api/taches", "/api/portal/actions", "/api/admin/users"):
        assert attendu in chemins, attendu


# ── 6. Règle de périmètre (service pur, sans HTTP) ──────────────────────────
def test_regle_de_perimetre_par_role():
    from types import SimpleNamespace

    from api.schemas.filtres import FilterRequest
    from api.services.erreurs import AccesRefuse
    from api.services.perimetre import code_client_impose, restreindre

    directeur = SimpleNamespace(role="directeur", client_code=None)
    client = SimpleNamespace(role="client", client_code="CLI_A")
    assert code_client_impose(directeur) is None
    assert code_client_impose(client) == "CLI_A"
    assert restreindre(FilterRequest(selected_clients=["CLI_B"]), client).selected_clients == ["CLI_A"]
    assert restreindre(FilterRequest(selected_clients=["CLI_B"]), directeur).selected_clients == ["CLI_B"]
    # Un employé n'a aucun périmètre de données, même si un code lui a été
    # attribué par erreur ; un client sans code n'en a pas non plus.
    for refuse in (SimpleNamespace(role="employe", client_code=None),
                   SimpleNamespace(role="employe", client_code="CLI_A"),
                   SimpleNamespace(role="client", client_code=None)):
        with pytest.raises(AccesRefuse):
            code_client_impose(refuse)
