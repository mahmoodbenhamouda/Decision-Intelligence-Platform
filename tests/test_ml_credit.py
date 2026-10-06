"""Garde-fous du modèle de conditions de crédit (`ml_engine/analytics/credit_risk_model.py`)."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_engine.analytics import credit_risk_model as crm

BASE = Path(__file__).resolve().parents[1]
RAPPORT = BASE / "reports" / "credit_risk_metrics.json"
SCORES = BASE / "output" / "client_risk.json"

pytestmark = pytest.mark.skipif(
    not RAPPORT.exists(),
    reason="modèle non entraîné — lancer `python -m ml_engine.analytics.credit_risk_model`")


@pytest.fixture(scope="module")
def rapport():
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucune_variable_interdite_dans_les_features():
    """La cible et ses transcriptions ne doivent jamais redevenir des variables."""
    fautives = [f for f in crm.FEATURES if f.lower() in crm._FEATURES_INTERDITES]
    assert not fautives, f"variables interdites réintroduites : {fautives}"


def test_mode_reglement_reste_exclu():
    """`MODEREGL` code le délai en toutes lettres — sa réintroduction ferait remonter l'AUC à 0,99 sans…"""
    assert "mode_regl" not in crm.FEATURES
    assert "mode_regl" in crm._FEATURES_INTERDITES


def test_aucun_agregat_du_client_dans_les_features():
    """En cold start le client est inconnu : tout agrégat de son historique est à la fois indisponible…"""
    assert not [f for f in crm.FEATURES if f.startswith("cli_") or f == "norme_client"]


def test_auc_cold_start_non_quasi_parfaite(rapport):
    """Une AUC > 0,98 sur ce problème signale une fuite, pas une réussite — c'est ce garde-fou qui a…"""
    auc = rapport["regime_B_cold_start"]["auc"]
    assert auc < 0.98, f"AUC cold start {auc:.4f} — fuite probable"
    assert rapport["decision_deploiement"]["fuite_suspectee"] is False


def test_garde_fou_de_fuite_est_actif(rapport):
    """Le champ doit exister : sans lui, rien ne distingue une AUC élevée légitime d'une fuite."""
    assert "fuite_suspectee" in rapport["decision_deploiement"]


def test_refutation_v1_est_chiffree(rapport):
    """Le rejet de la v1 doit reposer sur des mesures reproductibles."""
    d = rapport["refutation_v1"]
    assert d["ecart_type_intra_client_median_j"] < d["ecart_type_global_j"] / 5
    assert d["auc_regle_un_seuil"] > 0.85


def test_proxy_mode_reglement_documente(rapport):
    """Une fuite écartée doit rester traçable, sinon on ne distingue plus « variable jamais essayée »…"""
    p = rapport["fuite_2_proxy_mode_reglement"]
    assert p["auc_mode_reglement_seul"] > 0.85
    assert p["delai_median_par_mode"]


def test_protocole_est_bien_group_kfold(rapport):
    assert "GroupKFold" in rapport["regime_B_cold_start"]["protocole"]
    assert len(rapport["regime_B_cold_start"]["auc_par_pli"]) == 5


def test_protocole_hors_periode_present(rapport):
    """Le GroupKFold seul brasse les périodes."""
    hp = rapport["regime_B_cold_start"]["cold_start_hors_periode"]
    assert hp["applicable"] is True
    assert hp["n_clients_test"] > 0
    assert 0.0 <= hp["auc"] <= 1.0


def test_ecart_entre_protocoles_est_publie(rapport):
    """L'écart GroupKFold → hors période mesure la fuite temporelle."""
    b = rapport["regime_B_cold_start"]
    assert b["cold_start_hors_periode"]["auc"] <= b["auc"] + 1e-9


def test_deploiement_exige_confirmation_hors_periode(rapport):
    """Même règle que la prévision de demande 30/60/90 j : si le gain ne tient pas sur le protocole qui…"""
    d = rapport["decision_deploiement"]
    if d["modele_deploye"]:
        assert d["gain_confirme"] and d["confirme_hors_periode"]
    else:
        assert not (d["gain_confirme"] and d["confirme_hors_periode"]
                    and not d["fuite_suspectee"])


def test_rapport_et_modele_concordent(rapport):
    """Le rapport ne doit pas prétendre autre chose que ce que le bundle embarque réellement."""
    joblib = pytest.importorskip("joblib")
    p = BASE / "models" / "credit_risk_model.joblib"
    if not p.exists():
        pytest.skip("bundle absent")
    bundle = joblib.load(p)
    assert bundle["deploye"] == rapport["decision_deploiement"]["modele_deploye"]
    assert bundle["features"] == crm.FEATURES


def test_modele_bat_les_references_triviales(rapport):
    """Sur le protocole où il est évalué, le modèle doit au minimum dépasser la classe majoritaire —…"""
    b = rapport["regime_B_cold_start"]
    assert b["auc"] > b["baselines"]["classe_majoritaire"]


def test_ablation_degrade_le_modele(rapport):
    """Retirer les variables les plus informatives doit coûter : sans cela, le modèle ne s'appuie sur…"""
    b = rapport["regime_B_cold_start"]
    assert b["perte_ablation"] > 0.01, "l'ablation ne dégrade pas : signal non localisé"


def test_ecart_train_test_controle(rapport):
    ecart = rapport["regime_B_cold_start"]["ecart_train_test_auc"]
    assert ecart < 0.25, f"écart train-test {ecart} — surapprentissage"


@pytest.mark.skipif(not SCORES.exists(), reason="scores clients absents")
def test_contrat_de_sortie_des_scores():
    scores = json.loads(SCORES.read_text(encoding="utf-8"))
    assert scores
    for cl, v in list(scores.items())[:200]:
        assert 0.0 <= v["score"] <= 100.0, f"{cl}: score hors bornes"
        assert v["exposure"] >= 0 and v["n"] >= 1
        assert v["source"] in {"regle_historique", "modele_cold_start", "taux_de_base"}


@pytest.mark.skipif(not SCORES.exists(), reason="scores clients absents")
def test_provenance_du_score_est_explicite(rapport):
    """Un score issu d'une règle et un score issu d'un modèle ne s'interprètent pas pareil : l'origine…"""
    scores = json.loads(SCORES.read_text(encoding="utf-8"))
    sources = {v["source"] for v in scores.values()}
    assert "regle_historique" in sources
    if not rapport["decision_deploiement"]["modele_deploye"]:
        assert "modele_cold_start" not in sources, \
            "un modèle refusé ne doit pas servir ses probabilités"
