"""Tests d'authentification et de RBAC (deux rôles : directeur, employé)."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from tests import base_postgres  # noqa: E402
_DB_URL = base_postgres.preparer(__name__)

from api.auth import security  # noqa: E402
from api.auth.database import reset_for_tests, get_db  # noqa: E402
from api.auth.models import AuditLog, User  # noqa: E402
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)

DIRECTEUR = ("dir@test.tn", "Directeur#Test1")
EMPLOYE = ("emp@test.tn", "EmployeTest#1")
# Compte d'un rôle retiré (« client ») resté en base : il ne doit plus ouvrir de session.
ANCIEN_CLIENT = ("ancien.client@test.tn", "ClientAAAA#1")


@pytest.fixture(scope="module", autouse=True)
def seed_users():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur"),
        User(email=EMPLOYE[0], password_hash=hash_password(EMPLOYE[1]),
             role="employe", poste="recouvrement"),
        User(email=ANCIEN_CLIENT[0], password_hash=hash_password(ANCIEN_CLIENT[1]),
             role="client"),
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


@pytest.mark.parametrize("method,url", [
    ("post", "/api/dashboard"), ("post", "/api/copilot"),
    ("post", "/api/ai_insight"), ("post", "/api/fleet/briefing"),
    ("post", "/api/forecast"), ("get", "/api/supply"),
    ("get", "/api/impact"),
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


def test_login_ok_et_me():
    h = token_of(*DIRECTEUR)
    me = client.get("/api/auth/me", headers=h).json()
    assert me["role"] == "directeur" and "client_code" not in me


def test_login_mauvais_mdp_401_reponse_neutre():
    r1 = login(DIRECTEUR[0], "mauvais")
    r2 = login("inconnu@test.tn", "mauvais")
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


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
    _clear_attempts()


def test_rate_limiting_est_persistant_en_base():
    """Le compteur d'échecs survit à un redémarrage : il est en BDD, pas en RAM."""
    email = "persist@test.tn"
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        login(email, "x")
    security._attempts.clear()
    r = login(email, "x")
    assert r.status_code == 429, "le quota doit tenir même après reset mémoire"
    _clear_attempts()


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
    ha = token_of(*EMPLOYE)
    users = client.get("/api/admin/users", headers=hd).json()
    uid = next(u["id"] for u in users if u["email"] == EMPLOYE[0])
    r = client.patch(f"/api/admin/users/{uid}", headers=hd,
                     json={"password": "NouveauMdp#2026x"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=ha).status_code == 401, \
        "l'ancienne session doit être invalidée (token_version)"
    client.patch(f"/api/admin/users/{uid}", headers=hd,
                 json={"password": EMPLOYE[1]})


def test_login_pose_un_cookie_httponly():
    r = login(*DIRECTEUR)
    set_cookie = r.headers.get("set-cookie", "")
    assert "finbot_access=" in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie.replace("Lax", "lax")


@pytest.mark.vitrine
def test_un_compte_d_un_role_retire_ne_se_connecte_plus():
    """Le rôle « client » a été retiré : un ancien compte resté en base est refusé,
    avec la même réponse neutre qu'un mauvais mot de passe."""
    r = login(*ANCIEN_CLIENT)
    assert r.status_code == 401
    assert r.json()["detail"] == login(DIRECTEUR[0], "mauvais").json()["detail"]
    _clear_attempts()


@pytest.mark.vitrine
@pytest.mark.parametrize("method,url", [
    ("post", "/api/dashboard"), ("post", "/api/copilot"), ("post", "/api/ai_insight"),
    ("post", "/api/fleet/briefing"), ("post", "/api/forecast"),
    ("post", "/api/payment-scenarios"), ("get", "/api/supply"), ("get", "/api/churn"),
    ("get", "/api/commercial/devis"), ("get", "/api/commercial/recommandations"),
    ("get", "/api/stock"), ("get", "/api/ocr/status"), ("get", "/api/models/metrics"),
    ("get", "/api/admin/users"), ("get", "/api/impact"),
])
def test_un_employe_n_accede_qu_a_ses_taches(method, url):
    """L'employé exécute ce qu'on lui confie : les analyses restent au directeur."""
    h = token_of(*EMPLOYE)
    r = client.post(url, headers=h, json={}) if method == "post" else client.get(url, headers=h)
    assert r.status_code == 403, f"{url} doit être refusé à un employé"


def test_directeur_garde_ses_filtres():
    h = token_of(*DIRECTEUR)
    r = client.post("/api/dashboard", headers=h,
                    json={"selected_clients": ["CLI_B"]})
    assert r.status_code == 200
    assert r.json()["active_filters"]["clients"] == ["CLI_B"]


def test_supply_autorise_directeur():
    h = token_of(*DIRECTEUR)
    assert client.get("/api/supply", headers=h).status_code == 200


def test_route_opportunites_bien_supprimee():
    """La veille externe a été retirée du projet : la route ne doit plus exister."""
    h = token_of(*DIRECTEUR)
    assert client.get("/api/fleet/opportunities", headers=h).status_code == 404


def test_audit_log_alimente():
    token_of(*DIRECTEUR)
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


def test_tableau_des_modeles_reserve_au_directeur():
    hd = token_of(*DIRECTEUR)
    r = client.get("/api/models/metrics", headers=hd)
    assert r.status_code == 200 and isinstance(r.json().get("modeles"), list)


# ---------------------------------------------------------------------------
# Rôle retiré : il ne suffit pas qu'un ancien compte ne puisse plus se
# connecter. Tant qu'il reste en base, il s'affiche, il se compte, et il
# laisse croire que la plateforme sert encore un portail client. Ces quatre
# tests couvrent le cycle complet : invisible, dénombré, effacé, et surtout
# une purge qui n'emporte AUCUN compte de rôle en vigueur.
# ---------------------------------------------------------------------------

@pytest.mark.vitrine
def test_un_compte_d_un_role_retire_n_est_pas_liste():
    """La liste des comptes ne montre que les rôles en vigueur."""
    hd = token_of(*DIRECTEUR)
    emails = {u["email"] for u in client.get("/api/admin/users", headers=hd).json()}
    assert ANCIEN_CLIENT[0] not in emails, \
        "un compte de rôle retiré ne doit plus apparaître dans la liste"
    assert {DIRECTEUR[0], EMPLOYE[0]} <= emails


def test_un_role_retire_reste_inspectable_explicitement():
    """Masqué par défaut n'est pas caché : le directeur peut le demander."""
    hd = token_of(*DIRECTEUR)
    r = client.get("/api/admin/users?inclure_retires=true", headers=hd)
    assert r.status_code == 200
    assert ANCIEN_CLIENT[0] in {u["email"] for u in r.json()}


def test_les_roles_retires_sont_denombres():
    hd = token_of(*DIRECTEUR)
    r = client.get("/api/admin/roles-retires", headers=hd)
    assert r.status_code == 200 and r.json()["n"] >= 1


@pytest.mark.vitrine
def test_la_purge_efface_les_roles_retires_sans_toucher_a_l_equipe():
    """La purge est ciblée : elle efface le rôle retiré et RIEN d'autre.

    Le journal d'audit n'est pas amputé — ses entrées sont anonymisées, jamais
    supprimées : effacer un compte ne doit pas effacer la preuve de ce qu'il a fait.
    """
    hd = token_of(*DIRECTEUR)

    db = next(get_db())
    try:
        audit_avant = db.query(AuditLog).count()
    finally:
        db.close()

    r = client.post("/api/admin/purger-roles-retires", headers=hd)
    assert r.status_code == 200, r.text
    assert r.json()["n_supprimes"] >= 1
    assert ANCIEN_CLIENT[0] in r.json()["emails"]

    # Plus aucun rôle retiré en base, y compris en demandant à les voir.
    assert client.get("/api/admin/roles-retires", headers=hd).json()["n"] == 0
    restants = client.get("/api/admin/users?inclure_retires=true", headers=hd).json()
    assert ANCIEN_CLIENT[0] not in {u["email"] for u in restants}

    # L'équipe est intacte, et le journal n'a rien perdu.
    assert {DIRECTEUR[0], EMPLOYE[0]} <= {u["email"] for u in restants}
    db = next(get_db())
    try:
        assert db.query(AuditLog).count() >= audit_avant, \
            "le journal d'audit ne doit jamais perdre d'entrée lors d'une purge"
        # Le compte est reposé pour que l'ordre des tests reste sans effet.
        db.add(User(email=ANCIEN_CLIENT[0],
                    password_hash=hash_password(ANCIEN_CLIENT[1]), role="client"))
        db.commit()
    finally:
        db.close()


def test_la_purge_est_reservee_au_directeur():
    """Un employé ne purge pas la base, et un anonyme non plus.

    Les cookies sont vidés avant l'appel anonyme : le client de test conserve le
    cookie httpOnly posé par les connexions précédentes, et sans cette purge
    l'appel « sans jeton » serait en réalité authentifié — le test passerait pour
    la mauvaise raison.
    """
    h = token_of(*EMPLOYE)
    assert client.post("/api/admin/purger-roles-retires", headers=h).status_code == 403
    client.cookies.clear()
    assert client.post("/api/admin/purger-roles-retires").status_code == 401
