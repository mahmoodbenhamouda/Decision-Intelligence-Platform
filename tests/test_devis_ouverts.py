"""Devis ouverts : protocole d'action et taux de conversion non censuré.

Deux exigences distinctes :

  * un montant ouvert doit se traduire en ACTION — un devis gros et improbable
    est un appel d'offres, il ne se relance pas au téléphone ;
  * un taux de conversion doit être mesuré sur des devis MÛRS. Un devis émis il
    y a trois semaines n'a pas encore eu le temps d'être signé : le compter
    ferait baisser le taux pour une raison étrangère au devis.
"""

from __future__ import annotations

import pytest

from ml_engine.analytics import conversion_devis as cd


# ── Protocole d'action ───────────────────────────────────────────────────────

def test_un_gros_devis_probable_appelle_un_appel():
    assert cd.protocole(cd.SEUIL_MONTANT_GROS_DT + 1, 0.9) == "appeler"


def test_un_gros_devis_improbable_est_un_appel_d_offres():
    """Le cas qui justifie la règle : 67 M DT de devis au-delà de 100 K dans
    cet ERP, zéro signé. Les relancer commercialement est du temps perdu."""
    assert cd.protocole(500_000, 0.02) == "appel_offres"


def test_un_petit_devis_probable_se_traite_en_lot():
    assert cd.protocole(3_000, 0.5) == "traiter_en_lot"


def test_un_petit_devis_improbable_ne_merite_aucune_action():
    assert cd.protocole(500, 0.01) == "laisser"


def test_les_quatre_protocoles_portent_un_libelle_et_une_consigne():
    for code, meta in cd.PROTOCOLES.items():
        assert meta["libelle"], f"{code} sans libellé"
        assert len(meta["quoi_faire"]) > 40, (
            f"{code} : la consigne doit dire quoi faire, pas seulement nommer")


def test_le_seuil_de_chance_est_coherent_avec_les_bornes():
    assert 0 < cd.SEUIL_CHANCE_HAUTE < 1
    assert cd.SEUIL_MONTANT_GROS_DT > 0
    assert cd.AGE_DEVIS_MORT_J > 0


# ── Taux de conversion constaté ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def reperes():
    r = cd.reperes_conversion()
    if not r.get("servi"):
        pytest.skip("repères indisponibles")
    return r


def test_le_taux_decroit_quand_le_montant_monte(reperes):
    """Le fait qui change la lecture des « ventes probables » : un même
    montant ouvert n'a pas la même valeur selon sa tranche."""
    taux = [t["taux_pct"] for t in reperes["par_tranche_de_montant"]
            if t["taux_pct"] is not None]
    assert len(taux) >= 3, "pas assez de tranches pour juger"
    assert taux[0] > taux[-1], (
        f"la petite tranche ({taux[0]} %) doit convertir mieux que la grosse "
        f"({taux[-1]} %)")


def test_les_devis_recents_sont_exclus_du_taux_et_comptes_a_part(reperes):
    """Censure à droite : sans cette exclusion, le taux serait faux."""
    nj = reperes["non_jugeables"]
    assert nj["n_devis"] > 0
    assert nj["montant_dt"] > 0
    assert "récent" in nj["motif"] or "recent" in nj["motif"]
    assert reperes["maturation_mois"] == cd.MATURATION_MOIS


def test_les_signes_ne_depassent_jamais_les_devis(reperes):
    for t in reperes["par_tranche_de_montant"]:
        assert 0 <= t["n_signes"] <= t["n_devis"]
        if t["taux_pct"] is not None:
            assert abs(t["taux_pct"] - t["n_signes"] / t["n_devis"] * 100) < 0.1


def test_la_source_du_statut_est_declaree_sans_jargon(reperes):
    """La source doit être nommée, mais en langage de gestion.

    Elle citait le nom technique du champ : un directeur n'a pas à connaître
    la structure interne du logiciel pour lire son taux de conversion."""
    source = reperes["source"]
    assert "devis" in source.lower() and "facture" in source.lower()
    assert "ETATPIECE" not in source.upper()


def test_un_filtre_client_restreint_les_reperes(reperes):
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        code = con.execute(
            "SELECT client FROM devis WHERE client IS NOT NULL "
            "GROUP BY client ORDER BY count(*) DESC LIMIT 1").fetchone()
    finally:
        con.close()
    if not code:
        pytest.skip("aucun client dans les devis")

    filtre = cd.reperes_conversion(clients=[code[0]])
    total_filtre = sum(t["n_devis"] for t in filtre["par_tranche_de_montant"])
    total_complet = sum(t["n_devis"] for t in reperes["par_tranche_de_montant"])
    assert total_filtre < total_complet
