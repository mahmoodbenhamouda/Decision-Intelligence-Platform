"""Les règles de l'architecture en couches de l'API (docs/ARCHITECTURE_API.md), vérifiées sur le…"""

from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault(
    "AUTH_DATABASE_URL",
    os.environ.get("AUTH_TEST_DATABASE_URL")
    or "postgresql+psycopg2://postgres:postgres@localhost:5432/finance_auth_test")
os.environ.setdefault("JWT_SECRET_KEY",
                      "secret-de-test-uniquement-assez-long-pour-hs256")

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


_INTERDITS_ROUTES = ("ml_engine", "duckdb", "pandas", "agents", "connectors", "sqlalchemy")


@pytest.mark.parametrize("fichier", _fichiers("routers"), ids=lambda p: p.name)
def test_une_route_ne_calcule_rien(fichier):
    fautifs = [m for m, noms in _imports(fichier)
               if m.split(".")[0] in _INTERDITS_ROUTES
               and not (m == "sqlalchemy.orm" and noms == ["Session"])]
    assert not fautifs, f"{fichier.name} accède directement à : {fautifs}"


@pytest.mark.parametrize("fichier", _fichiers("services") + _fichiers("donnees"),
                         ids=lambda p: p.name)
def test_un_service_ne_connait_pas_fastapi(fichier):
    fautifs = [m for m, _ in _imports(fichier)
               if m.split(".")[0] in ("fastapi", "starlette") or m.startswith("api.routers")]
    assert not fautifs, f"{fichier.name} dépend de la couche HTTP : {fautifs}"


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


def test_chaque_route_est_declaree_une_seule_fois():
    from api.main import app
    ops = [(m, p) for p, d in app.openapi()["paths"].items() for m in d]
    assert len(ops) == len(set(ops))
    chemins = {p for _, p in ops}
    for attendu in ("/api/health", "/api/auth/login", "/api/dashboard", "/api/copilot",
                    "/api/copilot/upload", "/api/fleet/briefing", "/api/churn",
                    "/api/commercial/devis", "/api/stock", "/api/models/metrics",
                    "/api/taches", "/api/admin/users"):
        assert attendu in chemins, attendu
    for retire in ("/api/portal/actions", "/api/portal/invoices", "/api/admin/requests"):
        assert retire not in chemins, f"{retire} : le rôle client a été retiré"


def test_regle_de_portee_des_filtres_sur_les_modeles():
    """Une seule règle décide ce que les modèles montrent sous des filtres."""
    from ml_engine import portee as po

    assert po.portee({})["mode"] == po.GLOBAL
    assert po.portee({"selected_clients": ["CLI_A"]}) == {
        "mode": po.CLIENTS, "clients": ["CLI_A"], "motif": po.MOTIF_GLOBAL}
    for periode in ({"selected_years": [2024]}, {"date_start": "2024-01-01"},
                    {"date_end": "2024-12-31"}):
        assert po.portee(periode)["mode"] == po.MASQUE
        assert po.portee(periode)["motif"] == po.MOTIF_PERIODE
    for facture in ({"payment_modes": ["CHQ"]}, {"risk_level": "Critique > 90j"},
                    {"min_amount": 10}, {"max_amount": 10}):
        assert po.portee(facture)["motif"] == po.MOTIF_FACTURE
    # Une période l'emporte sur un filtre client : une prévision ne se recalcule pas pour le passé.
    assert po.portee({"selected_clients": ["CLI_A"], "selected_years": [2024]})["mode"] == po.MASQUE
    p = po.portee({"selected_clients": ["CLI_A"]})
    assert po.pour_analyse_globale(p)["masque"] is True
    assert po.pour_analyse_par_client(p) is None
