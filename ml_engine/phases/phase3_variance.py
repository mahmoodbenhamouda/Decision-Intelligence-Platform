"""
ml_engine/phases/phase3_variance.py
===================================
Phase 3 : Analyse de variance et sélection de features.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    from sklearn.feature_selection import VarianceThreshold, mutual_info_regression
    from sklearn.ensemble import RandomForestRegressor
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from ml_engine.phases.phase1_data_quality import _sanitize, save_json


def _get_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Retourne uniquement les colonnes numériques."""
    return df.select_dtypes(include=[np.number])


def analyze_variance(
    X_df: pd.DataFrame,
    y: Optional[pd.Series] = None,
    corr_threshold: float = 0.95,
    variance_threshold: float = 0.01,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 3 : Analyse de variance et sélection de features.

    Applique :
        - VarianceThreshold : supprime features quasi-constantes
        - Matrice de corrélation : détecte redondance (|r| > 0.95)
        - Mutual Information : quantifie l'info par feature envers y
        - Feature Importance (RF) : importance permutation-based

    Args:
        X_df: DataFrame des features
        y: Série cible (optionnelle)
        corr_threshold: Seuil de corrélation de Pearson
        variance_threshold: Seuil de variance minimale
        output_dir: Répertoire de sortie pour le rapport

    Returns:
        dict: listes de features à conserver / supprimer + rapport
    """
    print("\n  [Phase 3] Analyse de Variance & Sélection de Features...")

    if not HAS_SKLEARN:
        return {"error": "scikit-learn n'est pas installé."}

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
    if HAS_MATPLOTLIB and output_dir:
        try:
            plots_dir = output_dir / "plots"
            plots_dir.mkdir(parents=True, exist_ok=True)
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
            plt.savefig(plots_dir / "phase3_correlation_heatmap.png", dpi=80)
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

    if output_dir:
        save_json(report, output_dir / "phase3_variance_analysis.json")
        print(f"    ✓ Rapport : {output_dir}/phase3_variance_analysis.json")
        
    return report

def get_variance_summary(report: Dict[str, Any]) -> str:
    """Génère un résumé textuel pour le LLM."""
    if "error" in report:
        return f"Erreur : {report['error']}"
    
    lines = ["Analyse de Variance et Features :"]
    low_var = report.get("low_variance", {})
    if low_var:
        lines.append(f"- {len(low_var.get('removed', []))} features supprimées (variance < {low_var.get('threshold')})")
        
    corr = report.get("high_correlation", {})
    if corr:
        lines.append(f"- {corr.get('n_redundant_pairs', 0)} paires fortement corrélées (r > {corr.get('threshold')})")
        
    fi = report.get("feature_importance_rf", {})
    if fi and "error" not in fi:
        top5 = list(fi.items())[:5]
        lines.append("- Top 5 features RF : " + ", ".join(f"{k} ({v:.3f})" for k, v in top5))
        
    return "\n".join(lines)
