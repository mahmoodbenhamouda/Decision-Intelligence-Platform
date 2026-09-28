"""
ml_engine/forecasting/evaluate_cashflow.py
==========================================
Évaluation RIGOUREUSE de la prévision d'encaissements (trésorerie).

Pourquoi ce module : la MAPE affichée par `forecast_cashflow` est un résidu
d'ajustement 1-pas (in-sample), donc optimiste. Ici, on mesure la performance
en conditions réelles :

  - BACKTEST WALK-FORWARD out-of-sample : pour chacun des `n_test` derniers
    mois, chaque modèle est ré-entraîné uniquement sur le passé, puis prédit
    le mois suivant (h=1) et l'horizon h=3. AUCUNE fuite du futur.
  - MODÈLES COMPARÉS : LSTM (PyTorch, si disponible), Holt-Winters léger
    (repli NumPy), et trois baselines qu'un candidat honnête doit battre —
    naïf (dernier mois), naïf saisonnier (m-12), moyenne mobile 3 mois.
  - MÉTRIQUES : MAPE, MAE, RMSE (h=1 et h=3) + COUVERTURE EMPIRIQUE de la
    bande de confiance à 95 % du modèle retenu.
  - Reproductible : seed 42, `python -m ml_engine.forecasting.evaluate_cashflow`.

Sortie : reports/cashflow_forecast_metrics.json + tableau console.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .lstm_cashflow import _TORCH, _forecast_fallback, _load_series

REPORTS = Path(__file__).resolve().parents[2] / "reports"
SEED = 42
N_TEST_DEFAULT = 12          # mois évalués en walk-forward
HORIZONS = (1, 3)


# ── Modèles candidats : signature f(z_train, horizon) -> np.ndarray ─────────
def _naif(z: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(z[-1], h)


def _naif_saisonnier(z: np.ndarray, h: int) -> np.ndarray:
    if len(z) < 12:
        return _naif(z, h)
    return np.array([z[len(z) - 12 + ((i) % 12)] if len(z) >= 12 else z[-1]
                     for i in range(h)])


def _moyenne_mobile3(z: np.ndarray, h: int) -> np.ndarray:
    return np.repeat(z[-3:].mean(), h)


def _holt_winters(z: np.ndarray, h: int) -> np.ndarray:
    preds, _ = _forecast_fallback(z, h)
    return preds


def _lstm(z: np.ndarray, h: int) -> np.ndarray:
    from .lstm_cashflow import _forecast_lstm
    lb = min(12, len(z) - 4)
    preds, _ = _forecast_lstm(z, h, lb, epochs=150, seed=SEED)
    return preds


def _candidats() -> Dict[str, Callable[[np.ndarray, int], np.ndarray]]:
    c: Dict[str, Callable] = {
        "naif_dernier_mois": _naif,
        "naif_saisonnier_m12": _naif_saisonnier,
        "moyenne_mobile_3m": _moyenne_mobile3,
        "holt_winters_leger": _holt_winters,
    }
    if _TORCH:
        c["lstm_pytorch"] = _lstm
    return c


# ── Backtest walk-forward ───────────────────────────────────────────────────
def _metrics(actual: np.ndarray, pred: np.ndarray) -> Dict[str, float]:
    err = actual - pred
    mask = actual > 0
    mape = float(np.mean(np.abs(err[mask] / actual[mask])) * 100) if mask.any() else None
    return {
        "mape_pct": round(mape, 1) if mape is not None else None,
        "mae_dt": round(float(np.mean(np.abs(err))), 0),
        "rmse_dt": round(float(np.sqrt(np.mean(err ** 2))), 0),
    }


def evaluate(n_test: int = N_TEST_DEFAULT, save: bool = True) -> Optional[dict]:
    np.random.seed(SEED)
    periods, raw = _load_series()
    if len(raw) < n_test + 18:
        n_test = max(6, len(raw) // 4)
    if len(raw) < 24:
        print("Série trop courte pour un backtest honnête.")
        return None

    # Même pré-traitement que la production : log1p + standardisation,
    # recalculés à CHAQUE pas uniquement sur le train (aucune fuite).
    results: Dict[str, Dict[str, Dict[str, float]]] = {}
    preds_store: Dict[str, Dict[int, List[Tuple[float, float]]]] = {}

    for name, fn in _candidats().items():
        preds_store[name] = {h: [] for h in HORIZONS}
        for t in range(len(raw) - n_test, len(raw)):
            train = raw[:t]
            logs = np.log1p(np.clip(train, 0, None))
            mu, sd = logs.mean(), (logs.std() or 1.0)
            z = (logs - mu) / sd
            try:
                pz = fn(z, max(HORIZONS))
            except Exception:
                continue
            back = np.expm1(pz * sd + mu)          # retour en dinars
            for h in HORIZONS:
                if t + h - 1 < len(raw):
                    preds_store[name][h].append((float(raw[t + h - 1]), float(back[h - 1])))
        results[name] = {}
        for h in HORIZONS:
            pairs = preds_store[name][h]
            if pairs:
                a = np.array([p[0] for p in pairs])
                p_ = np.array([p[1] for p in pairs])
                results[name][f"h{h}"] = {**_metrics(a, p_), "n_points": len(pairs)}

    # Modèle retenu = meilleure MAPE h=1 (hors baselines si un modèle les bat)
    classement = sorted(results.items(),
                        key=lambda kv: kv[1].get("h1", {}).get("mape_pct") or 1e9)
    retenu = classement[0][0]

    # Couverture empirique de la bande ±1.96σ du modèle retenu (h=1)
    couverture = None
    try:
        fn = _candidats()[retenu]
        hits, tot = 0, 0
        for t in range(len(raw) - n_test, len(raw)):
            train = raw[:t]
            logs = np.log1p(np.clip(train, 0, None))
            mu, sd = logs.mean(), (logs.std() or 1.0)
            z = (logs - mu) / sd
            if retenu == "holt_winters_leger":
                pz, resid = _forecast_fallback(z, 1)
            elif retenu == "lstm_pytorch":
                from .lstm_cashflow import _forecast_lstm
                pz, resid = _forecast_lstm(z, 1, min(12, len(z) - 4), epochs=150, seed=SEED)
            else:
                continue
            sigma = min(float(np.std(resid) or 0.0), 0.30)
            lo = np.expm1((pz[0] - 1.96 * sigma) * sd + mu)
            hi = np.expm1((pz[0] + 1.96 * sigma) * sd + mu)
            if lo <= raw[t] <= hi:
                hits += 1
            tot += 1
        if tot:
            couverture = round(hits / tot * 100, 1)
    except Exception:
        pass

    out = {
        "cible": "encaissements mensuels attendus (somme TTC par mois d'échéance)",
        "protocole": (f"backtest walk-forward out-of-sample sur les {n_test} derniers mois : "
                      "à chaque pas, ré-entraînement sur le seul passé (log1p + "
                      "standardisation recalculées sur le train), prédiction h=1 et h=3. "
                      "Aucune fuite du futur."),
        "seed": SEED,
        "n_mois_serie": len(raw),
        "periode": f"{periods[0]} → {periods[-1]}",
        "torch_disponible": _TORCH,
        "note_torch": (None if _TORCH else
                       "PyTorch absent de cet environnement : le LSTM n'est pas évalué ici. "
                       "Relancer sur une machine avec torch pour compléter la comparaison."),
        "resultats_par_modele": results,
        "modele_retenu": retenu,
        "couverture_bande_95pct_h1": couverture,
        "note_honnete": (
            "La MAPE affichée dans l'application (forecast_cashflow.mape_pct) est un "
            "résidu d'ajustement 1-pas in-sample, donc plus optimiste que ce backtest "
            "out-of-sample, qui fait foi. Si une baseline naïve rivalise avec le modèle, "
            "c'est dit ici tel quel."),
        "reproduction": "python -m ml_engine.forecasting.evaluate_cashflow",
    }

    if save:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / "cashflow_forecast_metrics.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Tableau console
    print(f"\n=== Backtest walk-forward encaissements ({n_test} mois, seed {SEED}) ===")
    print(f"{'modèle':<24} {'MAPE h1':>9} {'RMSE h1':>12} {'MAPE h3':>9} {'RMSE h3':>12}")
    for name, r in classement:
        h1, h3 = r.get("h1", {}), r.get("h3", {})
        star = " ← retenu" if name == retenu else ""
        print(f"{name:<24} {str(h1.get('mape_pct')):>8}% {str(h1.get('rmse_dt')):>12} "
              f"{str(h3.get('mape_pct')):>8}% {str(h3.get('rmse_dt')):>12}{star}")
    if couverture is not None:
        print(f"Couverture empirique bande 95 % (h=1) : {couverture}% "
              f"{'(bien calibrée)' if 85 <= couverture <= 99 else '(à recalibrer)'}")
    if not _TORCH:
        print("⚠ PyTorch absent : LSTM non évalué dans cet environnement.")
    return out


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    evaluate()
