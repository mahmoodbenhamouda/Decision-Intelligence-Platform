"""
ml_engine/phases/phase1_data_quality.py
=======================================
Phase 1 : Validation complète de la qualité des données.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


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


def save_json(data: Any, path: Path) -> None:
    """Sauvegarde un objet en JSON avec sérialisation numpy-safe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(data), f, indent=2, ensure_ascii=False, default=str)


def validate_data_quality(
    warehouse: Dict[str, pd.DataFrame],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 1 : Validation complète de la qualité des données.

    Analyses :
        - Valeurs manquantes (taux par colonne/table)
        - Outliers (IQR 3x)
        - Variance nulle / quasi-nulle
        - Distribution des features
        - Déséquilibre de classes (classification)
        - Cohérence temporelle (dates dans l'ordre)

    Args:
        warehouse: Dict des DataFrames (Fact_Ventes, Fact_Achats, ...)
        output_dir: Répertoire de sortie pour les rapports JSON

    Returns:
        report: Dict consolidé de toutes les métriques de qualité
    """
    print("\n" + "=" * 60)
    print("PHASE 1 — VALIDATION QUALITÉ DES DONNÉES")
    print("=" * 60)

    report: Dict[str, Any] = {
        "timestamp": pd.Timestamp.now().isoformat(),
        "tables_analyzed": [],
        "global_score": 0.0,
        "tables": {},
    }

    scores = []

    for table_name, df in warehouse.items():
        if df.empty:
            continue

        print(f"\n  [{table_name}] {df.shape[0]:,} lignes × {df.shape[1]} colonnes")
        table_report: Dict[str, Any] = {"shape": {"rows": len(df), "columns": len(df.columns)}}

        # ── 1.1 Valeurs manquantes ────────────────────────────────────────────
        null_counts = df.isnull().sum()
        null_pct = (null_counts / len(df) * 100).round(2)
        missing = {
            col: {"count": int(null_counts[col]), "pct": float(null_pct[col])}
            for col in df.columns if null_counts[col] > 0
        }
        total_cells = len(df) * len(df.columns)
        total_missing = int(null_counts.sum())
        missing_pct = round(total_missing / total_cells * 100, 2) if total_cells > 0 else 0

        table_report["missing_values"] = {
            "total_missing_cells": total_missing,
            "total_pct": missing_pct,
            "by_column": missing,
        }

        # ── 1.2 Outliers (IQR 3x, sur numériques) ────────────────────────────
        num = df.select_dtypes(include=[np.number])
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

        # ── 1.3 Variance nulle / quasi-nulle ─────────────────────────────────
        low_variance = {}
        for col in num.columns:
            v = float(num[col].var())
            if v < 1e-6:
                low_variance[col] = {"variance": v}
        table_report["low_variance_columns"] = low_variance

        # ── 1.4 Statistiques descriptives ─────────────────────────────────────
        if not num.empty:
            desc = num.describe().round(4).to_dict()
            table_report["descriptive_stats"] = desc

        # ── 1.5 Cohérence temporelle ──────────────────────────────────────────
        date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        temporal_issues: Dict[str, Any] = {}
        for col in date_cols:
            n_future = int((df[col] > pd.Timestamp.now()).sum())
            n_before_2000 = int((df[col] < pd.Timestamp("2000-01-01")).sum())
            n_null = int(df[col].isnull().sum())
            temporal_issues[col] = {
                "future_dates": n_future,
                "before_year_2000": n_before_2000,
                "null_dates": n_null,
                "min_date": str(df[col].min()) if df[col].notna().any() else None,
                "max_date": str(df[col].max()) if df[col].notna().any() else None,
            }
        table_report["temporal_analysis"] = temporal_issues

        # ── 1.6 Déséquilibre de classes (si colonne binaire) ──────────────────
        class_balance: Dict[str, Any] = {}
        for col in df.columns:
            if df[col].nunique() == 2 and pd.api.types.is_numeric_dtype(df[col]):
                vc = df[col].value_counts(normalize=True).round(4).to_dict()
                class_balance[col] = vc
                break
        table_report["class_balance"] = class_balance

        # ── 1.7 Score de qualité global (0-100) ───────────────────────────────
        quality_score = 100.0
        quality_score -= min(missing_pct * 2, 30)          # -2 pts par % de nulls
        quality_score -= min(len(low_variance) * 5, 20)    # -5 pts par colonne zero-var
        outlier_cols = len([v for v in outlier_summary.values() if v.get("pct", 0) > 5])
        quality_score -= min(outlier_cols * 5, 30)          # -5 pts par col avec >5% outliers
        quality_score = max(0.0, quality_score)

        table_report["quality_score"] = round(quality_score, 1)
        scores.append(quality_score)

        missing_count = total_missing
        outlier_count = sum(v["n_outliers"] for v in outlier_summary.values())
        print(f"    ✓ Manquantes: {missing_count:,} ({missing_pct:.1f}%) | "
              f"Outliers: {outlier_count:,} | Variance nulle: {len(low_variance)} | "
              f"Score qualité: {quality_score:.0f}/100")

        report["tables"][table_name] = table_report
        report["tables_analyzed"].append(table_name)

    # ── Score global ──────────────────────────────────────────────────────────
    report["global_score"] = round(float(np.mean(scores)) if scores else 0.0, 1)
    report["n_tables"] = len(scores)

    print(f"\n  ✅ Score qualité global : {report['global_score']}/100")

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        save_json(report, output_dir / "phase1_data_quality.json")
        print(f"  → Rapport : {output_dir}/phase1_data_quality.json")

    return report


def get_data_quality_summary(report: Dict[str, Any]) -> str:
    """Génère un résumé textuel du rapport de qualité (pour le LLM)."""
    lines = [
        f"Score qualité global : {report.get('global_score', 0)}/100",
        f"Tables analysées : {', '.join(report.get('tables_analyzed', []))}",
    ]
    for table, data in report.get("tables", {}).items():
        mv = data.get("missing_values", {})
        out = data.get("outliers", {})
        score = data.get("quality_score", 0)
        lines.append(
            f"- {table}: {mv.get('total_pct', 0):.1f}% manquants, "
            f"{len(out)} colonnes avec outliers, score={score}/100"
        )
    return "\n".join(lines)
