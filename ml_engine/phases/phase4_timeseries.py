"""
ml_engine/phases/phase4_timeseries.py
=====================================
Phase 4 : Analyse statistique des séries temporelles.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.stattools import adfuller, acf, pacf
    from statsmodels.tsa.seasonal import seasonal_decompose
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from ml_engine.phases.phase1_data_quality import _sanitize, save_json


def analyze_time_series(
    ts_df: pd.DataFrame,
    value_col: str = "y",
    date_col: str = "ds",
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 4 : Analyse statistique des séries temporelles.

    Applique :
        - Test ADF (stationnarité)
        - Décomposition saisonnière (trend, seasonal, residual)
        - Autocorrélation (ACF)
        - Autocorrélation partielle (PACF)
        - Détection automatique saisonnalité

    Args:
        ts_df: DataFrame temporel
        value_col: Colonne cible
        date_col: Colonne date
        output_dir: Répertoire de sortie pour le rapport

    Returns:
        dict : résultats de tous les tests
    """
    print("\n  [Phase 4] Analyse Séries Temporelles...")

    if not HAS_STATSMODELS:
        print("    ⚠ statsmodels non installé — skip")
        return {"error": "statsmodels not available"}

    report: Dict[str, Any] = {}
    
    if value_col not in ts_df.columns:
        return {"error": f"Colonne {value_col} absente"}
        
    series = ts_df[value_col].dropna()
    if len(series) < 5:
        return {"error": "Série temporelle trop courte (< 5)"}

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
            date_range = (pd.to_datetime(ts_df[date_col]).max() - pd.to_datetime(ts_df[date_col]).min()).days
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
            if HAS_MATPLOTLIB and output_dir:
                try:
                    plots_dir = output_dir / "plots"
                    plots_dir.mkdir(parents=True, exist_ok=True)
                    fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True)
                    axes[0].plot(series.values, color="#2196F3"); axes[0].set_title("Série originale")
                    axes[1].plot(decomp.trend.values, color="#FF9800"); axes[1].set_title("Tendance")
                    axes[2].plot(decomp.seasonal.values, color="#4CAF50"); axes[2].set_title("Saisonnalité")
                    axes[3].plot(decomp.resid.values, color="#F44336"); axes[3].set_title("Résidus")
                    plt.suptitle("Décomposition Saisonnière", fontsize=11)
                    plt.tight_layout()
                    plt.savefig(plots_dir / "phase4_seasonal_decomposition.png", dpi=80)
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
            if HAS_MATPLOTLIB and output_dir:
                try:
                    plots_dir = output_dir / "plots"
                    plots_dir.mkdir(parents=True, exist_ok=True)
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
                    plt.savefig(plots_dir / "phase4_acf_pacf.png", dpi=80)
                    plt.close()
                except Exception:
                    pass
    except Exception as e:
        report["acf_pacf_error"] = str(e)

    if output_dir:
        save_json(report, output_dir / "phase4_timeseries_analysis.json")
        print(f"    ✓ Rapport : {output_dir}/phase4_timeseries_analysis.json")
        
    return report

def get_ts_summary(report: Dict[str, Any]) -> str:
    """Génère un résumé textuel pour le LLM."""
    if "error" in report:
        return f"Erreur : {report['error']}"
        
    lines = ["Analyse de Série Temporelle :"]
    adf = report.get("adf_test", {})
    if adf:
        if adf.get("is_stationary"):
            lines.append("- La série est stationnaire.")
        else:
            diff1 = report.get("adf_test_diff1", {})
            if diff1.get("is_stationary"):
                lines.append("- La série est non-stationnaire (différenciation d=1 requise).")
            else:
                lines.append("- La série est non-stationnaire.")
                
    decomp = report.get("decomposition", {})
    if decomp and "error" not in decomp:
        lines.append(f"- Période détectée : {decomp.get('period')}")
        if decomp.get('has_strong_trend'):
            lines.append("- Tendance forte détectée.")
        if decomp.get('has_strong_seasonality'):
            lines.append("- Saisonnalité forte détectée.")
            
    lags = report.get("significant_lags", {})
    if lags:
        acf_lags = lags.get('acf_lags', [])
        if acf_lags:
            lines.append(f"- Lags ACF significatifs : {acf_lags[:3]}")
            
    return "\n".join(lines)
