"""La BOUCLE D'ACTION de bout en bout : alerte → tâche confiée → résultat → mesure → retour vers…"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from tests import base_postgres  # noqa: E402
_DB_URL = base_postgres.preparer(__name__)

from api.auth.database import get_db, reset_for_tests  # noqa: E402
from api.auth.models import Tache, User  # noqa: E402
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)

DIRECTEUR = ("dir.boucle@test.tn", "Directeur#Test1")
EMPLOYE_A = ("sami@test.tn", "Employe#Test1")
EMPLOYE_B = ("nadia@test.tn", "Employe#Test2")
CLIENT_CODE = "CLI_H"


@pytest.fixture(scope="module", autouse=True)
def comptes():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur", full_name="Direction"),
        User(email=EMPLOYE_A[0], password_hash=hash_password(EMPLOYE_A[1]),
             role="employe", full_name="Sami", poste="recouvrement"),
        User(email=EMPLOYE_B[0], password_hash=hash_password(EMPLOYE_B[1]),
             role="employe", full_name="Nadia", poste="commercial"),
    ])
    db.commit()
    db.close()
    yield


def _entete(email: str, mot_de_passe: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": mot_de_passe})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def dir_h():
    return _entete(*DIRECTEUR)


@pytest.fixture(scope="module")
def emp_a():
    return _entete(*EMPLOYE_A)


@pytest.fixture(scope="module")
def emp_b():
    return _entete(*EMPLOYE_B)


def _id_employe(dir_h, nom: str) -> int:
    emps = client.get("/api/taches/employes", headers=dir_h).json()["employes"]
    return next(e["id"] for e in emps if e["nom"] == nom)


def test_un_employe_na_pas_acces_aux_tableaux_de_bord(emp_a):
    """Un employé traite des tâches ; il ne lit ni le chiffre d'affaires ni les clients."""
    r = client.post("/api/dashboard", headers=emp_a, json={})
    assert r.status_code == 403
    assert client.get("/api/supply", headers=emp_a).status_code == 403


def test_le_directeur_confie_une_tache_depuis_une_alerte(dir_h, emp_a):
    sami = _id_employe(dir_h, "Sami")
    r = client.post("/api/taches", headers=dir_h, json={
        "titre": "Relancer les factures de plus de 90 jours",
        "client_code": CLIENT_CODE, "client_nom": "Hôpital de test",
        "type": "appel", "montant_dt": 12400, "severite": "critique",
        "origine_categorie": "Recouvrement",
        "origine_titre": "Factures à plus de 90 jours",
        "assigne_id": sami,
    })
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["origine_categorie"] == "Recouvrement"
    assert t["statut"] == "a_faire"
    assert t["echeance"] is not None
    assert t["assigne_nom"] == "Sami"


def test_un_employe_ne_peut_pas_confier_de_tache(emp_a):
    r = client.post("/api/taches", headers=emp_a, json={"titre": "Tâche que je m'attribue"})
    assert r.status_code == 403


def test_chacun_ne_voit_que_ses_taches(dir_h, emp_a, emp_b):
    mes = client.get("/api/taches", headers=emp_a).json()["taches"]
    assert mes and all(t["assigne_nom"] == "Sami" for t in mes)
    assert client.get("/api/taches", headers=emp_b).json()["taches"] == []
    autre = client.get("/api/taches?assigne_id=1", headers=emp_b).json()["taches"]
    assert autre == []
    assert len(client.get("/api/taches", headers=dir_h).json()["taches"]) >= 1


@pytest.mark.vitrine
def test_une_tache_dun_collegue_est_introuvable(dir_h, emp_a, emp_b):
    """404 et non 403 : un 403 confirmerait que la tâche existe."""
    sami = _id_employe(dir_h, "Sami")
    tid = client.post("/api/taches", headers=dir_h, json={
        "titre": "Appeler le service achats", "client_code": CLIENT_CODE,
        "severite": "moyenne", "assigne_id": sami}).json()["id"]

    assert client.get(f"/api/taches/{tid}", headers=emp_a).status_code == 200
    assert client.get(f"/api/taches/{tid}", headers=emp_b).status_code == 404
    assert client.patch(f"/api/taches/{tid}", headers=emp_b,
                        json={"statut": "en_cours"}).status_code == 404


def test_un_employe_ne_peut_pas_reaffecter(emp_a, dir_h):
    tid = client.get("/api/taches", headers=emp_a).json()["taches"][0]["id"]
    nadia = _id_employe(dir_h, "Nadia")
    r = client.patch(f"/api/taches/{tid}", headers=emp_a, json={"assigne_id": nadia})
    assert r.status_code == 403


def test_une_tache_ne_se_cloture_pas_sans_resultat(emp_a):
    """Une tâche close sans issue connue ne mesure rien : elle casserait la boucle en silence."""
    tid = client.get("/api/taches", headers=emp_a).json()["taches"][0]["id"]
    assert client.patch(f"/api/taches/{tid}", headers=emp_a,
                        json={"statut": "en_cours"}).status_code == 200
    r = client.patch(f"/api/taches/{tid}", headers=emp_a, json={"statut": "terminee"})
    assert r.status_code == 422
    assert "résultat" in r.json()["detail"].lower()


def test_le_resultat_alimente_la_mesure_dimpact(emp_a, dir_h):
    tid = client.get("/api/taches", headers=emp_a).json()["taches"][0]["id"]
    r = client.patch(f"/api/taches/{tid}", headers=emp_a, json={
        "statut": "terminee", "resultat": "paye", "resultat_montant_dt": 12400,
        "resultat_commentaire": "Virement reçu le 12",
    })
    assert r.status_code == 200
    assert r.json()["resultat_label"] == "Payé"

    impact = client.get("/api/taches/impact", headers=dir_h).json()
    assert impact["recupere_dt"] == 12400
    assert impact["taches_terminees"] >= 1
    assert impact["par_mois"], "le montant obtenu doit être daté pour être suivi"

    hist = client.get(f"/api/taches/{tid}", headers=dir_h).json()["historique"]
    assert [e["type"] for e in hist][:2] == ["creation", "affectation"]
    assert any(e["type"] == "resultat" for e in hist)


@pytest.mark.vitrine
def test_une_issue_perdue_ne_compte_pas_comme_un_gain(dir_h, emp_a):
    """Un client perdu ne doit jamais gonfler « récupéré grâce aux actions »."""
    sami = _id_employe(dir_h, "Sami")
    tid = client.post("/api/taches", headers=dir_h, json={
        "titre": "Retenir un compte qui part", "client_code": CLIENT_CODE,
        "montant_dt": 50000, "severite": "haute", "assigne_id": sami,
        "origine_categorie": "Rétention",
    }).json()["id"]
    avant = client.get("/api/taches/impact", headers=dir_h).json()["recupere_dt"]
    client.patch(f"/api/taches/{tid}", headers=emp_a, json={
        "statut": "terminee", "resultat": "client_perdu", "resultat_montant_dt": 50000})
    apres = client.get("/api/taches/impact", headers=dir_h).json()
    assert apres["recupere_dt"] == avant
    perdus = next(x for x in apres["par_resultat"] if x["resultat"] == "client_perdu")
    assert perdus["montant_en_jeu_dt"] == 50000


def test_lexport_alimente_lentrepot_avec_des_lignes_exploitables(tmp_path, monkeypatch):
    """L'export écrit un entrepôt lisible par les entraînements."""
    import duckdb

    from ml_engine import boucle

    faux = tmp_path / "store_test.duckdb"
    monkeypatch.setattr(boucle, "_store_path", lambda: faux)

    absent = boucle.exporter_retours(verbose=False)
    assert absent["ok"] is False and "absent" in absent["motif"]

    duckdb.connect(str(faux)).close()
    info = boucle.exporter_retours(verbose=False)
    assert info["ok"] is True
    assert info["taches"] >= 3

    r = boucle.resume()
    assert r["disponible"] is True
    assert r["gagnees"] >= 1
    assert r["montant_obtenu_dt"] >= 12400
    domaines = {d["domaine"] for d in r["par_domaine"]}
    assert "Recouvrement" in domaines

    con = duckdb.connect(str(faux), read_only=True)
    lignes = con.execute(
        "SELECT resultat, gagnee, montant_obtenu_dt FROM retours_taches "
        "WHERE resultat = 'client_perdu'").fetchall()
    con.close()
    assert lignes and lignes[0][1] == 0


def test_le_directeur_voit_letat_de_la_boucle(dir_h):
    r = client.get("/api/taches/boucle", headers=dir_h)
    assert r.status_code == 200
    d = r.json()
    # Deux résultats enregistrés par les employés plus haut (payé, client perdu).
    assert d["resultats_enregistres"] >= 2


ALERTE = "Relancer le devis DV-2026-114 — Clinique du Lac"


@pytest.mark.vitrine
def test_une_alerte_deja_confiee_ne_se_confie_pas_une_seconde_fois(dir_h):
    """Deux tâches pour la même alerte, ce sont deux personnes qui appellent le même client — et un…"""
    nadia = _id_employe(dir_h, "Nadia")
    corps = {"titre": "Relancer ce devis", "client_code": "CLI_LAC",
             "client_nom": "Clinique du Lac", "type": "relance_devis",
             "origine_categorie": "Commercial", "origine_titre": ALERTE,
             "assigne_id": nadia}

    assert client.post("/api/taches", headers=dir_h, json=corps).status_code == 201

    r = client.post("/api/taches", headers=dir_h, json=corps)
    assert r.status_code == 409
    assert "Nadia" in r.json()["detail"]

    autre = {**corps, "origine_titre": "Relancer le devis DV-2026-115 — Clinique du Lac"}
    assert client.post("/api/taches", headers=dir_h, json=autre).status_code == 201


def test_le_tableau_de_bord_sait_quelles_alertes_sont_deja_confiees(dir_h):
    """C'est cette route qui remplace le bouton par « Confiée à … » — et qui survit au rechargement de…"""
    confiees = client.get("/api/taches/confiees", headers=dir_h).json()["confiees"]
    assert ALERTE in confiees
    assert confiees[ALERTE]["assigne_nom"] == "Nadia"
    assert confiees[ALERTE]["statut"] in ("a_faire", "en_cours")


def test_une_alerte_traitee_redevient_confiable(dir_h, emp_b):
    """Si le problème revient plus tard, l'alerte doit pouvoir repartir en action : le verrou porte sur…"""
    tid = client.get("/api/taches/confiees", headers=dir_h).json()["confiees"][ALERTE]["id"]
    assert client.patch(f"/api/taches/{tid}", headers=emp_b, json={
        "statut": "terminee", "resultat": "devis_signe"}).status_code == 200

    assert ALERTE not in client.get("/api/taches/confiees", headers=dir_h).json()["confiees"]
    assert client.post("/api/taches", headers=dir_h, json={
        "titre": "Relancer ce devis", "origine_titre": ALERTE,
        "origine_categorie": "Commercial"}).status_code == 201
