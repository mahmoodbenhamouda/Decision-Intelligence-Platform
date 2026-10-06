"""Période de référence des indicateurs : les 12 derniers mois par défaut.

Un directeur ouvre son tableau de bord pour savoir où il en est maintenant ; un
chiffre d'affaires cumulé depuis 2017 ne répond pas à cette question."""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.analytics.kpi_engine import STORE_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(not STORE_PATH.exists(), reason="entrepot DuckDB absent")


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(str(STORE_PATH), read_only=True)
    yield c
    c.close()


@pytest.fixture(scope="module")
def tableaux():
    from ml_engine.analytics.kpi_engine import compute_dashboard
    return {p: compute_dashboard({} if p == "defaut" else {"periode": p})
            for p in ("defaut", "12m", "annee", "tout")}


@pytest.mark.vitrine
def test_le_defaut_est_les_12_derniers_mois(tableaux, con):
    k = tableaux["defaut"]
    p = k["periode_reference"]
    assert p["code"] == "12m"
    fin = con.execute("SELECT max(date) FROM sales").fetchone()[0]
    assert p["fin"] == fin.isoformat()
    debut = date.fromisoformat(p["debut"])
    assert 364 <= (fin - debut).days <= 365, "une fenêtre de 12 mois exactement"
    attendu = con.execute("SELECT sum(ttc) FROM sales WHERE date BETWEEN ? AND ?",
                          [debut, fin]).fetchone()[0]
    assert k["ca_total_ttc"] == pytest.approx(float(attendu), rel=1e-9)


def test_le_cumul_n_est_plus_le_defaut(tableaux):
    assert tableaux["defaut"]["ca_total_ttc"] < tableaux["tout"]["ca_total_ttc"]
    assert tableaux["defaut"]["nb_clients"] < tableaux["tout"]["nb_clients"], (
        "« clients actifs » ne doit plus compter un client parti en 2018")


def test_l_evolution_compare_des_periodes_de_meme_longueur(tableaux, con):
    p = tableaux["defaut"]["periode_reference"]
    prec = con.execute("SELECT sum(ttc) FROM sales WHERE date BETWEEN ? AND ?",
                       [p["comparaison_debut"], p["comparaison_fin"]]).fetchone()[0]
    assert p["ca_precedent_dt"] == round(float(prec), 0)
    attendu = (tableaux["defaut"]["ca_total_ttc"] - float(prec)) / float(prec) * 100
    assert p["evolution_pct"] == pytest.approx(attendu)


def test_l_annee_en_cours_commence_au_premier_janvier(tableaux):
    p = tableaux["annee"]["periode_reference"]
    assert p["debut"].endswith("-01-01") and p["debut"][:4] == p["fin"][:4]


def test_les_series_d_evolution_gardent_tout_l_historique(tableaux):
    """La tendance se lit sur plusieurs années, même quand les chiffres portent sur 12 mois."""
    assert tableaux["defaut"]["monthly_sales"] == tableaux["tout"]["monthly_sales"]
    assert tableaux["defaut"]["yoy_comparison"] == tableaux["tout"]["yoy_comparison"]


def test_une_annee_choisie_prime_sur_le_defaut():
    from ml_engine.analytics.kpi_engine import compute_dashboard
    k = compute_dashboard({"selected_years": [2024]})
    assert k["periode_reference"]["code"] == "personnalisee"
    assert all(m["period"].startswith("2024") for m in k["monthly_sales"])


def test_la_periode_par_defaut_ne_masque_pas_les_previsions():
    """Seule une période passée choisie à la main masque les prévisions."""
    from ml_engine import portee as po
    for p in ("12m", "annee", "tout"):
        assert po.portee({"periode": p})["mode"] == po.GLOBAL
    assert po.portee({"periode": "12m", "selected_years": [2023]})["mode"] == po.MASQUE
