"""
ml_engine/phases/phase2_feature_eng.py
=======================================
Phase 2 : Feature Engineering Financier Avancé.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


# Calendrier Ramadan approximatif (Tunisie)
_RAMADAN_MONTH: Dict[int, int] = {
    2016: 6, 2017: 6, 2018: 5, 2019: 5, 2020: 4,
    2021: 4, 2022: 4, 2023: 3, 2024: 3, 2025: 3, 2026: 2,
}


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
        - Lag features (lag_1, lag_3, lag_6, lag_12, lag_24)
        - Trend features (MA, momentum, pct_change, EMA, MACD)

    Args:
        fact_df:   DataFrame source (transaction ou série temporelle)
        date_col:  Colonne de date
        value_col: Colonne de valeur cible

    Returns:
        DataFrame enrichi avec ~60 features supplémentaires
    """
    print(f"\n  [Phase 2] Feature Engineering avancé sur '{value_col}'...")

    df = fact_df.copy()

    if date_col not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        print(f"    ⚠ Colonne '{date_col}' absente ou non-datetime — skip")
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

    # Encodage cyclique (meilleur pour linéaires/DL)
    df["feat_month_sin"]  = np.sin(2 * np.pi * df["feat_month"] / 12)
    df["feat_month_cos"]  = np.cos(2 * np.pi * df["feat_month"] / 12)
    df["feat_dow_sin"]    = np.sin(2 * np.pi * df["feat_dayofweek"] / 7)
    df["feat_dow_cos"]    = np.cos(2 * np.pi * df["feat_dayofweek"] / 7)
    df["feat_quarter_sin"] = np.sin(2 * np.pi * df["feat_quarter"] / 4)
    df["feat_quarter_cos"] = np.cos(2 * np.pi * df["feat_quarter"] / 4)

    # Indicateurs saisonniers tunisiens
    df["feat_is_summer"]   = (df["feat_month"].isin([6, 7, 8])).astype(int)
    df["feat_is_end_year"] = (df["feat_month"].isin([11, 12])).astype(int)
    df["feat_is_winter"]   = (df["feat_month"].isin([12, 1, 2])).astype(int)

    # Indicateur Ramadan (calendrier lunaire tunisien approximatif)
    df["feat_is_ramadan"] = [
        int(_RAMADAN_MONTH.get(int(yr), 0) == int(mo))
        for yr, mo in zip(df["feat_year"], df["feat_month"])
    ]

    # ── 2.2 Rolling statistics (strict causal : shift(1) avant rolling) ────────
    if value_col in df.columns and pd.api.types.is_numeric_dtype(df[value_col]):
        v = pd.to_numeric(df[value_col], errors="coerce")
        history = v.shift(1)  # Causal : n'utilise que les données passées

        for w in [7, 30, 90, 365]:
            prefix = f"roll_{w}d"
            hw = history.rolling(w, min_periods=max(2, min(w, 3)))
            df[f"{prefix}_mean"]   = hw.mean()
            df[f"{prefix}_median"] = hw.median()
            df[f"{prefix}_std"]    = hw.std()
            df[f"{prefix}_min"]    = hw.min()
            df[f"{prefix}_max"]    = hw.max()
            df[f"{prefix}_growth"] = hw.apply(
                lambda x: (x.iloc[-1] - x.iloc[0]) / (abs(x.iloc[0]) + 1e-9) * 100
                if len(x) > 1 else 0,
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

        # MACD (signal technique)
        ema_12 = history.ewm(span=12, adjust=False).mean()
        ema_26 = history.ewm(span=26, adjust=False).mean()
        df["trend_ema_12"]       = ema_12
        df["trend_ema_26"]       = ema_26
        df["trend_macd"]         = ema_12 - ema_26
        df["trend_macd_signal"]  = df["trend_macd"].ewm(span=9, adjust=False).mean()

        # Croissance cumulée
        first_val = history.dropna().iloc[0] if history.notna().any() else np.nan
        df["trend_cumgrowth"] = history.apply(
            lambda x: (x / (first_val + 1e-9)) - 1 if pd.notna(x) else np.nan
        )

    new_cols = [c for c in df.columns if c.startswith(("feat_", "roll_", "lag_", "trend_"))]
    print(f"    ✓ {len(new_cols)} features générées")
    return df


def build_timeseries_features(
    warehouse: Dict[str, pd.DataFrame],
    date_col: str = "datepiece",
    value_col: str = "ttc_dev",
    freq: str = "ME",
) -> pd.DataFrame:
    """
    Construit une série temporelle mensuelle agrégée depuis Fact_Ventes
    et y applique engineer_features.

    Args:
        warehouse: Dict des tables du warehouse
        date_col:  Colonne date dans Fact_Ventes
        value_col: Colonne valeur (TTC)
        freq:      Fréquence d'agrégation ('ME'=fin de mois, 'W'=semaine)

    Returns:
        DataFrame mensuel enrichi avec features temporelles
    """
    fact = warehouse.get("Fact_Ventes", pd.DataFrame())
    if fact.empty or date_col not in fact.columns:
        print("    ⚠ Fact_Ventes vide ou sans colonne date — skip")
        return pd.DataFrame()

    ts = fact[[date_col, value_col]].copy()
    ts[date_col] = pd.to_datetime(ts[date_col], errors="coerce")
    ts = ts.dropna()

    # Agrégation mensuelle avec indicateurs complémentaires
    ts_agg = (
        ts.set_index(date_col)
        .resample(freq)
        .agg({value_col: ["sum", "count", "mean", "std"]})
    )
    ts_agg.columns = ["y", "nb_invoices", "avg_invoice_amount", "std_invoice_amount"]
    ts_agg = ts_agg.reset_index().rename(columns={date_col: "ds"})
    ts_agg = ts_agg.sort_values("ds").reset_index(drop=True)
    ts_agg["y"] = ts_agg["y"].fillna(ts_agg["y"].median())
    ts_agg["nb_invoices"] = ts_agg["nb_invoices"].fillna(0).astype(float)
    ts_agg["avg_invoice_amount"] = ts_agg["avg_invoice_amount"].fillna(0)
    ts_agg["std_invoice_amount"] = ts_agg["std_invoice_amount"].fillna(0)

    # Application du feature engineering complet
    ts_enriched = engineer_features(ts_agg, date_col="ds", value_col="y")

    # YoY growth (Year-over-Year)
    if "lag_1" in ts_enriched.columns and "lag_12" in ts_enriched.columns:
        lag1 = ts_enriched["lag_1"]
        lag12 = ts_enriched["lag_12"]
        ts_enriched["yoy_growth"] = (lag1 / (lag12.replace(0, np.nan)) - 1).clip(-2, 5).fillna(0)
        ts_enriched["yoy_delta"]  = (lag1 - lag12).fillna(0)

    # Rolling invoice count
    if "nb_invoices" in ts_enriched.columns:
        nb = ts_enriched["nb_invoices"].shift(1)
        ts_enriched["nb_invoices_ma3"] = nb.rolling(3, min_periods=1).mean()
        ts_enriched["nb_invoices_ma6"] = nb.rolling(6, min_periods=1).mean()

    print(f"    ✓ Série mensuelle : {ts_enriched.shape[0]} périodes × {ts_enriched.shape[1]} features")
    return ts_enriched


def get_feature_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """Retourne un résumé des features générées."""
    feat_cols = [c for c in df.columns if c.startswith(("feat_", "roll_", "lag_", "trend_"))]
    return {
        "n_total_features": len(df.columns),
        "n_engineered_features": len(feat_cols),
        "temporal_features": [c for c in feat_cols if c.startswith("feat_")],
        "rolling_features": [c for c in feat_cols if c.startswith("roll_")],
        "lag_features": [c for c in feat_cols if c.startswith("lag_")],
        "trend_features": [c for c in feat_cols if c.startswith("trend_")],
        "n_rows": len(df),
    }
