"""Le processus d'approvisionnement doit dire ce qu'il mesure ET ce qu'il ignore.

Le piège de ce chantier n'est pas de mal compter : c'est d'afficher cinq étapes
alors que l'ERP n'en trace que trois. Une étape inventée découverte en réunion
discrédite les quatre autres. Les tests vérifient donc autant les chiffres que
les aveux.
"""

from __future__ import annotations

import pytest

from api.services import approvisionnement as svc
from ml_engine.analytics import approvisionnement as ap


@pytest.fixture(scope="module")
def p():
    r = svc.processus()
    if not r.get("servi"):
        pytest.skip(f"approvisionnement indisponible : {r.get('motif')}")
    return r


# ── Les cinq étapes, et leur honnêteté ───────────────────────────────────────

def test_les_cinq_etapes_sont_publiees(p):
    rangs = [e["rang"] for e in p["etapes"]]
    assert rangs == [1, 2, 3, 4, 5]


def test_une_etape_non_couverte_dit_pourquoi(p):
    """Masquer une étape manquante ferait croire que le processus en compte
    trois ; l'afficher sans raison ferait croire à un oubli."""
    absentes = [e for e in p["etapes"] if e["couverte"] is False]
    assert absentes, "aucune étape déclarée absente — suspect sur cet ERP"
    for e in absentes:
        assert e.get("pourquoi_absent"), f"{e['code']} absente sans explication"
        assert len(e["pourquoi_absent"]) > 60
        assert not e.get("chiffres"), f"{e['code']} absente mais porte des chiffres"


def test_une_etape_partielle_nomme_ce_qui_manque(p):
    partielles = [e for e in p["etapes"] if e["couverte"] == "partielle"]
    assert partielles
    for e in partielles:
        assert e.get("ce_qui_manque"), f"{e['code']} partielle sans manque nommé"
        assert e.get("ce_qu_on_voit"), f"{e['code']} partielle sans apport nommé"


def test_chaque_etape_couverte_declare_sa_source(p):
    for e in p["etapes"]:
        if e["couverte"] is not False:
            assert e.get("source") and e["source"] != "aucune"


def test_les_echantillons_ne_sont_pas_mesurables(p):
    """L'ERP ne porte aucune demande d'échantillon : l'affirmer protège d'une
    étape qu'on serait tenté de remplir avec autre chose."""
    e = next(x for x in p["etapes"] if x["code"] == "echantillons")
    assert e["couverte"] is False


def test_la_logistique_ne_pretend_pas_mesurer_un_delai(p):
    """L'écart entre deux factures d'achat est une FRÉQUENCE. Sans date de
    réception, aucun délai de livraison n'est calculable."""
    e = next(x for x in p["etapes"] if x["code"] == "logistique")
    assert e["couverte"] == "partielle"
    assert "réception" in e["ce_qui_manque"].lower()
    nie = p["reapprovisionnement"]["ce_n_est_pas"].lower()
    assert "délai de livraison" in nie


# ── Fournisseurs et dépendance ───────────────────────────────────────────────

def test_les_parts_fournisseurs_sont_coherentes(p):
    f = p["fournisseurs"]
    assert f["n_fournisseurs"] > 0
    assert f["achats_total_dt"] > 0
    assert all(0 <= x["part_pct"] <= 100 for x in f["top"])
    # Le top est trié par montant décroissant.
    montants = [x["montant_dt"] for x in f["top"]]
    assert montants == sorted(montants, reverse=True)


def test_la_dependance_est_jugee_sur_un_seuil_declare(p):
    d = p["fournisseurs"]["dependance"]
    assert d["seuil_pct"] == ap.SEUIL_DEPENDANCE_PCT
    assert d["critique"] == (d["part_pct"] >= d["seuil_pct"])
    if d["critique"]:
        assert d.get("consequence"), (
            "une dépendance critique sans conséquence énoncée n'aide à rien")


def test_le_hhi_est_borne_et_explique(p):
    f = p["fournisseurs"]
    assert 0 < f["hhi"] <= 10_000
    assert f.get("hhi_lecture")
    assert "10 000" in f["hhi_methode"]


def test_les_parts_par_pays_somment_a_cent(p):
    parts = [x["part_pct"] for x in p["fournisseurs"]["par_pays"]]
    # Le top est limité à 8 pays : la somme ne dépasse jamais 100.
    assert 0 < sum(parts) <= 100.5


# ── Mono-source ──────────────────────────────────────────────────────────────

def test_le_mono_source_est_un_sous_ensemble_des_references(p):
    m = p["mono_source"]
    assert 0 <= m["n_mono_source"] <= m["n_references"]
    assert abs(m["part_mono_source_pct"]
               - m["n_mono_source"] / m["n_references"] * 100) < 0.2


def test_chaque_reference_mono_source_nomme_son_unique_fournisseur(p):
    for x in p["mono_source"]["top"]:
        assert x["fournisseur"] and x["fournisseur"] != "—"
        assert x["montant_dt"] >= 0


def test_le_mono_source_ne_pretend_pas_qu_aucun_autre_fournisseur_existe(p):
    """Nuance décisive : la donnée dit qu'aucun AUTRE n'a été utilisé, pas
    qu'aucun autre n'existe sur le marché."""
    assert "n'a été utilisé" in p["mono_source"]["lecture"]


# ── Réapprovisionnement ──────────────────────────────────────────────────────

def test_les_reassorts_en_retard_depassent_leur_propre_rythme(p):
    for x in p["reapprovisionnement"]["a_recommander"]:
        assert x["jours_depuis"] > x["intervalle_median_j"], (
            f"{x['designation']} listé sans être en retard")
        assert x["n_reappros"] >= 3, "un rythme ne se déduit pas de deux achats"


def test_les_reassorts_en_retard_concernent_des_produits_encore_vendus(p):
    """Sans cette condition, la liste remonte des fournitures arrêtées depuis
    huit ans dont le « retard » atteint 96 fois le rythme et ne veut rien dire."""
    lignes = p["reapprovisionnement"]["a_recommander"]
    if not lignes:
        pytest.skip("aucun réassort en retard sur ce jeu")
    for x in lignes:
        assert x["derniere_vente"], f"{x['designation']} sans vente récente"
    assert "encore vendues" in p["reapprovisionnement"]["regle"]


def test_les_contrats_de_maintenance_sont_ecartes(p):
    """Un contrat se refacture, il ne se réapprovisionne pas."""
    for x in p["reapprovisionnement"]["a_recommander"]:
        haut = x["designation"].upper()
        assert "CONTRAT" not in haut and "MAINTENANCE" not in haut


def test_le_classement_par_retard_est_decroissant(p):
    ratios = [x["retard_x"] for x in p["reapprovisionnement"]["a_recommander"]
              if x["retard_x"] is not None]
    assert ratios == sorted(ratios, reverse=True)


# ── Position de stock ────────────────────────────────────────────────────────

def test_la_position_negative_est_expliquee_et_non_masquee(p):
    """1 043 produits affichent une position négative. La cause est l'absence
    d'inventaire d'ouverture, pas un stock réellement négatif."""
    s = p["stock"]
    assert s["n_produits"] > 0
    assert 0 <= s["n_rapproches"] <= s["n_produits"]
    assert 0 <= s["n_position_negative"] <= s["n_produits"]
    pourquoi = s["pourquoi_negatif"].lower()
    assert "ouverture" in pourquoi
    assert "pas un stock réellement négatif" in pourquoi


def test_un_filtre_de_periode_restreint_les_achats(p):
    recent = svc.processus({"selected_years": [2025]})
    if not recent.get("servi"):
        pytest.skip("indisponible sur 2025")
    assert (recent["fournisseurs"]["achats_total_dt"]
            < p["fournisseurs"]["achats_total_dt"])
