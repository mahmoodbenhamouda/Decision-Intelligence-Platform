"""
tools/ml/shap_explainability_tool.py
====================================
Outil LangChain pour l'explicabilité (SHAP).
"""
import json
import traceback
from pathlib import Path
from langchain.tools import tool
import joblib

try:
    from ml_engine.phases.phase7_shap import explain_model, get_shap_summary
    HAS_SHAP_MOD = True
except ImportError:
    HAS_SHAP_MOD = False

@tool("explain_predictions_shap")
def explain_predictions_shap(task: str = "regression") -> str:
    """
    Génère une explication SHAP pour le modèle spécifié.
    Args:
        task: 'regression' ou 'classification'
    """
    try:
        if not HAS_SHAP_MOD: return json.dumps({"error": "Module SHAP manquant"})
        
        # Load best model
        model_path = Path("models") / f"{task}_best.joblib"
        if not model_path.exists():
            return json.dumps({"error": f"Modèle {model_path} introuvable."})
            
        model = joblib.load(model_path)
        
        # For POC, use synthetic test data since we don't store X_test
        import numpy as np
        X_fake = np.random.rand(100, 5) 
        features = [f"f_{i}" for i in range(5)]
        
        report = explain_model(model, X_fake, X_fake, features, task_name=task, output_dir=Path("reports"))
        return json.dumps({
            "summary": get_shap_summary(report),
            "report": report
        })
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
