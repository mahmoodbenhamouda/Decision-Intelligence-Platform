"""
tests/test_demand_engine.py
===========================
Tests unitaires du moteur Demande & Approvisionnement (fonctions pures,
aucune dépendance à l'entrepôt).

Exécution :
    python -m pytest tests/test_demand_engine.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from ml_engine.analytics.demand_engine import _backtest, _forecast, _mape, _predict


# ── MAPE ────────────────────────────────────────────────────────────────────
def test_mape_parfait():
    assert _mape(np.array([10, 20, 30]), np.array([10, 20, 30])) == 0.0


def test_mape_erreur_50pct():
    assert _mape(np.array([100.0]), np.array([150.0])) == pytest.approx(50.0)


def test_mape_ignore_les_zeros():
    """Les mois à zéro ne doivent pas produire de division par zéro."""
    v = _mape(np.array([0.0, 100.0]), np.array([50.0, 110.0]))
    assert v == pytest.approx(10.0)


def test_mape_serie_toute_nulle():
    assert _mape(np.zeros(5), np.ones(5)) == 0.0


# ── Prévision ───────────────────────────────────────────────────────────────
def test_predict_saisonnier_reprend_le_mois_n_moins_12():
    hist = np.arange(1, 25, dtype=float)   # 24 mois : 1..24
    assert _predict(hist, "saisonnier") == 13.0   # valeur d'il y a 12 mois


def test_predict_moyenne_mobile():
    hist = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert _predict(hist, "moyenne_mobile") == 5.0


def test_predict_serie_courte_ne_plante_pas():
    """Moins de 12 mois : le saisonnier doit se replier sur la tendance."""
    hist = np.array([10.0, 12.0, 14.0])
    v = _predict(hist, "saisonnier")
    assert np.isfinite(v)


def test_forecast_jamais_negative():
    hist = np.array([5.0, 3.0, 1.0, 0.5, 0.2, 0.1])
    preds = _forecast(hist, "tendance", h=3)
    assert all(p >= 0 for p in preds)


def test_backtest_retourne_toutes_les_methodes():
    rng = np.random.default_rng(42)   # seed fixée → reproductible
    q = 100 + 10 * np.sin(np.arange(36) * 2 * np.pi / 12) + rng.normal(0, 3, 36)
    bt = _backtest(q)
    assert set(bt) == {"saisonnier", "saisonnier_croissance", "moyenne_mobile", "tendance"}
    assert all(v >= 0 for v in bt.values())
    # Sur une série saisonnière propre, le saisonnier doit battre la moyenne mobile
    assert bt["saisonnier"] <= bt["moyenne_mobile"]


def test_backtest_serie_courte():
    q = np.array([10.0, 12.0, 9.0, 11.0, 10.0, 12.0, 11.0, 10.0])
    bt = _backtest(q)
    assert isinstance(bt, dict) and bt   # pas d'exception, résultats présents


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
