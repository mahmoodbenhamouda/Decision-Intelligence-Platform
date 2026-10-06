"""La probabilité annoncée vaut-elle ce qu'elle dit ?

Pourquoi ces tests existent. L'écran affiche des **dinars** : « ventes
probables » est un montant multiplié par une probabilité. Or l'AUC, seule
métrique publiée jusqu'ici pour ce modèle, ne mesure que l'ORDRE. Un modèle qui
annoncerait 3 % partout où le taux réel est 30 % aurait exactement la même AUC
— et l'espérance affichée serait dix fois trop basse, sans qu'aucune métrique du
projet ne s'en aperçoive.

La calibration est donc ce qui autorise à écrire un montant. Ces tests
vérifient qu'elle le dit **honnêtement** : qu'un modèle calibré est reconnu
comme tel, qu'un modèle optimiste est dénoncé comme optimiste, que le signe du
biais ne s'inverse pas, et qu'elle refuse de répondre sur un échantillon trop
petit plutôt que de publier une courbe illisible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml_engine.analytics.conversion_devis import calibration_par_decile  # noqa: E402

SEED = 20261005


def _tirage(n: int, facteur: float = 1.0):
    """`n` devis dont la vraie probabilité est `facteur` fois celle annoncée."""
    rng = np.random.default_rng(SEED)
    p = rng.uniform(0.01, 0.95, n)
    y = rng.binomial(1, np.clip(p * facteur, 0, 1))
    return y, p


# --------------------------------------------------------------------------
# Le cas de référence
# --------------------------------------------------------------------------

@pytest.mark.vitrine
def test_un_modele_calibre_est_reconnu_comme_tel():
    y, p = _tirage(4000)
    c = calibration_par_decile(y, p)
    assert c["applicable"]
    assert c["ece_pt"] < 3, f"ECE de {c['ece_pt']} pt sur un modèle calibré"
    assert abs(c["biais_pt"]) < 2
    assert "sans biais" in c["sens_du_biais"]


@pytest.mark.vitrine
def test_un_modele_optimiste_est_denonce_comme_optimiste():
    """Le cas qui compte : l'espérance en dinars serait surestimée."""
    y, p = _tirage(4000, facteur=0.5)
    c = calibration_par_decile(y, p)
    assert c["biais_pt"] > 5, "un modèle deux fois trop optimiste doit se voir"
    assert "optimiste" in c["sens_du_biais"]
    assert "surestimée" in c["sens_du_biais"]


def test_un_modele_pessimiste_est_denonce_dans_l_autre_sens():
    rng = np.random.default_rng(SEED)
    p = rng.uniform(0.01, 0.45, 4000)
    y = rng.binomial(1, np.clip(p * 2, 0, 1))
    c = calibration_par_decile(y, p)
    assert c["biais_pt"] < -5
    assert "pessimiste" in c["sens_du_biais"]


# --------------------------------------------------------------------------
# Les invariants de la découpe
# --------------------------------------------------------------------------

def test_les_groupes_couvrent_tous_les_devis_sans_doublon():
    y, p = _tirage(1337)
    c = calibration_par_decile(y, p)
    assert sum(g["n_devis"] for g in c["par_groupe"]) == len(y)
    assert c["n_devis"] == len(y)


def test_les_groupes_sont_ordonnes_par_probabilite_croissante():
    y, p = _tirage(2000)
    c = calibration_par_decile(y, p)
    predites = [g["probabilite_predite_moyenne_pct"] for g in c["par_groupe"]]
    assert predites == sorted(predites)
    # Les intervalles ne se chevauchent pas : la découpe est bien par rangs.
    for a, b in zip(c["par_groupe"], c["par_groupe"][1:]):
        assert a["probabilite_max_pct"] <= b["probabilite_min_pct"] + 1e-6


def test_le_decoupage_par_rangs_evite_les_groupes_vides():
    """Beaucoup de probabilités identiques : c'est le cas réel ici.

    Les positifs étant rares, le modèle produit une masse de probabilités
    basses très proches. Un découpage par quantiles de VALEUR confondrait les
    bornes et rendrait des groupes vides ; le découpage par rangs ne peut pas.
    """
    p = np.concatenate([np.full(900, 0.02), np.linspace(0.1, 0.9, 100)])
    rng = np.random.default_rng(SEED)
    y = rng.binomial(1, p)
    c = calibration_par_decile(y, p)
    assert c["applicable"]
    assert c["n_groupes"] == 10
    assert all(g["n_devis"] > 0 for g in c["par_groupe"])


def test_l_ecart_par_groupe_est_la_difference_annonce_moins_observe():
    y, p = _tirage(2000)
    c = calibration_par_decile(y, p)
    for g in c["par_groupe"]:
        attendu = g["probabilite_predite_moyenne_pct"] - g["taux_observe_pct"]
        assert g["ecart_pt"] == pytest.approx(attendu, abs=0.02)


def test_le_taux_observe_est_bien_les_signes_sur_l_effectif():
    y, p = _tirage(2000)
    c = calibration_par_decile(y, p)
    for g in c["par_groupe"]:
        assert g["taux_observe_pct"] == pytest.approx(
            g["n_signes"] / g["n_devis"] * 100, abs=0.02)


# --------------------------------------------------------------------------
# Ce qu'elle refuse de faire
# --------------------------------------------------------------------------

def test_un_echantillon_trop_petit_est_refuse_et_non_bricole():
    """Mieux vaut pas de courbe qu'une courbe de deux points par groupe."""
    y, p = _tirage(12)
    c = calibration_par_decile(y, p)
    assert c["applicable"] is False
    assert "trop faibles" in c["motif"]


def test_le_nombre_de_groupes_est_reglable():
    y, p = _tirage(500)
    c = calibration_par_decile(y, p, n_groupes=5)
    assert c["n_groupes"] == 5


def test_elle_dit_qu_elle_est_hors_periode():
    """Une calibration mesurée sur l'entraînement est toujours bonne.

    Le rapport doit donc porter la mention, sinon le chiffre est trompeur
    même en étant juste.
    """
    y, p = _tirage(2000)
    c = calibration_par_decile(y, p)
    assert "jamais sur les devis" in c["pourquoi_hors_periode"]
    assert "ordre" in c["lecture"]


# --------------------------------------------------------------------------
# Le branchement : passerelle et API
# --------------------------------------------------------------------------

def test_la_passerelle_sert_la_calibration_ou_dit_pourquoi_non():
    """Jamais d'exception, jamais de courbe inventée : servie, ou motivée."""
    from ml_engine import passerelle as pw
    c = pw.calibration_devis()
    assert isinstance(c, dict)
    if c.get("applicable"):
        assert c["par_groupe"] and c["ece_pt"] >= 0
    else:
        assert c["motif"], "un refus doit porter son motif"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
