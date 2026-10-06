"""Les délais de paiement doivent dire leur sens, leur base et leur nature.

Trois pièges que ce bloc évite, et que le chiffre seul ne pouvait pas éviter :

  * le SENS — « délai moyen » ne disait pas qui attend qui ;
  * la PONDÉRATION — une moyenne par facture compte 500 DT comme 500 000 DT ;
  * la NATURE — l'ERP ne porte aucune date de règlement, donc aucun retard
    réel n'est mesurable : seul le délai ACCORDÉ l'est.
"""

from __future__ import annotations

import pytest

from ml_engine.analytics.kpi_engine import compute_dashboard

TOUT = {"periode": "tout"}


@pytest.fixture(scope="module")
def delais():
    k = compute_dashboard(TOUT)
    d = k.get("delais")
    if not d:
        pytest.skip("bloc délais absent")
    return d


def test_les_deux_sens_sont_nommes_sans_ambiguite(delais):
    """Le mot « clients » et le mot « fournisseurs » doivent apparaître dans
    la description de chaque sens, sinon l'ambiguïté reste entière."""
    assert "client" in delais["accorde_aux_clients"]["sens"].lower()
    assert "fournisseur" in delais["obtenu_des_fournisseurs"]["sens"].lower()


def test_la_moyenne_ponderee_et_la_moyenne_simple_sont_toutes_deux_publiees(delais):
    for sens in ("accorde_aux_clients", "obtenu_des_fournisseurs"):
        bloc = delais[sens]
        assert bloc["moyenne_ponderee_j"] >= 0
        assert bloc["moyenne_par_facture_j"] >= 0
        assert bloc["n_factures"] > 0, f"{sens} sans base de calcul"
        assert bloc["montant_dt"] != 0


def test_l_ecart_est_la_difference_des_moyennes_ponderees(delais):
    attendu = (delais["accorde_aux_clients"]["moyenne_ponderee_j"]
               - delais["obtenu_des_fournisseurs"]["moyenne_ponderee_j"])
    assert abs(delais["ecart_j"] - attendu) < 0.2


def test_le_libelle_de_tresorerie_suit_le_signe_de_l_ecart(delais):
    """Un montant négatif sous « trésorerie immobilisée » se lirait à
    contresens : le libellé doit basculer avec le signe."""
    libelle = delais["tresorerie_cycle_libelle"].lower()
    if delais["ecart_j"] > 0:
        assert "overlyne" in libelle
    else:
        assert "fournisseur" in libelle


def test_la_repartition_somme_a_cent_pour_cent(delais):
    parts = [t["part_pct"] for t in delais["repartition"] if t["part_pct"] is not None]
    assert parts, "aucune tranche renseignée"
    assert abs(sum(parts) - 100) < 0.5


def test_chaque_tranche_porte_son_montant_et_sa_signification(delais):
    for t in delais["repartition"]:
        assert t["tranche"]
        assert t["signification"], f"{t['code']} sans explication"
        assert t["montant_dt"] >= 0
        assert t["n_factures"] >= 0


def test_la_part_au_dela_du_seuil_correspond_aux_tranches_concernees(delais):
    tranches = {t["code"]: (t["part_pct"] or 0) for t in delais["repartition"]}
    attendu = tranches.get("j90", 0) + tranches.get("j90p", 0)
    assert abs(delais["part_au_dela_du_seuil_pct"] - attendu) < 0.5


def test_la_nature_du_chiffre_est_declaree_et_le_malentendu_ecarte(delais):
    """Le point le plus important : le tableau de bord doit dire lui-même que
    ce n'est PAS un retard de paiement."""
    assert "accordé" in delais["nature"].lower()
    nie = delais["ce_n_est_pas"].lower()
    assert "retard" in nie
    assert "règlement" in nie or "reglement" in nie


def test_un_filtre_de_periode_restreint_la_base(delais):
    douze = compute_dashboard({})["delais"]
    assert (douze["accorde_aux_clients"]["n_factures"]
            <= delais["accorde_aux_clients"]["n_factures"])


def test_la_moyenne_ponderee_differe_de_la_simple_cote_fournisseurs(delais):
    """Sur ce jeu de données, les grosses factures d'achat portent des délais
    bien plus longs : c'est précisément ce que la moyenne simple cachait. Si
    les deux lectures devenaient identiques, la pondération serait inutile."""
    bloc = delais["obtenu_des_fournisseurs"]
    assert abs(bloc["moyenne_ponderee_j"] - bloc["moyenne_par_facture_j"]) > 1.0
