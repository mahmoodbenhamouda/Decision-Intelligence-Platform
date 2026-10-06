"""Non-regression sur l'integrite du chiffre d'affaires."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.analytics.kpi_engine import STORE_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(
    not STORE_PATH.exists(), reason="entrepot DuckDB absent")

CA_NET_ATTENDU = 274_696_489.0
CA_AVANT_CORRECTION = 290_506_268.0
N_AVOIRS = 5_761
TTC_AVOIRS = 7_377_921.0
N_DOUBLONS_SUPPRIMES = 1_324
TOLERANCE = 50_000.0


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(str(STORE_PATH), read_only=True)
    yield c
    c.close()


def test_colonnes_de_tracabilite_presentes(con):
    """Sans `ent_id` ni `piece_no`, un doublon est indiscernable de deux ventes identiques legitimes —…"""
    cols = {d[0] for d in con.execute("DESCRIBE sales").fetchall()}
    for attendue in ("ent_id", "piece_no", "est_avoir"):
        assert attendue in cols, f"colonne `{attendue}` absente de sales"


@pytest.mark.vitrine
def test_ca_net_conforme_a_l_audit(con):
    ca = con.execute("SELECT sum(ttc) FROM sales").fetchone()[0]
    assert ca == pytest.approx(CA_NET_ATTENDU, abs=TOLERANCE), (
        f"CA = {ca:,.0f} DT, attendu {CA_NET_ATTENDU:,.0f} DT. "
        "Le signe des avoirs ou la deduplication a saute.")


def test_le_ca_brut_d_avant_n_est_plus_atteint(con):
    """Garde-fou explicite contre un retour a la somme non signee."""
    ca = con.execute("SELECT sum(ttc) FROM sales").fetchone()[0]
    assert ca < CA_AVANT_CORRECTION - 10_000_000, (
        "Le CA est revenu au niveau d'avant correction : les avoirs sont "
        "probablement recomptes en positif.")


def test_les_avoirs_sont_negatifs(con):
    n, somme = con.execute(
        "SELECT count(*), sum(ttc) FROM sales WHERE est_avoir").fetchone()
    assert n == pytest.approx(N_AVOIRS, abs=50)
    assert somme < 0, "un avoir doit peser negativement dans le CA"
    assert abs(somme) == pytest.approx(TTC_AVOIRS, abs=TOLERANCE)


def test_aucune_vente_n_est_negative(con):
    """Seuls les avoirs portent un montant negatif."""
    n = con.execute(
        "SELECT count(*) FROM sales WHERE ttc < 0 AND NOT est_avoir").fetchone()[0]
    assert n == 0


def test_plus_aucun_doublon_de_numero_de_piece(con):
    reste = con.execute("""
        SELECT count(*) FROM (
            SELECT 1 FROM sales
            WHERE piece_no IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, client, date, ttc HAVING count(*) > 1
        )
    """).fetchone()[0]
    assert reste == 0, f"{reste} groupe(s) de factures encore en double"


def test_le_nombre_de_lignes_a_bien_diminue(con):
    n = con.execute("SELECT count(*) FROM sales").fetchone()[0]
    assert n == pytest.approx(128_848 - N_DOUBLONS_SUPPRIMES, abs=50)


def test_un_avoir_n_est_pas_compte_comme_une_facture():
    """Le panier moyen divisait un CA net par un nombre de pieces brut."""
    from ml_engine.analytics.kpi_engine import compute_dashboard
    k = compute_dashboard({"periode": "tout"})
    assert k["nb_avoirs"] > 0
    assert k["nb_factures_vente"] + k["nb_avoirs"] == pytest.approx(
        con_lignes(), abs=50)
    attendu = k["ca_total_ttc"] / k["nb_factures_vente"]
    assert k["panier_moyen"] == pytest.approx(attendu, rel=1e-6)


def con_lignes() -> int:
    import duckdb
    c = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        return c.execute("SELECT count(*) FROM sales").fetchone()[0]
    finally:
        c.close()


def test_exposition_au_recouvrement_exclut_les_avoirs():
    from ml_engine.analytics.kpi_engine import compute_dashboard
    k = compute_dashboard({"periode": "tout"})
    assert k["montant_delai_sup_60j_ttc"] >= 0
    assert k["montant_delai_sup_90j_ttc"] >= 0
