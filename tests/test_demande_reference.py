"""Garanties du protocole de prévision par référence."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.forecasting import demande_reference as dr  # noqa: E402


def _donnees(n_refs: int = 12, graine: int = 0, dernier_mois: str = "2026-04-01") -> dr.Donnees:
    rng = np.random.default_rng(graine)
    mois = pd.date_range("2021-01-01", dernier_mois, freq="MS")
    lignes = []
    for i in range(n_refs):
        niveau = rng.uniform(2, 40)
        proba = rng.uniform(0.3, 1.0)
        for m in mois:
            if rng.random() < proba:
                q = rng.poisson(niveau * (1.4 if m.month == 12 else 1.0))
                for c in ("C1", "C2"):
                    lignes.append({"reference": f"R{i:02d}", "designation": f"VIDAS TEST {i}",
                                   "famille": "REACTIF", "client": c, "mois": m,
                                   "qte": q / 2, "montant": q * 10.0, "cout": q * 6.0})
    lignes.append({"reference": "S1", "designation": "REPARATION", "famille": "SERVICE SAV",
                   "client": "C1", "mois": mois[5], "qte": 3, "montant": 900.0, "cout": 0.0})
    L = pd.DataFrame(lignes)
    pos = pd.DataFrame({"cle": ["VIDAS TEST 0"] * len(mois), "mois": mois,
                        "entrees": 5.0, "sorties": 4.0, "position_fin": 1.0, "cout_unitaire": 2.0})
    cli = pd.DataFrame({"client_code": ["C1", "C2"], "client_name": ["CHU SFAX", "LABO ANALYSES"]})
    return dr.Donnees(lignes=L, positions=pos, clients=cli, source="synthétique")


@pytest.fixture(scope="module")
def panel():
    return dr.construire_panel(_donnees())


def test_perimetre_et_dernier_mois_ecarte(panel):
    assert "S1" not in panel.refs, "un service a été pris pour un réactif"
    assert panel.mois[0] == pd.Timestamp("2021-01-01")
    assert panel.mois[-1] == pd.Timestamp("2026-03-01"), "le dernier mois, incomplet, doit être écarté"
    assert (panel.Y >= 0).all()


def test_fenetres_validation_et_test(panel):
    o = dr.origines(panel)
    assert len(o["validation"]) == dr.N_VALIDATION and len(o["test"]) == dr.N_TEST
    assert max(o["validation"]) < min(o["test"]), "validation et test se chevauchent"
    assert panel.mois[o["test"][0] + 1] == pd.Timestamp("2024-10-01")
    assert panel.mois[o["test"][-1] + 1] == pd.Timestamp("2026-03-01")
    assert panel.mois[o["validation"][0] + 1] == pd.Timestamp("2023-10-01")


@pytest.mark.vitrine
def test_aucune_variable_ne_lit_le_futur(panel):
    """Modifier tous les mois APRÈS l'origine ne doit rien changer aux variables ni à l'éligibilité —…"""
    o = dr.origines(panel)["test"][3]
    m = dr.eligibles(panel, o)
    avant = dr.variables(panel, o, 2, m)

    import copy
    futur = copy.deepcopy(panel)
    rng = np.random.default_rng(1)
    futur.Y[:, o + 1:] = rng.integers(0, 500, futur.Y[:, o + 1:].shape)
    futur.montant[:, o + 1:] = 1e6
    for t in futur.clients_type:
        futur.clients_type[t][:, o + 1:] = 999.0
    futur.entrees[:, o + 1:] = 777.0
    futur.position[:, o + 1:] = -5.0
    futur.C[:, o + 1:] = 333.0
    futur.D[:, o + 1:] = 1e7

    assert np.array_equal(dr.eligibles(futur, o), m)
    apres = dr.variables(futur, o, 2, m)
    pd.testing.assert_frame_equal(avant, apres)
    for nom in dr.regles(panel, o, 2, m):
        assert np.allclose(dr.regles(panel, o, 2, m)[nom], dr.regles(futur, o, 2, m)[nom]), nom


def test_le_jeu_d_entrainement_s_arrete_a_l_origine(panel):
    """À l'origine `o`, un modèle ne voit que des cibles de mois ≤ o."""
    o, h = dr.origines(panel)["validation"][0], 3
    _, _, _, orig = dr.jeu(panel, range(12, o - h + 1), h)
    assert orig.max() + h <= o


def test_wape_biais_et_sens_du_bootstrap():
    y = np.array([10.0, 0.0, 30.0])
    assert dr.wape(y, y) == 0
    assert dr.wape(y, np.array([20.0, 0.0, 30.0])) == pytest.approx(25.0)
    assert dr.biais(y, np.array([20.0, 0.0, 30.0])) == pytest.approx(25.0)
    rng = np.random.default_rng(0)
    refs = np.repeat(np.arange(40), 5)
    y = rng.poisson(10, 200).astype(float)
    mauvais, bon = y + rng.normal(0, 6, 200), y + rng.normal(0, 1, 200)
    c = dr.ecart_bootstrap(y, mauvais, bon, refs, n=300)
    assert c["ecart_pts"] > 0 and c["significatif"] and c["ic95"][0] > 0, (
        "écart positif = le second candidat est meilleur")


def test_methodes_de_demande_intermittente():
    y = np.array([0, 0, 6, 0, 0, 0, 6, 0, 0, 6], float)
    croston = dr._croston(y, 0.1, "croston")
    sba = dr._croston(y, 0.1, "sba")
    tsb = dr._croston(y, 0.1, "tsb")
    assert 1.5 < croston < 3.5, "Croston ≈ taille / intervalle"
    assert sba == pytest.approx(croston * 0.95), "SBA corrige le biais de Croston de (1 − α/2)"
    assert 0 < tsb < 6
    assert dr._croston(np.zeros(12), 0.1, "sba") == 0.0


def test_regle_saisonniere_lit_le_meme_mois_l_an_dernier(panel):
    o = dr.origines(panel)["test"][0]
    m = dr.eligibles(panel, o)
    for h in dr.HORIZONS:
        assert np.array_equal(dr.regles(panel, o, h, m)["naif_saisonnier"], panel.Y[m, o + h - 12])


def test_structure_client_typee(panel):
    o = dr.origines(panel)["test"][0]
    X = dr.variables(panel, o, 1, dr.eligibles(panel, o))
    parts = X[[f"part_{t.lower()}" for t in dr.TYPES_ETAB]].sum(axis=1)
    assert np.allclose(parts.dropna(), 1.0)
    assert (X["part_hopital_public"].dropna() > 0).all(), "« CHU SFAX » doit être un hôpital public"


@pytest.fixture()
def dossiers(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dr, "MODELS_DIR", tmp_path / "models")
    extrait = tmp_path / "extrait"
    extrait.mkdir()
    d = _donnees(n_refs=14, graine=3)
    dr.ecrire_parquet(d.lignes, extrait / "ventes_ref_client_mois.parquet")
    dr.ecrire_parquet(d.positions, extrait / "stock_position_mensuelle.parquet")
    dr.ecrire_parquet(d.clients, extrait / "dim_client.parquet")
    return tmp_path, extrait


def test_train_applique_la_regle_de_deploiement(dossiers):
    pytest.importorskip("lightgbm")
    tmp, extrait = dossiers
    r = dr.train(extrait=extrait)
    comp = r["comparaison_challenger_vs_reference_h1"]
    attendu = comp["ecart_pts"] >= dr.SEUIL_GAIN_PTS and comp["ic95"][0] > 0
    assert r["decision"]["challenger_servi"] is attendu
    assert r["methode_servie"]["statut"] == "servi", "une méthode est toujours servie"
    assert (tmp / "reports" / dr.RAPPORT).exists()
    if not attendu:
        assert r["methode_servie"]["nom"] == dr.REGLE_DE_REFERENCE
        assert r["methode_servie"]["wape_h1_pct"] == r["regle_de_reference"]["test"]["wape_h1_pct"]


def test_decision_refuse_un_gain_non_significatif(dossiers, monkeypatch):
    """Un écart de +3 points dont l'intervalle touche zéro ne suffit pas."""
    pytest.importorskip("lightgbm")
    _, extrait = dossiers
    monkeypatch.setattr(dr, "ecart_bootstrap", lambda *a, **k: {
        "ecart_pts": 3.0, "ic95": [-0.4, 6.1], "significatif": False, "n_references": 14})
    r = dr.train(extrait=extrait)
    assert r["decision"]["challenger_servi"] is False
    assert r["methode_servie"]["nom"] == dr.REGLE_DE_REFERENCE


def test_prevoir_donne_trois_mois_et_une_borne_haute(dossiers, monkeypatch):
    _, extrait = dossiers
    monkeypatch.setattr(dr, "_long_methode", _sans_challenger(dr._long_methode))
    dr.train(extrait=extrait)
    out = dr.prevoir(extrait=extrait)
    assert out["servi"] and out["mois"] == ["2026-04", "2026-05", "2026-06"]
    for ref in out["references"]:
        assert len(ref["prevision"]) == 3
        assert ref["borne_haute_3_mois"] >= ref["cumul_3_mois"] >= 0
        assert ref["cumul_3_mois"] == pytest.approx(sum(ref["prevision"]), abs=0.2)
    cumuls = [r["cumul_3_mois"] for r in out["references"]]
    assert cumuls == sorted(cumuls, reverse=True), "les plus grosses quantités d'abord"


def test_sans_rapport_rien_n_est_servi(dossiers):
    _, extrait = dossiers
    assert dr.prevoir(extrait=extrait)["servi"] is False


def _sans_challenger(original):
    """Simule l'absence de LightGBM : la règle doit être servie, rapport à l'appui."""
    def f(p, origines_, methode):
        if methode == "challenger":
            raise ImportError("lightgbm absent (simulé)")
        return original(p, origines_, methode)
    return f


def test_sans_lightgbm_la_regle_est_servie_et_le_rapport_le_dit(dossiers, monkeypatch):
    _, extrait = dossiers
    monkeypatch.setattr(dr, "_long_methode", _sans_challenger(dr._long_methode))
    r = dr.train(extrait=extrait)
    assert r["decision"]["challenger_servi"] is False
    assert "indisponible" in r["decision"]["motif"]
    assert r["methode_servie"]["nom"] == dr.REGLE_DE_REFERENCE
