"""
tools/ml/model_prediction_tool.py
=================================
Outil LangChain pour faire des prédictions.
"""
import json
import traceback
from pathlib import Path
from langchain.tools import tool
import numpy as np

try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

@tool("predict_with_model")
def predict_with_model(task: str, features_json: str) -> str:
    """
    Fait une prédiction avec un modèle entraîné.
    Args:
        task: 'regression' ou 'classification'
        features_json: Chaine JSON représentant un dict de features (ex: '{"f1": 10, "f2": 5}')
    """
    try:
        if not HAS_JOBLIB: return json.dumps({"error": "joblib manquant"})
        
        features_dict = json.loads(features_json)
        arr = np.array([list(features_dict.values())], dtype=float)
        
        model_path = Path("models") / f"{task}_best.joblib"
        if not model_path.exists():
             return json.dumps({"error": f"Modèle introuvable : {model_path}"})
             
        model = joblib.load(model_path)
        pred = model.predict(arr)
        
        return json.dumps({"prediction": pred.tolist()})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
