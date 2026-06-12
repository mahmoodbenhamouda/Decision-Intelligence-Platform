"""
ml_engine/phases/phase8_selection.py
====================================
Phase 8 : Recommandations et sélection automatique des modèles.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ml_engine.phases.phase1_data_quality import save_json


def recommend_models(
    reg_benchmark: Dict[str, Any],
    ts_benchmark: Dict[str, Any],
    dl_benchmark: Dict[str, Any],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    print("\n  [Phase 8] Recommandations de Modèles...")
    
    recommendations: Dict[str, Any] = {}
    
    # Meilleur regresseur
    valid_reg = {k: v for k, v in reg_benchmark.items() if isinstance(v, dict) and "test_rmse" in v}
    if valid_reg:
        best_reg = min(valid_reg.items(), key=lambda x: x[1]["test_rmse"])[0]
        recommendations["regression_best"] = {
            "model": best_reg,
            "rmse": valid_reg[best_reg]["test_rmse"],
            "r2": valid_reg[best_reg].get("test_r2")
        }
        
    # Meilleur TimeSeries
    valid_ts = {k: v for k, v in {**ts_benchmark, **dl_benchmark}.items() if isinstance(v, dict) and "rmse" in v}
    if valid_ts:
        best_ts = min(valid_ts.items(), key=lambda x: x[1]["rmse"])[0]
        recommendations["timeseries_best"] = {
            "model": best_ts,
            "rmse": valid_ts[best_ts]["rmse"],
            "mape": valid_ts[best_ts].get("mape")
        }
        
    if output_dir:
        save_json(recommendations, output_dir / "phase8_recommendations.json")
        
    return recommendations
