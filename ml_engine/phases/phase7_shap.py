"""
ml_engine/phases/phase7_shap.py
===============================
Phase 7 : Explicabilité avec SHAP.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False
    
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from ml_engine.phases.phase1_data_quality import save_json


def explain_model(
    model: Any,
    X_train: np.ndarray,
    X_test: np.ndarray,
    feature_names: List[str],
    task_name: str = "model",
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    print(f"\n  [Phase 7] Explicabilité SHAP ({task_name})...")
    
    if not HAS_SHAP:
        return {"error": "SHAP non installé"}

    report: Dict[str, Any] = {}
    
    try:
        # Echantillon si trop grand
        if len(X_test) > 500:
            np.random.seed(42)
            idx = np.random.choice(len(X_test), 500, replace=False)
            X_sample = X_test[idx]
        else:
            X_sample = X_test

        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_sample)
        
        # Gestions multi-class (liste de SHAP values)
        if isinstance(shap_values, list):
            sv = np.abs(shap_values[1]).mean(0)
        else:
            sv = np.abs(shap_values).mean(0)
            
        feature_importance = pd.DataFrame({
            "feature": feature_names,
            "importance": sv
        }).sort_values("importance", ascending=False)
        
        top_features = feature_importance.head(10).set_index("feature")["importance"].to_dict()
        report["top_features"] = {k: round(float(v), 4) for k, v in top_features.items()}
        
        if HAS_MATPLOTLIB and output_dir:
            plots_dir = output_dir / "plots"
            plots_dir.mkdir(parents=True, exist_ok=True)
            plt.figure()
            shap.summary_plot(shap_values, X_sample, feature_names=feature_names, show=False)
            plt.savefig(plots_dir / f"phase7_{task_name}_shap_summary.png", bbox_inches="tight")
            plt.close()
            
    except Exception as e:
        report["error"] = str(e)
        
    if output_dir:
        save_json(report, output_dir / f"phase7_{task_name}_shap.json")
        
    return report

def get_shap_summary(report: Dict[str, Any]) -> str:
    if "error" in report:
        return f"Erreur SHAP : {report['error']}"
    tf = report.get("top_features", {})
    return "Top features SHAP : " + ", ".join([f"{k} ({v})" for k, v in tf.items()])
