"""
ml_engine/phases/phase5_benchmark.py
====================================
Phase 5 : Benchmarking multi-modèles (Regression, Classification, TimeSeries, Deep Learning).
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

# ── Scikit-Learn Imports ──────────────────────────────────────────────────────
try:
    from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
    from sklearn.linear_model import Ridge
    from sklearn.metrics import (
        accuracy_score, f1_score, mean_absolute_error,
        mean_squared_error, precision_score, r2_score, recall_score,
    )
    from sklearn.model_selection import KFold, TimeSeriesSplit, cross_val_score
    from sklearn.preprocessing import RobustScaler
    from sklearn.pipeline import Pipeline as SklearnPipeline
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# ── Gradient Boosting Imports ─────────────────────────────────────────────────
try:
    from xgboost import XGBClassifier, XGBRegressor
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from catboost import CatBoostClassifier, CatBoostRegressor
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

# ── TimeSeries Imports ────────────────────────────────────────────────────────
try:
    from prophet import Prophet
    HAS_PROPHET = True
except ImportError:
    HAS_PROPHET = False

try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

# ── Deep Learning Imports ─────────────────────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except (ImportError, OSError):
    HAS_TORCH = False


warnings.filterwarnings("ignore")

def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_t, y_p = np.array(y_true, dtype=float), np.array(y_pred, dtype=float)
    non_zero = (y_t != 0) & np.isfinite(y_t) & np.isfinite(y_p)
    if not np.any(non_zero): return float("inf")
    return float(np.mean(np.abs((y_t[non_zero] - y_p[non_zero]) / y_t[non_zero])) * 100)


def _sanitize_forecast(pred: np.ndarray) -> np.ndarray:
    arr = np.asarray(pred, dtype=float)
    arr = np.nan_to_num(arr, nan=0.0, posinf=np.nanmax(arr[np.isfinite(arr)]) if np.isfinite(arr).any() else 0.0, neginf=0.0)
    return np.clip(arr, 0.0, None)


def _build_ts_splits(ts_df: pd.DataFrame, n_test: int, value_col: str = "y") -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    train = ts_df[:-n_test].copy()
    test  = ts_df[-n_test:].copy()
    feat_cols = [c for c in ts_df.columns if c not in ["ds", value_col] and pd.api.types.is_numeric_dtype(ts_df[c])]
    feat_cols = feat_cols or [value_col]
    X_tr = np.nan_to_num(train[feat_cols].fillna(0).values.astype(float))
    y_tr = train[value_col].values
    X_te = np.nan_to_num(test[feat_cols].fillna(0).values.astype(float))
    y_te = test[value_col].values
    return X_tr, y_tr, X_te, y_te


def _timeseries_cv_rmse(model_factory: Any, X: np.ndarray, y: np.ndarray, n_splits: int = 4) -> float:
    if len(X) < 12: return float("inf")
    split_count = min(n_splits, max(2, len(X) - 1))
    splitter = TimeSeriesSplit(n_splits=split_count)
    rmses: List[float] = []
    for tr_idx, va_idx in splitter.split(X):
        model = model_factory()
        model.fit(X[tr_idx], y[tr_idx])
        pred = _sanitize_forecast(model.predict(X[va_idx]))
        rmses.append(float(np.sqrt(mean_squared_error(y[va_idx], pred))))
    return float(np.mean(rmses)) if rmses else float("inf")


def benchmark_regression_models(
    X_train: np.ndarray, X_test: np.ndarray, y_train: np.ndarray, y_test: np.ndarray,
    n_cv: int = 5, time_aware: bool = False,
) -> Dict[str, Dict[str, float]]:
    print("\n    [5.1] Benchmarking modèles de régression...")
    if not HAS_SKLEARN: return {"error": "scikit-learn non installé"}
    
    splitter = TimeSeriesSplit(n_splits=min(n_cv, max(2, len(X_train) - 1))) if time_aware else KFold(n_splits=n_cv, shuffle=True, random_state=42)
    results: Dict[str, Any] = {}

    def _eval(name: str, model: Any) -> None:
        try:
            cv_rmse = np.sqrt(-cross_val_score(model, X_train, y_train, scoring="neg_mean_squared_error", cv=splitter, n_jobs=-1))
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            results[name] = {
                "cv_rmse_mean": round(float(cv_rmse.mean()), 4),
                "test_rmse":    round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4),
                "test_r2":      round(float(r2_score(y_test, y_pred)), 4),
                "test_mape":    round(mape(y_test, y_pred), 4),
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    _eval("random_forest", RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1))
    if HAS_XGB: _eval("xgboost", XGBRegressor(n_estimators=100, max_depth=5, random_state=42, verbosity=0, n_jobs=-1))
    if HAS_LGB: _eval("lightgbm", lgb.LGBMRegressor(n_estimators=100, max_depth=5, random_state=42, verbose=-1, n_jobs=-1))
    if HAS_CATBOOST: _eval("catboost", CatBoostRegressor(iterations=100, depth=5, random_state=42, verbose=0))
    _eval("ridge", Ridge(alpha=10.0))
    return results


def benchmark_classification_models(
    X_train: np.ndarray, X_test: np.ndarray, y_train: np.ndarray, y_test: np.ndarray, n_cv: int = 5,
) -> Dict[str, Dict[str, float]]:
    print("\n    [5.2] Benchmarking modèles de classification...")
    if not HAS_SKLEARN: return {"error": "scikit-learn non installé"}
    
    splitter = KFold(n_splits=n_cv, shuffle=True, random_state=42)
    results: Dict[str, Any] = {}

    def _eval(name: str, model: Any) -> None:
        try:
            cv_f1 = cross_val_score(model, X_train, y_train, scoring="f1_macro", cv=splitter, n_jobs=-1)
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            results[name] = {
                "cv_f1_macro_mean": round(float(cv_f1.mean()), 4),
                "test_accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
                "test_f1_macro": round(float(f1_score(y_test, y_pred, average="macro", zero_division=0)), 4),
            }
        except Exception as e:
            results[name] = {"error": str(e)}

    _eval("random_forest_clf", RandomForestClassifier(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1))
    if HAS_XGB: _eval("xgboost_clf", XGBClassifier(n_estimators=100, max_depth=5, random_state=42, verbosity=0, n_jobs=-1))
    if HAS_LGB: _eval("lightgbm_clf", lgb.LGBMClassifier(n_estimators=100, max_depth=5, random_state=42, verbose=-1, n_jobs=-1))
    if HAS_CATBOOST: _eval("catboost_clf", CatBoostClassifier(iterations=100, depth=5, random_state=42, verbose=0))
    return results


def benchmark_timeseries_models(ts_df: pd.DataFrame, n_test: int = 12, value_col: str = "y") -> Dict[str, Dict[str, Any]]:
    print("\n    [5.3] Benchmarking modèles TS...")
    train_df, test_df = ts_df[:-n_test].copy(), ts_df[-n_test:].copy()
    y_test = test_df[value_col].astype(float).values
    results, ts_predictions = {}, {}

    def _ts_metrics(name: str, y_pred: np.ndarray) -> None:
        y_pred = _sanitize_forecast(y_pred)
        results[name] = {
            "rmse": round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4),
            "mape": round(mape(y_test.astype(float), y_pred), 4),
        }
        ts_predictions[name] = y_pred

    try:
        _ts_metrics("naive_last", np.repeat(float(train_df[value_col].iloc[-1]), n_test))
    except Exception: pass

    if HAS_PROPHET:
        try:
            m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
            m.fit(train_df[["ds", value_col]].rename(columns={value_col: "y"}))
            _ts_metrics("prophet", m.predict(test_df[["ds"]])["yhat"].values)
        except Exception as e: results["prophet"] = {"error": str(e)}
        
    if HAS_STATSMODELS:
        try:
            mod = SARIMAX(train_df[value_col], order=(1,1,1), seasonal_order=(1,1,1,12), enforce_stationarity=False, enforce_invertibility=False)
            _ts_metrics("sarima", mod.fit(disp=False).get_forecast(steps=n_test).predicted_mean.values)
        except Exception as e: results["sarima"] = {"error": str(e)}
        
        try:
            ets = ExponentialSmoothing(train_df[value_col], trend="add", seasonal="add", seasonal_periods=12, initialization_method="estimated").fit()
            _ts_metrics("ets", ets.forecast(n_test))
        except Exception as e: results["ets"] = {"error": str(e)}

    # XGBoost TS
    if HAS_XGB and HAS_SKLEARN:
        try:
            X_tr, y_tr, X_te, y_te = _build_ts_splits(ts_df, n_test, value_col)
            if len(X_tr) > 0:
                model = SklearnPipeline([("scaler", RobustScaler()), ("model", XGBRegressor(random_state=42, verbosity=0, n_jobs=-1, n_estimators=150, max_depth=3))])
                model.fit(X_tr, y_tr)
                _ts_metrics("xgboost_ts", model.predict(X_te))
        except Exception as e: results["xgboost_ts"] = {"error": str(e)}

    # Ensemble
    eligible = [n for n in ts_predictions if n != "naive_last"]
    if len(eligible) >= 2:
        ensemble_pred = np.mean(np.vstack([ts_predictions[name] for name in eligible]), axis=0)
        _ts_metrics("ensemble_mean", ensemble_pred)
        
        mape_eligible = [n for n in eligible if "mape" in results[n] and results[n]["mape"] < 50]
        if len(mape_eligible) >= 2:
            inv_mapes = np.array([1.0 / (results[n]["mape"] + 1e-9) for n in mape_eligible])
            weighted_pred = np.average(np.vstack([ts_predictions[n] for n in mape_eligible]), axis=0, weights=inv_mapes / inv_mapes.sum())
            _ts_metrics("ensemble_weighted", weighted_pred)

    baseline = results.get("naive_last", {})
    base_rmse = baseline.get("rmse", np.nan)
    if np.isfinite(base_rmse) and base_rmse > 0:
        for name, metrics in results.items():
            if "rmse" in metrics: metrics["rmse_gain_vs_naive_pct"] = round((base_rmse - float(metrics["rmse"])) / base_rmse * 100.0, 2)
            
    return results


def benchmark_dl_models(ts_df: pd.DataFrame, n_test: int = 12, value_col: str = "y") -> Dict[str, Dict[str, Any]]:
    print("\n    [5.4] Benchmarking DL (LSTM/GRU)...")
    if not HAS_TORCH: return {"note": "PyTorch required"}
    
    series = ts_df[value_col].values.astype(float)
    if len(series) <= n_test + 8: return {"note": "Série trop courte pour DL"}
    
    # Placeholder simple LSTM
    results: Dict[str, Any] = {}
    train_series = series[:-n_test]
    mean_s, std_s = float(np.mean(train_series)), float(np.std(train_series) + 1e-9)
    
    try:
        class _RNNModel(nn.Module):
            def __init__(self, cell="lstm"):
                super().__init__()
                rnn_cls = nn.LSTM if cell == "lstm" else nn.GRU
                self.rnn = rnn_cls(1, 16, 1, batch_first=True)
                self.fc  = nn.Linear(16, 1)
            def forward(self, x):
                out, _ = self.rnn(x)
                return self.fc(out[:, -1, :])

        X, y = [], []
        seq_len = min(6, len(series) - n_test - 1)
        norm_series = (series - mean_s) / std_s
        for i in range(len(norm_series) - seq_len):
            X.append(norm_series[i:i + seq_len])
            y.append(norm_series[i + seq_len])
        X_all, y_all = np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)
        
        split = len(X_all) - n_test
        X_tr = torch.tensor(X_all[:split]).unsqueeze(-1)
        y_tr = torch.tensor(y_all[:split]).unsqueeze(-1)
        
        def train_and_eval(cell: str) -> None:
            model = _RNNModel(cell)
            optimizer = optim.Adam(model.parameters(), lr=0.01)
            criterion = nn.MSELoss()
            for _ in range(30):
                optimizer.zero_grad()
                criterion(model(X_tr), y_tr).backward()
                optimizer.step()
                
            model.eval()
            last_seq = torch.tensor(norm_series[split-seq_len:split], dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
            preds = []
            with torch.no_grad():
                for _ in range(n_test):
                    p = model(last_seq)
                    preds.append(p.item())
                    last_seq = torch.cat([last_seq[:, 1:, :], p.unsqueeze(-1)], dim=1)
            
            y_pred = _sanitize_forecast(np.array(preds) * std_s + mean_s)
            y_test = series[-n_test:]
            results[cell] = {
                "rmse": round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4),
                "mape": round(mape(y_test, y_pred), 4),
            }
            
        train_and_eval("lstm")
        train_and_eval("gru")
    except Exception as e:
        results["dl_error"] = str(e)
        
    return results
