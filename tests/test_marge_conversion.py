"""
tests/test_marge_conversion.py
==============================
Tests des deux limites RÉSOLUES par l'exploration des données :

1. MARGE RÉELLE par client — le coût de revient ERP (`MTCRSIGNE`) est présent
   sur les lignes de vente. La marge devient donc attribuable au client, là où
   l'approximation « CA HT − achats TTC » ne l'était pas (et donnait 77 %).

2. TAUX DE CONVERSION RÉEL — le statut ERP du devis (`ETATPIECE = '8'`) indique
   la transformation en facture. Interprétation validée empiriquement.

Exécution :
    python -m pytest tests/test_marge_conversion.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from ml_engine.analytics.kpi_engine import STORE_PATH, compute_dashboard

besoin_entrepot = pytest.mark.skipif(not os.path.exists(str(STORE_PATH)),
                                     reason="entrepôt DuckDB absent")


# ── 1. Marge réelle ─────────────────────────────────────────────────────────
@besoin_entrepot
def test_marge_globale_plausible():
    """Un distributeur de matériel médical marge entre 10 % et 45 %.
    L'ancienne formule donnait 77 % — invraisemblable."""
    k = compute_dashboard({})
    assert k["marge_source"] == "cout_revient_erp"
    assert 10 < k["taux_marge"] < 45, f"taux de marge implausible : {k['taux_marge']}"


@besoin_entrepot
def test_marge_est_attribuable_par_client():
    """LE point corrigé : la marge existe désormais en vue client."""
    k = compute_dashboard({"selected_clients": ["CE000016"]})
    assert k["marge_brute"] is not None, "la marge doit être attribuable au client"
    assert k["taux_marge"] is not None
    assert 0 < k["taux_marge"] < 60


@besoin_entrepot
def test_coherence_marge_ca_cout():
    """marge = CA des lignes − coût de revient, exactement."""
    k = compute_dashboard({})
    assert k["marge_brute"] == pytest.approx(
        k["marge_ca_reference_dt"] - k["marge_cout_revient_dt"], abs=1.0)


@besoin_entrepot
def test_qualite_nettoyage_signalee():
    """Le nettoyage des aberrations doit être transparent et rester marginal."""
    k = compute_dashboard({})
    assert "marge_lignes_exclues" in k
    assert k["marge_lignes_exclues_pct"] < 1.0, \
        "si plus de 1 % des lignes sont exclues, le seuil est à revoir"


@besoin_entrepot
def test_marge_mensuelle_alignee():
    k = compute_dashboard({})
    assert k["monthly_margin"], "la marge mensuelle doit être calculée"
    assert len(k["monthly_margin"]) == len(k["monthly_sales"])


@besoin_entrepot
def test_waterfall_sur_marge_reelle():
    k = compute_dashboard({})
    steps = {w["step"]: w["value"] for w in k["waterfall"]}
    assert "Coût de revient" in steps
    assert steps["Coût de revient"] < 0        # présenté en négatif
    assert steps["Marge brute"] == pytest.approx(k["marge_brute"], abs=1.0)


@besoin_entrepot
def test_somme_des_marges_clients_coherente():
    """La marge globale doit être proche de la somme des marges par client."""
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    total = con.execute("SELECT sum(marge) FROM client_margin").fetchone()[0]
    con.close()
    k = compute_dashboard({})
    assert float(total) == pytest.approx(k["marge_brute"], rel=0.01)


# ── 2. Taux de conversion des devis ─────────────────────────────────────────
@besoin_entrepot
def test_conversion_basee_sur_statut_erp():
    k = compute_dashboard({})
    assert k["taux_conversion_source"] == "etat_piece_erp"
    assert k["devis_transformes"] > 0


@besoin_entrepot
def test_conversion_coherente_avec_le_nombre_de_devis():
    k = compute_dashboard({})
    attendu = k["devis_transformes"] / k["nb_devis"] * 100
    assert k["taux_conversion_devis"] == pytest.approx(attendu, abs=0.01)
    assert 0 <= k["taux_conversion_devis"] <= 100


@besoin_entrepot
def test_conversion_plus_realiste_qu_avant():
    """L'ancienne heuristique donnait ~95 % (tout client ayant facturé).
    Le taux réel de transformation de devis est bien plus bas."""
    k = compute_dashboard({})
    assert k["taux_conversion_devis"] < 50, \
        "un taux > 50 % signalerait un retour à l'ancienne heuristique"


@besoin_entrepot
def test_hypothese_etat_8_reste_valide():
    """Re-vérifie l'interprétation ETATPIECE=8 : les devis transformés doivent
    s'apparier à une facture bien plus souvent que les autres."""
    import duckdb
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    r = con.execute("""
        SELECT
          sum(CASE WHEN d.transforme AND EXISTS (
              SELECT 1 FROM sales s WHERE s.client = d.client
              AND abs(s.ttc - d.ttc) <= 0.01 * d.ttc) THEN 1 ELSE 0 END) AS t_ok,
          count(*) FILTER (WHERE d.transforme)                            AS t_n,
          sum(CASE WHEN NOT d.transforme AND EXISTS (
              SELECT 1 FROM sales s WHERE s.client = d.client
              AND abs(s.ttc - d.ttc) <= 0.01 * d.ttc) THEN 1 ELSE 0 END) AS f_ok,
          count(*) FILTER (WHERE NOT d.transforme)                        AS f_n
        FROM devis d WHERE d.ttc > 0
    """).fetchone()
    con.close()
    taux_transf = r[0] / r[1] if r[1] else 0
    taux_autres = r[2] / r[3] if r[3] else 0
    assert taux_transf > 0.75, f"appariement trop faible pour l'état 8 : {taux_transf:.1%}"
    assert taux_transf > taux_autres * 1.5, \
        "l'état 8 doit s'apparier nettement mieux que les autres états"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
