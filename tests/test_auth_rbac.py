"""
tests/test_auth_rbac.py
=======================
Tests d'authentification, de RBAC et d'ISOLATION inter-clients.

Preuves apportées :
1. Sans jeton → 401 sur tous les endpoints protégés.
2. Mauvais mot de passe → 401 ; brute-force → 429 (rate limiting).
3. Un compte `client` ne peut PAS lire les données d'un autre client :
   le périmètre est forcé côté serveur même si la requête est manipulée.
4. Ressources directeur (`/api/supply`, `/api/forecast`, refresh AO) → 403 client.
5. Journal d'audit alimenté (login, accès, refus).

Base : SQLite temporaire (schéma identique à PostgreSQL via SQLAlchemy).

Exécution :
    python -m pytest tests/test_auth_rbac.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

# Base d'auth ISOLÉE pour CE module (constante locale : ne dépend pas de
# l'ordre d'import des autres fichiers de tests qui modifient aussi l'env).
_tmpdir = tempfile.mkdtemp(prefix="authtest_")
_DB_URL = f"sqlite:///{Path(_tmpdir).as_posix()}/auth_test.db"
os.environ["AUTH_DATABASE_URL"] = _DB_URL
os.environ.setdefault("JWT_SECRET_KEY", "secret-de-test-uniquement")

from api.auth import security  # noqa: E402
from api.auth.database import reset_for_tests, get_db  # noqa: E402
from api.auth.models import AuditLog, User  # noqa: E402
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)

DIRECTEUR = ("dir@test.tn", "Directeur#Test1")
CLIENT_A = ("a@test.tn", "ClientAAAA#1", "CLI_A")
CLIENT_B = ("b@test.tn", "ClientBBBB#1", "CLI_B")


@pytest.fixture(scope="module", autouse=True)
def seed_users():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur", client_code=None),
        User(email=CLIENT_A[0], password_hash=hash_password(CLIENT_A[1]),
             role="client", client_code=CLIENT_A[2]),
        User(email=CLIENT_B[0], password_hash=hash_password(CLIENT_B[1]),
             role="client", client_code=CLIENT_B[2]),
    ])
    db.commit()
    db.close()
    yield


def login(email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def token_of(email: str, password: str) -> dict:
    r = login(email, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── 1. Authentification requise ─────────────────────────────────────────────
@pytest.mark.parametrize("method,url", [
    ("post", "/api/dashboard"), ("post", "/api/copilot"),
    ("post", "/api/ai_insight"), ("post", "/api/fleet/briefing"),
    ("post", "/api/forecast"), ("get", "/api/supply"),
    ("get", "/api/auth/me"),
    ("get", "/api/ocr/status"), ("post", "/api/ocr/extract"),
    ("post", "/api/ocr/invoice"), ("post", "/api/ocr/to-rag"),
])
def test_endpoints_proteges_sans_jeton_401(method, url):
    r = client.post(url, json={}) if method == "post" else client.get(url)
    assert r.status_code in (401, 403), f"{url} doit exiger l'authentification"


def test_jeton_falsifie_rejete():
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer faux.jeton.ici"})
    assert r.status_code == 401


def test_health_reste_public():
    assert client.get("/api/health").status_code == 200


# ── 2. Login / mot de passe / rate limiting ────────────────────────────────
def test_login_ok_et_me():
    h = token_of(*DIRECTEUR)
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "directeur" and me["client_code"] is None


def test_login_mauvais_mdp_401_reponse_neutre():
    r1 = login(DIRECTEUR[0], "mauvais")
    r2 = login("inconnu@test.tn", "mauvais")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]   # pas de fuite d'existence


def _clear_attempts():
    """Purge la table login_attempts (rate limiting PERSISTANT en base)."""
    from sqlalchemy import delete
    from api.auth.models import LoginAttempt
    db = next(get_db())
    try:
        db.execute(delete(LoginAttempt))
        db.commit()
    finally:
        db.close()
    security._attempts.clear()


@pytest.mark.vitrine
def test_rate_limiting_apres_5_echecs():
    email = "brute@test.tn"
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        login(email, "x")
    r = login(email, "x")
    assert r.status_code == 429
    _clear_attempts()   # ne pas polluer les autres tests (IP partagée)


def test_rate_limiting_est_persistant_en_base():
    """Le compteur d'échecs survit à un redémarrage : il est en BDD, pas en RAM."""
    email = "persist@test.tn"
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        login(email, "x")
    security._attempts.clear()          # simule un redémarrage du processus
    r = login(email, "x")
    assert r.status_code == 429, "le quota doit tenir même après reset mémoire"
    _clear_attempts()


# ── Révocation des jetons ───────────────────────────────────────────────────
@pytest.mark.vitrine
def test_logout_revoque_le_jeton_immediatement():
    """Après logout, le MÊME jeton ne doit plus fonctionner (denylist jti)."""
    h = token_of(*DIRECTEUR)
    assert client.get("/api/auth/me", headers=h).status_code == 200
    r = client.post("/api/auth/logout", headers=h)
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert client.get("/api/auth/me", headers=h).status_code == 401, \
        "un jeton révoqué doit être refusé même avant son expiration"


def test_changement_de_mot_de_passe_revoque_les_sessions():
    """Le reset admin d'un mot de passe invalide TOUS les jetons antérieurs."""
    hd = token_of(*DIRECTEUR)
    ha = token_of(CLIENT_A[0], CLIENT_A[1])      # session active du client A
    users = client.get("/api/admin/users", headers=hd).json()
    uid = next(u["id"] for u in users if u["email"] == CLIENT_A[0])
    r = client.patch(f"/api/admin/users/{uid}", headers=hd,
                     json={"password": "NouveauMdp#2026x"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=ha).status_code == 401, \
        "l'ancienne session doit être invalidée (token_version)"
    # remettre l'ancien mot de passe pour les tests suivants
    client.patch(f"/api/admin/users/{uid}", headers=hd,
                 json={"password": CLIENT_A[1]})


def test_login_pose_un_cookie_httponly():
    r = login(*DIRECTEUR)
    set_cookie = r.headers.get("set-cookie", "")
    assert "finbot_access=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie.replace("Lax", "lax")


# ── 3. ISOLATION : un client ne lit QUE ses données ─────────────────────────
@pytest.mark.vitrine
def test_client_scope_force_sur_dashboard():
    """Client A demande explicitement les données de B → le serveur force A."""
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    r = client.post("/api/dashboard", headers=h,
                    json={"selected_clients": [CLIENT_B[2]]})
    assert r.status_code == 200
    af = r.json().get("active_filters", {})
    assert af.get("clients") == [CLIENT_A[2]], \
        "le périmètre doit être écrasé par le client_code du compte"
    # La liste des clients proposée ne doit contenir que lui-même
    filters = r.json().get("filters") or {}
    if "available_clients" in filters:
        assert set(filters["available_clients"]) <= {CLIENT_A[2]}


def test_fichier_joint_au_copilote_reste_dans_le_perimetre(monkeypatch):
    """Les filtres envoyés AVEC un fichier sont eux aussi réécrits : un client
    ne peut pas faire lire au copilote les indicateurs d'un autre client."""
    from types import SimpleNamespace

    from api.core import moteurs
    vus = []
    monkeypatch.setattr(moteurs, "kpi_engine", SimpleNamespace(
        compute_dashboard=lambda f: vus.append(f) or {}))
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    r = client.post("/api/copilot/upload", headers=h,
                    files={"file": ("ventes.csv", b"mois,montant\n2026-01,100\n", "text/csv")},
                    data={"question": "total ?",
                          "filters": '{"selected_clients": ["%s"]}' % CLIENT_B[2]})
    assert r.status_code == 200, r.text
    assert vus and vus[0]["selected_clients"] == [CLIENT_A[2]]


def test_directeur_garde_ses_filtres():
    h = token_of(*DIRECTEUR)
    r = client.post("/api/dashboard", headers=h,
                    json={"selected_clients": [CLIENT_B[2]]})
    assert r.status_code == 200
    assert r.json()["active_filters"]["clients"] == [CLIENT_B[2]]


def test_copilot_et_briefing_scopes():
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    for url in ("/api/copilot", "/api/fleet/briefing"):
        r = client.post(url, headers=h,
                        json={"question": "état ?", "selected_clients": [CLIENT_B[2]]})
        assert r.status_code == 200, url
        assert r.json()["active_filters"]["clients"] == [CLIENT_A[2]], url


# ── 4. Ressources réservées au directeur ────────────────────────────────────
def test_supply_interdit_aux_clients():
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    assert client.get("/api/supply", headers=h).status_code == 403


def test_forecast_global_interdit_aux_clients():
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    assert client.post("/api/forecast", headers=h, json={}).status_code == 403


def test_supply_autorise_directeur():
    h = token_of(*DIRECTEUR)
    assert client.get("/api/supply", headers=h).status_code == 200


def test_route_opportunites_bien_supprimee():
    """La veille externe a été retirée du projet : la route ne doit plus exister.

    Une route supprimée du code mais laissée accessible — par un routeur monté
    ailleurs, par exemple — rendrait la suppression incomplète sans que rien ne
    le signale."""
    h = token_of(*DIRECTEUR)
    assert client.get("/api/fleet/opportunities", headers=h).status_code == 404


# ── 5. Audit ────────────────────────────────────────────────────────────────
def test_audit_log_alimente():
    token_of(*DIRECTEUR)   # provoque un login
    db = next(get_db())
    try:
        actions = {a.action for a in db.query(AuditLog).all()}
    finally:
        db.close()
    assert "login" in actions
    assert "login_failed" in actions
    assert "access" in actions or "forbidden" in actions


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ── 6. Routes des modèles ajoutées avec la passerelle ───────────────────────
def test_recommandations_forcees_sur_le_client():
    """Un client ne peut pas lire les recommandations d'un autre client."""
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    r = client.get(f"/api/commercial/recommandations?client={CLIENT_B[2]}", headers=h)
    assert r.status_code == 200
    body = r.json()
    if body.get("servi"):
        assert body.get("client") == CLIENT_A[2]
        assert "top" not in body, "un client ne doit jamais recevoir la liste globale"


def test_tableau_des_modeles_reserve_au_directeur():
    h = token_of(CLIENT_A[0], CLIENT_A[1])
    assert client.get("/api/models/metrics", headers=h).status_code == 403
    hd = token_of(*DIRECTEUR)
    r = client.get("/api/models/metrics", headers=hd)
    assert r.status_code == 200 and isinstance(r.json().get("modeles"), list)
