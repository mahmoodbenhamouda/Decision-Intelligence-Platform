"""La boucle d'approvisionnement : ce que la plateforme crée et que l'ERP n'a pas.

L'export ERP ne contient que des factures d'achat. Ni bon de commande, ni date
de réception : trois étapes du processus n'y existent pas, et aucun délai de
livraison n'y est calculable.

Ces tests vérifient deux choses distinctes :

  * le CYCLE est un ordre, pas un champ libre. Une commande ne se reçoit pas
    sans avoir été passée, un refus est définitif, une référence n'a qu'une
    commande ouverte à la fois ;
  * la boucle PRODUIT la donnée manquante. Dès la première réception saisie, le
    délai de livraison réel devient mesurable — et les étapes du processus
    changent d'état en conséquence.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from tests import base_postgres  # noqa: E402
_DB_URL = base_postgres.preparer(__name__)

from api.auth.database import get_db, reset_for_tests  # noqa: E402
from api.auth.models import (COMMANDE_OUVERTS, COMMANDE_TRANSITIONS,  # noqa: E402
                             STATUTS_OUVERTS, CommandeFournisseur,
                             EvenementCommande, EvenementTache, Tache, User)
from api.auth.security import hash_password  # noqa: E402
from api.services import commandes as svc  # noqa: E402
from api.services.erreurs import Conflit, DonneesInvalides, Introuvable  # noqa: E402

DIRECTEUR = ("dir.commandes@test.tn", "Directeur#Test1")
LOGISTICIEN = ("log.commandes@test.tn", "Employe#Test1")

PROPOSITION = {
    "reference": "30400",
    "designation": "VIDAS TSH 60 tests",
    "fournisseur_code": "F001",
    "fournisseur_nom": "BIOMERIEUX",
    "motif": "Dernier achat il y a 146 jours pour un rythme de 31 jours.",
    "qte_proposee": 200.0,
    "montant_estime_dt": 21718.0,
}


@pytest.fixture(scope="module", autouse=True)
def compte():
    reset_for_tests(_DB_URL)
    db = next(get_db())
    db.add_all([
        User(email=DIRECTEUR[0], password_hash=hash_password(DIRECTEUR[1]),
             role="directeur", full_name="Direction"),
        User(email=LOGISTICIEN[0], password_hash=hash_password(LOGISTICIEN[1]),
             role="employe", full_name="Karim", poste="logistique"),
    ])
    db.commit()
    db.close()
    yield


@pytest.fixture
def db():
    """Base vidée de ses commandes et de ses tâches : même état de départ."""
    s = next(get_db())
    s.query(EvenementCommande).delete()
    s.query(CommandeFournisseur).delete()
    s.query(EvenementTache).delete()
    s.query(Tache).delete()
    s.commit()
    yield s
    s.close()


@pytest.fixture
def directeur(db):
    return db.query(User).filter(User.email == DIRECTEUR[0]).first()


@pytest.fixture
def logisticien(db):
    return db.query(User).filter(User.email == LOGISTICIEN[0]).first()


def _creer(db, directeur, **kw):
    return svc.creer(db, directeur, {**PROPOSITION, **kw})


# ── Le cycle de vie ──────────────────────────────────────────────────────────

def test_une_proposition_nait_en_attente_de_decision(db, directeur):
    c = _creer(db, directeur)
    assert c["statut"] == "recommandee"
    assert c["ouverte"] is True
    assert c["prochain_geste"] == "Valider ou refuser"
    assert c["delai_livraison_j"] is None


def test_le_parcours_complet_produit_un_delai_de_livraison(db, directeur):
    """Le cœur du chantier : commande → réception = la donnée que l'ERP n'a pas."""
    c = _creer(db, directeur)
    c = svc.decider(db, directeur, c["id"], valide=True)
    assert c["statut"] == "validee"

    c = svc.passer_commande(db, directeur, c["id"])
    assert c["statut"] == "commandee"
    assert c["commande_at"] is not None

    c = svc.receptionner(db, directeur, c["id"], qte_recue=180)
    assert c["statut"] == "recue"
    assert c["recue_at"] is not None
    assert c["qte_recue"] == 180
    assert c["delai_livraison_j"] is not None, (
        "commande et réception existent : le délai doit être calculable")
    assert c["delai_livraison_j"] >= 0
    assert c["ouverte"] is False


def test_une_commande_ne_se_recoit_pas_sans_avoir_ete_passee(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    with pytest.raises(Conflit) as e:
        svc.receptionner(db, directeur, c["id"])
    assert "ne peut pas passer" in str(e.value.detail)


def test_un_refus_est_definitif(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=False, motif_refus="Stock encore suffisant")
    for geste in (lambda: svc.decider(db, directeur, c["id"], valide=True),
                  lambda: svc.passer_commande(db, directeur, c["id"])):
        with pytest.raises(Conflit):
            geste()


def test_un_refus_exige_son_motif(db, directeur):
    """Sans motif, l'analyse ne peut rien apprendre de ce refus."""
    c = _creer(db, directeur)
    with pytest.raises(DonneesInvalides):
        svc.decider(db, directeur, c["id"], valide=False, motif_refus="   ")


def test_le_message_de_refus_nomme_les_transitions_possibles(db, directeur):
    """Un message qui dit seulement « interdit » oblige à lire le code."""
    c = _creer(db, directeur)
    with pytest.raises(Conflit) as e:
        svc.receptionner(db, directeur, c["id"])
    assert "Transitions possibles" in str(e.value.detail)


def test_une_reference_n_a_qu_une_commande_ouverte_a_la_fois(db, directeur):
    """Sinon le directeur revoit chaque matin la ligne validée la veille."""
    _creer(db, directeur)
    with pytest.raises(Conflit) as e:
        _creer(db, directeur)
    assert "déjà en cours" in str(e.value.detail)


def test_une_reference_refusee_peut_etre_reproposee_plus_tard(db, directeur):
    """Un refus ferme la commande : la référence redevient disponible."""
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=False, motif_refus="Pas maintenant")
    nouvelle = _creer(db, directeur)
    assert nouvelle["statut"] == "recommandee"


def test_une_commande_inconnue_est_introuvable(db, directeur):
    with pytest.raises(Introuvable):
        svc.decider(db, directeur, 999_999, valide=True)


def test_la_quantite_recue_ne_peut_pas_etre_negative(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    svc.passer_commande(db, directeur, c["id"])
    with pytest.raises(DonneesInvalides):
        svc.receptionner(db, directeur, c["id"], qte_recue=-5)


def test_sans_quantite_saisie_la_reception_vaut_la_quantite_commandee(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    svc.passer_commande(db, directeur, c["id"])
    c = svc.receptionner(db, directeur, c["id"])
    assert c["qte_recue"] == PROPOSITION["qte_proposee"]


def test_la_table_des_transitions_ne_boucle_pas(db):
    """Les états terminaux ne mènent nulle part : le cycle a une fin."""
    for terminal in ("refusee", "recue", "annulee"):
        assert COMMANDE_TRANSITIONS[terminal] == ()
    for ouvert in COMMANDE_OUVERTS:
        assert COMMANDE_TRANSITIONS[ouvert], f"{ouvert} est une impasse"


# ── L'histoire ───────────────────────────────────────────────────────────────

def test_chaque_transition_laisse_une_trace(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    svc.passer_commande(db, directeur, c["id"])
    svc.receptionner(db, directeur, c["id"])

    h = svc.histoire(db, c["id"])
    assert [e["vers"] for e in h] == ["recommandee", "validee", "commandee", "recue"]
    assert all(e["par"] == DIRECTEUR[0] for e in h)
    assert h[1]["de"] == "recommandee"


def test_le_motif_de_refus_est_conserve(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=False,
                motif_refus="Le produit sort du catalogue")
    rouvert = svc.lister(db)[0]
    assert rouvert["motif_refus"] == "Le produit sort du catalogue"


# ── Le bilan, et la donnée produite ──────────────────────────────────────────

def test_sans_reception_le_delai_est_declare_non_mesurable(db, directeur):
    """Afficher un zéro le ferait passer pour une mesure."""
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    svc.passer_commande(db, directeur, c["id"])

    d = svc.bilan(db)["delai_livraison"]
    assert d["mesurable"] is False
    assert d["median_j"] is None
    assert d["motif_si_absent"]


def test_le_delai_devient_mesurable_des_la_premiere_reception(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    svc.passer_commande(db, directeur, c["id"])
    svc.receptionner(db, directeur, c["id"])

    d = svc.bilan(db)["delai_livraison"]
    assert d["mesurable"] is True
    assert d["n_receptions"] == 1
    assert d["median_j"] is not None
    assert d["motif_si_absent"] is None

    # Ce que l'origine doit DIRE, et non la phrase exacte qui le dit : le délai
    # naît des saisies de la plateforme et ne se trouve dans aucun export ERP.
    # C'est l'argument qui justifie la boucle d'action — une donnée que
    # l'entreprise ne possédait pas avant. Tester la formulation mot pour mot
    # faisait échouer ce test à la première reformulation, sans qu'aucun
    # comportement n'ait changé.
    origine = d["origine"].lower()
    assert "date de commande" in origine and "date de réception" in origine
    assert "saisies" in origine
    assert "n'existe" in origine


def test_le_montant_engage_ne_compte_que_ce_qui_n_est_pas_recu(db, directeur):
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    assert svc.bilan(db)["montant_engage_dt"] == PROPOSITION["montant_estime_dt"]

    svc.passer_commande(db, directeur, c["id"])
    assert svc.bilan(db)["montant_engage_dt"] == PROPOSITION["montant_estime_dt"]

    svc.receptionner(db, directeur, c["id"])
    assert svc.bilan(db)["montant_engage_dt"] == 0


def test_une_reference_deja_decidee_n_est_plus_proposee(db, directeur):
    """La liste de propositions ne doit pas reproposer ce qui est traité."""
    avant = svc.recommandations(db)
    if not avant.get("servi"):
        pytest.skip(f"analyse indisponible : {avant.get('motif')}")
    if not avant["propositions"]:
        pytest.skip("aucune proposition sur ce jeu de données")

    p = avant["propositions"][0]
    svc.creer(db, directeur, {
        "reference": p["reference"], "designation": p["designation"],
        "qte_proposee": p.get("qte_proposee") or 0,
        "montant_estime_dt": p.get("montant_estime_dt") or 0,
    })

    apres = svc.recommandations(db)
    refs = {x["reference"] for x in apres["propositions"]}
    assert p["reference"] not in refs
    assert apres["n_deja_traitees"] >= 1


# ── La délégation : le directeur décide, l'équipe exécute ────────────────────

def test_valider_confie_l_execution_a_la_logistique(db, directeur, logisticien):
    """Le directeur occupe une position de décision, pas de saisie.

    Valider un réassort doit faire partir le travail d'exécution — passer la
    commande, suivre la livraison, saisir la réception — vers l'employé
    logistique, sur son écran."""
    c = _creer(db, directeur)
    vue = svc.decider(db, directeur, c["id"], valide=True)
    assert vue["confie_a"] == logisticien.full_name

    tache = db.query(Tache).filter(
        Tache.origine_titre == f"commande-{c['id']}").first()
    assert tache is not None, "aucune tâche créée pour l'équipe"
    assert tache.assigne_id == logisticien.id
    assert tache.type == "commande"
    assert tache.statut in STATUTS_OUVERTS
    assert tache.origine_categorie == "Approvisionnement"
    assert PROPOSITION["designation"] in tache.titre


def test_la_tache_porte_le_motif_et_le_geste_attendu(db, directeur, logisticien):
    """L'employé reçoit de quoi agir sans revenir demander."""
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)
    tache = db.query(Tache).filter(
        Tache.origine_titre == f"commande-{c['id']}").first()
    assert PROPOSITION["motif"][:30] in (tache.details or "")
    assert "réception" in (tache.details or "").lower()
    assert tache.montant_dt == PROPOSITION["montant_estime_dt"]


def test_refuser_ne_confie_rien(db, directeur):
    """Un refus arrête la chaîne : personne n'a de travail à faire."""
    c = _creer(db, directeur)
    vue = svc.decider(db, directeur, c["id"], valide=False, motif_refus="Stock suffisant")
    assert vue["confie_a"] is None
    assert db.query(Tache).filter(
        Tache.origine_titre == f"commande-{c['id']}").first() is None


def test_l_employe_peut_faire_avancer_la_commande(db, directeur, logisticien):
    """Les gestes d'exécution appartiennent à celui qui les fait."""
    c = _creer(db, directeur)
    svc.decider(db, directeur, c["id"], valide=True)

    c = svc.passer_commande(db, logisticien, c["id"])
    assert c["statut"] == "commandee"
    c = svc.receptionner(db, logisticien, c["id"], qte_recue=150)
    assert c["statut"] == "recue"
    assert c["delai_livraison_j"] is not None

    # L'histoire garde qui a fait quoi : la décision et l'exécution ne sont
    # pas du même ressort, elles ne doivent pas se confondre.
    h = svc.histoire(db, c["id"])
    par = {e["vers"]: e["par"] for e in h}
    assert par["validee"] == DIRECTEUR[0]
    assert par["commandee"] == LOGISTICIEN[0]
    assert par["recue"] == LOGISTICIEN[0]


def test_sans_equipe_logistique_la_decision_tient_quand_meme(db, directeur,
                                                             logisticien):
    """Un défaut d'affectation ne doit pas défaire la décision du directeur."""
    logisticien.poste = "recouvrement"   # plus personne en logistique
    db.commit()
    try:
        c = _creer(db, directeur)
        vue = svc.decider(db, directeur, c["id"], valide=True)
        assert vue["statut"] == "validee", "la décision doit survivre"
        assert vue["confie_a"] is None
    finally:
        logisticien.poste = "logistique"
        db.commit()


def test_la_liste_filtre_sur_les_commandes_ouvertes(db, directeur):
    a = _creer(db, directeur)
    b = svc.creer(db, directeur, {**PROPOSITION, "reference": "30411"})
    svc.decider(db, directeur, b["id"], valide=False, motif_refus="Non")

    ouvertes = svc.lister(db, statut="ouvertes")
    assert [c["id"] for c in ouvertes] == [a["id"]]
    assert len(svc.lister(db)) == 2
