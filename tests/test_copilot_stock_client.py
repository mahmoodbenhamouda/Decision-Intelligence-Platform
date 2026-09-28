"""
tests/test_copilot_stock_client.py
==================================
Deux défauts constatés en usage réel sur la question
« top 5 clients qui n'ont pas de risque sur le stock » :

1. Le copilote répondait « donnée non disponible » alors que chaque ligne de
   stock porte un client — l'information existait, rien ne l'agrégeait.
2. Il citait « exposition secteur public 30 396 136 DT », un montant qui ne
   correspond à AUCUN indicateur (exposition récente réelle : 11,2 M DT).

Ces tests verrouillent les deux corrections.

Exécution :
    python -m pytest tests/test_copilot_stock_client.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.copilote.intention import detect_theme
from agents.copilote.verification import _valeurs_numeriques, chiffres_non_sources
from ml_engine.stock import classer_clients_par_risque, stock_available

besoin_stock = pytest.mark.skipif(
    not stock_available(),
    reason="stock non généré — lancer `python -m ml_engine.stock.generator`")


# ── 1. Routage de la question ──────────────────────────────────────────────
@pytest.mark.parametrize("question", [
    "parle moi des top 5 client qui n'ont pas de rique sur le stock",
    "top 5 clients sans risque sur le stock",
    "quels clients n'ont pas de risque de stock ?",
    "quels sont mes clients les plus exposés au stock ?",
    "quels sont mes principaux clients en rupture de stock ?",
])
def test_question_client_et_stock_route_vers_le_bon_theme(question):
    """Une question qui classe des CLIENTS et parle de STOCK porte sur le
    croisement des deux. Sans ce thème, elle tombait sur `palmares` (via
    « top 5 ») ou `approvisionnement` (via « stock »), et la réponse parlait
    de chiffre d'affaires ou de fournisseurs."""
    assert "risque_stock_client" in detect_theme(question)


@pytest.mark.parametrize("question", [
    "quels sont mes top 5 clients ?",
    "quelle est ma dépendance fournisseur ?",
    "quels réactifs risquent de périmer ?",
])
def test_pas_de_declenchement_abusif(question):
    """Le thème croisé ne doit pas absorber les questions qui ne portent que
    sur les clients, que sur les fournisseurs, ou que sur les produits."""
    assert "risque_stock_client" not in detect_theme(question)


# ── 2. Agrégation du stock par client ──────────────────────────────────────
@besoin_stock
def test_agregation_par_client_est_exploitable():
    r = classer_clients_par_risque(limit=5)
    assert not r.get("error")
    assert r["n_clients_analyses"] > 0
    assert r["n_clients_sans_risque"] + r["n_clients_exposes"] == r["n_clients_analyses"]
    assert len(r["clients_sans_risque"]) <= 5
    assert len(r["top_par_valeur"]) <= 5


@besoin_stock
def test_un_client_sans_risque_n_a_aucune_reference_a_risque():
    """Définition stricte : ni rupture, ni surstock, ni à commander."""
    for c in classer_clients_par_risque(limit=20)["clients_sans_risque"]:
        assert c["n_rupture"] == 0 and c["n_surstock"] == 0 and c["n_a_commander"] == 0
        assert c["n_a_risque"] == 0
        assert c["n_sain"] == c["n_references"]
        assert c["part_saine_pct"] == 100.0


@besoin_stock
def test_comptages_coherents_par_client():
    """La somme des situations doit égaler le nombre de références."""
    r = classer_clients_par_risque(limit=10)
    for c in r["clients_sans_risque"] + r["top_par_valeur"] + r["clients_les_plus_exposes"]:
        assert (c["n_sain"] + c["n_rupture"] + c["n_surstock"]
                + c["n_a_commander"]) == c["n_references"]
        assert c["valeur_stock_dt"] >= 0
        assert c["n_references"] >= r["min_references"]


@besoin_stock
def test_seuil_de_references_ecarte_les_clients_non_significatifs():
    """Un client à une seule référence saine n'est pas un « client sans
    risque » : c'est un client sans données."""
    assert all(c["n_references"] >= 8
               for c in classer_clients_par_risque(limit=5, min_references=8)["top_par_valeur"])


@besoin_stock
def test_classement_par_valeur_decroissante():
    vals = [c["valeur_stock_dt"] for c in classer_clients_par_risque(limit=10)["top_par_valeur"]]
    assert vals == sorted(vals, reverse=True)


@besoin_stock
def test_resultat_reproductible():
    """Le tri départage les ex æquo : deux appels donnent le même classement."""
    a = classer_clients_par_risque(limit=5)
    b = classer_clients_par_risque(limit=5)
    assert [c["client"] for c in a["top_par_valeur"]] == [c["client"] for c in b["top_par_valeur"]]
    assert [c["client"] for c in a["clients_sans_risque"]] == \
           [c["client"] for c in b["clients_sans_risque"]]


@besoin_stock
def test_provenance_du_stock_reste_signalee():
    """Le stock est simulé : l'avertissement ne doit jamais disparaître."""
    r = classer_clients_par_risque()
    assert r["is_simulated"] is True
    assert "SIMUL" in r["avertissement"].upper()


@besoin_stock
def test_code_client_sans_libelle_est_marque_comme_tel():
    """Certains comptes n'ont aucun libellé dans l'ERP : le code est alors leur
    seul identifiant. L'affichage doit le dire au lieu de laisser croire à une
    donnée manquante."""
    tous = (classer_clients_par_risque(limit=50)["top_par_valeur"]
            + classer_clients_par_risque(limit=50)["clients_sans_risque"])
    for c in tous:
        assert c["code"]
        if not c["nom_resolu"]:
            assert c["client"] == c["code"]


# ── 3. Traçabilité des montants cités ──────────────────────────────────────
def test_montant_fabrique_est_detecte():
    """Le cas réel : 30 396 136 DT ne figure nulle part dans le contexte."""
    ctx = "Exposition récente >60j : 11.22 M DT\ndont critique : 2.83 M DT"
    assert chiffres_non_sources("exposition secteur public 30 396 136 DT", ctx)


def test_montant_fabrique_detecte_aussi_au_format_anglais():
    ctx = "Exposition récente >60j : 11.22 M DT"
    assert chiffres_non_sources("exposition **30,396,136 DT**", ctx)


def test_montant_du_contexte_est_accepte_quel_que_soit_le_format():
    """« 11.22 M DT » et « 11 218 990 DT » désignent la même valeur."""
    ctx = "Exposition récente >60j : 11.22 M DT sur 2614 factures"
    assert not chiffres_non_sources("**11 218 990 DT** en retard", ctx)
    assert not chiffres_non_sources("**11.22 M DT** en retard", ctx)


def test_somme_calculee_par_le_modele_est_rejetee():
    """Le modèle n'a pas le droit d'additionner lui-même les montants."""
    ctx = "Client A : 763.4 K DT\nClient B : 639.8 K DT"
    assert chiffres_non_sources("au total 1 403 200 DT exposés", ctx)


def test_annees_et_compteurs_ne_sont_pas_des_faux_positifs():
    """« En 2026, 2614 factures » ne doit pas être lu comme un montant."""
    ctx = "Exposition : 11.22 M DT sur 2614 factures, DSO 44 jours"
    assert not chiffres_non_sources("En 2026, 2614 factures, DSO 44 jours", ctx)


def test_lecture_des_echelles():
    vals = _valeurs_numeriques("11.22 M DT, 763.4 K DT, 2614 factures")
    assert pytest.approx(11_220_000, rel=1e-6) in vals
    assert pytest.approx(763_400, rel=1e-6) in vals
    assert 2614 in vals
