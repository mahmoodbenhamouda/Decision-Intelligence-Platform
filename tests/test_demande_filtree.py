"""La prévision de demande doit suivre le filtre, et avouer quand elle dérape.

Deux exigences opposées, qui se tiennent :

  * la demande d'un établissement se prévoit comme celle de l'entreprise. La
    masquer sous un filtre client privait le directeur de la seule réponse
    disponible sur ce périmètre ;
  * mais elle dérape. Agrégée, la demande est régulière — 16 % d'erreur. Chez un
    hôpital qui commande par à-coups, l'erreur dépasse 200 %. Publier les deux
    chiffres de la même façon laisserait croire qu'ils se décident pareil.
"""

from __future__ import annotations

import pytest

from api.services.stock import demande_et_approvisionnement as demande
from ml_engine.analytics.demand_engine import MAPE_MAXIMALE_EXPLOITABLE
from ml_engine.forecasting import demande_hybride as dh


@pytest.fixture(scope="module")
def globale():
    r = demande()
    if r.get("error"):
        pytest.skip(f"moteur de demande indisponible : {r['error']}")
    return r


def _un_gros_client() -> str:
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        r = con.execute("SELECT client FROM sales WHERE client IS NOT NULL "
                        "GROUP BY client ORDER BY sum(ttc) DESC NULLS LAST "
                        "LIMIT 1").fetchone()
    finally:
        con.close()
    if not r:
        pytest.skip("aucun client dans les ventes")
    return r[0]


# ── La requête tourne ────────────────────────────────────────────────────────

def test_la_serie_de_demande_n_est_pas_vide(globale):
    """Garde-fou de la panne réelle : un nettoyage de texte avait transformé
    `sum(nbr_article)` en `sum` et l'écran affichait une erreur de requête."""
    serie = globale["demande_mensuelle"]
    assert len(serie) > 12, "série trop courte : la requête ne renvoie rien"
    assert sum(p["qte"] for p in serie) > 0, "demande nulle sur tout l'historique"


def test_la_prevision_couvre_trois_mois(globale):
    prev = globale["demande_prevision"]
    assert len(prev) == 3
    assert all(p["qte"] >= 0 for p in prev)
    for p in prev:
        if p.get("bas") is not None and p.get("haut") is not None:
            assert p["bas"] <= p["qte"] <= p["haut"], (
                "la prévision doit tomber dans sa propre fourchette")


# ── Le filtre s'applique ─────────────────────────────────────────────────────

def test_le_filtre_client_restreint_la_demande(globale):
    """Ce volet n'est plus masqué : il répond sur le périmètre demandé."""
    r = demande({"selected_clients": [_un_gros_client()]})
    assert not r.get("masque"), "la demande ne doit plus être masquée"
    assert r["perimetre"]["n_clients"] == 1

    total_client = sum(p["qte"] for p in r["demande_mensuelle"])
    total_global = sum(p["qte"] for p in globale["demande_mensuelle"])
    assert 0 < total_client < total_global


def test_sans_filtre_le_perimetre_est_l_entreprise(globale):
    assert globale["perimetre"]["n_clients"] == 0
    assert "entreprise" in globale["perimetre"]["libelle"]


def test_la_serie_du_modele_suit_aussi_le_filtre():
    """Le moteur de prévision lit la même série que l'affichage : sans ça, la
    courbe et la prévision parleraient de périmètres différents."""
    mois_tous, serie_tous = dh.charger_serie()
    mois_un, serie_un = dh.charger_serie(clients=[_un_gros_client()])
    assert len(serie_un) <= len(serie_tous)
    assert serie_un.sum() < serie_tous.sum()


# ── La fiabilité est déclarée ────────────────────────────────────────────────

def test_la_demande_globale_est_exploitable(globale):
    assert globale["demande_exploitable"] is True
    assert globale["demande_mape"] <= MAPE_MAXIMALE_EXPLOITABLE
    assert "demande_reserve" not in globale


def test_une_prevision_trop_incertaine_est_etiquetee():
    """Elle reste affichée — la cacher ferait croire à une panne — mais le
    chiffre porte sa réserve."""
    r = demande({"selected_clients": [_un_gros_client()]})
    if r.get("demande_mape") is None:
        pytest.skip("pas de prévision sur ce périmètre")
    assert r["demande_seuil_mape"] == MAPE_MAXIMALE_EXPLOITABLE
    assert r["demande_exploitable"] == (
        r["demande_mape"] <= MAPE_MAXIMALE_EXPLOITABLE)
    if not r["demande_exploitable"]:
        reserve = r["demande_reserve"].lower()
        assert reserve, "aucune réserve sur un chiffre non fiable"
        assert "budg" in reserve, (
            "la réserve doit dire que ce chiffre ne se budgète pas")
        assert f"{r['demande_mape']:.0f}" in reserve, (
            "la réserve doit porter l'erreur mesurée, pas un avertissement vague")


def test_le_seuil_est_declare_et_raisonnable():
    """Un seuil fixé après coup pour faire passer le modèle ne vaut rien."""
    assert 0 < MAPE_MAXIMALE_EXPLOITABLE < 100


def test_les_fournisseurs_restent_mesures_quel_que_soit_le_filtre(globale):
    """La concentration des achats ne dépend pas du client : elle ne doit pas
    disparaître quand on en filtre un."""
    r = demande({"selected_clients": [_un_gros_client()]})
    assert r["fournisseurs_nb"] == globale["fournisseurs_nb"]
    assert r["fournisseur_top1_pct"] == globale["fournisseur_top1_pct"]
