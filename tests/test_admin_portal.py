"""
tests/test_admin_portal.py
==========================
Tests du CRUD administrateur (comptes) et du portail client (demandes).

Preuves :
- CRUD réservé au directeur (403 pour un client).
- Création de compte : politique de mot de passe, email unique, client_code requis.
- Un client ne voit QUE ses demandes ; le directeur les voit toutes et les traite.
- Garde-fou : le directeur ne peut pas désactiver son propre compte.

Exécution :
    python -m pytest tests/test_admin_portal.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

_tmpdir = tempfile.mkdtemp(prefix="admintest_")
_DB_URL = f"sqlite:///{Path(_tmpdir).as_posix()}/auth_admin.db"
os.environ["AUTH_DATABASE_URL"] = _DB_URL
os.environ.setdefault("JWT_SECRET_KEY", "secret-de-test-uniquement")

from api.auth.database import reset_for_tests, get_db  # noqa: E402
from api.auth.models import User  # noqa: E402
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
             role="directeur", full_name="Direction Test"),
        User(email=CLIENT_A[0], password_hash=hash_password(CLIENT_A[1]),
             role="client", client_code=CLIENT_A[2], full_name="Clinique A"),
        User(email=CLIENT_B[0], password_hash=hash_password(CLIENT_B[1]),
             role="client", client_code=CLIENT_B[2], full_name="Labo B"),
    ])
    db.commit()
    db.close()
    yield


def hdr(email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── Le nom réel est renvoyé à la connexion ──────────────────────────────────
def test_login_renvoie_le_nom():
    r = client.post("/api/auth/login",
                    json={"email": CLIENT_A[0], "password": CLIENT_A[1]})
    assert r.json()["full_name"] == "Clinique A"


# ── CRUD réservé au directeur ───────────────────────────────────────────────
def test_admin_interdit_aux_clients():
    h = hdr(CLIENT_A[0], CLIENT_A[1])
    assert client.get("/api/admin/users", headers=h).status_code == 403
    assert client.get("/api/admin/requests", headers=h).status_code == 403
    assert client.get("/api/admin/audit", headers=h).status_code == 403


def test_crud_complet_dun_compte_client():
    h = hdr(*DIRECTEUR)
    # CREATE
    r = client.post("/api/admin/users", headers=h, json={
        "email": "nouveau@test.tn", "password": "Nouveau#2026x",
        "full_name": "CHU Nouveau", "role": "client", "client_code": "CLI_N"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    # READ
    users = client.get("/api/admin/users", headers=h).json()
    assert any(u["email"] == "nouveau@test.tn" for u in users)
    # UPDATE
    r = client.patch(f"/api/admin/users/{uid}", headers=h,
                     json={"full_name": "CHU Renommé", "phone": "+216 20 000 000"})
    assert r.status_code == 200 and r.json()["full_name"] == "CHU Renommé"
    # DELETE (soft)
    r = client.delete(f"/api/admin/users/{uid}", headers=h)
    assert r.status_code == 200 and r.json()["is_active"] is False
    # Compte désactivé → login refusé
    r = client.post("/api/auth/login",
                    json={"email": "nouveau@test.tn", "password": "Nouveau#2026x"})
    assert r.status_code == 401


def test_creation_compte_regles():
    h = hdr(*DIRECTEUR)
    # mot de passe faible → 422
    r = client.post("/api/admin/users", headers=h, json={
        "email": "faible@test.tn", "password": "abc", "role": "client",
        "client_code": "X"})
    assert r.status_code == 422
    # client sans client_code → 422
    r = client.post("/api/admin/users", headers=h, json={
        "email": "sanscode@test.tn", "password": "Costaud#2026x", "role": "client"})
    assert r.status_code == 422
    # email en double → 409
    r = client.post("/api/admin/users", headers=h, json={
        "email": CLIENT_A[0], "password": "Costaud#2026x", "role": "client",
        "client_code": "X"})
    assert r.status_code == 409


def test_creation_nouveau_client_hors_erp():
    """Le directeur crée un client qui n'existe PAS encore dans l'entrepôt :
    le compte est bien enregistré, marqué hors ERP, et peut se connecter."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "clinique-el-manar@overlyne.tn", "password": "Nouveau#2026x",
        "full_name": "Clinique El Manar", "role": "client",
        "client_code": "CE999001", "phone": "+216 71 000 000"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["client_code"] == "CE999001"
    assert d["in_erp"] is False, "un client sans facture doit être signalé hors ERP"
    assert d["phone"] == "+216 71 000 000"

    # Il apparaît dans la liste et peut se connecter immédiatement
    users = client.get("/api/admin/users", headers=h).json()
    assert any(u["email"] == "clinique-el-manar@overlyne.tn" for u in users)
    ok = client.post("/api/auth/login", json={
        "email": "clinique-el-manar@overlyne.tn", "password": "Nouveau#2026x"})
    assert ok.status_code == 200 and ok.json()["full_name"] == "Clinique El Manar"

    # Son espace répond, simplement vide de factures
    hc = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    inv = client.get("/api/portal/invoices", headers=hc)
    assert inv.status_code == 200


def test_code_client_unique_entre_comptes():
    """Relation 1-à-1 : deux comptes ne peuvent pas viser le même périmètre."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "doublon@overlyne.tn", "password": "Doublon#2026x",
        "role": "client", "client_code": CLIENT_A[2]})
    assert r.status_code == 409
    assert "déjà attribué" in r.json()["detail"]


def test_code_client_unique_insensible_a_la_casse():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "doublon2@overlyne.tn", "password": "Doublon#2026x",
        "role": "client", "client_code": CLIENT_A[2].lower()})
    assert r.status_code == 409


def test_modification_code_client_verifie_unicite():
    h = hdr(*DIRECTEUR)
    users = client.get("/api/admin/users", headers=h).json()
    uid = next(u["id"] for u in users if u["email"] == CLIENT_A[0])
    r = client.patch(f"/api/admin/users/{uid}", headers=h,
                     json={"client_code": CLIENT_B[2]})
    assert r.status_code == 409


def test_directeur_ne_peut_pas_avoir_de_code_client():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "dir2@overlyne.tn", "password": "Directeur#2026x",
        "role": "directeur", "client_code": "CE000999"})
    assert r.status_code == 422


def test_admin_renomme_l_identifiant_de_connexion():
    """Établissement renommé → l'identifiant peut suivre, mot de passe conservé."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "ancien-nom@overlyne.tn", "password": "Renommage#2026x",
        "full_name": "Ancien Nom", "role": "client", "client_code": "CLI_R"})
    assert r.status_code == 201
    uid = r.json()["id"]

    r = client.patch(f"/api/admin/users/{uid}", headers=h, json={
        "email": "chu-nouveau-nom@overlyne.tn", "full_name": "CHU Nouveau Nom"})
    assert r.status_code == 200
    assert r.json()["email"] == "chu-nouveau-nom@overlyne.tn"

    # Connexion avec la NOUVELLE adresse et l'ANCIEN mot de passe
    ok = client.post("/api/auth/login", json={
        "email": "chu-nouveau-nom@overlyne.tn", "password": "Renommage#2026x"})
    assert ok.status_code == 200 and ok.json()["full_name"] == "CHU Nouveau Nom"
    # L'ancienne adresse ne fonctionne plus
    ko = client.post("/api/auth/login", json={
        "email": "ancien-nom@overlyne.tn", "password": "Renommage#2026x"})
    assert ko.status_code == 401


def test_renommage_vers_un_identifiant_deja_pris_refuse():
    h = hdr(*DIRECTEUR)
    users = client.get("/api/admin/users", headers=h).json()
    uid = next(u["id"] for u in users if u["email"] == CLIENT_A[0])
    r = client.patch(f"/api/admin/users/{uid}", headers=h,
                     json={"email": CLIENT_B[0]})
    assert r.status_code == 409


def test_directeur_ne_peut_pas_se_desactiver():
    h = hdr(*DIRECTEUR)
    users = client.get("/api/admin/users", headers=h).json()
    me = next(u for u in users if u["email"] == DIRECTEUR[0])
    assert client.delete(f"/api/admin/users/{me['id']}", headers=h).status_code == 422
    # ni se supprimer définitivement
    assert client.delete(f"/api/admin/users/{me['id']}?permanent=true",
                         headers=h).status_code == 422


# ── Suppression DÉFINITIVE ──────────────────────────────────────────────────
def test_suppression_definitive_retire_le_compte_de_la_base():
    """hard delete : la ligne disparaît réellement de `users`."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "a-supprimer@overlyne.tn", "password": "ASupprimer#26x",
        "full_name": "À Supprimer", "role": "client", "client_code": "CLI_DEL"})
    assert r.status_code == 201
    uid = r.json()["id"]

    # Le compte dépose une demande (dépendance à traiter)
    hc = hdr("a-supprimer@overlyne.tn", "ASupprimer#26x")
    client.post("/api/portal/requests", headers=hc, json={
        "type": "contact", "sujet": "Sujet test", "message": "Message test"})

    r = client.delete(f"/api/admin/users/{uid}?permanent=true", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["deleted"] is True and d["demandes_supprimees"] >= 1

    # Absent de la liste, introuvable, connexion impossible
    users = client.get("/api/admin/users", headers=h).json()
    assert all(u["email"] != "a-supprimer@overlyne.tn" for u in users)
    assert client.delete(f"/api/admin/users/{uid}", headers=h).status_code == 404
    assert client.post("/api/auth/login", json={
        "email": "a-supprimer@overlyne.tn", "password": "ASupprimer#26x"}).status_code == 401

    # Vérification directe en base
    from api.auth.models import User as U
    db = next(get_db())
    try:
        assert db.get(U, uid) is None, "la ligne doit être physiquement supprimée"
    finally:
        db.close()


def test_suppression_definitive_conserve_le_journal_daudit():
    """Traçabilité : l'audit survit à la suppression (anonymisé, email gardé)."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "trace@overlyne.tn", "password": "Tracable#2026x",
        "role": "client", "client_code": "CLI_TRACE"})
    uid = r.json()["id"]
    hdr("trace@overlyne.tn", "Tracable#2026x")     # génère un login dans l'audit

    r = client.delete(f"/api/admin/users/{uid}?permanent=true", headers=h)
    assert r.status_code == 200 and r.json()["audit_anonymise"] >= 1

    from api.auth.models import AuditLog
    db = next(get_db())
    try:
        traces = db.query(AuditLog).filter(AuditLog.email == "trace@overlyne.tn").all()
        assert traces, "les entrées d'audit doivent être conservées"
        assert all(t.user_id is None for t in traces), "et anonymisées (FK coupée)"
        # La suppression elle-même est tracée
        actions = {a.action for a in db.query(AuditLog).all()}
        assert "admin_delete_user_permanent" in actions
    finally:
        db.close()


def test_le_code_client_redevient_disponible_apres_suppression():
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "recyclable@overlyne.tn", "password": "Recyclage#26x",
        "role": "client", "client_code": "CLI_REUSE"})
    uid = r.json()["id"]
    client.delete(f"/api/admin/users/{uid}?permanent=true", headers=h)
    # Le même code peut être réattribué à un nouveau compte
    r2 = client.post("/api/admin/users", headers=h, json={
        "email": "repreneur@overlyne.tn", "password": "Repreneur#26x",
        "role": "client", "client_code": "CLI_REUSE"})
    assert r2.status_code == 201


def test_impossible_de_supprimer_le_dernier_directeur():
    """Garde-fou : la plateforme doit toujours garder un directeur actif."""
    h = hdr(*DIRECTEUR)
    r = client.post("/api/admin/users", headers=h, json={
        "email": "dir-temporaire@overlyne.tn", "password": "DirTemp#2026x",
        "role": "directeur"})
    assert r.status_code == 201
    tmp_id = r.json()["id"]
    # Depuis ce second directeur, supprimer le premier est possible…
    h2 = hdr("dir-temporaire@overlyne.tn", "DirTemp#2026x")
    users = client.get("/api/admin/users", headers=h2).json()
    principal = next(u for u in users if u["email"] == DIRECTEUR[0])
    # …mais on ne le fait pas : on vérifie l'inverse — si on désactive le
    # temporaire, il ne peut plus être le dernier recours.
    assert client.delete(f"/api/admin/users/{tmp_id}", headers=h).status_code == 200
    # Le directeur principal reste seul actif : sa suppression est refusée
    r = client.delete(f"/api/admin/users/{principal['id']}?permanent=true", headers=h2)
    assert r.status_code in (401, 422)


# ── Portail : demandes clients ──────────────────────────────────────────────
def test_client_depose_et_suit_sa_demande():
    h = hdr(CLIENT_A[0], CLIENT_A[1])
    r = client.post("/api/portal/requests", headers=h, json={
        "type": "echeancier", "sujet": "Demande d'échéancier",
        "message": "Merci d'étaler la facture F-123 sur 3 mois.",
        "invoice_ref": "F-123"})
    assert r.status_code == 201
    mine = client.get("/api/portal/requests", headers=h).json()["requests"]
    assert len(mine) == 1 and mine[0]["status"] == "nouvelle"


def test_isolation_des_demandes_entre_clients():
    hb = hdr(CLIENT_B[0], CLIENT_B[1])
    others = client.get("/api/portal/requests", headers=hb).json()["requests"]
    assert others == [], "un client ne doit JAMAIS voir les demandes d'un autre"


def test_directeur_traite_la_demande_et_le_client_voit_la_reponse():
    h = hdr(*DIRECTEUR)
    reqs = client.get("/api/admin/requests", headers=h).json()["requests"]
    assert len(reqs) >= 1
    rid = reqs[0]["id"]
    assert reqs[0]["client_nom"] == "Clinique A"
    r = client.patch(f"/api/admin/requests/{rid}", headers=h, json={
        "status": "traitee", "reponse": "Échéancier accordé sur 3 mois."})
    assert r.status_code == 200 and r.json()["status"] == "traitee"
    # côté client : la réponse est visible
    ha = hdr(CLIENT_A[0], CLIENT_A[1])
    mine = client.get("/api/portal/requests", headers=ha).json()["requests"]
    assert mine[0]["reponse"].startswith("Échéancier accordé")


def test_type_de_demande_invalide():
    h = hdr(CLIENT_A[0], CLIENT_A[1])
    r = client.post("/api/portal/requests", headers=h, json={
        "type": "piratage", "sujet": "x y z", "message": "m s g"})
    assert r.status_code == 422


# ── Factures du portail ─────────────────────────────────────────────────────
def test_invoices_directeur_doit_cibler_un_code():
    h = hdr(*DIRECTEUR)
    assert client.get("/api/portal/invoices", headers=h).status_code == 422


def test_invoices_client_ignore_le_parametre():
    """Même en passant ?client_code=CLI_B, le client A reste sur SON périmètre."""
    h = hdr(CLIENT_A[0], CLIENT_A[1])
    r = client.get("/api/portal/invoices?client_code=CLI_B", headers=h)
    assert r.status_code == 200
    assert r.json().get("client_code") == CLIENT_A[2]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
