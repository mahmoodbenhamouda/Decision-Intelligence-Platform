"""Tests du CRUD administrateur : les comptes de l'équipe (directeur, employés)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from tests import base_postgres  # noqa: E402
_DB_URL = base_postgres.preparer(__name__)

from api.auth.database import reset_for_tests, get_db  # noqa: E402
from api.auth.models import User  # noqa: E402
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)

DIRECTEUR = ("dir@test.tn", "Directeur#Test1")
EMPLOYE_A = ("a@test.tn", "EmployeAAA#1")
EMPLOYE_B = ("b@test.tn", "EmployeBBB#1")


@pytest.fixture(scope="module", autouse=True)
def seed_users():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur", full_name="Direction Test"),
        User(email=EMPLOYE_A[0], password_hash=hash_password(EMPLOYE_A[1]),
             role="employe", full_name="Sami A", poste="recouvrement"),
        User(email=EMPLOYE_B[0], password_hash=hash_password(EMPLOYE_B[1]),
             role="employe", full_name="Nadia B", poste="commercial"),
    ])
    db.commit()
    db.close()
    yield


def hdr(email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_login_renvoie_le_nom():
    r = client.post("/api/auth/login",
                    json={"email": EMPLOYE_A[0], "password": EMPLOYE_A[1]})
    assert r.json()["full_name"] == "Sami A"


def test_admin_interdit_aux_employes():
    h = hdr(*EMPLOYE_A)
    assert client.get("/api/admin/users", headers=h).status_code == 403
    assert client.get("/api/admin/audit", headers=h).status_code == 403


def test_les_routes_du_portail_client_n_existent_plus():
    """Le rôle client a été retiré : son portail aussi."""
    h = hdr(*DIRECTEUR)
    assert client.get("/api/portal/invoices", headers=h).status_code == 404
    assert client.get("/api/admin/requests", headers=h).status_code == 404


def test_crud_complet_dun_compte_employe():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "nouveau@test.tn", "password": "Nouveau#2026x",
        "full_name": "Karim Nouveau", "role": "employe", "poste": "logistique"})
    assert r.status_code == 201, r.text
    assert r.json()["poste"] == "logistique"
    uid = r.json()["id"]
    users = client.get("/api/admin/users", headers=h).json()
    assert any(u["email"] == "nouveau@test.tn" for u in users)
    r = client.patch(f"/api/admin/users/{uid}", headers=h,
                     json={"full_name": "Karim Renommé", "phone": "+216 20 000 000"})
    assert r.status_code == 200 and r.json()["full_name"] == "Karim Renommé"
    r = client.delete(f"/api/admin/users/{uid}", headers=h)
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = client.post("/api/auth/login",
                    json={"email": "nouveau@test.tn", "password": "Nouveau#2026x"})
    assert r.status_code == 401


def test_creation_compte_regles():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "faible@test.tn", "password": "abc", "role": "employe"})
    assert r.status_code == 422
    r = client.post("/api/admin/users", headers=h, json={
        "email": EMPLOYE_A[0], "password": "Costaud#2026x", "role": "employe"})
    assert r.status_code == 409


def test_le_role_client_ne_peut_plus_etre_cree():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "clinique@overlyne.tn", "password": "Clinique#2026x", "role": "client"})
    assert r.status_code == 422
    assert "directeur" in r.json()["detail"] and "employe" in r.json()["detail"]


def test_admin_renomme_l_identifiant_de_connexion():
    """L'identifiant peut changer, le mot de passe est conservé."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "ancien-nom@overlyne.tn", "password": "Renommage#2026x",
        "full_name": "Ancien Nom", "role": "employe"})
    assert r.status_code == 201
    uid = r.json()["id"]

    r = client.patch(f"/api/admin/users/{uid}", headers=h, json={
        "email": "nouveau-nom@overlyne.tn", "full_name": "Nouveau Nom"})
    assert r.status_code == 200
    assert r.json()["email"] == "nouveau-nom@overlyne.tn"

    ok = client.post("/api/auth/login", json={
        "email": "nouveau-nom@overlyne.tn", "password": "Renommage#2026x"})
    assert ok.status_code == 200 and ok.json()["full_name"] == "Nouveau Nom"
    ko = client.post("/api/auth/login", json={
        "email": "ancien-nom@overlyne.tn", "password": "Renommage#2026x"})
    assert ko.status_code == 401


def test_renommage_vers_un_identifiant_deja_pris_refuse():
    h = hdr(*DIRECTEUR)
    users = client.get("/api/admin/users", headers=h).json()
    uid = next(u["id"] for u in users if u["email"] == EMPLOYE_A[0])
    r = client.patch(f"/api/admin/users/{uid}", headers=h,
                     json={"email": EMPLOYE_B[0]})
    assert r.status_code == 409


def test_directeur_ne_peut_pas_se_desactiver():
    h = hdr(*DIRECTEUR)
    users = client.get("/api/admin/users", headers=h).json()
    me = next(u for u in users if u["email"] == DIRECTEUR[0])
    assert client.delete(f"/api/admin/users/{me['id']}", headers=h).status_code == 422
    assert client.delete(f"/api/admin/users/{me['id']}?permanent=true",
                         headers=h).status_code == 422


def test_suppression_definitive_retire_le_compte_de_la_base():
    """hard delete : la ligne disparaît réellement de `users`."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "a-supprimer@overlyne.tn", "password": "ASupprimer#26x",
        "full_name": "À Supprimer", "role": "employe"})
    assert r.status_code == 201
    uid = r.json()["id"]

    r = client.delete(f"/api/admin/users/{uid}?permanent=true", headers=h)
    assert r.status_code == 200 and r.json()["deleted"] is True

    users = client.get("/api/admin/users", headers=h).json()
    assert all(u["email"] != "a-supprimer@overlyne.tn" for u in users)
    assert client.delete(f"/api/admin/users/{uid}", headers=h).status_code == 404
    assert client.post("/api/auth/login", json={
        "email": "a-supprimer@overlyne.tn", "password": "ASupprimer#26x"}).status_code == 401

    db = next(get_db())
    try:
        assert db.get(User, uid) is None, "la ligne doit être physiquement supprimée"
    finally:
        db.close()


def test_suppression_definitive_conserve_le_journal_daudit():
    """Traçabilité : l'audit survit à la suppression (anonymisé, email gardé)."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "trace@overlyne.tn", "password": "Tracable#2026x", "role": "employe"})
    uid = r.json()["id"]
    hdr("trace@overlyne.tn", "Tracable#2026x")

    r = client.delete(f"/api/admin/users/{uid}?permanent=true", headers=h)
    assert r.status_code == 200 and r.json()["audit_anonymise"] >= 1

    from api.auth.models import AuditLog
    db = next(get_db())
    try:
        traces = db.query(AuditLog).filter(AuditLog.email == "trace@overlyne.tn").all()
        assert traces, "les entrées d'audit doivent être conservées"
        assert all(t.user_id is None for t in traces), "et anonymisées (FK coupée)"
        actions = {a.action for a in db.query(AuditLog).all()}
        assert "admin_delete_user_permanent" in actions
    finally:
        db.close()


def test_impossible_de_supprimer_le_dernier_directeur():
    """Garde-fou : la plateforme doit toujours garder un directeur actif."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "dir-temporaire@overlyne.tn", "password": "DirTemp#2026x",
        "role": "directeur"})
    assert r.status_code == 201
    tmp_id = r.json()["id"]
    h2 = hdr("dir-temporaire@overlyne.tn", "DirTemp#2026x")
    users = client.get("/api/admin/users", headers=h2).json()
    principal = next(u for u in users if u["email"] == DIRECTEUR[0])
    assert client.delete(f"/api/admin/users/{tmp_id}", headers=h).status_code == 200
    r = client.delete(f"/api/admin/users/{principal['id']}?permanent=true", headers=h2)
    assert r.status_code in (401, 422)


def test_le_seed_desactive_les_comptes_d_un_role_retire():
    """Les anciens comptes « client » restés en base sont désactivés, jamais supprimés."""
    from api.auth import seed as seed_mod
    db = next(get_db())
    db.add(User(email="ex-client@overlyne.tn", password_hash=hash_password("ExClient#2026x"),
                role="client", is_active=True))
    db.commit()
    db.close()

    seed_mod.seed(verbose=False)

    db = next(get_db())
    try:
        u = db.query(User).filter(User.email == "ex-client@overlyne.tn").one()
        assert u.is_active is False
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
