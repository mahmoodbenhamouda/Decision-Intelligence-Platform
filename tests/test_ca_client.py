"""Le modèle de chiffre d'affaires à venir — et ce qu'il refuse de faire.

Ce module est né d'une objection juste : « pourquoi `top_clients` n'est-il pas un
modèle ? ». Il ne l'est pas, et ne doit pas l'être — le chiffre d'affaires déjà
facturé est connu exactement. Ce qui se prédit, c'est celui qui n'est pas encore
facturé. Ces tests gardent cette frontière.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from ml_engine.analytics import ca_client as cc  # noqa: E402


@pytest.fixture(scope="module")
def brut():
    """Agrégat client × mois synthétique, aux colonnes du module réel."""
    rng = np.random.default_rng(7)
    clients = [f"C{i:03d}" for i in range(120)]
    mois = pd.date_range("2020-01-01", periods=60, freq="MS")
    niveaux = rng.lognormal(9, 1.2, len(clients))
    pente = rng.normal(1.0, 0.03, len(clients))

    lignes = []
    for i, c in enumerate(clients):
        niveau = niveaux[i]
        for m in mois:
            niveau *= pente[i]
            v = max(0.0, niveau * rng.lognormal(0, 0.3))
            lignes.append((c, m, v, v * 0.72, int(rng.integers(1, 9)),
                           int(rng.integers(1, 4)), v * 0.3, v * 0.5, v * 0.2, v))
    return pd.DataFrame(lignes, columns=[
        "client", "mois", "montant", "cout", "n_lignes", "n_familles",
        "m_equipement", "m_reactif", "m_service", "m_abs"])


@pytest.fixture(scope="module")
def delais(brut):
    return brut[["client", "mois"]].assign(delai_median=60.0)


@pytest.fixture(scope="module")
def panel(brut, delais):
    return cc.construire_panel(brut=brut, delais=delais, horizon=3)


# ── La cible est observée, et seulement observée ──────────────────────────────

def test_la_cible_est_la_somme_des_mois_suivants(brut, delais):
    """Vérification directe contre les données, sans refaire le calcul du module."""
    p = cc.construire_panel(brut=brut, delais=delais, horizon=3)
    assert not p.empty

    ligne = p.iloc[len(p) // 2]
    futur = brut[(brut["client"] == ligne["client"])
                 & (brut["mois"] > ligne["mois"])
                 & (brut["mois"] <= ligne["mois"] + pd.DateOffset(months=3))]
    attendu = float(futur["montant"].clip(lower=0).sum())
    assert ligne["ca_futur"] == pytest.approx(attendu, rel=1e-9)


def test_aucune_variable_ne_regarde_apres_la_date_dobservation(brut, delais):
    """Modifier le futur ne doit changer que la cible, jamais les variables."""
    p1 = cc.construire_panel(brut=brut, delais=delais, horizon=3)
    coupe = p1["mois"].quantile(0.5)

    trafique = brut.copy()
    apres = trafique["mois"] > coupe
    trafique.loc[apres, "montant"] = trafique.loc[apres, "montant"] * 100.0
    p2 = cc.construire_panel(brut=trafique, delais=delais, horizon=3)

    a = p1[p1["mois"] <= coupe].sort_values(["client", "mois"]).reset_index(drop=True)
    b = p2[p2["mois"] <= coupe].sort_values(["client", "mois"]).reset_index(drop=True)
    communes = min(len(a), len(b))
    for v in cc.FEATURES:
        assert np.allclose(a[v][:communes], b[v][:communes], rtol=1e-9), (
            f"« {v} » change quand on modifie le FUTUR : fuite temporelle")


def test_les_derniers_mois_sont_exclus_car_leur_cible_est_tronquee(brut, delais):
    """Sans ce filtre, les dernières lignes porteraient un CA incomplet, donc
    systématiquement sous-estimé, et le modèle apprendrait la troncature."""
    horizon = 6
    p = cc.construire_panel(brut=brut, delais=delais, horizon=horizon)
    dernier_mois_donnees = brut["mois"].max()
    assert p["mois"].max() <= dernier_mois_donnees - pd.DateOffset(months=horizon)


def test_un_horizon_plus_long_coupe_davantage(brut, delais):
    p3 = cc.construire_panel(brut=brut, delais=delais, horizon=3)
    p12 = cc.construire_panel(brut=brut, delais=delais, horizon=12)
    assert p12["mois"].max() < p3["mois"].max()


def test_toutes_les_variables_declarees_existent(panel):
    manquantes = [v for v in cc.FEATURES if v not in panel.columns]
    assert not manquantes, manquantes
    assert panel[cc.FEATURES].notna().all().all()


def test_la_cible_nest_pas_une_variable():
    """La tautologie que ce module existe pour éviter."""
    for interdit in ("ca_futur", "ca_attendu_dt"):
        assert interdit not in cc.FEATURES
    for jeu in cc.JEUX_DE_VARIABLES.values():
        assert "ca_futur" not in jeu


# ── Les références triviales ─────────────────────────────────────────────────

def test_la_persistance_est_declaree_comme_reference(panel):
    """La référence à battre doit être la plus dure disponible : reporter le
    passé. Une référence facile rendrait tout modèle brillant."""
    refs = cc.references_triviales(panel, 3)
    assert "persistance" in refs
    assert np.allclose(refs["persistance"], panel["ca_3m"].to_numpy(dtype=float))


def test_la_persistance_est_un_adversaire_serieux(panel):
    """Contrôle de réalisme : si la persistance était mauvaise, le seuil de gain
    de 5 % ne voudrait rien dire."""
    y = panel["ca_futur"].to_numpy(dtype=float)
    m = cc.mesurer(y, cc.references_triviales(panel, 3)["persistance"])
    assert m["spearman"] > 0.5


# ── Les mesures ──────────────────────────────────────────────────────────────

def test_une_prediction_parfaite_donne_une_erreur_nulle():
    y = np.array([100.0, 2000.0, 50000.0, 10.0])
    m = cc.mesurer(y, y.copy(), n_top=2)
    assert m["erreur_absolue_medianne_dt"] == 0.0
    assert m["spearman"] == pytest.approx(1.0)
    assert m["precision_top_2"] == 1.0


def test_la_precision_du_top_ne_recompense_pas_un_mauvais_classement():
    y = np.array([1.0, 2.0, 3.0, 100.0, 200.0])
    inverse = -y
    m = cc.mesurer(y, inverse, n_top=2)
    assert m["precision_top_2"] == 0.0


def test_l_erreur_medianne_resiste_a_un_client_geant():
    """La raison du choix de la médiane : une erreur moyenne serait dictée par
    un seul client."""
    y = np.r_[np.full(99, 1000.0), [10_000_000.0]]
    pred = np.r_[np.full(99, 1100.0), [1000.0]]
    m = cc.mesurer(y, pred)
    assert m["erreur_absolue_medianne_dt"] == pytest.approx(100.0)
    assert m["erreur_absolue_moyenne_dt"] > 50_000


# ── Sélection et décision ────────────────────────────────────────────────────

def test_le_surapprentissage_disqualifie_avant_de_comparer(panel):
    """Critère d'ÉLIGIBILITÉ, pas constat d'après-coup."""
    choix = cc.selectionner(panel[panel["mois"] <= panel["mois"].quantile(0.7)], 3)
    assert choix["applicable"]
    assert not choix["retenu"]["disqualifie"]
    for essai in choix["essais"]:
        if essai["ecart_relatif"] > cc.ECART_TRAIN_VALID_MAXIMAL_RELATIF:
            assert essai["disqualifie"]


def test_la_parcimonie_prefere_le_modele_simple():
    assert cc.CANDIDATS[0] == "ridge_log"
    assert 0 < cc.ECART_PARCIMONIE_RELATIF < 0.10
    assert "volume_seul" in cc.JEUX_DE_VARIABLES


def test_les_seuils_sont_declares_avant_la_mesure():
    """Un seuil choisi après avoir vu le résultat ne décide de rien."""
    assert cc.GAIN_MINIMAL_RELATIF > 0
    assert 0.5 < cc.SPEARMAN_MINIMAL < 1.0
    assert cc.ECART_TRAIN_VALID_MAXIMAL_RELATIF > 0


def test_l_evaluation_respecte_la_marge_anti_fuite(panel):
    ev = cc.evaluer(panel, 3)
    if not ev.get("applicable"):
        pytest.skip(ev.get("motif"))
    assert ev["n_train"] > 0 and ev["n_test"] > 0
    assert "coupure" in ev and "marge_anti_fuite" in ev
    assert ev["meilleure_reference_triviale"] in cc.references_triviales(panel, 3)


def test_un_horizon_sans_assez_d_historique_est_refuse(brut, delais):
    """Le refus doit être explicite, jamais un résultat silencieusement faible."""
    court = brut[brut["mois"] <= brut["mois"].min() + pd.DateOffset(months=20)]
    p = cc.construire_panel(brut=court, delais=delais, horizon=12)
    ev = cc.evaluer(p, 12)
    assert ev["applicable"] is False
    assert ev["motif"]


# ── Registre ─────────────────────────────────────────────────────────────────

def test_les_deux_horizons_sont_declares_au_registre():
    from ml_engine.registre import MODELES
    for h in cc.HORIZONS:
        cle = f"ca_client_{h}m"
        assert cle in MODELES, f"{cle} absent du registre"
        assert MODELES[cle]["sens"] == "bas", (
            "la métrique est une erreur : sa dégradation se lit à la hausse")
        assert MODELES[cle]["artefact"] == f"ca_client_{h}m.joblib"


def test_les_artefacts_sont_declares_a_la_maintenance():
    """Un artefact qu'aucune commande ne réaligne devient périmé en silence."""
    import importlib.util
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "retrain_all", racine / "scripts" / "retrain_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fichiers = {a["fichier"] for a in mod.ARTEFACTS}
    for h in cc.HORIZONS:
        assert f"ca_client_{h}m.joblib" in fichiers
