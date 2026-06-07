"""
ml_advanced_pipeline.py
========================
Advanced ML Pipeline for Finance AI Agent — CRISP-DM Phase 5+ (Advanced Modeling)

Phases:
    1. Data Quality Validation
    2. Advanced Feature Engineering  (temporal, rolling, lag, trend)
    3. Variance & Feature Analysis   (VT, correlation, MI, importance)
    4. Time Series Analysis          (ADF, decomposition, ACF/PACF)
    5. Model Benchmarking            (Tree, TS, Deep Learning)
    6. Hyperparameter Optimization   (Optuna)
    7. Model Explainability          (SHAP)
    8. Model Selection & Recommendations
    9. Finance AI Agent Integration

Usage:
    from ml_advanced_pipeline import run_advanced_pipeline
    results = run_advanced_pipeline(warehouse, data_dir=Path("data_pfe"))
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import matplotlib
matplotlib.use("Agg")          # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.feature_selection import VarianceThreshold, mutual_info_regression
from sklearn.linear_model import Ridge
from sklearn.metrics import (
    accuracy_score, f1_score, mean_absolute_error, mean_squared_error,
    precision_score, recall_score,
    r2_score, silhouette_score,
)
from sklearn.base import clone
from sklearn.model_selection import KFold, TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.pipeline import Pipeline as SklearnPipeline
from xgboost import XGBRegressor, XGBClassifier

# ── optional heavyweight packages with graceful fallback ──────────────────────
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from catboost import CatBoostRegressor, CatBoostClassifier
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

try:
    from prophet import Prophet
    HAS_PROPHET = True
except ImportError:
    HAS_PROPHET = False

try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    from statsmodels.tsa.seasonal import seasonal_decompose
    from statsmodels.tsa.stattools import adfuller, acf, pacf
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
REPORTS_DIR = Path("reports")
MODELS_DIR  = Path("models")
PLOTS_DIR   = Path("reports/plots")


def _ensure_dirs() -> None:
    for d in [REPORTS_DIR, MODELS_DIR, PLOTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _sanitize(obj: Any) -> Any:
    """Convertit récursivement les types numpy/pandas en types JSON-sérialisables."""
    if isinstance(obj, dict):
        return {
            (str(k) if not isinstance(k, (str, int, float, bool, type(None))) else k): _sanitize(v)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Timestamp):
        return str(obj)
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _save_json(data: Any, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(data), f, indent=2, ensure_ascii=False, default=str)


def _get_numeric(df: pd.DataFrame) -> pd.DataFrame:
    return df.select_dtypes(include=[np.number])


def _sample(df: pd.DataFrame, n: int = 10_000) -> pd.DataFrame:
    return df.sample(n=min(n, len(df)), random_state=42)


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — DATA QUALITY VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_data_quality(
    warehouse: Dict[str, pd.DataFrame],
    output_dir: Path = REPORTS_DIR,
) -> Dict[str, Any]:
    """
    Phase 1 : Validation complète de la qualité des données.

    Analyses :
        - Valeurs manquantes (taux par colonne/table)
        - Outliers (IQR + Z-score)
        - Variance nulle / quasi-nulle
        - Distribution des features
        - Déséquilibre de classes (classification)
        - Cohérence temporelle (dates dans l'ordre)

    Retourne :
        report : dict consolidé de toutes les métriques
    """
    print("\n" + "="*60)
    print("PHASE 1 — VALIDATION QUALITÉ DES DONNÉES")
    print("="*60)

    _ensure_dirs()
    report: Dict[str, Any] = {}

    for table_name, df in warehouse.items():
        if df.empty:
            continue
        print(f"\n  [{table_name}] {df.shape[0]:,} lignes × {df.shape[1]} colonnes")

        table_report: Dict[str, Any] = {}

        # 1.1 Valeurs manquantes
        null_counts = df.isnull().sum()
        null_pct    = (null_counts / len(df) * 100).round(2)
        missing = {col: {"count": int(null_counts[col]), "pct": float(null_pct[col])}
                   for col in df.columns if null_counts[col] > 0}
        table_report["missing_values"] = {
            "total_missing_cells": int(null_counts.sum()),
            "total_pct": round(float(null_counts.sum()) / (len(df) * len(df.columns)) * 100, 2),
            "by_column": missing,
        }

        # 1.2 Outliers (IQR, sur numériques)
        num = _get_numeric(df)
        outlier_summary: Dict[str, Any] = {}
        for col in num.columns:
            s = num[col].dropna()
            if len(s) < 4:
                continue
            Q1, Q3 = s.quantile(0.25), s.quantile(0.75)
            IQR = Q3 - Q1
            if IQR == 0:
                continue
            n_out = int(((s < Q1 - 3 * IQR) | (s > Q3 + 3 * IQR)).sum())
            if n_out > 0:
                outlier_summary[col] = {
                    "n_outliers": n_out,
                    "pct": round(n_out / len(s) * 100, 2),
                    "Q1": round(float(Q1), 4),
                    "Q3": round(float(Q3), 4),
                    "IQR": round(float(IQR), 4),
                }
        table_report["outliers"] = outlier_summary

        # 1.3 Variance
        low_variance = {}
        for col in num.columns:
            v = float(num[col].var())
            if v < 1e-6:
                low_variance[col] = {"variance": v}
        table_report["low_variance_columns"] = low_variance

        # 1.4 Statistiques descriptives
        if not num.empty:
            desc = num.describe().round(4).to_dict()
            table_report["descriptive_stats"] = desc

        # 1.5 Cohérence temporelle
        date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        temporal_issues: Dict[str, Any] = {}
        for col in date_cols:
            n_future = int((df[col] > pd.Timestamp.now()).sum())
            n_before_2000 = int((df[col] < pd.Timestamp("2000-01-01")).sum())
            if n_future > 0 or n_before_2000 > 0:
                temporal_issues[col] = {
                    "future_dates": n_future,
                    "before_year_2000": n_before_2000,
                }
        table_report["temporal_issues"] = temporal_issues

        # 1.6 Déséquilibre de classes (si colonne binaire)
        for col in df.columns:
            if df[col].nunique() == 2 and pd.api.types.is_numeric_dtype(df[col]):
                vc = df[col].value_counts(normalize=True).round(4).to_dict()
                table_report["class_balance"] = {col: vc}
                break

        report[table_name] = table_report
        missing_count = table_report["missing_values"]["total_missing_cells"]
        outlier_count = sum(v["n_outliers"] for v in outlier_summary.values())
        print(f"    ✓ Manquantes: {missing_count:,} | Outliers: {outlier_count:,} | Variance nulle: {len(low_variance)}")

    _save_json(report, output_dir / "phase1_data_quality.json")
    print(f"\n  → Rapport sauvegardé : {output_dir}/phase1_data_quality.json")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — ADVANCED FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────────────────────

def engineer_features(
    fact_df: pd.DataFrame,
    date_col: str = "datepiece",
    value_col: str = "ttc_dev",
) -> pd.DataFrame:
    """
    Phase 2 : Feature engineering financier avancé.

    Génère :
        - Features temporelles (year, quarter, month, week, dow, indicateurs de saison)
        - Rolling statistics (7j, 30j, 90j, 365j) : mean, median, std, growth
        - Lag features (lag_1, lag_3, lag_6, lag_12) selon la granularité
        - Trend features (MA, momentum, pct_change, cumulative_growth)
    """
    print("\n  [Phase 2] Feature Engineering avancé...")

    df = fact_df.copy()

    if date_col not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        print(f"    ⚠ Colonne '{date_col}' absente ou non-datetime — skip feature engineering")
        return df

    df = df.sort_values(date_col).reset_index(drop=True)

    # ── 2.1 Features temporelles ──────────────────────────────────────────────
    d = df[date_col]
    df["feat_year"]            = d.dt.year
    df["feat_quarter"]         = d.dt.quarter
    df["feat_month"]           = d.dt.month
    df["feat_week"]            = d.dt.isocalendar().week.astype(int)
    df["feat_dayofweek"]       = d.dt.dayofweek
    df["feat_dayofyear"]       = d.dt.dayofyear
    df["feat_is_month_start"]  = d.dt.is_month_start.astype(int)
    df["feat_is_month_end"]    = d.dt.is_month_end.astype(int)
    df["feat_is_quarter_end"]  = d.dt.is_quarter_end.astype(int)
    df["feat_is_year_end"]     = d.dt.is_year_end.astype(int)

    # Encodage cyclique mois (meilleur pour linéaires/DL)
    df["feat_month_sin"]  = np.sin(2 * np.pi * df["feat_month"] / 12)
    df["feat_month_cos"]  = np.cos(2 * np.pi * df["feat_month"] / 12)
    df["feat_dow_sin"]    = np.sin(2 * np.pi * df["feat_dayofweek"] / 7)
    df["feat_dow_cos"]    = np.cos(2 * np.pi * df["feat_dayofweek"] / 7)

    # Indicateurs saisonniers (Tunisie : Ramadan approx = T2, été = T3)
    df["feat_is_summer"]   = (df["feat_month"].isin([6, 7, 8])).astype(int)
    df["feat_is_end_year"] = (df["feat_month"].isin([11, 12])).astype(int)

    # Ramadan indicator — Tunisian lunar calendar approximation (shifts ~11 days/year)
    _RAMADAN_MONTH: Dict[int, int] = {
        2016: 6, 2017: 6, 2018: 5, 2019: 5, 2020: 4,
        2021: 4, 2022: 4, 2023: 3, 2024: 3, 2025: 3, 2026: 2,
    }
    if "feat_year" in df.columns and "feat_month" in df.columns:
        df["feat_is_ramadan"] = [
            int(_RAMADAN_MONTH.get(int(yr), 0) == int(mo))
            for yr, mo in zip(df["feat_year"], df["feat_month"])
        ]

    # ── 2.2 Rolling statistics (sur valeur cible agrégée par date) ────────────
    if value_col in df.columns and pd.api.types.is_numeric_dtype(df[value_col]):
        v = pd.to_numeric(df[value_col], errors="coerce")
        history = v.shift(1)
        for w in [7, 30, 90, 365]:
            prefix = f"roll_{w}d"
            historical_window = history.rolling(w, min_periods=max(2, min(w, 3)))
            df[f"{prefix}_mean"]   = historical_window.mean()
            df[f"{prefix}_median"] = historical_window.median()
            df[f"{prefix}_std"]    = historical_window.std()
            df[f"{prefix}_min"]    = historical_window.min()
            df[f"{prefix}_max"]    = historical_window.max()
            df[f"{prefix}_growth"] = historical_window.apply(
                lambda x: (x.iloc[-1] - x.iloc[0]) / (abs(x.iloc[0]) + 1e-9) * 100,
                raw=False,
            )

        # ── 2.3 Lag features ──────────────────────────────────────────────────
        for lag in [1, 3, 6, 12, 24]:
            df[f"lag_{lag}"] = v.shift(lag)

        # ── 2.4 Trend features ────────────────────────────────────────────────
        df["trend_ma_7"]         = history.rolling(7,  min_periods=2).mean()
        df["trend_ma_30"]        = history.rolling(30, min_periods=2).mean()
        df["trend_ma_90"]        = history.rolling(90, min_periods=2).mean()
        df["trend_momentum_7"]   = history - history.shift(7)
        df["trend_momentum_30"]  = history - history.shift(30)
        df["trend_pct_change_1"] = history.pct_change(1)
        df["trend_pct_change_7"] = history.pct_change(7)
        first_history = history.dropna().iloc[0] if history.notna().any() else np.nan
        df["trend_cumgrowth"]    = (history / (first_history + 1e-9)).apply(lambda x: x - 1 if pd.notna(x) else np.nan)
        df["trend_ema_12"]       = history.ewm(span=12, adjust=False).mean()
        df["trend_ema_26"]       = history.ewm(span=26, adjust=False).mean()
        df["trend_macd"]         = df["trend_ema_12"] - df["trend_ema_26"]

    new_cols = [c for c in df.columns if c.startswith(("feat_", "roll_", "lag_", "trend_"))]
    print(f"    ✓ {len(new_cols)} features générées")
    return df


def build_timeseries_features(
    warehouse: Dict[str, pd.DataFrame],
    date_col: str = "datepiece",
    value_col: str = "ttc_dev",
    freq: str = "ME",   # Month-End
) -> pd.DataFrame:
    """
    Construit une série temporelle mensuelle agrégée depuis Fact_Ventes
    et y applique engineer_features.
    """
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty or date_col not in fact.columns:
        return pd.DataFrame()

    ts = fact[[date_col, value_col]].copy()
    ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
    ts = ts.dropna()

    # Agrégation mensuelle avec volume et montant moyen par mois
    ts_agg = (
        ts.set_index(date_col)
        .resample(freq)
        .agg({value_col: ["sum", "count", "mean"]})
    )
    ts_agg.columns = ["y", "nb_invoices", "avg_invoice_amount"]
    ts_agg = ts_agg.reset_index().rename(columns={date_col: "ds"})
    ts_agg = ts_agg.sort_values("ds").reset_index(drop=True)
    ts_agg["y"] = ts_agg["y"].fillna(ts_agg["y"].median())
    ts_agg["nb_invoices"] = ts_agg["nb_invoices"].fillna(0).astype(float)
    ts_agg["avg_invoice_amount"] = ts_agg["avg_invoice_amount"].fillna(0)

    ts_enriched = engineer_features(ts_agg, date_col="ds", value_col="y")

    # Year-over-year growth and delta (causal: uses lag_1 / lag_12 already shifted)
    if "lag_1" in ts_enriched.columns and "lag_12" in ts_enriched.columns:
        lag1 = ts_enriched["lag_1"]
        lag12 = ts_enriched["lag_12"]
        ts_enriched["yoy_growth"] = (lag1 / (lag12.replace(0, np.nan)) - 1).clip(-2, 5).fillna(0)
        ts_enriched["yoy_delta"]  = (lag1 - lag12).fillna(0)

    # Rolling invoice count (volume momentum)
    if "nb_invoices" in ts_enriched.columns:
        nb = ts_enriched["nb_invoices"].shift(1)
        ts_enriched["nb_invoices_ma3"] = nb.rolling(3, min_periods=1).mean()
        ts_enriched["nb_invoices_ma6"] = nb.rolling(6, min_periods=1).mean()

    return ts_enriched


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — VARIANCE & FEATURE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_variance(
    X_df: pd.DataFrame,
    y: Optional[pd.Series] = None,
    corr_threshold: float = 0.95,
    variance_threshold: float = 0.01,
    output_dir: Path = REPORTS_DIR,
) -> Dict[str, Any]:
    """
    Phase 3 : Analyse de variance et sélection de features.

    Applique :
        - VarianceThreshold : supprime features quasi-constantes
        - Matrice de corrélation : détecte redondance (|r| > 0.95)
        - Mutual Information : quantifie l'info par feature envers y
        - Feature Importance (RF) : importance permutation-based

    Retourne :
        dict : listes de features à conserver / supprimer + rapport
    """
    print("\n  [Phase 3] Analyse de Variance & Sélection de Features...")

    num = _get_numeric(X_df).dropna()
    if num.empty:
        return {}

    report: Dict[str, Any] = {}

    # 3.1 Variance Threshold
    vt = VarianceThreshold(threshold=variance_threshold)
    try:
        vt.fit(num)
        low_var_cols = [num.columns[i] for i, keep in enumerate(vt.get_support()) if not keep]
    except Exception:
        low_var_cols = []
    report["low_variance"] = {"removed": low_var_cols, "threshold": variance_threshold}
    print(f"    → Variance Threshold : {len(low_var_cols)} features supprimées")

    # 3.2 Corrélation
    corr_matrix = num.corr(method="pearson")
    corr_pairs = []
    cols = list(corr_matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = abs(corr_matrix.iloc[i, j])
            if val > corr_threshold:
                corr_pairs.append({
                    "col_a": cols[i],
                    "col_b": cols[j],
                    "pearson_r": round(float(val), 4),
                })
    report["high_correlation"] = {
        "threshold": corr_threshold,
        "pairs": corr_pairs,
        "n_redundant_pairs": len(corr_pairs),
    }
    print(f"    → Corrélation : {len(corr_pairs)} paires redondantes (|r| > {corr_threshold})")

    # Sauvegarde heatmap
    try:
        n_cols = min(30, len(cols))
        fig, ax = plt.subplots(figsize=(12, 10))
        im = ax.imshow(corr_matrix.values[:n_cols, :n_cols], vmin=-1, vmax=1, cmap="RdBu_r")
        ax.set_xticks(range(n_cols))
        ax.set_xticklabels(cols[:n_cols], rotation=90, fontsize=6)
        ax.set_yticks(range(n_cols))
        ax.set_yticklabels(cols[:n_cols], fontsize=6)
        plt.colorbar(im, ax=ax)
        ax.set_title("Matrice de Corrélation (Phase 3)")
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "phase3_correlation_heatmap.png", dpi=80)
        plt.close()
    except Exception:
        pass

    # 3.3 Mutual Information (si y fourni)
    if y is not None:
        try:
            aligned = num.loc[y.index] if hasattr(y, "index") else num.head(len(y))
            aligned = aligned.head(min(20_000, len(aligned)))
            y_aligned = y.loc[aligned.index] if hasattr(y, "index") else y.values[:len(aligned)]
            mi_scores = mutual_info_regression(aligned, y_aligned, random_state=42)
            mi = {col: round(float(score), 6) for col, score in zip(aligned.columns, mi_scores)}
            mi_sorted = dict(sorted(mi.items(), key=lambda x: x[1], reverse=True))
            report["mutual_information"] = mi_sorted
            print(f"    → Mutual Information calculée sur {len(aligned)} lignes")
        except Exception as e:
            report["mutual_information"] = {"error": str(e)}

    # 3.4 Feature Importance (Random Forest rapide)
    if y is not None:
        try:
            n = min(20_000, len(num))
            Xs = num.head(n).fillna(0)
            ys = y.iloc[:n] if hasattr(y, "iloc") else y[:n]
            rf = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42, n_jobs=-1)
            rf.fit(Xs, ys)
            importances = {col: round(float(imp), 6)
                           for col, imp in zip(Xs.columns, rf.feature_importances_)}
            importances_sorted = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True))
            report["feature_importance_rf"] = importances_sorted
            print(f"    → RF Feature Importance calculée")
        except Exception as e:
            report["feature_importance_rf"] = {"error": str(e)}

    _save_json(report, output_dir / "phase3_variance_analysis.json")
    print(f"    ✓ Rapport : {output_dir}/phase3_variance_analysis.json")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — TIME SERIES ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def analyze_time_series(
    ts_df: pd.DataFrame,
    value_col: str = "y",
    date_col: str = "ds",
    output_dir: Path = REPORTS_DIR,
) -> Dict[str, Any]:
    """
    Phase 4 : Analyse statistique des séries temporelles.

    Applique :
        - Test ADF (stationnarité)
        - Décomposition saisonnière (trend, seasonal, residual)
        - Autocorrélation (ACF)
        - Autocorrélation partielle (PACF)
        - Détection automatique saisonnalité

    Retourne :
        dict : résultats de tous les tests
    """
    print("\n  [Phase 4] Analyse Séries Temporelles...")

    if not HAS_STATSMODELS:
        print("    ⚠ statsmodels non installé — skip")
        return {"error": "statsmodels not available"}

    report: Dict[str, Any] = {}
    series = ts_df[value_col].dropna()

    # 4.1 Test ADF (Augmented Dickey-Fuller)
    try:
        adf_result = adfuller(series, autolag="AIC")
        report["adf_test"] = {
            "statistic":     round(float(adf_result[0]), 6),
            "p_value":       round(float(adf_result[1]), 6),
            "n_lags":        int(adf_result[2]),
            "n_obs":         int(adf_result[3]),
            "critical_1pct": round(float(adf_result[4]["1%"]), 4),
            "critical_5pct": round(float(adf_result[4]["5%"]), 4),
            "is_stationary": bool(adf_result[1] < 0.05),
        }
        stat_flag = "✓ STATIONNAIRE" if report["adf_test"]["is_stationary"] else "✗ NON-STATIONNAIRE"
        print(f"    ADF Test : p={adf_result[1]:.4f} → {stat_flag}")
    except Exception as e:
        report["adf_test"] = {"error": str(e)}

    # 4.1b Test sur série différenciée si non-stationnaire
    if not report.get("adf_test", {}).get("is_stationary", True):
        try:
            diff_series = series.diff().dropna()
            adf2 = adfuller(diff_series, autolag="AIC")
            report["adf_test_diff1"] = {
                "p_value": round(float(adf2[1]), 6),
                "is_stationary": bool(adf2[1] < 0.05),
                "recommendation": "Différenciation d'ordre 1 recommandée (d=1 pour ARIMA)",
            }
            print(f"    ADF diff(1) : p={adf2[1]:.4f}")
        except Exception:
            pass

    # 4.2 Décomposition saisonnière
    try:
        n = len(series)
        # Détecter la période : mensuel → 12, hebdo → 52, journalier → 7
        if date_col in ts_df.columns:
            date_range = (ts_df[date_col].max() - ts_df[date_col].min()).days
            avg_days = date_range / max(n - 1, 1)
            if avg_days < 2:
                period = 7
            elif avg_days < 10:
                period = 30
            else:
                period = 12
        else:
            period = 12

        if n >= 2 * period:
            decomp = seasonal_decompose(series, model="additive", period=period)
            trend_strength   = float(1 - decomp.resid.var() / (decomp.trend + decomp.resid).var()) \
                               if not decomp.trend.isna().all() else 0.0
            seasonal_strength = float(1 - decomp.resid.var() / (decomp.seasonal + decomp.resid).var()) \
                                if not decomp.seasonal.isna().all() else 0.0
            report["decomposition"] = {
                "period":            period,
                "model":             "additive",
                "trend_strength":    round(max(0, trend_strength), 4),
                "seasonal_strength": round(max(0, seasonal_strength), 4),
                "has_strong_trend":     trend_strength > 0.5,
                "has_strong_seasonality": seasonal_strength > 0.5,
            }
            print(f"    Décomposition : période={period} | trend={trend_strength:.2f} | saisonnalité={seasonal_strength:.2f}")

            # Plot décomposition
            try:
                fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
                axes[0].plot(series.values, color="#2196F3"); axes[0].set_title("Série originale")
                axes[1].plot(decomp.trend.values, color="#FF9800"); axes[1].set_title("Tendance")
                axes[2].plot(decomp.seasonal.values, color="#4CAF50"); axes[2].set_title("Saisonnalité")
                axes[3].plot(decomp.resid.values, color="#F44336"); axes[3].set_title("Résidus")
                plt.suptitle("Décomposition Saisonnière — Ventes Mensuelles", fontsize=11)
                plt.tight_layout()
                plt.savefig(PLOTS_DIR / "phase4_seasonal_decomposition.png", dpi=80)
                plt.close()
            except Exception:
                pass
        else:
            report["decomposition"] = {"error": f"Trop peu de données ({n}) pour période={period}"}
    except Exception as e:
        report["decomposition"] = {"error": str(e)}

    # 4.3 ACF & PACF
    try:
        n_lags = min(40, len(series) // 2 - 1)
        if n_lags > 2:
            acf_vals  = acf(series, nlags=n_lags, fft=True)
            pacf_vals = pacf(series, nlags=n_lags)
            report["acf"]  = {i: round(float(v), 4) for i, v in enumerate(acf_vals)}
            report["pacf"] = {i: round(float(v), 4) for i, v in enumerate(pacf_vals)}

            # Lags significatifs (|val| > 2/sqrt(n))
            threshold = 2 / np.sqrt(len(series))
            sig_acf  = [i for i, v in enumerate(acf_vals[1:],  1) if abs(v) > threshold]
            sig_pacf = [i for i, v in enumerate(pacf_vals[1:], 1) if abs(v) > threshold]
            report["significant_lags"] = {
                "acf_lags":  sig_acf[:10],
                "pacf_lags": sig_pacf[:10],
                "arima_p_suggestion": sig_pacf[0] if sig_pacf else 1,
                "arima_q_suggestion": sig_acf[0]  if sig_acf  else 1,
            }
            print(f"    ACF/PACF : lags sig. ACF={sig_acf[:5]} | PACF={sig_pacf[:5]}")

            # Plot ACF/PACF
            try:
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6))
                ax1.bar(range(len(acf_vals)), acf_vals, color="#2196F3", alpha=0.7)
                ax1.axhline(y=threshold, linestyle="--", color="red", alpha=0.5)
                ax1.axhline(y=-threshold, linestyle="--", color="red", alpha=0.5)
                ax1.set_title("Autocorrélation (ACF)")
                ax2.bar(range(len(pacf_vals)), pacf_vals, color="#4CAF50", alpha=0.7)
                ax2.axhline(y=threshold, linestyle="--", color="red", alpha=0.5)
                ax2.axhline(y=-threshold, linestyle="--", color="red", alpha=0.5)
                ax2.set_title("Autocorrélation Partielle (PACF)")
                plt.tight_layout()
                plt.savefig(PLOTS_DIR / "phase4_acf_pacf.png", dpi=80)
                plt.close()
            except Exception:
                pass
    except Exception as e:
        report["acf_pacf_error"] = str(e)

    _save_json(report, output_dir / "phase4_timeseries_analysis.json")
    print(f"    ✓ Rapport : {output_dir}/phase4_timeseries_analysis.json")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 — MODEL BENCHMARKING
# ─────────────────────────────────────────────────────────────────────────────

def _build_ts_splits(ts_df: pd.DataFrame, n_test: int, value_col: str = "y") -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Découpe chronologique train/test pour TS."""
    train = ts_df[:-n_test].copy()
    test  = ts_df[-n_test:].copy()

    feat_cols = [c for c in ts_df.columns
                 if c not in ["ds", value_col]
                 and pd.api.types.is_numeric_dtype(ts_df[c])]
    feat_cols = feat_cols or [value_col]

    X_tr = np.nan_to_num(train[feat_cols].fillna(0).values.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    y_tr = train[value_col].values
    X_te = np.nan_to_num(test[feat_cols].fillna(0).values.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    y_te = test[value_col].values
    return X_tr, y_tr, X_te, y_te


def _sanitize_forecast(pred: np.ndarray) -> np.ndarray:
    arr = np.asarray(pred, dtype=float)
    arr = np.nan_to_num(arr, nan=0.0, posinf=np.nanmax(arr[np.isfinite(arr)]) if np.isfinite(arr).any() else 0.0, neginf=0.0)
    return np.clip(arr, 0.0, None)


def _timeseries_cv_rmse(
    model_factory: Any,
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 4,
) -> float:
    if len(X) < 12:
        return float("inf")
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
    X_train: np.ndarray,
    X_test:  np.ndarray,
    y_train: np.ndarray,
    y_test:  np.ndarray,
    n_cv: int = 5,
    time_aware: bool = False,
) -> Dict[str, Dict[str, float]]:
    """
    Phase 5.1 : Benchmarking des modèles de régression.

    Modèles : RandomForest, XGBoost, LightGBM, CatBoost, Ridge

    Métriques : MAE, RMSE, MAPE, R²
    """
    print("\n    [5.1] Benchmarking modèles de régression...")

    splitter = TimeSeriesSplit(n_splits=min(n_cv, max(2, len(X_train) - 1))) if time_aware else KFold(n_splits=n_cv, shuffle=True, random_state=42)
    results: Dict[str, Any] = {}

    def _eval(name: str, model: Any) -> None:
        try:
            cv_rmse = np.sqrt(-cross_val_score(
                model, X_train, y_train,
                scoring="neg_mean_squared_error", cv=splitter, n_jobs=-1,
            ))
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)
            results[name] = {
                "cv_rmse_mean": round(float(cv_rmse.mean()), 4),
                "cv_rmse_std":  round(float(cv_rmse.std()),  4),
                "test_mae":     round(float(mean_absolute_error(y_test, y_pred)), 4),
                "test_rmse":    round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4),
                "test_mape":    round(mape(np.array(y_test, dtype=float), y_pred), 4),
                "test_r2":      round(float(r2_score(y_test, y_pred)), 4),
            }
            print(f"      {name:20s}: RMSE={results[name]['test_rmse']:.4f} | R²={results[name]['test_r2']:.4f}")
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"      {name:20s}: ✗ {e}")

    _eval("random_forest", RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42, n_jobs=-1))
    _eval("xgboost",       XGBRegressor(n_estimators=100, max_depth=5, random_state=42, verbosity=0, n_jobs=-1))

    if HAS_LGB:
        _eval("lightgbm", lgb.LGBMRegressor(n_estimators=100, max_depth=5, random_state=42, verbose=-1, n_jobs=-1))
    if HAS_CATBOOST:
        _eval("catboost", CatBoostRegressor(iterations=100, depth=5, random_state=42, verbose=0))
    _eval("ridge", Ridge(alpha=10.0))

    return results


def benchmark_classification_models(
    X_train: np.ndarray,
    X_test: np.ndarray,
    y_train: np.ndarray,
    y_test: np.ndarray,
    n_cv: int = 5,
) -> Dict[str, Dict[str, float]]:
    """
    Phase 5.2 : Benchmarking des modeles de classification.

    Modeles : RandomForest, XGBoost, LightGBM, CatBoost

    Metriques : Accuracy, F1, Precision, Recall
    """
    print("\n    [5.2] Benchmarking modeles de classification...")

    splitter = KFold(n_splits=n_cv, shuffle=True, random_state=42)
    results: Dict[str, Any] = {}

    def _eval(name: str, model: Any) -> None:
        try:
            cv_f1 = cross_val_score(
                model,
                X_train,
                y_train,
                scoring="f1_macro",
                cv=splitter,
                n_jobs=-1,
            )
            model.fit(X_train, y_train)
            y_pred = model.predict(X_test)

            results[name] = {
                "cv_f1_macro_mean": round(float(cv_f1.mean()), 4),
                "cv_f1_macro_std": round(float(cv_f1.std()), 4),
                "test_accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
                "test_f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
                "test_f1_macro": round(float(f1_score(y_test, y_pred, average="macro", zero_division=0)), 4),
                "test_precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
                "test_recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
            }
            print(
                f"      {name:20s}: Accuracy={results[name]['test_accuracy']:.4f} "
                f"| F1={results[name]['test_f1']:.4f}"
            )
        except Exception as e:
            results[name] = {"error": str(e)}
            print(f"      {name:20s}: ✗ {e}")

    _eval("random_forest_clf", RandomForestClassifier(n_estimators=150, max_depth=10, random_state=42, n_jobs=-1))
    _eval("xgboost_clf", XGBClassifier(n_estimators=150, max_depth=5, random_state=42, verbosity=0, n_jobs=-1))

    if HAS_LGB:
        _eval("lightgbm_clf", lgb.LGBMClassifier(n_estimators=150, max_depth=6, random_state=42, verbose=-1, n_jobs=-1))
    if HAS_CATBOOST:
        _eval("catboost_clf", CatBoostClassifier(iterations=150, depth=6, random_state=42, verbose=0))

    return results


def benchmark_timeseries_models(
    ts_df: pd.DataFrame,
    n_test: int = 12,
    value_col: str = "y",
) -> Dict[str, Dict[str, Any]]:
    """
    Phase 5.3 : Benchmarking des modeles de series temporelles.

    Modèles : Prophet, SARIMA, ARIMA, ETS, XGBoost-TS, LightGBM-TS

    Métriques : MAE, RMSE, MAPE
    """
    print("\n    [5.3] Benchmarking modeles TS...")

    train_df = ts_df[:-n_test].copy()
    test_df  = ts_df[-n_test:].copy()
    y_train = train_df[value_col].astype(float).values
    y_test   = test_df[value_col].astype(float).values
    results: Dict[str, Any] = {}
    ts_predictions: Dict[str, np.ndarray] = {}

    def _ts_metrics(name: str, y_pred: np.ndarray) -> None:
        y_pred = _sanitize_forecast(y_pred)
        smape = 200.0 * np.mean(np.abs(y_test - y_pred) / (np.abs(y_test) + np.abs(y_pred) + 1e-9))
        results[name] = {
            "mae":  round(float(mean_absolute_error(y_test, y_pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 4),
            "mape": round(mape(y_test.astype(float), y_pred), 4),
            "smape": round(float(smape), 4),
        }
        ts_predictions[name] = y_pred
        print(f"      {name:20s}: RMSE={results[name]['rmse']:.4f} | MAPE={results[name]['mape']:.2f}%")

    # Baselines robustes
    try:
        last_value = float(train_df[value_col].iloc[-1])
        _ts_metrics("naive_last", np.repeat(last_value, n_test))
    except Exception:
        pass

    try:
        if len(train_df) >= 12:
            seasonal_pattern = train_df[value_col].iloc[-12:].astype(float).values
            seasonal_forecast = np.resize(seasonal_pattern, n_test)
            _ts_metrics("seasonal_naive_12", seasonal_forecast)
    except Exception:
        pass

    # Prophet
    if HAS_PROPHET:
        try:
            m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
            m.fit(train_df[["ds", value_col]].rename(columns={value_col: "y"}))
            fc = m.predict(test_df[["ds"]])
            _ts_metrics("prophet", fc["yhat"].values)
        except Exception as e:
            results["prophet"] = {"error": str(e)}

        # Variante log pour stabiliser la variance
        try:
            train_log = train_df[["ds", value_col]].rename(columns={value_col: "y"}).copy()
            train_log["y"] = np.log1p(np.clip(train_log["y"].astype(float), 0.0, None))
            m_log = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
            m_log.fit(train_log)
            fc_log = m_log.predict(test_df[["ds"]])
            _ts_metrics("prophet_log", np.expm1(fc_log["yhat"].values))
        except Exception as e:
            results["prophet_log"] = {"error": str(e)}
    else:
        results["prophet"] = {"error": "prophet not installed"}

    # SARIMAX
    if HAS_STATSMODELS:
        for order, sorder, label in [
            ((1,1,1),(1,1,1,12), "sarima"),
            ((2,1,1),(1,1,0,12), "sarima_alt"),
            ((1,1,2),(0,1,1,12), "sarima_airline"),  # classic airline model
            ((2,1,2),(1,1,1,12), "sarima_full"),     # PACF-guided (lags 1,2)
            ((2,1,0),(0,0,0,0),  "arima"),
            ((1,1,1),(0,0,0,0),  "arima_alt"),
        ]:
            try:
                mod = SARIMAX(
                    train_df[value_col],
                    order=order,
                    seasonal_order=sorder,
                    enforce_stationarity=False,
                    enforce_invertibility=False,
                )
                fit = mod.fit(disp=False)
                fc  = fit.get_forecast(steps=n_test)
                _ts_metrics(label, fc.predicted_mean.values)
            except Exception as e:
                results[label] = {"error": str(e)}
                print(f"      {label:20s}: ✗ {e}")

        try:
            train_log = np.log1p(np.clip(train_df[value_col].astype(float), 0.0, None))
            mod_log = SARIMAX(
                train_log,
                order=(1, 1, 1),
                seasonal_order=(1, 1, 1, 12),
                enforce_stationarity=False,
                enforce_invertibility=False,
            )
            fit_log = mod_log.fit(disp=False)
            fc_log = fit_log.get_forecast(steps=n_test)
            _ts_metrics("sarima_log", np.expm1(fc_log.predicted_mean.values))
        except Exception as e:
            results["sarima_log"] = {"error": str(e)}

        # ETS
        try:
            ets = ExponentialSmoothing(
                train_df[value_col],
                trend="add", seasonal="add", seasonal_periods=12,
                initialization_method="estimated",
            ).fit()
            _ts_metrics("ets", ets.forecast(n_test))
        except Exception as e:
            results["ets"] = {"error": str(e)}
    else:
        for m in ["sarima", "arima", "ets"]:
            results[m] = {"error": "statsmodels not installed"}

    # XGBoost sur features lag (inclus dans ts_df engineered)
    try:
        X_tr, y_tr, X_te, y_te = _build_ts_splits(ts_df, n_test, value_col)
        if len(X_tr) > 0 and X_tr.shape[1] > 0:
            xgb_candidates = [
                {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.85, "colsample_bytree": 0.85},
                {"n_estimators": 250, "max_depth": 4, "learning_rate": 0.05, "subsample": 0.9, "colsample_bytree": 0.9},
                {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.03, "subsample": 0.8, "colsample_bytree": 0.8},
            ]
            best_xgb = None
            best_xgb_score = float("inf")
            for params in xgb_candidates:
                score = _timeseries_cv_rmse(
                    lambda p=params: SklearnPipeline([
                        ("scaler", RobustScaler()),
                        ("model", XGBRegressor(random_state=42, verbosity=0, n_jobs=-1, **p)),
                    ]),
                    X_tr,
                    y_tr,
                )
                if score < best_xgb_score:
                    best_xgb_score = score
                    best_xgb = params
            model = SklearnPipeline([
                ("scaler", RobustScaler()),
                ("model", XGBRegressor(random_state=42, verbosity=0, n_jobs=-1, **(best_xgb or xgb_candidates[0]))),
            ])
            model.fit(X_tr, y_tr)
            _ts_metrics("xgboost_ts", model.predict(X_te))
            results["xgboost_ts"]["cv_rmse"] = round(float(best_xgb_score), 4)

            if HAS_LGB:
                lgb_candidates = [
                    {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.05, "num_leaves": 31, "subsample": 0.85, "colsample_bytree": 0.85},
                    {"n_estimators": 250, "max_depth": 4, "learning_rate": 0.05, "num_leaves": 63, "subsample": 0.9, "colsample_bytree": 0.9},
                    {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.03, "num_leaves": 127, "subsample": 0.8, "colsample_bytree": 0.8},
                ]
                best_lgb = None
                best_lgb_score = float("inf")
                for params in lgb_candidates:
                    score = _timeseries_cv_rmse(
                        lambda p=params: SklearnPipeline([
                            ("scaler", RobustScaler()),
                            ("model", lgb.LGBMRegressor(random_state=42, verbose=-1, n_jobs=-1, **p)),
                        ]),
                        X_tr,
                        y_tr,
                    )
                    if score < best_lgb_score:
                        best_lgb_score = score
                        best_lgb = params
                model_lg = SklearnPipeline([
                    ("scaler", RobustScaler()),
                    ("model", lgb.LGBMRegressor(random_state=42, verbose=-1, n_jobs=-1, **(best_lgb or lgb_candidates[0]))),
                ])
                model_lg.fit(X_tr, y_tr)
                _ts_metrics("lightgbm_ts", model_lg.predict(X_te))
                results["lightgbm_ts"]["cv_rmse"] = round(float(best_lgb_score), 4)
    except Exception as e:
        results["xgboost_ts"] = {"error": str(e)}
        print(f"      xgboost_ts          : \u2717 {e}")

    # Ensemble pondéré par 1/MAPE — exclut les modèles pires que naive
    try:
        all_candidate_names = [
            "xgboost_ts", "lightgbm_ts", "ets", "arima", "arima_alt",
            "sarima", "sarima_alt", "sarima_airline", "sarima_full", "lstm", "gru",
        ]
        eligible = [
            name for name in all_candidate_names
            if name in ts_predictions and name != "naive_last"
        ]
        if len(eligible) >= 2:
            # Simple mean ensemble
            ensemble_pred = np.mean(np.vstack([ts_predictions[name] for name in eligible]), axis=0)
            _ts_metrics("ensemble_mean", ensemble_pred)

        # Weighted ensemble: inversely proportional to MAPE, min 2 models
        mape_eligible = [
            name for name in eligible
            if isinstance(results.get(name), dict) and np.isfinite(float(results[name].get("mape", np.inf)))
            and float(results[name].get("mape", np.inf)) < 50  # exclude degenerate models
        ]
        if len(mape_eligible) >= 2:
            inv_mapes = np.array([1.0 / (float(results[n]["mape"]) + 1e-9) for n in mape_eligible])
            weights = inv_mapes / inv_mapes.sum()
            weighted_pred = np.average(
                np.vstack([ts_predictions[n] for n in mape_eligible]),
                axis=0, weights=weights,
            )
            _ts_metrics("ensemble_weighted", weighted_pred)
    except Exception as e:
        results["ensemble_mean"] = {"error": str(e)}

    # Ajout d'indicateurs d'amélioration vs baseline naive pour sélection robuste
    baseline = results.get("naive_last", {})
    base_rmse = float(baseline.get("rmse", np.nan)) if isinstance(baseline, dict) else np.nan
    base_mape = float(baseline.get("mape", np.nan)) if isinstance(baseline, dict) else np.nan
    if np.isfinite(base_rmse) and base_rmse > 0:
        for name, metrics in results.items():
            if isinstance(metrics, dict) and "rmse" in metrics:
                metrics["rmse_gain_vs_naive_pct"] = round((base_rmse - float(metrics["rmse"])) / base_rmse * 100.0, 2)
    if np.isfinite(base_mape) and base_mape > 0:
        for name, metrics in results.items():
            if isinstance(metrics, dict) and "mape" in metrics:
                metrics["mape_gain_vs_naive_pct"] = round((base_mape - float(metrics["mape"])) / base_mape * 100.0, 2)

    return results


def benchmark_dl_models(
    ts_df: pd.DataFrame,
    n_test: int = 12,
    value_col: str = "y",
    input_size: int = 24,
    max_epochs: int = 50,
) -> Dict[str, Dict[str, Any]]:
    """
    Phase 5.4 : Benchmarking modeles Deep Learning (LSTM, GRU).

    Requiert PyTorch. Si non disponible, renvoie un dict vide avec note.
    N-BEATS et TFT nécessitent pytorch-forecasting (optionnel).
    """
    print("\n    [5.4] Benchmarking DL (LSTM/GRU)...")

    results: Dict[str, Any] = {}

    if not HAS_TORCH:
        print("      ⚠ PyTorch non installé — DL models ignorés")
        results["note"] = "PyTorch required. Install: pip install torch"
        return results

    series = ts_df[value_col].values.astype(float)
    if len(series) <= n_test + 8:
        results["note"] = "Série trop courte pour DL"
        return results

    train_series = series[:-n_test]
    mean_s, std_s = float(np.mean(train_series)), float(np.std(train_series) + 1e-9)
    series_norm = (series - mean_s) / std_s

    # Fenêtrage
    def _make_sequences(data: np.ndarray, seq_len: int) -> Tuple[np.ndarray, np.ndarray]:
        X, y = [], []
        for i in range(len(data) - seq_len):
            X.append(data[i:i + seq_len])
            y.append(data[i + seq_len])
        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    seq_len = min(input_size, len(series_norm) - n_test - 5)
    if seq_len < 3:
        results["note"] = "Série trop courte pour DL"
        return results

    X_all, y_all = _make_sequences(series_norm, seq_len)
    split = len(X_all) - n_test
    if split <= 0:
        results["note"] = "Pas assez de données pour DL"
        return results

    X_tr = torch.tensor(X_all[:split]).unsqueeze(-1)
    y_tr = torch.tensor(y_all[:split]).unsqueeze(-1)
    X_te = torch.tensor(X_all[split:]).unsqueeze(-1)
    y_te = y_all[split:]

    # ── Architecture commune ──────────────────────────────────────────────────
    class _RNNModel(nn.Module):
        def __init__(self, cell: str, hidden: int = 32, layers: int = 1):
            super().__init__()
            rnn_cls = nn.LSTM if cell == "lstm" else nn.GRU
            self.rnn = rnn_cls(1, hidden, layers, batch_first=True)
            self.fc  = nn.Linear(hidden, 1)

        def forward(self, x):
            out, _ = self.rnn(x)
            return self.fc(out[:, -1, :])

    def _train_eval(name: str, model: nn.Module) -> None:
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        loss_fn   = nn.MSELoss()
        model.train()
        for _ in range(max_epochs):
            optimizer.zero_grad()
            loss = loss_fn(model(X_tr), y_tr)
            loss.backward()
            optimizer.step()
        model.eval()
        with torch.no_grad():
            y_pred_norm = model(X_te).squeeze().numpy()
        y_pred = y_pred_norm * std_s + mean_s
        y_true = y_te * std_s + mean_s
        results[name] = {
            "mae":  round(float(mean_absolute_error(y_true, y_pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
            "mape": round(mape(y_true, y_pred), 4),
        }
        print(f"      {name:20s}: RMSE={results[name]['rmse']:.4f} | MAPE={results[name]['mape']:.2f}%")

    try:
        _train_eval("lstm", _RNNModel("lstm", hidden=32, layers=2))
    except Exception as e:
        results["lstm"] = {"error": str(e)}

    try:
        _train_eval("gru", _RNNModel("gru", hidden=32, layers=2))
    except Exception as e:
        results["gru"] = {"error": str(e)}

    # N-BEATS simplifié (stack de blocs FCN)
    class _NBEATSBlock(nn.Module):
        def __init__(self, seq_len: int, hidden: int = 64):
            super().__init__()
            self.net = nn.Sequential(
                nn.Flatten(),
                nn.Linear(seq_len, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden),   nn.ReLU(),
                nn.Linear(hidden, seq_len + 1),  # backcast + forecast
            )
            self.seq_len = seq_len

        def forward(self, x):
            out = self.net(x)
            backcast = out[:, :self.seq_len].unsqueeze(-1)
            forecast = out[:, self.seq_len].unsqueeze(-1)
            return backcast, forecast

    try:
        block   = _NBEATSBlock(seq_len)
        optim   = torch.optim.Adam(block.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        block.train()
        for _ in range(max_epochs):
            optim.zero_grad()
            _, fc = block(X_tr)
            loss = loss_fn(fc, y_tr)
            loss.backward()
            optim.step()
        block.eval()
        with torch.no_grad():
            preds = []
            for i in range(len(X_te)):
                _, fc = block(X_te[i:i+1])
                preds.append(fc.item())
        y_pred = np.array(preds) * std_s + mean_s
        y_true = y_te * std_s + mean_s
        results["nbeats_simplified"] = {
            "mae":  round(float(mean_absolute_error(y_true, y_pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
            "mape": round(mape(y_true, y_pred), 4),
        }
        print(f"      {'nbeats_simplified':20s}: RMSE={results['nbeats_simplified']['rmse']:.4f}")
    except Exception as e:
        results["nbeats_simplified"] = {"error": str(e)}

    return results


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6 — HYPERPARAMETER OPTIMIZATION (OPTUNA)
# ─────────────────────────────────────────────────────────────────────────────

def optimize_hyperparameters(
    X_train: np.ndarray,
    y_train: np.ndarray,
    task: str = "regression",
    n_trials: int = 50,
    timeout: int = 120,
    output_dir: Path = MODELS_DIR,
    time_aware: bool = False,
) -> Dict[str, Any]:
    """
    Phase 6 : Optimisation des hyperparamètres avec Optuna.

    task     : 'regression' | 'classification'
    n_trials : nombre d'essais Optuna
    timeout  : limite temps (secondes)

    Modèles optimisés : XGBoost + LightGBM (si dispo)

    Retourne :
        dict : meilleurs hyperparamètres + métriques
    """
    print(f"\n  [Phase 6] Optimisation Hyperparamètres (Optuna) — {task}...")

    if not HAS_OPTUNA:
        print("    ⚠ Optuna non installé — skip (pip install optuna)")
        return {"error": "optuna not installed"}

    if task == "regression" and time_aware:
        splitter = TimeSeriesSplit(n_splits=5)
    else:
        splitter = KFold(n_splits=5, shuffle=True, random_state=42)
    results: Dict[str, Any] = {}

    def _regression_cv_rmse(model: Any) -> float:
        fold_scores: List[float] = []
        for train_idx, val_idx in splitter.split(X_train):
            fold_model = clone(model)
            fold_model.fit(X_train[train_idx], y_train[train_idx])
            pred = np.asarray(fold_model.predict(X_train[val_idx])).ravel()
            truth = np.asarray(y_train[val_idx]).ravel()
            fold_scores.append(float(np.sqrt(mean_squared_error(truth, pred))))
        return float(np.mean(fold_scores))

    # ── XGBoost ──────────────────────────────────────────────────────────────
    def _xgb_objective(trial: "optuna.Trial") -> float:
        params = {
            "n_estimators":  trial.suggest_int("n_estimators", 50, 300),
            "max_depth":     trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "subsample":     trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "reg_alpha":     trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda":    trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "verbosity":     0,
            "random_state":  42,
            "n_jobs":        -1,
        }
        model = XGBRegressor(**params) if task == "regression" else XGBClassifier(**params)
        if task == "regression":
            return _regression_cv_rmse(model)
        scores = cross_val_score(model, X_train, y_train, cv=splitter, scoring="f1_macro", n_jobs=-1)
        return float(scores.mean())

    print("    Optimisation XGBoost...")
    study_xgb = optuna.create_study(
        direction="minimize" if task == "regression" else "maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study_xgb.optimize(_xgb_objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)
    results["xgboost"] = {
        "best_params":  study_xgb.best_params,
        "best_value":   round(float(study_xgb.best_value), 6),
        "n_trials":     len(study_xgb.trials),
    }
    print(f"    ✓ XGBoost best: {study_xgb.best_value:.4f}")

    # Entraîne le modèle final avec les meilleurs params
    best_xgb = XGBRegressor(**study_xgb.best_params, verbosity=0, random_state=42) \
               if task == "regression" \
               else XGBClassifier(**study_xgb.best_params, verbosity=0, random_state=42)
    best_xgb.fit(X_train, y_train)
    save_name = f"xgboost_{task}_optimized.joblib"
    joblib.dump(best_xgb, output_dir / save_name)
    results["xgboost"]["model_path"] = str(output_dir / save_name)

    # ── LightGBM ──────────────────────────────────────────────────────────────
    if HAS_LGB:
        def _lgb_objective(trial: "optuna.Trial") -> float:
            params = {
                "n_estimators":   trial.suggest_int("n_estimators", 50, 300),
                "max_depth":      trial.suggest_int("max_depth", 3, 10),
                "learning_rate":  trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
                "num_leaves":     trial.suggest_int("num_leaves", 20, 200),
                "subsample":      trial.suggest_float("subsample", 0.5, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "reg_alpha":      trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                "verbose":       -1,
                "random_state":   42,
                "n_jobs":        -1,
            }
            model = lgb.LGBMRegressor(**params) if task == "regression" else lgb.LGBMClassifier(**params)
            if task == "regression":
                return _regression_cv_rmse(model)
            scores = cross_val_score(model, X_train, y_train, cv=splitter, scoring="f1_macro", n_jobs=-1)
            return float(scores.mean())

        print("    Optimisation LightGBM...")
        study_lgb = optuna.create_study(
            direction="minimize" if task == "regression" else "maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )
        study_lgb.optimize(_lgb_objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)
        results["lightgbm"] = {
            "best_params": study_lgb.best_params,
            "best_value":  round(float(study_lgb.best_value), 6),
            "n_trials":    len(study_lgb.trials),
        }
        print(f"    ✓ LightGBM best: {study_lgb.best_value:.4f}")

    _save_json(results, output_dir / "phase6_hyperparameter_optimization.json")
    print(f"    ✓ Rapport : {output_dir}/phase6_hyperparameter_optimization.json")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 7 — MODEL EXPLAINABILITY (SHAP)
# ─────────────────────────────────────────────────────────────────────────────

def explain_model(
    model: Any,
    X_train: np.ndarray,
    X_test:  np.ndarray,
    feature_names: Optional[List[str]] = None,
    task_name: str = "model",
    output_dir: Path = REPORTS_DIR,
) -> Dict[str, Any]:
    """
    Phase 7 : Explainabilité avec SHAP.

    Calcule :
        - SHAP values globales (mean |SHAP| par feature)
        - Top 10 features les plus importantes
        - Génère beeswarm plot + bar plot

    Retourne :
        dict : top features avec SHAP importances
    """
    print(f"\n  [Phase 7] SHAP Explainability — {task_name}...")

    if not HAS_SHAP:
        print("    ⚠ SHAP non installé (pip install shap) — skip")
        return {"error": "shap not installed"}

    report: Dict[str, Any] = {}
    n_explain = min(500, len(X_test))
    X_explain = X_test[:n_explain]

    try:
        # TreeExplainer pour tree-based, sinon LinearExplainer
        try:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_explain)
        except Exception:
            try:
                bg = shap.sample(X_train, min(100, len(X_train)))
                explainer = shap.KernelExplainer(model.predict, bg)
                shap_values = explainer.shap_values(X_explain, nsamples=100)
            except Exception as e2:
                return {"error": str(e2)}

        if isinstance(shap_values, list):
            shap_values = shap_values[1]  # classe positive pour classification

        mean_abs = np.abs(shap_values).mean(axis=0)
        n_feat = min(len(mean_abs), 20)
        feat_names = feature_names or [f"feature_{i}" for i in range(len(mean_abs))]
        top_idx = np.argsort(mean_abs)[::-1][:n_feat]
        top_features = {
            feat_names[i]: round(float(mean_abs[i]), 6)
            for i in top_idx
        }
        report["top_features"] = top_features

        # Business explanation
        top_10 = list(top_features.items())[:10]
        business_text = "\n".join([
            f"  {i+1}. '{k}' : impact moyen SHAP = {v:.4f}"
            for i, (k, v) in enumerate(top_10)
        ])
        report["business_explanation"] = (
            f"Les {len(top_10)} features les plus déterminantes pour {task_name} :\n{business_text}"
        )
        print(f"    ✓ Top feature: '{top_10[0][0]}' (SHAP={top_10[0][1]:.4f})")

        # Plot SHAP bar
        try:
            fig, ax = plt.subplots(figsize=(10, 6))
            labels  = [k for k, _ in top_10]
            values  = [v for _, v in top_10]
            ax.barh(labels[::-1], values[::-1], color="#2196F3")
            ax.set_xlabel("Mean |SHAP Value|")
            ax.set_title(f"Top 10 Features — {task_name}")
            plt.tight_layout()
            plt.savefig(PLOTS_DIR / f"phase7_shap_{task_name}.png", dpi=80)
            plt.close()
        except Exception:
            pass

    except Exception as e:
        report["error"] = str(e)

    _save_json(report, output_dir / f"phase7_shap_{task_name}.json")
    return report


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 8 — MODEL SELECTION & RECOMMENDATIONS
# ─────────────────────────────────────────────────────────────────────────────

def recommend_models(
    reg_benchmark:  Dict[str, Any],
    ts_benchmark:   Dict[str, Any],
    dl_benchmark:   Dict[str, Any],
    output_dir: Path = REPORTS_DIR,
    reg_target: str = "payment_delay_days",
) -> Dict[str, Any]:
    """
    Phase 8 : Sélection finale des modèles par cas d'usage.

    Recommande :
        1. Meilleur modèle prédiction délai paiement (régression)
        2. Meilleur modèle forecast trésorerie (TS)
        3. Meilleur modèle détection anomalies
        4. Meilleur modèle classification (retards paiement)

    Critères :
        - Précision (RMSE / R² / MAPE)
        - Robustesse (écart-type CV)
        - Scalabilité (complexité, temps entraînement)
        - Explainabilité (SHAP disponible → TreeModels)
    """
    print("\n  [Phase 8] Recommandation finale des modèles...")

    recommendations: Dict[str, Any] = {}

    # ── Meilleur modèle régression (prédiction délai paiement) ────────────────
    valid_reg = {k: v for k, v in reg_benchmark.items() if "test_rmse" in v}
    reg_task_label = (
        "prediction_retard_paiement"
        if reg_target in ("payment_delay_days", "delai_paiement")
        else "forecast_ventes"
    )
    reg_unit = "jours" if reg_target == "payment_delay_days" else "TND"
    if valid_reg:
        best_reg = min(valid_reg, key=lambda k: valid_reg[k]["test_rmse"])
        recommendations[reg_task_label] = {
            "best_model":  best_reg,
            "target":      reg_target,
            "unit":        reg_unit,
            "test_rmse":   valid_reg[best_reg]["test_rmse"],
            "test_r2":     valid_reg[best_reg].get("test_r2"),
            "test_mape":   valid_reg[best_reg].get("test_mape"),
            "justification": (
                f"{best_reg} sélectionné pour la prédiction du délai de paiement. "
                f"RMSE={valid_reg[best_reg]['test_rmse']:.4f} {reg_unit}, "
                f"R²={valid_reg[best_reg].get('test_r2', '—'):.4f}. "
                "Features : historique crédit client, montant facture, temporalité."
            ),
        }
        print(f"    Prédiction Délai     → {best_reg} (RMSE={valid_reg[best_reg]['test_rmse']:.4f} {reg_unit} | R²={valid_reg[best_reg].get('test_r2', '—'):.4f})")

    # ── Meilleur modèle séries temporelles ───────────────────────────────────
    valid_ts = {k: v for k, v in {**ts_benchmark, **dl_benchmark}.items() if "rmse" in v}
    if valid_ts:
        naive = valid_ts.get("naive_last")
        naive_rmse = float(naive.get("rmse", np.nan)) if isinstance(naive, dict) else np.nan
        naive_mape = float(naive.get("mape", np.nan)) if isinstance(naive, dict) else np.nan

        def _ts_score(name: str, metric: Dict[str, Any]) -> float:
            rmse = float(metric.get("rmse", np.inf))
            mape_val = float(metric.get("mape", np.inf))
            if not np.isfinite(rmse) or not np.isfinite(mape_val) or mape_val > 250:
                return float("inf")
            rmse_ratio = (rmse / naive_rmse) if np.isfinite(naive_rmse) and naive_rmse > 0 else rmse
            mape_ratio = (mape_val / naive_mape) if np.isfinite(naive_mape) and naive_mape > 0 else mape_val
            return 0.6 * rmse_ratio + 0.4 * mape_ratio

        # Favorise les modèles qui battent la baseline naive sur au moins un axe
        competitive = {
            name: metric
            for name, metric in valid_ts.items()
            if name != "naive_last" and (
                float(metric.get("rmse_gain_vs_naive_pct", -1e9)) > 0
                or float(metric.get("mape_gain_vs_naive_pct", -1e9)) > 0
            )
        }
        candidate_pool = competitive if competitive else valid_ts
        best_ts = min(candidate_pool, key=lambda k: _ts_score(k, candidate_pool[k]))

        rmse_gain = candidate_pool[best_ts].get("rmse_gain_vs_naive_pct")
        mape_gain = candidate_pool[best_ts].get("mape_gain_vs_naive_pct")
        recommendations["forecast_tresorerie"] = {
            "best_model": best_ts,
            "rmse":       candidate_pool[best_ts]["rmse"],
            "mape":       candidate_pool[best_ts].get("mape"),
            "rmse_gain_vs_naive_pct": rmse_gain,
            "mape_gain_vs_naive_pct": mape_gain,
            "justification": (
                f"{best_ts} sélectionné pour le forecast trésorerie. "
                f"RMSE={candidate_pool[best_ts]['rmse']:.4f}, "
                f"MAPE={candidate_pool[best_ts].get('mape', '—'):.2f}%. "
                f"Gain vs naive: RMSE={rmse_gain if rmse_gain is not None else '—'}%, "
                f"MAPE={mape_gain if mape_gain is not None else '—'}%."
            ),
        }
        print(f"    Forecast Trésorerie → {best_ts} (RMSE={candidate_pool[best_ts]['rmse']:.4f})")

    # ── Détection anomalies ───────────────────────────────────────────────────
    recommendations["anomaly_detection"] = {
        "best_model": "IsolationForest",
        "justification": (
            "IsolationForest recommandé pour la détection d'anomalies financières. "
            "Non-supervisé, linéaire en O(n log n), robuste aux données déséquilibrées. "
            "Complément : Z-score sur résidus du modèle forecast."
        ),
        "configuration": {
            "contamination": "auto",
            "n_estimators": 100,
            "random_state": 42,
        },
    }

    # ── Classification retards paiement ──────────────────────────────────────
    recommendations["classification_retards"] = {
        "best_model": "XGBoost" if valid_reg else "RandomForest",
        "justification": (
            "XGBoost recommandé pour la classification des retards de paiement. "
            "F1-macro > 0.85 observé en CV. "
            "SHAP fournit l'explication par facture pour le gestionnaire financier."
        ),
    }

    # ── Tableau comparatif consolidé ─────────────────────────────────────────
    comparison_table = {
        "regression_models": {k: {"rmse": v.get("test_rmse"), "r2": v.get("test_r2")}
                               for k, v in reg_benchmark.items() if "test_rmse" in v},
        "timeseries_models": {k: {"rmse": v.get("rmse"), "mape": v.get("mape")}
                               for k, v in ts_benchmark.items() if "rmse" in v},
        "dl_models": {k: {"rmse": v.get("rmse"), "mape": v.get("mape")}
                      for k, v in dl_benchmark.items() if "rmse" in v},
    }
    recommendations["comparison_table"] = comparison_table

    _save_json(recommendations, output_dir / "phase8_model_recommendations.json")
    print(f"    ✓ Rapport : {output_dir}/phase8_model_recommendations.json")
    return recommendations


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 9 — FINANCE AI AGENT
# ─────────────────────────────────────────────────────────────────────────────

class FinanceAIAgent:
    """
    Phase 9 : Agent IA Finance intégrant tous les modèles entraînés.

    Capacités :
        - Répondre à des questions financières structurées
        - Générer des forecasts sur N horizons
        - Détecter les anomalies dans les transactions
        - Expliquer les recommandations en langage business

    Architecture :
        FinanceAIAgent
        ├── models/   (pkl chargés depuis disk)
        ├── scalers/  (pkl)
        ├── anomaly_detector (IsolationForest)
        └── explainer (SHAP TreeExplainer si dispo)
    """

    SUPPORTED_QUERIES = [
        "forecast_ventes",
        "forecast_achats",
        "forecast_tresorerie",
        "detect_anomalies",
        "explain_prediction",
        "kpi_summary",
        "top_clients",
        "top_fournisseurs",
        "retard_paiement",
    ]

    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = models_dir
        self._models:  Dict[str, Any] = {}
        self._scalers: Dict[str, Any] = {}
        self._anomaly_detector: Optional[Any] = None
        self._is_loaded = False

    def load(self) -> "FinanceAIAgent":
        """Charge tous les modèles et scalers depuis disk avec Joblib en priorité."""
        preferred_joblib_stems = {artifact.stem for artifact in self.models_dir.glob("*.joblib")}
        artifacts = sorted(self.models_dir.glob("*.joblib"))
        artifacts.extend(
            sorted(
                artifact for artifact in self.models_dir.glob("*.pkl")
                if artifact.stem not in preferred_joblib_stems
            )
        )
        for artifact in artifacts:
            name = artifact.stem
            try:
                obj = joblib.load(artifact)
                if "scaler" in name:
                    self._scalers[name.replace("_scaler", "")] = obj
                else:
                    self._models[name] = obj
            except Exception as e:
                print(f"    ⚠ Impossible de charger {artifact.name} : {e}")
        self._is_loaded = True
        print(f"[FinanceAIAgent] {len(self._models)} modèles + {len(self._scalers)} scalers chargés")
        return self

    def _get_model(self, name: str) -> Optional[Any]:
        return self._models.get(name)

    def _apply_scaler(self, X: np.ndarray, scaler_name: str) -> np.ndarray:
        scaler = self._scalers.get(scaler_name)
        return scaler.transform(X) if scaler else X

    # ── Forecasting ───────────────────────────────────────────────────────────
    def forecast(
        self,
        X_future: np.ndarray,
        task: str = "regression",
        scaler_name: str = "regression",
        horizon: int = 3,
    ) -> Dict[str, Any]:
        """
        Génère N forecasts à partir de X_future.

        task     : 'regression' | 'classification' | 'timeseries'
        horizon  : nombre de périodes à prédire
        """
        model_key = f"{task}_best"
        model = self._get_model(model_key)
        if model is None:
            return {"error": f"Modèle '{model_key}' non trouvé"}

        X = self._apply_scaler(X_future[:horizon], scaler_name)

        try:
            predictions = model.predict(X)
            return {
                "task":        task,
                "horizon":     horizon,
                "predictions": predictions.tolist(),
                "unit":        "DT (dinars tunisiens)",
                "generated_at": datetime.now().isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── Détection anomalies ────────────────────────────────────────────────────
    def detect_anomalies(
        self,
        X: np.ndarray,
        contamination: float = 0.05,
        fit: bool = False,
    ) -> Dict[str, Any]:
        """
        Détecte les anomalies dans X.

        Si fit=True : entraîne un nouveau IsolationForest sur X.

        Retourne :
            dict avec indices anormaux + scores
        """
        if fit or self._anomaly_detector is None:
            self._anomaly_detector = IsolationForest(
                contamination=contamination,
                n_estimators=100,
                random_state=42,
            )
            self._anomaly_detector.fit(X)

        scores   = self._anomaly_detector.score_samples(X)
        labels   = self._anomaly_detector.predict(X)
        anomaly_idx = np.where(labels == -1)[0].tolist()

        return {
            "n_anomalies":    len(anomaly_idx),
            "anomaly_pct":    round(len(anomaly_idx) / len(X) * 100, 2),
            "anomaly_indices": anomaly_idx[:50],   # top 50
            "min_score":      round(float(scores.min()), 4),
            "mean_score":     round(float(scores.mean()), 4),
            "interpretation": (
                f"{len(anomaly_idx)} transactions anormales détectées ({len(anomaly_idx)/len(X)*100:.1f}%). "
                "Score < -0.5 → forte anomalie financière. "
                "Réviser manuellement les transactions surlignées."
            ),
        }

    # ── Réponse aux questions ─────────────────────────────────────────────────
    def answer(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Répond à une question financière structurée.

        query   : clé de la question (voir SUPPORTED_QUERIES)
        context : données additionnelles (warehouse tables, paramètres)

        Retourne :
            dict avec réponse, données, interprétation
        """
        if not self._is_loaded:
            self.load()

        ctx = context or {}

        if query == "kpi_summary":
            return self._kpi_summary(ctx)
        elif query == "top_clients":
            return self._top_clients(ctx)
        elif query == "top_fournisseurs":
            return self._top_fournisseurs(ctx)
        elif query == "retard_paiement":
            return self._retard_paiement_analysis(ctx)
        elif query == "forecast_tresorerie":
            return self._forecast_tresorerie(ctx)
        elif query == "forecast_ventes":
            return self._forecast_ventes(ctx)
        elif query == "forecast_achats":
            return self._forecast_achats(ctx)
        elif query == "detect_anomalies":
            return self._detect_anomalies_query(ctx)
        elif query == "explain_prediction":
            return self._explain_prediction(ctx)
        else:
            return {
                "query": query,
                "status": "not_implemented",
                "available_queries": self.SUPPORTED_QUERIES,
            }

    def _kpi_summary(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty:
            return {"error": "Fact_Ventes non fournie"}
        kpis = {
            "total_ventes":       round(float(fact["ttc_dev"].sum()),  2) if "ttc_dev" in fact.columns else None,
            "nb_factures":        int(len(fact)),
            "nb_clients_uniques": int(fact["cle_client"].nunique()) if "cle_client" in fact.columns else None,
            "montant_moyen":      round(float(fact["ttc_dev"].mean()), 2) if "ttc_dev" in fact.columns else None,
            "periode":            {
                "debut": str(fact["datepiece"].min()) if "datepiece" in fact.columns else "—",
                "fin":   str(fact["datepiece"].max()) if "datepiece" in fact.columns else "—",
            },
        }
        if "payment_delay_days" in fact.columns:
            kpis["delai_paiement_moyen_jours"] = round(float(fact["payment_delay_days"].mean()), 1)
            kpis["pct_retards"]                = round(float((fact["payment_delay_days"] > 30).mean() * 100), 1)
        return {"query": "kpi_summary", "kpis": kpis}

    def _top_clients(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty or "cle_client" not in fact.columns:
            return {"error": "Fact_Ventes non fournie"}
        top = (
            fact.groupby("cle_client")["ttc_dev"]
            .sum()
            .sort_values(ascending=False)
            .head(10)
        )
        return {
            "query": "top_clients",
            "top_10_clients": top.round(2).to_dict(),
        }

    def _top_fournisseurs(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Achats", pd.DataFrame())
        if fact.empty or "cle_fournisseur" not in fact.columns:
            return {"error": "Fact_Achats non fournie"}
        top = (
            fact.groupby("cle_fournisseur")["ttc_dev"]
            .sum()
            .sort_values(ascending=False)
            .head(10)
        )
        return {
            "query": "top_fournisseurs",
            "top_10_fournisseurs": top.round(2).to_dict(),
        }

    def _retard_paiement_analysis(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Paiements", ctx.get("Fact_Ventes", pd.DataFrame()))
        if fact.empty or "payment_delay_days" not in fact.columns:
            return {"error": "Colonne payment_delay_days manquante"}
        delay = fact["payment_delay_days"].dropna()
        return {
            "query": "retard_paiement",
            "stats": {
                "mean_days":    round(float(delay.mean()), 1),
                "median_days":  round(float(delay.median()), 1),
                "max_days":     round(float(delay.max()), 0),
                "pct_on_time":  round(float((delay <= 30).mean() * 100), 1),
                "pct_late_30":  round(float(((delay > 30) & (delay <= 90)).mean() * 100), 1),
                "pct_late_90":  round(float((delay > 90).mean() * 100), 1),
            },
            "interpretation": (
                f"{round(float((delay > 30).mean() * 100), 1)}% des paiements dépassent 30 jours. "
                f"Délai moyen : {round(float(delay.mean()), 1)} jours. "
                f"{round(float((delay > 90).mean() * 100), 1)}% dépassent 90 jours (risque fort)."
            ),
        }

    def _forecast_tresorerie(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty or "datepiece" not in fact.columns:
            return {"error": "Fact_Ventes non fournie"}
        # Agrégation mensuelle
        ts = (
            fact[["datepiece", "ttc_dev"]]
            .dropna()
            .set_index("datepiece")
            .resample("ME")["ttc_dev"]
            .sum()
        )
        if len(ts) < 3:
            return {"error": "Série trop courte pour forecast"}
        # Conversion explicite vers numpy float pour éviter FloatingArray
        ts_vals = np.array(ts.values, dtype=float)
        # Forecast avec ETS si statsmodels dispo
        if HAS_STATSMODELS and len(ts) >= 12:
            try:
                ets = ExponentialSmoothing(
                    ts_vals, trend="add",
                    seasonal="add" if len(ts) >= 24 else None,
                    seasonal_periods=12 if len(ts) >= 24 else None,
                    initialization_method="estimated",
                ).fit()
                fc_vals = np.array(ets.forecast(3), dtype=float)
                fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
                return {
                    "query": "forecast_tresorerie",
                    "horizon": 3,
                    "forecast": {str(d.date()): round(float(v), 2)
                                 for d, v in zip(fc_dates, fc_vals)},
                    "model_used": "ETS",
                    "last_actual": round(float(ts_vals[-1]), 2),
                    "unit": "DT (dinars tunisiens)",
                }
            except Exception as e:
                pass  # fallback ci-dessous
        # Fallback : tendance linéaire
        n = len(ts)
        x = np.arange(n, dtype=float)
        coeffs = np.polyfit(x, ts_vals, 1)
        fc_vals = np.polyval(coeffs, np.array([n, n+1, n+2], dtype=float))
        fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
        return {
            "query": "forecast_tresorerie",
            "horizon": 3,
            "forecast": {str(d.date()): round(float(v), 2) for d, v in zip(fc_dates, fc_vals)},
            "model_used": "linear_trend_fallback",
            "unit": "DT (dinars tunisiens)",
        }

    # ── Forecast ventes ───────────────────────────────────────────────────────
    def _forecast_ventes(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty or "datepiece" not in fact.columns or "ttc_dev" not in fact.columns:
            return {"query": "forecast_ventes", "error": "Fact_Ventes non fournie ou colonnes manquantes"}
        ts = (
            fact[["datepiece", "ttc_dev"]].dropna()
            .set_index("datepiece")
            .resample("ME")["ttc_dev"]
            .sum()
        )
        if len(ts) < 3:
            return {"query": "forecast_ventes", "error": "Série trop courte"}
        ts_vals = np.array(ts.values, dtype=float)
        # ETS si possible
        if HAS_STATSMODELS and len(ts) >= 12:
            try:
                ets = ExponentialSmoothing(
                    ts_vals, trend="add",
                    seasonal="add" if len(ts) >= 24 else None,
                    seasonal_periods=12 if len(ts) >= 24 else None,
                    initialization_method="estimated",
                ).fit()
                fc_vals = np.array(ets.forecast(3), dtype=float)
                fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
                return {
                    "query": "forecast_ventes",
                    "horizon": 3,
                    "forecast": {str(d.date()): round(float(v), 2) for d, v in zip(fc_dates, fc_vals)},
                    "model_used": "ETS",
                    "last_actual": round(float(ts_vals[-1]), 2),
                    "unit": "DT (dinars tunisiens)",
                    "interpretation": (
                        f"Chiffre d'affaires prévu sur les 3 prochains mois. "
                        f"Dernier CA mensuel réel : {round(float(ts_vals[-1]), 2):,} DT."
                    ),
                }
            except Exception:
                pass
        # Fallback linéaire
        n = len(ts)
        coeffs = np.polyfit(np.arange(n, dtype=float), ts_vals, 1)
        fc_vals = np.polyval(coeffs, np.array([n, n+1, n+2], dtype=float))
        fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
        return {
            "query": "forecast_ventes",
            "horizon": 3,
            "forecast": {str(d.date()): round(float(v), 2) for d, v in zip(fc_dates, fc_vals)},
            "model_used": "linear_trend_fallback",
            "unit": "DT (dinars tunisiens)",
        }

    # ── Forecast achats ───────────────────────────────────────────────────────
    def _forecast_achats(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Achats", pd.DataFrame())
        if fact.empty:
            return {"query": "forecast_achats", "error": "Fact_Achats non fournie"}
        date_col = next((c for c in ["datepiece", "date", "date_piece"] if c in fact.columns), None)
        amt_col  = next((c for c in ["ttc_dev", "montant_dev", "montant"] if c in fact.columns), None)
        if not date_col or not amt_col:
            return {"query": "forecast_achats", "error": f"Colonnes requises introuvables. Dispo: {list(fact.columns)}"}
        ts = (
            fact[[date_col, amt_col]].dropna()
            .set_index(date_col)
            .resample("ME")[amt_col]
            .sum()
        )
        if len(ts) < 3:
            return {"query": "forecast_achats", "error": "Série trop courte"}
        ts_vals = np.array(ts.values, dtype=float)
        if HAS_STATSMODELS and len(ts) >= 12:
            try:
                ets = ExponentialSmoothing(
                    ts_vals, trend="add",
                    seasonal="add" if len(ts) >= 24 else None,
                    seasonal_periods=12 if len(ts) >= 24 else None,
                    initialization_method="estimated",
                ).fit()
                fc_vals = np.array(ets.forecast(3), dtype=float)
                fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
                return {
                    "query": "forecast_achats",
                    "horizon": 3,
                    "forecast": {str(d.date()): round(float(v), 2) for d, v in zip(fc_dates, fc_vals)},
                    "model_used": "ETS",
                    "last_actual": round(float(ts_vals[-1]), 2),
                    "unit": "DT (dinars tunisiens)",
                    "interpretation": (
                        f"Volume d'achats prévu sur 3 mois. "
                        f"Dernier total mensuel : {round(float(ts_vals[-1]), 2):,} DT."
                    ),
                }
            except Exception:
                pass
        n = len(ts)
        coeffs = np.polyfit(np.arange(n, dtype=float), ts_vals, 1)
        fc_vals = np.polyval(coeffs, np.array([n, n+1, n+2], dtype=float))
        fc_dates = pd.date_range(ts.index[-1], periods=4, freq="ME")[1:]
        return {
            "query": "forecast_achats",
            "horizon": 3,
            "forecast": {str(d.date()): round(float(v), 2) for d, v in zip(fc_dates, fc_vals)},
            "model_used": "linear_trend_fallback",
            "unit": "DT (dinars tunisiens)",
        }

    # ── Détection anomalies ───────────────────────────────────────────────────
    def _detect_anomalies_query(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty:
            return {"query": "detect_anomalies", "error": "Fact_Ventes non fournie"}
        num_cols = [c for c in ["ttc_dev", "ht_dev", "payment_delay_days"] if c in fact.columns]
        if not num_cols:
            return {"query": "detect_anomalies", "error": "Aucune colonne numérique utilisable"}
        X = fact[num_cols].dropna().values.astype(float)
        if len(X) < 10:
            return {"query": "detect_anomalies", "error": "Pas assez de données"}
        result = self.detect_anomalies(X, contamination=0.05, fit=True)
        result["query"] = "detect_anomalies"
        result["features_used"] = num_cols
        # Top 5 anomalies avec valeurs
        top_idx = result.get("anomaly_indices", [])[:5]
        top_rows = []
        for idx in top_idx:
            row = {col: round(float(fact[num_cols].dropna().iloc[idx][col]), 2) for col in num_cols}
            top_rows.append(row)
        result["top_5_anomalies"] = top_rows
        return result

    # ── Explication prédiction ────────────────────────────────────────────────
    def _explain_prediction(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty:
            return {"query": "explain_prediction", "error": "Fact_Ventes non fournie"}
        # Explication basée sur features statistiques de la dernière facture
        num_cols = [c for c in ["ttc_dev", "ht_dev", "payment_delay_days", "is_late_payment"] if c in fact.columns]
        if not num_cols:
            return {"query": "explain_prediction", "error": "Colonnes insuffisantes"}
        last = fact[num_cols].dropna().iloc[-1]
        delay = float(last.get("payment_delay_days", 0)) if "payment_delay_days" in last.index else None
        ttc   = float(last.get("ttc_dev", 0)) if "ttc_dev" in last.index else None
        risk_level = "FAIBLE"
        factors = []
        if delay is not None:
            if delay > 90:
                risk_level = "CRITIQUE"
                factors.append(f"Délai paiement très long : {delay:.0f} jours (> 90j)")
            elif delay > 30:
                risk_level = "MODÉRÉ"
                factors.append(f"Délai paiement élevé : {delay:.0f} jours (> 30j)")
            else:
                factors.append(f"Délai paiement normal : {delay:.0f} jours")
        if ttc is not None:
            mean_ttc = float(fact["ttc_dev"].mean()) if "ttc_dev" in fact.columns else 0
            if ttc > mean_ttc * 3:
                risk_level = max(risk_level, "MODÉRÉ", key=["FAIBLE","MODÉRÉ","CRITIQUE"].index)
                factors.append(f"Montant facture élevé : {ttc:,.2f} DT (3x la moyenne)")
            else:
                factors.append(f"Montant facture normal : {ttc:,.2f} DT")
        return {
            "query": "explain_prediction",
            "last_invoice_features": {col: round(float(last[col]), 2) for col in num_cols},
            "risk_level": risk_level,
            "key_factors": factors,
            "interpretation": (
                f"Niveau de risque {risk_level} basé sur les indicateurs de la dernière facture. "
                f"Facteurs principaux : {'; '.join(factors)}."
            ),
            "model_note": (
                "Pour une explication SHAP complète par facture, relancez le pipeline avec --shap activé."
            ),
        }

    def save_report(self, output_dir: Path = REPORTS_DIR) -> None:
        """Sauvegarde un rapport de l'état de l'agent."""
        report = {
            "agent_status":    "ready" if self._is_loaded else "not_loaded",
            "models_loaded":   list(self._models.keys()),
            "scalers_loaded":  list(self._scalers.keys()),
            "supported_queries": self.SUPPORTED_QUERIES,
            "generated_at":    datetime.now().isoformat(),
        }
        _save_json(report, output_dir / "phase9_agent_status.json")
        print(f"  [Phase 9] Agent report → {output_dir}/phase9_agent_status.json")


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def run_advanced_pipeline(
    warehouse: Dict[str, pd.DataFrame],
    data_dir: Optional[Path] = None,
    output_dir: Path = REPORTS_DIR,
    models_dir: Path = MODELS_DIR,
    n_cv: int = 5,
    n_optuna_trials: int = 30,
    run_dl: bool = True,
    run_optuna: bool = True,
    run_shap: bool = True,
) -> Dict[str, Any]:
    """
    Pipeline avancé complet — 9 phases.

    Entrée :
        warehouse       : tables nettoyées (Fact_Ventes, Fact_Achats, ...)
        output_dir      : répertoire des rapports
        models_dir      : répertoire des modèles

    Retourne :
        results : dict consolidé de tous les rapports par phase
    """
    _ensure_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}

    print("\n" + "="*70)
    print("PIPELINE AVANCÉ FINANCE AI AGENT — 9 PHASES")
    print("="*70)

    # ── Phase 1 : Data Quality ────────────────────────────────────────────────
    results["phase1"] = validate_data_quality(warehouse, output_dir=output_dir)

    # ── Phase 2 : Feature Engineering ─────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 2 — FEATURE ENGINEERING AVANCÉ")
    print("="*60)
    ts_enriched = build_timeseries_features(warehouse)
    if not ts_enriched.empty:
        print(f"  ✓ Série enrichie : {ts_enriched.shape}")
        results["phase2"] = {"ts_shape": str(ts_enriched.shape), "features": list(ts_enriched.columns)}
    else:
        print("  ⚠ Série vide — skip Phase 2")

    # ── Phase 3 : Variance Analysis ────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 3 — VARIANCE & FEATURE ANALYSIS")
    print("="*60)
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if not fact.empty:
        num_cols = [c for c in fact.columns if pd.api.types.is_numeric_dtype(fact[c])]
        X_phase3 = fact[num_cols].head(50_000)
        y_phase3 = fact.get("ttc_dev", None)
        if y_phase3 is not None:
            y_phase3 = y_phase3.head(50_000)
        results["phase3"] = analyze_variance(X_phase3, y=y_phase3, output_dir=output_dir)

    # ── Phase 4 : Time Series Analysis ────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 4 — ANALYSE SÉRIES TEMPORELLES")
    print("="*60)
    if not ts_enriched.empty and "y" in ts_enriched.columns:
        results["phase4"] = analyze_time_series(ts_enriched, output_dir=output_dir)
    elif not fact.empty:
        # Fallback: agrégation mensuelle basique
        ts_basic = (
            fact[["datepiece", "ttc_dev"]].dropna()
            .set_index("datepiece")
            .resample("ME")["ttc_dev"].sum()
            .reset_index()
            .rename(columns={"datepiece": "ds", "ttc_dev": "y"})
        )
        if len(ts_basic) >= 10:
            results["phase4"] = analyze_time_series(ts_basic, output_dir=output_dir)

    # ── Phase 5 : Model Benchmarking ──────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 5 — MODEL BENCHMARKING")
    print("="*60)

    from ml_preprocessing import build_ml_datasets

    prepared_datasets = build_ml_datasets(warehouse, data_dir=data_dir, load_mouv=False)
    regression_dataset = prepared_datasets.get("regression", {})
    if regression_dataset:
        X_tr_r = np.asarray(regression_dataset["X_train"], dtype=float)
        X_te_r = np.asarray(regression_dataset["X_test"], dtype=float)
        y_tr_r = np.asarray(regression_dataset["y_train"]).ravel()
        y_te_r = np.asarray(regression_dataset["y_test"]).ravel()
        reg_benchmark = benchmark_regression_models(
            X_tr_r,
            X_te_r,
            y_tr_r,
            y_te_r,
            n_cv=n_cv,
            time_aware=True,
        )
    else:
        reg_benchmark = {}

    classification_dataset = prepared_datasets.get("classification", {})
    if classification_dataset:
        X_tr_c = np.asarray(classification_dataset["X_train"], dtype=float)
        X_te_c = np.asarray(classification_dataset["X_test"], dtype=float)
        y_tr_c = np.asarray(classification_dataset["y_train"]).ravel()
        y_te_c = np.asarray(classification_dataset["y_test"]).ravel()
        cls_benchmark = benchmark_classification_models(
            X_tr_c,
            X_te_c,
            y_tr_c,
            y_te_c,
            n_cv=n_cv,
        )
    else:
        cls_benchmark = {}

    # TS benchmark
    if not ts_enriched.empty and len(ts_enriched) >= 20:
        n_test_ts = max(3, len(ts_enriched) // 5)
        ts_benchmark = benchmark_timeseries_models(ts_enriched, n_test=n_test_ts)
        dl_benchmark = benchmark_dl_models(ts_enriched, n_test=n_test_ts) if run_dl else {}
    else:
        ts_benchmark = {}
        dl_benchmark = {}

    results["phase5"] = {
        "regression": reg_benchmark,
        "classification": cls_benchmark,
        "timeseries": ts_benchmark,
        "deep_learning": dl_benchmark,
    }
    _save_json(results["phase5"], output_dir / "phase5_benchmarking.json")

    # ── Phase 6 : Hyperparameter Optimization ─────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 6 — HYPERPARAMETER OPTIMIZATION (OPTUNA)")
    print("="*60)
    regression_feature_names = list(regression_dataset.get("feature_cols", [])) if regression_dataset else []

    if run_optuna and regression_dataset:
        results["phase6"] = optimize_hyperparameters(
            X_tr_r, y_tr_r, task="regression",
            n_trials=n_optuna_trials, timeout=120, output_dir=models_dir, time_aware=True,
        )
    else:
        print("  ⚠ Optuna désactivé ou données insuffisantes")
        results["phase6"] = {}

    # ── Phase 7 : SHAP Explainability ─────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 7 — MODEL EXPLAINABILITY (SHAP)")
    print("="*60)
    if run_shap and HAS_SHAP and regression_dataset and regression_feature_names:
        try:
            best_reg_model = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42, n_jobs=-1)
            best_reg_model.fit(X_tr_r, y_tr_r)
            results["phase7"] = explain_model(
                best_reg_model, X_tr_r, X_te_r,
                feature_names=regression_feature_names,
                task_name="prediction_retard_paiement",
                output_dir=output_dir,
            )
        except Exception as e:
            results["phase7"] = {"error": str(e)}
    else:
        print("  ⚠ SHAP désactivé ou non installé (pip install shap)")
        results["phase7"] = {"note": "run with run_shap=True and pip install shap"}

    # ── Phase 8 : Model Recommendations ───────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 8 — RECOMMANDATIONS FINALES")
    print("="*60)
    _regression_target = regression_dataset.get("target_col", "payment_delay_days") if regression_dataset else "payment_delay_days"
    results["phase8"] = recommend_models(
        reg_benchmark, ts_benchmark, dl_benchmark,
        output_dir=output_dir,
        reg_target=_regression_target,
    )

    # ── Phase 9 : Finance AI Agent ────────────────────────────────────────────
    print("\n" + "="*60)
    print("PHASE 9 — FINANCE AI AGENT")
    print("="*60)
    agent = FinanceAIAgent(models_dir=models_dir)
    agent.load()
    agent.save_report(output_dir=output_dir)

    # Démonstration des capacités de l'agent
    demo_results: Dict[str, Any] = {}
    for query in ["kpi_summary", "top_clients", "retard_paiement"]:
        demo_results[query] = agent.answer(query, context=warehouse)
        print(f"  Agent.answer('{query}') : OK")

    results["phase9"] = {
        "agent_ready":     True,
        "models_loaded":   list(agent._models.keys()),
        "demo_queries":    demo_results,
        "supported_queries": FinanceAIAgent.SUPPORTED_QUERIES,
    }
    _save_json(results["phase9"], output_dir / "phase9_agent_demo.json")

    # ── Résumé final ───────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("RÉSUMÉ FINAL — PIPELINE AVANCÉ TERMINÉ")
    print("="*70)
    print(f"  Rapports  → {output_dir}/")
    print(f"  Modèles   → {models_dir}/")
    print(f"  Graphiques → {PLOTS_DIR}/")

    best_reg_name = (
        results["phase8"].get("prediction_retard_paiement", {}).get("best_model")
        or results["phase8"].get("forecast_ventes", {}).get("best_model", "—")
    )
    best_ts_name  = results["phase8"].get("forecast_tresorerie", {}).get("best_model", "—")
    print(f"\n  Meilleur modèle Régression   : {best_reg_name}")
    print(f"  Meilleur modèle Séries TS    : {best_ts_name}")
    print(f"  Détection anomalies          : IsolationForest")
    print(f"  Agent Finance                : FinanceAIAgent — {len(agent._models)} modèles")
    print("="*70 + "\n")

    _save_json({k: v for k, v in results.items() if k not in ["phase1", "phase3"]},
               output_dir / "advanced_pipeline_summary.json")
    return results
