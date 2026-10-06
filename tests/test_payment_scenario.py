"""Tests du module de scénarios d'encaissement."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from ml_engine.analytics.payment_scenario import (AVERTISSEMENT, SCENARIOS,
                                                  PaymentScenario,
                                                  compute_scenarios)

STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "output", "analytics_store.duckdb")
besoin_entrepot = pytest.mark.skipif(not os.path.exists(STORE),
                                     reason="entrepôt DuckDB absent")


def test_dso_simule_formule():
    """DSO simulé = délai accordé + retard × part concernée."""
    sc = PaymentScenario("Test", retard_moyen_jours=30, part_en_retard_pct=20.0)
    assert sc.dso_reel_estime(44.0) == pytest.approx(50.0)


def test_scenario_sans_retard_ne_change_rien():
    sc = PaymentScenario("Parfait", 0, 100.0)
    assert sc.dso_reel_estime(44.0) == 44.0


def test_scenario_tout_le_monde_en_retard():
    sc = PaymentScenario("Total", 60, 100.0)
    assert sc.dso_reel_estime(40.0) == 100.0


def test_scenarios_par_defaut_ordonnes():
    """Optimiste < Central < Pessimiste, par construction."""
    d = 44.0
    o = SCENARIOS["optimiste"].dso_reel_estime(d)
    c = SCENARIOS["central"].dso_reel_estime(d)
    p = SCENARIOS["pessimiste"].dso_reel_estime(d)
    assert o <= c < p


def test_avertissement_explicite():
    """L'avertissement doit dire que ce n'est PAS une prédiction."""
    a = AVERTISSEMENT.upper()
    assert "HYPOTHÈSE" in a or "HYPOTHESE" in a
    assert "PAS UNE PRÉDICTION" in a or "PAS UNE PREDICTION" in a


def test_chaque_scenario_porte_son_hypothese():
    """Aucun chiffre ne doit être renvoyé sans l'hypothèse qui le produit."""
    sc = SCENARIOS["central"]
    assert sc.description and sc.retard_moyen_jours and sc.part_en_retard_pct


@besoin_entrepot
def test_sortie_contient_avertissement_et_champs_manquants():
    res = compute_scenarios({})
    assert res.get("avertissement"), "l'avertissement doit accompagner les résultats"
    assert "REG" in (res.get("donnees_manquantes") or []), \
        "les champs ERP manquants doivent être nommés"
    for s in res["scenarios"]:
        assert s["hypothese"], "chaque scénario expose son hypothèse"


@besoin_entrepot
def test_calcul_sur_donnees_reelles():
    res = compute_scenarios({})
    assert not res.get("error")
    assert len(res["scenarios"]) == 3
    assert res["dso_accorde_jours"] > 0
    for s in res["scenarios"]:
        assert s["dso_simule_jours"] >= s["dso_accorde_jours"]
        assert s["encours_estime_dt"] >= 0


@besoin_entrepot
def test_monotonie_des_scenarios():
    """Plus l'hypothèse est dure, plus le DSO et l'encours augmentent."""
    res = compute_scenarios({})
    par_nom = {s["scenario"]: s for s in res["scenarios"]}
    assert par_nom["Optimiste"]["dso_simule_jours"] <= par_nom["Central"]["dso_simule_jours"]
    assert par_nom["Central"]["dso_simule_jours"] < par_nom["Pessimiste"]["dso_simule_jours"]
    assert par_nom["Central"]["encours_estime_dt"] <= par_nom["Pessimiste"]["encours_estime_dt"]


@besoin_entrepot
def test_date_observation_est_la_derniere_facture():
    """Volontairement pas max(echeance) : une échéance isolée fausserait tout."""
    import duckdb
    con = duckdb.connect(STORE, read_only=True)
    last_invoice = con.execute("SELECT max(date) FROM sales").fetchone()[0]
    last_due = con.execute("SELECT max(echeance) FROM sales").fetchone()[0]
    con.close()
    res = compute_scenarios({})
    assert res["date_observation"] == last_invoice.isoformat()
    if last_due and last_due != last_invoice:
        assert res["date_observation"] != last_due.isoformat()


@besoin_entrepot
def test_scenario_personnalise():
    sc = PaymentScenario("Sur mesure", 15, 50.0, "Hypothèse du directeur financier")
    res = compute_scenarios({}, scenario_custom=sc)
    assert len(res["scenarios"]) == 1
    s = res["scenarios"][0]
    assert s["scenario"] == "Sur mesure"
    assert s["surcout_dso_jours"] == pytest.approx(7.5, abs=0.1)


@besoin_entrepot
def test_perimetre_client_respecte():
    """Un filtre client réduit le périmètre (isolation multi-comptes)."""
    global_res = compute_scenarios({})
    import duckdb
    con = duckdb.connect(STORE, read_only=True)
    code = con.execute("SELECT client FROM sales WHERE client IS NOT NULL "
                       "GROUP BY client ORDER BY sum(ttc) DESC LIMIT 1").fetchone()[0]
    con.close()
    client_res = compute_scenarios({"selected_clients": [code]})
    assert client_res["n_factures_avec_echeance"] < global_res["n_factures_avec_echeance"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
