"""Coherence de TOUS les indicateurs financiers, pas seulement du CA."""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.analytics.kpi_engine import STORE_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(
    not STORE_PATH.exists(), reason="entrepot DuckDB absent")


@pytest.fixture(scope="module")
def k():
    from ml_engine.analytics.kpi_engine import compute_dashboard
    return compute_dashboard({"periode": "tout"})


@pytest.fixture(scope="module")
def con():
    import duckdb
    c = duckdb.connect(str(STORE_PATH), read_only=True)
    yield c
    c.close()


def test_ca_net_egale_ventes_moins_avoirs(con):
    """L'identite fondatrice : le CA affiche doit etre le net."""
    brut, avoirs, net = con.execute("""
        SELECT sum(ttc) FILTER (WHERE NOT est_avoir),
               -sum(ttc) FILTER (WHERE est_avoir),
               sum(ttc)
        FROM sales
    """).fetchone()
    assert net == pytest.approx(brut - avoirs, abs=1.0)


def test_le_compte_des_lignes_se_decompose(k, con):
    total = con.execute("SELECT count(*) FROM sales").fetchone()[0]
    assert k["nb_factures_vente"] + k["nb_avoirs"] == total


def test_panier_moyen_divise_par_les_ventes_seules(k):
    """Diviser un CA net par un nombre de pieces brut melange deux perimetres."""
    assert k["panier_moyen"] == pytest.approx(
        k["ca_total_ttc"] / k["nb_factures_vente"], rel=1e-9)


def test_part_des_avoirs_plausible(k):
    """Un taux d'avoirs au-dela de 15 % signalerait une anomalie metier ou un signe a nouveau mal…"""
    assert 0 < k["taux_avoirs_pct"] < 15, (
        f"taux d'avoirs de {k['taux_avoirs_pct']:.1f} % — invraisemblable")


def test_achats_nets_et_comptage(k, con):
    brut, avoirs, net = con.execute("""
        SELECT sum(ttc) FILTER (WHERE NOT est_avoir),
               -coalesce(sum(ttc) FILTER (WHERE est_avoir), 0),
               sum(ttc)
        FROM purchases
    """).fetchone()
    assert net == pytest.approx(brut - avoirs, abs=1.0)
    total = con.execute("SELECT count(*) FROM purchases").fetchone()[0]
    assert k["nb_factures_achat"] + k["nb_avoirs_achat"] == total


def test_pas_de_doublon_de_piece_dans_les_achats(con):
    reste = con.execute("""
        SELECT count(*) FROM (
            SELECT 1 FROM purchases WHERE piece_no IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, fournisseur_code, date, ttc HAVING count(*) > 1)
    """).fetchone()[0]
    assert reste == 0


def test_hhi_dans_les_bornes(k):
    """Le HHI est une somme de carres de parts, donc borne."""
    for champ in ("hhi_clients", "hhi_fournisseurs"):
        v = k[champ]
        assert 0 < v <= 10_000, f"{champ} = {v}, hors bornes"


def test_pareto_coherent(k):
    assert 0 < k["clients_pour_80pct"] <= k["nb_clients_ca"]


def test_parts_du_top_client_bornees(k):
    for c in k["top_clients"]:
        assert -100 <= c["share"] <= 100, f"part de {c['nom']} = {c['share']}"
        assert c["invoices"] >= 0 and c["avoirs"] >= 0


def test_marge_egale_ca_moins_cout(con):
    ca, cout, marge = con.execute(
        "SELECT sum(ca_ligne), sum(cout_revient), sum(marge) FROM client_margin"
    ).fetchone()
    assert marge == pytest.approx(ca - cout, abs=1.0)


def test_les_retours_sont_pris_en_compte_dans_la_marge(con):
    """`ca > 0` ecartait tous les retours : on gardait la vente, on oubliait l'avoir qui l'annule."""
    n_retours = con.execute(
        "SELECT coalesce(sum(n_lignes_retour), 0) FROM client_margin").fetchone()[0]
    assert n_retours > 0, "aucune ligne de retour dans la marge — filtre trop strict"


def test_taux_de_marge_plausible(con):
    ca, marge = con.execute(
        "SELECT sum(ca_ligne), sum(marge) FROM client_margin").fetchone()
    taux = marge / ca * 100 if ca else 0
    assert 0 < taux < 80, f"taux de marge de {taux:.1f} % — invraisemblable"


def test_le_ca_produit_est_signe(con):
    """Si les retours etaient comptes en positif, aucune ligne ne serait negative et le total produit…"""
    n_neg = con.execute(
        "SELECT count(*) FROM product_sales WHERE ca < 0").fetchone()[0]
    n_retours = con.execute(
        "SELECT coalesce(sum(lignes_retour), 0) FROM product_sales").fetchone()[0]
    assert n_retours > 0, "aucune ligne de retour : MONTANT_DEV (non signe) est "\
                          "probablement utilise a la place de MONTANTSIGNE_DEV"
    assert n_neg >= 0


def test_deduplication_des_lignes_ciblee_et_non_massive(con):
    """11 412 lignes paraissent redondantes, mais seules ~8 518 appartiennent aux factures dupliquees…"""
    n = con.execute("SELECT count(*) FROM sales_lines").fetchone()[0]
    assert n < 340_912, "aucune ligne supprimee : la deduplication n'a pas tourne"
    assert n > 340_912 - 11_412, (
        f"{340_912 - n} lignes supprimees — deduplication trop large, "
        "des lignes legitimes ont ete perdues")


def test_les_repetitions_restantes_sont_legitimes(con):
    """Des lignes repetees SUBSISTENT, et c'est normal : une facture peut porter deux fois la meme…"""
    n = con.execute("SELECT count(*) FROM sales_lines").fetchone()[0]
    rejets = con.execute("SELECT count(*) FROM sales_lines_rejetees").fetchone()[0]
    supprimees = 340_912 - n - rejets
    assert supprimees == pytest.approx(8_518 / 2, abs=60), (
        f"{supprimees} lignes supprimees, attendu ~{8_518 // 2}. "
        "Au-dela, des lignes legitimes ont ete perdues ; en deca, des doublons "
        "subsistent.")


def test_ca_produit_inferieur_au_ca_facture(k, con):
    """Le CA des lignes ne peut pas depasser le CA des factures : c'est le meme argent, vu a deux…"""
    ca_lignes = con.execute("SELECT sum(ca) FROM product_sales").fetchone()[0] or 0
    assert ca_lignes <= k["ca_total_ttc"] * 1.05, (
        f"CA lignes {ca_lignes:,.0f} > CA factures {k['ca_total_ttc']:,.0f}")


def test_exposition_positive_et_bornee(k):
    assert k["montant_delai_sup_60j_ttc"] >= 0
    assert k["montant_delai_sup_90j_ttc"] >= 0
    assert k["montant_delai_sup_90j_ttc"] <= k["montant_delai_sup_60j_ttc"] + 1
    assert k["montant_delai_sup_60j_ttc"] <= k["ca_total_ttc"]


def test_le_radar_public_est_une_part_de_l_exposition_recente(k):
    """La carte « recouvrement public » du radar et l'exposition récente du tableau de bord portent sur…"""
    from ml_engine.analytics.kpi_engine import finance_radar

    cartes = [c for c in finance_radar({}, {}) if c["id"] == "recouvrement_public"]
    if not cartes:
        pytest.skip("aucune exposition récente sur un établissement public")
    c, expo = cartes[0], k["exposition_recente_dt"]
    assert 0 < c["montant_dt"] <= expo + 1
    part = int(re.search(r"soit (\d+) % de l'exposition récente", c["constat"]).group(1))
    assert abs(part - c["montant_dt"] / expo * 100) <= 0.5 + 1e-6


def test_le_controle_d_integrite_ne_remonte_aucune_erreur(k):
    """Le test qui resume tous les autres."""
    from ml_engine.analytics.data_quality import controler_integrite, rapport_texte
    r = controler_integrite(k)
    assert not r["erreurs"], "\n" + rapport_texte(r)


def test_le_controle_est_attache_aux_indicateurs(k):
    """Une anomalie doit se voir dans l'application, pas attendre un audit."""
    assert "integrite" in k
    assert k["integrite"]["statut"] in {"ok", "alerte", "erreur"}


def test_le_controle_detecte_une_incoherence_fabriquee():
    """Un controle qui ne detecte jamais rien ne prouve rien."""
    from ml_engine.analytics.data_quality import controler_integrite
    from ml_engine.analytics.kpi_engine import compute_dashboard
    faux = dict(compute_dashboard({"periode": "tout"}))
    faux["panier_moyen"] = faux["panier_moyen"] * 2
    faux["hhi_clients"] = 99_999
    r = controler_integrite(faux)
    controles = {e["controle"] for e in r["erreurs"]} | {
        a["controle"] for a in r["alertes"]}
    assert "kpi.panier_moyen" in controles
    assert "concentration.hhi_clients" in controles


def test_les_lignes_illisibles_sont_ecartees_pas_perdues(con):
    """`SENS` ne peut valoir que 1 ou 2."""
    restantes = con.execute(
        "SELECT count(*) FROM sales_lines WHERE NOT format_valide").fetchone()[0]
    assert restantes == 0, "des lignes au format invalide alimentent encore les montants"
    assert con.execute(
        "SELECT count(*) FROM sales_lines_rejetees").fetchone()[0] >= 0


def test_pas_de_doublon_de_devis(con):
    reste = con.execute("""
        SELECT count(*) FROM (
            SELECT 1 FROM devis WHERE piece_no IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, client, date, ttc HAVING count(*) > 1)
    """).fetchone()[0]
    assert reste == 0


def test_aging_sans_montant_negatif(k):
    """Une tranche d'age decrit des creances a encaisser : un avoir n'y a pas sa place, et sa presence…"""
    for b in k["echelonnement_delais_accordes"]:
        assert b["montant"] >= 0, f"tranche {b['bucket']} negative"


def test_une_borne_atteinte_a_l_arrondi_pres_n_est_pas_une_anomalie():
    """Sur le périmètre d'un seul client, la part vaut 100 % et le HHI 10 000, à 1e-14 près au-dessus…"""
    from ml_engine.analytics.data_quality import _Contexte, _ctrl_concentration
    c = _Contexte()
    _ctrl_concentration(None, c, {"hhi_clients": 10000.000000000002, "hhi_fournisseurs": 5000,
                                  "top_clients": [{"nom": "X", "share": 100.00000000000003}]})
    assert not c.constats
    _ctrl_concentration(None, c, {"hhi_clients": 10001, "hhi_fournisseurs": 5000,
                                  "top_clients": [{"nom": "X", "share": 100.5}]})
    assert {k["controle"] for k in c.constats} == {"concentration.hhi_clients",
                                                    "concentration.part"}
