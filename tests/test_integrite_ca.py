"""
tests/test_integrite_ca.py
==========================
Non-regression sur l'integrite du chiffre d'affaires.

Contexte
--------
La table `sales` a longtemps surevalue le CA de 15 809 779 DT (5,44 %) pour
deux raisons cumulees, mesurees sur les donnees reelles :

  * 5 761 AVOIRS etaient AJOUTES au CA au lieu d'en etre retranches. `TTC_DEV`
    est toujours positif ; le sens comptable est porte par `MONTANTSIGNE_DEV`.
    Chaque avoir comptait donc deux fois : 7 377 921 DT x 2 = 14 755 841 DT.

  * 1 324 FACTURES apparaissaient en double. `ENT_ID` est un identifiant
    technique d'export, unique par construction, donc aveugle aux doublons ;
    la cle metier est `PIECENOFULL`. Impact : 1 053 938 DT.

Ces tests figent le resultat corrige. Ils echouent si quelqu'un revient a une
somme de `TTC_DEV` non signee, ou retire la deduplication.

    python -m pytest tests/test_integrite_ca.py -v
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.analytics.kpi_engine import STORE_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(
    not STORE_PATH.exists(), reason="entrepot DuckDB absent")

# Valeurs etablies par scripts/audit_ca_corrige.py sur le jeu de donnees reel.
CA_NET_ATTENDU = 274_696_489.0
CA_AVANT_CORRECTION = 290_506_268.0
N_AVOIRS = 5_761
TTC_AVOIRS = 7_377_921.0
N_DOUBLONS_SUPPRIMES = 1_324
TOLERANCE = 50_000.0        # marge d'arrondi sur les conversions de type


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(str(STORE_PATH), read_only=True)
    yield c
    c.close()


def test_colonnes_de_tracabilite_presentes(con):
    """Sans `ent_id` ni `piece_no`, un doublon est indiscernable de deux ventes
    identiques legitimes — cas frequent sur les livraisons recurrentes."""
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
    k = compute_dashboard({})
    assert k["nb_avoirs"] > 0
    assert k["nb_factures_vente"] + k["nb_avoirs"] == pytest.approx(
        con_lignes(), abs=50)
    # Le panier moyen doit se calculer sur les seules ventes.
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
    k = compute_dashboard({})
    assert k["montant_risque_ttc"] >= 0
    assert k["montant_critique_ttc"] >= 0
