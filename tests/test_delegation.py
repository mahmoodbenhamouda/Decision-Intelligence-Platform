"""La DÉLÉGATION AUTONOME : la flotte d'agents confie elle-même le travail d'exécution, sans…"""

import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from tests import base_postgres  # noqa: E402
_DB_URL = base_postgres.preparer(__name__)

from agents.fleet import nodes  # noqa: E402
from agents.fleet.delegation import (MAX_PAR_PASSAGE, POSTES, TYPES_ACTION,  # noqa: E402
                                     execution, planifier, titre_point_client)
from api.auth.database import get_db, reset_for_tests  # noqa: E402
from api.auth.models import (DelegationPassage, EvenementTache, Reglage,  # noqa: E402
                             Tache, User)
from api.auth.security import hash_password  # noqa: E402
from api.main import app  # noqa: E402
from api.services import delegation  # noqa: E402

client = TestClient(app)
RACINE = Path(__file__).resolve().parents[1]

DIRECTEUR = ("dir.delegation@test.tn", "Directeur#Test1")
SAMI = ("sami.delegation@test.tn", "Employe#Test1")
NADIA = ("nadia.delegation@test.tn", "Employe#Test2")


@pytest.fixture(scope="module", autouse=True)
def comptes():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur", full_name="Direction"),
        User(email=SAMI[0], password_hash=hash_password(SAMI[1]),
             role="employe", full_name="Sami", poste="recouvrement"),
        User(email=NADIA[0], password_hash=hash_password(NADIA[1]),
             role="employe", full_name="Nadia", poste="commercial"),
    ])
    db.commit()
    db.close()
    yield


@pytest.fixture
def db():
    """Une session sur une base SANS tâche ni passage : chaque test part du même état, et peut donc…"""
    reset_for_tests(_DB_URL)
    s = next(get_db())
    for modele in (EvenementTache, Tache, DelegationPassage, Reglage):
        s.query(modele).delete()
    s.commit()
    yield s
    s.close()


def _entete(email: str, mot_de_passe: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": mot_de_passe})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _specialistes(stock_severite: str = "moyenne"):
    return [
        {"agent": "Recouvrement", "categorie": "Recouvrement", "severite": "haute",
         "titre": "Créances à relancer en priorité", "montant_dt": 500_000,
         "constat": "…", "action": "Relancer UNOPS et CHU SFAX.",
         "execution": execution("recouvrement", "appel"),
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 300_000},
                               {"nom": "CHU SFAX", "montant_dt": 200_000}]},
        {"agent": "Commercial", "categorie": "Commercial", "severite": "haute",
         "titre": "Devis à relancer en priorité", "montant_dt": 400_000,
         "constat": "…", "action": "Relancer le devis UNOPS.",
         "execution": execution("commercial", "relance_devis"),
         "clients_concernes": [{"nom": "UNOPS", "montant_dt": 100_000}]},
        {"agent": "Trésorerie", "categorie": "Trésorerie", "severite": "haute",
         "titre": "Trésorerie : encaissements et stock dormant", "montant_dt": 900_000,
         "constat": "…", "action": "Renégocier les délais fournisseurs.",
         "execution": None},
        {"agent": "Stock & Approvisionnement", "domaine": "Stock", "categorie": "Stock",
         "severite": stock_severite, "titre": "Stock : ruptures et argent immobilisé",
         "montant_dt": 300_000, "constat": "…", "action": "Commander les ruptures.",
         "execution": execution("logistique", "commande")},
    ]


def _constats(**kw):
    specialistes = _specialistes(**kw)
    synthese = nodes.arbitre({"findings": specialistes, "trace": []})["findings"][0]
    return specialistes + [synthese]


def _flotte(**kw):
    return lambda: {"engine": "test", "briefing": "Briefing de test.",
                    "findings": _constats(**kw), "trace": []}


@pytest.mark.vitrine
def test_une_decision_de_direction_n_est_jamais_confiee_d_office():
    """La flotte confie l'exécution, jamais la décision : renégocier les délais fournisseurs engage…"""
    plan = planifier(_constats())
    titres = [p.origine_titre for p in plan.propositions]
    assert "Trésorerie : encaissements et stock dormant" not in titres
    assert [d["titre"] for d in plan.decisions_direction] == [
        "Trésorerie : encaissements et stock dormant"]


def test_un_constat_qui_ne_declare_rien_n_est_pas_delegue():
    """L'autonomie ne se suppose pas : sans déclaration de l'agent, rien."""
    constats = _specialistes()
    del constats[0]["execution"]
    synthese = nodes.arbitre({"findings": constats, "trace": []})["findings"][0]
    plan = planifier(constats + [synthese])
    assert "Créances à relancer en priorité" not in [p.origine_titre for p in plan.propositions]
    assert any(e["titre"] == "Créances à relancer en priorité"
               and "ne déclare pas" in e["raison"] for e in plan.ecartes)


def test_seules_les_gravites_hautes_partent_seules():
    plan = planifier(_constats(stock_severite="moyenne"))
    assert "Stock : ruptures et argent immobilisé" not in [p.origine_titre for p in plan.propositions]
    assert any("moyenne" in e["raison"] for e in plan.ecartes)
    plan = planifier(_constats(stock_severite="haute"))
    assert "Stock : ruptures et argent immobilisé" in [p.origine_titre for p in plan.propositions]


def test_les_clients_multi_signaux_passent_en_premier():
    """L'arbitre demande de traiter en premier un client qui doit de l'argent ET qui est signalé…"""
    plan = planifier(_constats())
    p1 = plan.propositions[0]
    assert p1.origine_titre == titre_point_client("UNOPS")
    assert p1.rang == 1
    assert (p1.poste, p1.origine_categorie) == ("recouvrement", "Recouvrement")
    assert "Créances à relancer en priorité" in p1.details
    assert "Devis à relancer en priorité" in p1.details
    suite = [p.origine_titre for p in plan.propositions[1:]]
    assert suite == ["Créances à relancer en priorité", "Devis à relancer en priorité"]


def test_un_client_deja_couvert_n_est_pas_appele_deux_fois():
    plan = planifier(_constats())
    creances = next(p for p in plan.propositions
                    if p.origine_titre == "Créances à relancer en priorité")
    assert "Déjà couverts par une tâche dédiée : UNOPS" in creances.details
    assert "CHU SFAX" not in creances.details.split("Déjà couverts")[1]


def test_le_montant_est_celui_du_bouton_confier():
    """Le même montant que le bouton « Confier » : l'enjeu à court terme."""
    constats = _constats()
    enjeu = next(c for c in constats[-1]["classement"]
                 if c["titre"] == "Créances à relancer en priorité")["enjeu_court_terme_dt"]
    creances = next(p for p in planifier(constats).propositions
                    if p.origine_titre == "Créances à relancer en priorité")
    assert creances.montant_dt == round(enjeu, 0)


def test_sans_classement_de_l_arbitre_rien_n_est_confie():
    """La gravité déclarée par chaque agent n'est pas une échelle commune."""
    plan = planifier(_specialistes())
    assert plan.classement_disponible is False and not plan.propositions


def test_plafond_par_passage():
    constats = _constats()
    synthese = constats[-1]
    for i in range(MAX_PAR_PASSAGE + 3):
        synthese["classement"].append({
            "titre": f"Alerte {i}", "categorie": "Commercial", "severite": "haute",
            "montant_dt": 1, "action": "…", "rang": 99 + i,
            "execution": execution("commercial", "appel")})
    plan = planifier(constats)
    assert len(plan.propositions) == MAX_PAR_PASSAGE
    assert [p.rang for p in plan.propositions] == list(range(1, MAX_PAR_PASSAGE + 1))
    assert any("plafond" in e["raison"] for e in plan.ecartes)


def test_les_listes_de_reference_sont_alignees():
    """Un agent n'importe pas l'API : ses listes sont dupliquées, donc vérifiées."""
    from api.auth.models import TACHE_TYPES
    from api.auth.seed import EMPLOYES
    assert tuple(TYPES_ACTION) == tuple(TACHE_TYPES)
    assert {poste for _, _, poste in EMPLOYES} == set(POSTES)
    ecran = RACINE / "frontend" / "src" / "features" / "admin" / "AdminPanel.tsx"
    if ecran.exists():
        options = set(re.findall(r'<option value="([a-z]+)">', ecran.read_text(encoding="utf-8")))
        assert set(POSTES) <= options, "l'écran Administration ne propose pas tous les métiers"


def test_la_cle_client_est_la_meme_que_celle_du_tableau_de_bord():
    """Si les deux formulations divergent, la flotte reconfierait un compte que le directeur a déjà…"""
    regles = RACINE / "frontend" / "src" / "features" / "briefing" / "briefing.regles.tsx"
    if not regles.exists():
        pytest.skip("frontend absent de cette copie")
    gabarit = re.search(r"titre: `([^`]*)\$\{c\.client\}`", regles.read_text(encoding="utf-8"))
    assert gabarit, "origineClient n'a plus la forme attendue"
    assert titre_point_client("X") == f"{gabarit.group(1)}X"


def test_un_passage_confie_au_bon_metier_et_se_journalise(db):
    p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    assert p["statut"] == "ok"
    assert p["n_creees"] == 3 and p["n_decisions"] == 1 and p["n_ecartees"] == 1
    assert p["briefing"] == "Briefing de test."

    par_titre = {l["titre"]: l for l in p["lignes"]}
    assert par_titre[titre_point_client("UNOPS")]["assigne"] == "Sami"
    assert par_titre["Créances à relancer en priorité"]["assigne"] == "Sami"
    assert par_titre["Devis à relancer en priorité"]["assigne"] == "Nadia"

    t = db.get(Tache, par_titre["Devis à relancer en priorité"]["tache_id"])
    assert t.delegation_auto is True and t.cree_par_id is None
    assert (t.type, t.statut, t.origine_categorie) == ("relance_devis", "a_faire", "Commercial")
    ech = t.echeance if t.echeance.tzinfo else t.echeance.replace(tzinfo=timezone.utc)
    assert timedelta(days=4) < ech - datetime.now(timezone.utc) <= timedelta(days=5)
    evts = db.query(EvenementTache).filter(EvenementTache.tache_id == t.id).all()
    assert [e.type for e in evts] == ["creation", "affectation"]
    assert "flotte" in evts[0].detail and "Nadia" in evts[1].detail


def test_l_employe_le_moins_charge_recoit_la_tache(db):
    """Deux personnes au même métier : la moins chargée reçoit la tâche."""
    sami = db.query(User).filter(User.email == SAMI[0]).one()
    renfort = User(email="renfort@test.tn", password_hash="x", role="employe",
                   full_name="Renfort", poste="recouvrement")
    db.add(renfort)
    db.commit()
    try:
        for i in range(2):
            db.add(Tache(titre=f"Déjà chez Sami {i}", assigne_id=sami.id, statut="a_faire"))
        db.commit()
        p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
        recouvrement = [l for l in p["lignes"] if l["poste"] == "recouvrement"]
        assert [l["assigne"] for l in recouvrement] == ["Renfort", "Renfort"]
        assert "le moins chargé des 2" in recouvrement[0]["raison"]
    finally:
        db.query(Tache).filter(Tache.assigne_id == renfort.id).update({"assigne_id": None})
        db.delete(renfort)
        db.commit()


@pytest.mark.vitrine
def test_la_flotte_ne_confie_jamais_deux_fois_la_meme_alerte(db):
    """Ni ce que le directeur a déjà confié à la main, ni ce qu'elle a elle-même confié la veille :…"""
    h = _entete(*DIRECTEUR)
    nadia = db.query(User).filter(User.email == NADIA[0]).one()
    r = client.post("/api/taches", headers=h, json={
        "titre": "Relancer ce devis", "type": "relance_devis",
        "origine_categorie": "Commercial", "origine_titre": "Devis à relancer en priorité",
        "assigne_id": nadia.id})
    assert r.status_code == 201

    p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    devis = next(l for l in p["lignes"] if l["titre"] == "Devis à relancer en priorité")
    assert devis["issue"] == "deja_confiee" and "Nadia" in devis["raison"]
    assert p["n_creees"] == 2

    second = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    assert second["n_creees"] == 0 and second["n_deja_confiees"] == 3
    assert db.query(Tache).count() == 3

    confiees = client.get("/api/taches/confiees", headers=h).json()["confiees"]
    assert confiees["Devis à relancer en priorité"]["par_la_flotte"] is False
    assert confiees["Créances à relancer en priorité"]["par_la_flotte"] is True


def test_une_alerte_traitee_recemment_n_est_pas_reconfiee(db):
    """Les données viennent d'exports : une créance payée hier y figure encore."""
    delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    t = db.query(Tache).filter(Tache.origine_titre == "Créances à relancer en priorité").one()
    t.statut, t.resultat = "terminee", "paye"
    t.closed_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()

    p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    ligne = next(l for l in p["lignes"] if l["titre"] == "Créances à relancer en priorité")
    assert ligne["issue"] == "recente" and "carence" in ligne["raison"]

    t.closed_at = datetime.now(timezone.utc) - timedelta(days=delegation.CARENCE_JOURS + 1)
    db.commit()
    p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    ligne = next(l for l in p["lignes"] if l["titre"] == "Créances à relancer en priorité")
    assert ligne["issue"] == "creee"


def test_sans_employe_du_metier_la_tache_attend_le_directeur(db):
    """Aucun logisticien : la tâche n'est confiée à personne d'autre au hasard, elle attend le…"""
    p = delegation.executer(db, declencheur="manuel",
                            lancer_flotte=_flotte(stock_severite="haute"))
    stock = next(l for l in p["lignes"] if l["titre"] == "Stock : ruptures et argent immobilisé")
    assert stock["issue"] == "creee" and stock["assigne"] is None
    t = db.get(Tache, stock["tache_id"])
    assert t.statut == "a_affecter" and t.assigne_id is None
    note = db.query(EvenementTache).filter(EvenementTache.tache_id == t.id,
                                           EvenementTache.type == "commentaire").one()
    assert "logistique" in note.detail


def test_au_dela_du_plafond_de_charge_la_tache_attend_le_directeur(db):
    nadia = db.query(User).filter(User.email == NADIA[0]).one()
    for i in range(delegation.CHARGE_MAX):
        db.add(Tache(titre=f"Charge {i}", assigne_id=nadia.id, statut="en_cours"))
    db.commit()
    p = delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    devis = next(l for l in p["lignes"] if l["titre"] == "Devis à relancer en priorité")
    assert devis["assigne"] is None and "saturée" in devis["raison"]


def test_une_flotte_en_erreur_ne_confie_rien(db):
    p = delegation.executer(db, declencheur="manuel",
                            lancer_flotte=lambda: {"engine": "erreur", "findings": []})
    assert p["statut"] == "echec" and p["n_creees"] == 0
    assert db.query(Tache).count() == 0


def test_quand_le_passage_hebdomadaire_est_du():
    """La délégation part une fois par SEMAINE, le lundi.

    Elle partait chaque matin. Sur un portefeuille d'hôpitaux qui commandent par
    cycles de plusieurs semaines, les mêmes alertes revenaient jour après jour
    et l'employé recevait du travail avant d'avoir fini celui de la veille."""
    from datetime import time
    h = time(7, 30)
    lundi = datetime(2026, 10, 5, 7, 29)          # 5 octobre 2026 est un lundi

    assert not delegation.passage_du(True, h, lundi, False), "avant l'heure"
    assert delegation.passage_du(True, h, lundi.replace(minute=30), False)
    assert delegation.passage_du(True, h, lundi.replace(hour=9), False)
    assert not delegation.passage_du(True, h, lundi.replace(hour=9), True), "déjà fait"
    assert not delegation.passage_du(False, h, lundi.replace(hour=9), False), "désactivée"

    # Le reste de la semaine ne déclenche rien tant que le passage est fait…
    mercredi = datetime(2026, 10, 7, 9, 0)
    assert not delegation.passage_du(True, h, mercredi, True)
    # …mais se rattrape s'il ne l'est pas : mieux vaut en retard que sauté.
    assert delegation.passage_du(True, h, mercredi, False)


def test_le_prochain_passage_vise_toujours_un_lundi():
    from datetime import time
    h = time(7, 30)
    lundi_prochain = datetime(2026, 10, 12, 7, 30)

    # Lundi, passage déjà fait → le lundi suivant.
    assert delegation.prochain_passage(
        True, h, datetime(2026, 10, 5, 9, 0), True) == lundi_prochain
    # Jeudi, passage de la semaine fait → le lundi suivant, pas celui d'après.
    assert delegation.prochain_passage(
        True, h, datetime(2026, 10, 8, 9, 0), True) == lundi_prochain
    # Lundi avant l'heure → aujourd'hui même.
    assert delegation.prochain_passage(
        True, h, datetime(2026, 10, 5, 7, 0), False) == datetime(2026, 10, 5, 7, 30)
    assert delegation.prochain_passage(False, h, lundi_prochain, False) is None


def test_la_cle_de_passage_est_la_semaine_et_non_le_jour():
    """Avec une clé journalière, un serveur arrêté le lundi sautait la semaine
    entière. La semaine ISO permet le rattrapage sans doublon."""
    assert delegation.jour_local(datetime(2026, 10, 5)) == \
        delegation.jour_local(datetime(2026, 10, 8)), "même semaine"
    assert delegation.jour_local(datetime(2026, 10, 5)) != \
        delegation.jour_local(datetime(2026, 10, 12)), "semaines différentes"


def test_un_seul_passage_planifie_par_jour(db):
    """Deux réveils le même jour — API relancée, ligne de commande en parallèle — ne confient pas deux…"""
    maintenant = datetime(2026, 9, 29, 8, 0)
    assert delegation.executer_si_du(maintenant, lancer_flotte=_flotte()) is None

    directeur = db.query(User).filter(User.email == DIRECTEUR[0]).one()
    delegation.modifier_reglages(db, directeur, active=True, heure="07:30")
    premier = delegation.executer_si_du(maintenant, lancer_flotte=_flotte())
    assert premier is not None and premier["declencheur"] == "planifie"
    assert delegation.executer_si_du(maintenant.replace(hour=9), lancer_flotte=_flotte()) is None

    assert delegation.executer(db, declencheur="planifie", lancer_flotte=_flotte(),
                               maintenant=maintenant) is None
    assert db.query(DelegationPassage).filter(
        DelegationPassage.declencheur == "planifie").count() == 1


def test_seul_le_directeur_regle_et_lance_la_delegation():
    for compte in (_entete(*SAMI),):
        assert client.get("/api/taches/delegation", headers=compte).status_code == 403
        assert client.put("/api/taches/delegation", headers=compte,
                          json={"active": True}).status_code == 403
        assert client.post("/api/taches/delegation/lancer", headers=compte).status_code == 403


def test_le_directeur_regle_et_lance_depuis_l_ecran(db, monkeypatch):
    h = _entete(*DIRECTEUR)
    etat = client.get("/api/taches/delegation", headers=h).json()
    assert etat["active"] is False and etat["heure"] == delegation.HEURE_PAR_DEFAUT

    r = client.put("/api/taches/delegation", headers=h, json={"active": True, "heure": "06:45"})
    assert r.status_code == 200 and r.json()["active"] is True and r.json()["heure"] == "06:45"
    assert client.put("/api/taches/delegation", headers=h,
                      json={"heure": "25h"}).status_code == 422

    monkeypatch.setattr(delegation, "_flotte_globale", _flotte())
    r = client.post("/api/taches/delegation/lancer", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["declencheur"] == "manuel" and r.json()["lance_par"] == "Direction"
    assert client.get("/api/taches/delegation", headers=h).json()["dernier"]["n_creees"] == 3


def test_la_mesure_distingue_la_flotte_de_la_direction(db, tmp_path, monkeypatch):
    """La seule question qui justifie de laisser la délégation active : ce que la flotte confie…"""
    h = _entete(*DIRECTEUR)
    delegation.executer(db, declencheur="manuel", lancer_flotte=_flotte())
    t = db.query(Tache).filter(Tache.origine_titre == "Créances à relancer en priorité").one()
    t.statut, t.resultat, t.resultat_montant_dt = "terminee", "paye", 40_000
    t.closed_at = datetime.now(timezone.utc)
    db.commit()
    client.post("/api/taches", headers=h, json={"titre": "Appeler le service achats"})

    par_origine = {o["origine"]: o for o in
                   client.get("/api/taches/impact", headers=h).json()["par_origine"]}
    assert par_origine["flotte"]["taches"] == 3
    assert par_origine["flotte"]["recupere_dt"] == 40_000
    assert par_origine["flotte"]["taux_reussite"] == 100.0
    assert par_origine["direction"]["taches"] == 1

    import duckdb

    from ml_engine import boucle
    faux = tmp_path / "store.duckdb"
    duckdb.connect(str(faux)).close()
    monkeypatch.setattr(boucle, "_store_path", lambda: faux)
    assert boucle.exporter_retours(verbose=False)["ok"]
    con = duckdb.connect(str(faux), read_only=True)
    n = con.execute("SELECT sum(delegation_auto) FROM retours_taches").fetchone()[0]
    con.close()
    assert n == 3


def test_sur_la_vraie_flotte_chaque_constat_declare_qui_peut_l_executer():
    """Sur l'entrepôt réel : chaque constat métier dit s'il relève de l'exécution (et de quel métier)…"""
    from ml_engine.analytics.kpi_engine import STORE_PATH
    if not STORE_PATH.exists():
        pytest.skip("entrepôt DuckDB absent")
    from agents.fleet.graph import run_briefing
    findings = run_briefing({})["findings"]
    synthese = next(f for f in findings if f.get("classement"))
    for c in synthese["classement"]:
        assert "execution" in c, f"« {c['titre']} » ne déclare pas qui peut l'exécuter"
        ex = c["execution"]
        assert ex is None or (ex["poste"] in POSTES and ex["type"] in TYPES_ACTION)
    decisions = {c["titre"] for c in synthese["classement"] if c["execution"] is None}
    plan = planifier(findings)
    assert not decisions & {p.origine_titre for p in plan.propositions}


@pytest.mark.vitrine
def test_une_carte_a_plusieurs_clients_donne_une_tache_par_client():
    """Une carte « créances à relancer » vise dix établissements : la flotte confie
    une tâche PAR client, avec son intitulé précis, pas « relancer la liste »."""
    from agents.fleet.delegation import MAX_PAR_CONSTAT, origine_cible
    specialistes = _specialistes()
    specialistes[0]["clients_concernes"] = [
        nodes._cible(f"HOPITAL {i}", 10_000 * (10 - i), f"{10 - i}0 K DT à plus de 60 j",
                     "appel", f"Appeler HOPITAL {i} : {10 - i}0 K DT de factures", code=f"C{i}")
        for i in range(6)]
    synthese = nodes.arbitre({"findings": specialistes, "trace": []})["findings"][0]
    plan = planifier(specialistes + [synthese])

    creances = [p for p in plan.propositions
                if p.origine_titre.startswith("Créances à relancer en priorité — ")]
    assert len(creances) == MAX_PAR_CONSTAT
    p0 = creances[0]
    assert p0.origine_titre == origine_cible("Créances à relancer en priorité", "HOPITAL 0")
    assert p0.titre == "Appeler HOPITAL 0 : 100 K DT de factures"
    assert (p0.client_nom, p0.client_code, p0.type) == ("HOPITAL 0", "C0", "appel")
    # Même échelle que la carte : la part de l'enjeu à court terme (créance × 0,15).
    assert p0.montant_dt == 15_000


def test_la_cle_d_une_ligne_est_la_meme_que_celle_du_tableau_de_bord():
    """Le bouton « Confier » d'une ligne et la flotte doivent viser la même tâche."""
    from agents.fleet.delegation import origine_cible
    regles = RACINE / "frontend" / "src" / "features" / "briefing" / "briefing.regles.tsx"
    if not regles.exists():
        pytest.skip("frontend absent de cette copie")
    gabarit = re.search(r"return `\$\{titreConstat\}([^`]*)\$\{nom\}`", regles.read_text(encoding="utf-8"))
    assert gabarit, "cleCible n'a plus la forme attendue"
    assert origine_cible("T", "X") == f"T{gabarit.group(1)}X"
