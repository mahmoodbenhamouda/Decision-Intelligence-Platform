"""
tests/test_boucle_action.py
===========================
La BOUCLE D'ACTION de bout en bout : alerte → tâche confiée → résultat →
mesure → retour vers les modèles.

Ce que ces tests démontrent (et qu'aucun autre fichier ne couvre) :

1. **Cloisonnement.** Un client ne voit RIEN du suivi interne ; un employé ne
   voit que SES tâches, et demander l'identifiant d'une tâche d'un collègue
   renvoie 404 — pas 403, qui confirmerait son existence.
2. **Responsabilité.** Seul le directeur confie et réaffecte. Un employé qui
   tente de réaffecter reçoit 403.
3. **Mesure.** Une tâche ne se clôture pas sans résultat ; le montant obtenu
   remonte dans « récupéré grâce aux actions », et jamais celui d'une issue
   perdue.
4. **Boucle client.** Une action du client crée une tâche non affectée, et la
   clôture de cette tâche répond automatiquement au client.
5. **Retour aux modèles.** L'export écrit dans l'entrepôt des lignes exploitables,
   dont l'étiquette d'intérêt produit qui manquait à la recommandation.
6. **Pas de doublon.** Une alerte déjà confiée ne se confie pas une seconde
   fois (409) ; une fois la tâche terminée, elle redevient confiable.

Exécution :
    python -m pytest tests/test_boucle_action.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

# Base d'auth ISOLÉE pour CE module (les autres fichiers de tests ont la leur).
_tmpdir = tempfile.mkdtemp(prefix="boucletest_")
_DB_URL = f"sqlite:///{Path(_tmpdir).as_posix()}/boucle_test.db"
os.environ["AUTH_DATABASE_URL"] = _DB_URL
os.environ.setdefault("JWT_SECRET_KEY", "secret-de-test-uniquement")

from api.auth.database import get_db, reset_for_tests  # noqa: E402
from api.auth.models import Tache, User  # noqa: E402
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402

client = TestClient(app)

DIRECTEUR = ("dir.boucle@test.tn", "Directeur#Test1")
EMPLOYE_A = ("sami@test.tn", "Employe#Test1")
EMPLOYE_B = ("nadia@test.tn", "Employe#Test2")
CLIENT = ("hopital@test.tn", "ClientAAAA#1", "CLI_H")


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
        User(email=CLIENT[0], password_hash=hash_password(CLIENT[1]),
             role="client", client_code=CLIENT[2], full_name="Hôpital de test"),
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


@pytest.fixture(scope="module")
def cli_h():
    return _entete(CLIENT[0], CLIENT[1])


def _id_employe(dir_h, nom: str) -> int:
    emps = client.get("/api/taches/employes", headers=dir_h).json()["employes"]
    return next(e["id"] for e in emps if e["nom"] == nom)


# ── 1. Cloisonnement ────────────────────────────────────────────────────────
def test_un_client_ne_voit_pas_le_suivi_interne(cli_h):
    """L'organisation interne du travail ne regarde pas le client."""
    assert client.get("/api/taches", headers=cli_h).status_code == 403
    assert client.get("/api/taches/impact", headers=cli_h).status_code == 403
    assert client.post("/api/taches", headers=cli_h,
                       json={"titre": "Tâche pirate"}).status_code == 403


def test_un_employe_na_pas_acces_aux_tableaux_de_bord(emp_a):
    """Un employé traite des tâches ; il ne lit ni le chiffre d'affaires ni les
    clients. Le refus vient du serveur, pas d'un onglet caché."""
    r = client.post("/api/dashboard", headers=emp_a, json={})
    assert r.status_code == 403
    assert client.get("/api/supply", headers=emp_a).status_code == 403


# ── 2. Confier, et seulement quand on en a le droit ─────────────────────────
def test_le_directeur_confie_une_tache_depuis_une_alerte(dir_h, emp_a):
    sami = _id_employe(dir_h, "Sami")
    r = client.post("/api/taches", headers=dir_h, json={
        "titre": "Relancer les factures de plus de 90 jours",
        "client_code": CLIENT[2], "client_nom": "Hôpital de test",
        "type": "appel", "montant_dt": 12400, "severite": "critique",
        "origine_categorie": "Recouvrement",
        "origine_titre": "Factures à plus de 90 jours",
        "assigne_id": sami,
    })
    assert r.status_code == 201, r.text
    t = r.json()
    # L'origine est conservée : sans elle, impossible de savoir plus tard si
    # les alertes de ce domaine mènent à quelque chose.
    assert t["origine_categorie"] == "Recouvrement"
    assert t["statut"] == "a_faire"          # déjà affectée → prête à traiter
    assert t["echeance"] is not None         # gravité critique → délai court
    assert t["assigne_nom"] == "Sami"


def test_un_employe_ne_peut_pas_confier_de_tache(emp_a):
    r = client.post("/api/taches", headers=emp_a, json={"titre": "Tâche que je m'attribue"})
    assert r.status_code == 403


def test_chacun_ne_voit_que_ses_taches(dir_h, emp_a, emp_b):
    mes = client.get("/api/taches", headers=emp_a).json()["taches"]
    assert mes and all(t["assigne_nom"] == "Sami" for t in mes)
    # Nadia n'a rien : la liste de Sami ne fuit pas.
    assert client.get("/api/taches", headers=emp_b).json()["taches"] == []
    # Même en demandant explicitement les tâches d'un collègue.
    autre = client.get("/api/taches?assigne_id=1", headers=emp_b).json()["taches"]
    assert autre == []
    # Le directeur, lui, voit l'ensemble.
    assert len(client.get("/api/taches", headers=dir_h).json()["taches"]) >= 1


@pytest.mark.vitrine
def test_une_tache_dun_collegue_est_introuvable(dir_h, emp_a, emp_b):
    """404 et non 403 : un 403 confirmerait que la tâche existe.

    Ce test crée sa propre tâche plutôt que de réutiliser celle d'un test
    précédent : c'est un test « vitrine », il doit passer seul
    (`pytest -m vitrine`) comme au sein de la suite.
    """
    sami = _id_employe(dir_h, "Sami")
    tid = client.post("/api/taches", headers=dir_h, json={
        "titre": "Appeler le service achats", "client_code": CLIENT[2],
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


# ── 3. Clôture et mesure ────────────────────────────────────────────────────
def test_une_tache_ne_se_cloture_pas_sans_resultat(emp_a):
    """Une tâche close sans issue connue ne mesure rien : elle casserait la
    boucle en silence."""
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

    # L'histoire de la tâche est complète : création, affectation, statuts, résultat.
    hist = client.get(f"/api/taches/{tid}", headers=dir_h).json()["historique"]
    assert [e["type"] for e in hist][:2] == ["creation", "affectation"]
    assert any(e["type"] == "resultat" for e in hist)


@pytest.mark.vitrine
def test_une_issue_perdue_ne_compte_pas_comme_un_gain(dir_h, emp_a):
    """Un client perdu ne doit jamais gonfler « récupéré grâce aux actions »."""
    sami = _id_employe(dir_h, "Sami")
    tid = client.post("/api/taches", headers=dir_h, json={
        "titre": "Retenir un compte qui part", "client_code": CLIENT[2],
        "montant_dt": 50000, "severite": "haute", "assigne_id": sami,
        "origine_categorie": "Rétention",
    }).json()["id"]
    avant = client.get("/api/taches/impact", headers=dir_h).json()["recupere_dt"]
    client.patch(f"/api/taches/{tid}", headers=emp_a, json={
        "statut": "terminee", "resultat": "client_perdu", "resultat_montant_dt": 50000})
    apres = client.get("/api/taches/impact", headers=dir_h).json()
    assert apres["recupere_dt"] == avant
    perdus = next(x for x in apres["par_resultat"] if x["resultat"] == "client_perdu")
    assert perdus["montant_en_jeu_dt"] == 50000   # la perte reste visible, ailleurs


# ── 4. La moitié client de la boucle ────────────────────────────────────────
def test_une_action_client_cree_une_tache_a_affecter(cli_h, dir_h):
    r = client.post("/api/portal/actions", headers=cli_h, json={
        "type": "promesse_paiement", "reference": "2026-02-11",
        "montant_dt": 8000, "date_prevue": "2026-10-05",
    })
    assert r.status_code == 201, r.text
    tache_id = r.json()["tache_id"]

    t = client.get(f"/api/taches/{tache_id}", headers=dir_h).json()
    assert t["statut"] == "a_affecter"     # personne ne l'a encore prise
    assert t["venue_du_client"] is True
    assert t["client_code"] == CLIENT[2]
    assert t["montant_dt"] == 8000
    assert "2026-10-05" in (t["details"] or "")


def test_un_directeur_ne_depose_pas_daction_a_la_place_du_client(dir_h):
    r = client.post("/api/portal/actions", headers=dir_h,
                    json={"type": "promesse_paiement", "montant_dt": 1})
    assert r.status_code == 403


def test_la_cloture_repond_automatiquement_au_client(cli_h, dir_h, emp_a):
    """Sans réponse, le client cesse d'agir : la clôture referme la boucle."""
    avant = client.get("/api/portal/requests", headers=cli_h).json()["requests"][0]
    assert avant["status"] == "nouvelle"

    tache_id = client.get("/api/taches?statut=a_affecter", headers=dir_h).json()["taches"][0]["id"]
    sami = _id_employe(dir_h, "Sami")
    assert client.patch(f"/api/taches/{tache_id}", headers=dir_h,
                        json={"assigne_id": sami}).json()["statut"] == "a_faire"
    client.patch(f"/api/taches/{tache_id}", headers=emp_a, json={
        "statut": "terminee", "resultat": "promesse",
        "resultat_commentaire": "Le client règle le 5 octobre."})

    apres = client.get("/api/portal/requests", headers=cli_h).json()["requests"][0]
    assert apres["status"] == "traitee"
    assert "5 octobre" in (apres["reponse"] or "")


def test_un_interet_produit_est_enregistre_une_seule_fois(cli_h):
    r = client.post("/api/portal/actions", headers=cli_h, json={
        "type": "interet_produit", "reference": "424641",
        "libelle": "VIDAS TOXO IGM 60T"})
    assert r.status_code == 201
    reco = client.get("/api/portal/recommandations", headers=cli_h).json()
    # Le produit déjà signalé est marqué comme tel s'il figure dans la liste :
    # on ne demande pas deux fois la même chose au client.
    for p in reco.get("produits", []):
        if p["reference"] == "424641":
            assert p["deja_signale"] is True


# ── 5. Retour vers les modèles ──────────────────────────────────────────────
def test_lexport_alimente_lentrepot_avec_des_lignes_exploitables(tmp_path, monkeypatch):
    """L'export écrit un entrepôt lisible par les entraînements.

    L'entrepôt réel n'est pas touché : on écrit dans un fichier temporaire, ce
    qui permet aussi de vérifier le cas « entrepôt absent ».
    """
    import duckdb

    from ml_engine import boucle

    faux = tmp_path / "store_test.duckdb"
    monkeypatch.setattr(boucle, "_store_path", lambda: faux)

    # Entrepôt absent : refus explicite, jamais d'exception.
    absent = boucle.exporter_retours(verbose=False)
    assert absent["ok"] is False and "absent" in absent["motif"]

    duckdb.connect(str(faux)).close()             # entrepôt vide mais existant
    info = boucle.exporter_retours(verbose=False)
    assert info["ok"] is True
    assert info["taches"] >= 3 and info["actions_client"] >= 2

    r = boucle.resume()
    assert r["disponible"] is True
    assert r["gagnees"] >= 1
    assert r["montant_obtenu_dt"] >= 12400
    # L'étiquette qui manquait à la recommandation : un vrai client a dit oui.
    assert r["retours_produits"] >= 1
    domaines = {d["domaine"] for d in r["par_domaine"]}
    assert "Recouvrement" in domaines

    con = duckdb.connect(str(faux), read_only=True)
    lignes = con.execute(
        "SELECT resultat, gagnee, montant_obtenu_dt FROM retours_taches "
        "WHERE resultat = 'client_perdu'").fetchall()
    con.close()
    # Une issue perdue part bien dans l'entrepôt, marquée comme non gagnée :
    # un modèle qui n'apprend que des succès n'apprend rien.
    assert lignes and lignes[0][1] == 0


def test_le_directeur_voit_letat_de_la_boucle(dir_h):
    r = client.get("/api/taches/boucle", headers=dir_h)
    assert r.status_code == 200
    d = r.json()
    assert d["resultats_enregistres"] >= 3


# ── 6. Une alerte ne se confie qu'une fois ──────────────────────────────────
ALERTE = "Relancer le devis DV-2026-114 — Clinique du Lac"


@pytest.mark.vitrine
def test_une_alerte_deja_confiee_ne_se_confie_pas_une_seconde_fois(dir_h):
    """Deux tâches pour la même alerte, ce sont deux personnes qui appellent le
    même client — et un client qui reçoit deux fois le même appel.

    L'écran cache déjà le bouton, mais un écran chargé avant la première
    affectation ne le sait pas : le refus qui compte est celui du serveur.
    """
    nadia = _id_employe(dir_h, "Nadia")
    corps = {"titre": "Relancer ce devis", "client_code": "CLI_LAC",
             "client_nom": "Clinique du Lac", "type": "relance_devis",
             "origine_categorie": "Commercial", "origine_titre": ALERTE,
             "assigne_id": nadia}

    assert client.post("/api/taches", headers=dir_h, json=corps).status_code == 201

    r = client.post("/api/taches", headers=dir_h, json=corps)
    assert r.status_code == 409
    # Le refus dit À QUI elle est confiée : « déjà fait » sans dire par qui
    # oblige le directeur à aller chercher l'information ailleurs.
    assert "Nadia" in r.json()["detail"]

    # Une AUTRE alerte reste confiable : le garde-fou vise le doublon, pas la
    # création de tâches.
    autre = {**corps, "origine_titre": "Relancer le devis DV-2026-115 — Clinique du Lac"}
    assert client.post("/api/taches", headers=dir_h, json=autre).status_code == 201


def test_le_tableau_de_bord_sait_quelles_alertes_sont_deja_confiees(dir_h):
    """C'est cette route qui remplace le bouton par « Confiée à … » — et qui
    survit au rechargement de la page, contrairement à une liste en mémoire."""
    confiees = client.get("/api/taches/confiees", headers=dir_h).json()["confiees"]
    assert ALERTE in confiees
    assert confiees[ALERTE]["assigne_nom"] == "Nadia"
    assert confiees[ALERTE]["statut"] in ("a_faire", "en_cours")


def test_une_alerte_traitee_redevient_confiable(dir_h, emp_b):
    """Si le problème revient plus tard, l'alerte doit pouvoir repartir en
    action : le verrou porte sur les tâches EN COURS, pas sur l'histoire."""
    tid = client.get("/api/taches/confiees", headers=dir_h).json()["confiees"][ALERTE]["id"]
    assert client.patch(f"/api/taches/{tid}", headers=emp_b, json={
        "statut": "terminee", "resultat": "devis_signe"}).status_code == 200

    assert ALERTE not in client.get("/api/taches/confiees", headers=dir_h).json()["confiees"]
    assert client.post("/api/taches", headers=dir_h, json={
        "titre": "Relancer ce devis", "origine_titre": ALERTE,
        "origine_categorie": "Commercial"}).status_code == 201
