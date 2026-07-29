"""
ml_engine/forecasting/lstm_cashflow.py
======================================
Prévision d'ENCAISSEMENTS / trésorerie par DEEP LEARNING (LSTM).

Objectif métier : anticiper les entrées de cash (basées sur les dates d'échéance
des factures de vente) sur 3–6 mois, pour piloter le recouvrement et la trésorerie.
Le résultat alimente le radar financier (levier « trésorerie prévisionnelle ») et
le copilote / l'avatar.

Conception robuste :
  - Modèle principal : LSTM (PyTorch) sur la série mensuelle log-transformée.
  - Repli automatique (si PyTorch absent) : lissage exponentiel + tendance +
    saisonnalité mensuelle, en NumPy pur → la fonction renvoie TOUJOURS un résultat.
  - Bande de confiance estimée à partir des résidus (backtest 1 pas).

API : forecast_cashflow(horizon=6, data_dir=None) -> dict
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:  # PyTorch est optionnel (cf. requirements.txt) — repli NumPy sinon
    import torch
    import torch.nn as nn
    _TORCH = True
except Exception:  # pragma: no cover
    _TORCH = False


# ─────────────────────────────────────────────────────────────────────────────
# Données : série mensuelle d'encaissements attendus (par date d'échéance)
# ─────────────────────────────────────────────────────────────────────────────
def _load_series(data_dir: Path | None = None) -> Tuple[List[str], np.ndarray]:
    from ml_engine.analytics import kpi_engine
    con = kpi_engine._connect(data_dir)
    rows = con.execute("""
        SELECT strftime(echeance, '%Y-%m') AS m, sum(ttc) AS montant, count(*) n
        FROM sales
        WHERE echeance IS NOT NULL AND year(echeance) BETWEEN 2016 AND 2035
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    con.close()
    if not rows:
        return [], np.array([])

    # Reindex mensuel continu (comble les trous par interpolation linéaire)
    def _key(s: str) -> int:
        y, mo = s.split("-"); return int(y) * 12 + (int(mo) - 1)
    idx = {r[0]: (float(r[1] or 0), int(r[2] or 0)) for r in rows}
    ks = sorted(idx)
    start, end = _key(ks[0]), _key(ks[-1])
    periods, vals, counts = [], [], []
    for k in range(start, end + 1):
        y, mo = divmod(k, 12); p = f"{y:04d}-{mo + 1:02d}"
        periods.append(p)
        v, n = idx.get(p, (np.nan, 0))
        vals.append(v); counts.append(n)
    arr = np.array(vals, dtype=float)
    cnt = np.array(counts, dtype=float)
    # interpolation des trous internes
    nans = np.isnan(arr)
    if nans.any():
        arr[nans] = np.interp(np.flatnonzero(nans), np.flatnonzero(~nans), arr[~nans])

    # Retire les mois de fin PARTIELS (échéances futures des factures déjà émises) :
    # un mois dont le nombre de factures s'effondre (< 40% de la médiane) est incomplet.
    med_cnt = np.median(cnt[cnt > 0]) if (cnt > 0).any() else 0
    while len(arr) > 24 and cnt[-1] < 0.4 * med_cnt:
        periods.pop(); arr = arr[:-1]; cnt = cnt[:-1]
    return periods, arr


# ─────────────────────────────────────────────────────────────────────────────
# Modèle LSTM (PyTorch)
# ─────────────────────────────────────────────────────────────────────────────
if _TORCH:
    class _LSTM(nn.Module):
        def __init__(self, hidden: int = 32, layers: int = 1):
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=hidden, num_layers=layers, batch_first=True)
            self.fc = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :])


def _windows(series: np.ndarray, look_back: int) -> Tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for i in range(len(series) - look_back):
        X.append(series[i:i + look_back]); y.append(series[i + look_back])
    return np.array(X), np.array(y)


def _forecast_lstm(z: np.ndarray, horizon: int, look_back: int,
                   epochs: int = 200, seed: int = 42) -> Tuple[np.ndarray, np.ndarray]:
    """Entraîne un LSTM sur la série normalisée z et prévoit `horizon` pas.
    Renvoie (prévisions normalisées, résidus de backtest 1-pas)."""
    torch.manual_seed(seed); np.random.seed(seed)
    X, y = _windows(z, look_back)
    Xt = torch.tensor(X, dtype=torch.float32).unsqueeze(-1)
    yt = torch.tensor(y, dtype=torch.float32).unsqueeze(-1)
    model = _LSTM()
    opt = torch.optim.Adam(model.parameters(), lr=0.01)
    loss_fn = nn.MSELoss()
    model.train()
    for _ in range(epochs):
        opt.zero_grad()
        pred = model(Xt)
        loss = loss_fn(pred, yt)
        loss.backward(); opt.step()
    # résidus de backtest (1 pas) pour la bande de confiance
    model.eval()
    with torch.no_grad():
        fitted = model(Xt).squeeze(-1).numpy()
    resid = y - fitted
    # prévision récursive
    model.eval(); window = list(z[-look_back:]); preds = []
    with torch.no_grad():
        for _ in range(horizon):
            xin = torch.tensor(window[-look_back:], dtype=torch.float32).view(1, look_back, 1)
            nxt = float(model(xin).item())
            preds.append(nxt); window.append(nxt)
    return np.array(preds), resid


# ─────────────────────────────────────────────────────────────────────────────
# Repli NumPy : lissage exponentiel + tendance + saisonnalité (Holt-Winters léger)
# ─────────────────────────────────────────────────────────────────────────────
def _forecast_fallback(z: np.ndarray, horizon: int, season: int = 12,
                       window: int = 30, damping: float = 0.85) -> Tuple[np.ndarray, np.ndarray]:
    """Holt-Winters léger, régime RÉCENT + tendance AMORTIE (évite l'extrapolation
    explosive d'une série à forte croissance)."""
    n = len(z)
    W = min(n, window)
    zr = z[-W:]
    xs = np.arange(W)
    a, b = np.polyfit(xs, zr, 1)          # tendance sur la fenêtre récente
    detr = zr - (a * xs + b)
    seas = np.zeros(season)
    if W >= season:
        for s in range(season):
            vals = detr[s::season]
            if len(vals):
                seas[s] = vals.mean()
        seas -= seas.mean()
    fitted = (a * xs + b) + np.array([seas[i % season] for i in range(W)])
    resid = zr - fitted
    level = a * (W - 1) + b
    preds = []
    cum = 0.0
    for h in range(1, horizon + 1):
        cum += damping ** h            # incrément de tendance amorti
        i = (W - 1) + h
        preds.append(level + a * cum + seas[i % season])
    return np.array(preds), resid


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────
def forecast_cashflow(horizon: int = 6, data_dir: Path | None = None,
                      look_back: int = 12) -> Optional[Dict[str, Any]]:
    """Prévoit les encaissements mensuels sur `horizon` mois.
    Renvoie history, forecast (avec bande de confiance), modèle utilisé et métriques."""
    periods, raw = _load_series(data_dir)
    if len(raw) < look_back + 6:
        return None

    # log-transform (série à forte croissance) + standardisation
    logs = np.log1p(np.clip(raw, 0, None))
    mu, sd = logs.mean(), (logs.std() or 1.0)
    z = (logs - mu) / sd

    used_lb = min(look_back, len(z) - 4)
    if _TORCH:
        try:
            preds_z, resid = _forecast_lstm(z, horizon, used_lb)
            model_name = "LSTM (PyTorch)"
        except Exception:
            preds_z, resid = _forecast_fallback(z, horizon)
            model_name = "Lissage saisonnier (repli)"
    else:
        preds_z, resid = _forecast_fallback(z, horizon)
        model_name = "Lissage saisonnier (repli NumPy)"

    # bande de confiance : σ des résidus en espace log, bornée pour rester réaliste
    sigma = min(float(resid.std() or 0.0), 0.30)

    def _inv(zv: float) -> float:
        return float(np.expm1(zv * sd + mu))

    last = periods[-1]; ly, lm = map(int, last.split("-"))
    forecast: List[Dict[str, Any]] = []
    for h in range(1, horizon + 1):
        m = lm + h; y = ly + (m - 1) // 12; m = ((m - 1) % 12) + 1
        center = _inv(preds_z[h - 1])
        lo = max(0.0, min(_inv(preds_z[h - 1] - 1.96 * sigma), 0.6 * center))
        hi = max(center, min(_inv(preds_z[h - 1] + 1.96 * sigma), 1.7 * center))
        forecast.append({
            "period": f"{y:04d}-{m:02d}",
            "montant": round(max(0.0, center), 0),
            "lower": round(lo, 0),
            "upper": round(hi, 0),
        })

    # métrique de backtest : MAPE 1-pas dans l'espace réel (mois significatifs)
    fitted_real = np.expm1(((z[-len(resid):] - resid) * sd) + mu)
    actual_real = np.expm1((z[-len(resid):] * sd) + mu)
    mask = actual_real > np.median(actual_real) * 0.1  # ignore les mois quasi nuls
    if mask.any():
        mape = float(np.mean(np.abs((actual_real[mask] - fitted_real[mask]) / actual_real[mask])) * 100)
    else:
        mape = 0.0

    history = [{"period": p, "montant": round(float(v), 0)} for p, v in zip(periods, raw)][-18:]
    total_fc = sum(f["montant"] for f in forecast)
    return {
        "model": model_name,
        "horizon": horizon,
        "history": history,
        "forecast": forecast,
        "encaissement_prevu_total": round(total_fc, 0),
        "mape_pct": round(mape, 1),
        "torch": _TORCH,
    }


def load_or_forecast(horizon: int = 6, data_dir: Path | None = None,
                     max_age_hours: float = 12.0) -> Optional[Dict[str, Any]]:
    """Version CACHÉE : réutilise la dernière prévision si elle a moins de
    `max_age_hours`, sinon réentraîne. Évite d'entraîner le LSTM à chaque requête."""
    import json
    import time as _time
    try:
        from config.settings import settings
        out_dir = Path(settings.output_dir)
    except Exception:
        out_dir = Path(__file__).resolve().parents[2] / "output"
    cache = out_dir / "cashflow_forecast.json"
    if cache.exists():
        try:
            age_h = (_time.time() - cache.stat().st_mtime) / 3600.0
            if age_h < max_age_hours:
                return json.load(open(cache, encoding="utf-8"))
        except Exception:
            pass
    res = forecast_cashflow(horizon, data_dir)
    if res:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            json.dump(res, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
    return res


if __name__ == "__main__":
    import json
    res = forecast_cashflow()
    if res:
        print(f"Modèle : {res['model']} | MAPE {res['mape_pct']}%")
        print(f"Encaissement prévu ({res['horizon']} mois) : {res['encaissement_prevu_total']:,.0f} DT".replace(",", " "))
        for f in res["forecast"]:
            print(f"  {f['period']} : {f['montant']:,.0f} DT  [{f['lower']:,.0f} – {f['upper']:,.0f}]".replace(",", " "))
    else:
        print("Série insuffisante.")
