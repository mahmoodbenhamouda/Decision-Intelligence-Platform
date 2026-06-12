"""
tools/forecast/ensemble_forecast_tool.py
========================================
Outil LangChain pour faire une prévision d'ensemble.
"""
import json
import traceback
from langchain.tools import tool
from connectors.warehouse_connector import get_warehouse
from ml_engine.phases.phase5_benchmark import benchmark_timeseries_models

@tool("generate_forecast")
def generate_forecast(table_name: str, target: str, horizon: int = 12) -> str:
    """
    Génère une prévision (forecast) en utilisant un ensemble de modèles.
    Args:
        table_name: Nom de la table
        target: Colonne cible (ex: 'ttc_dev' pour ventes)
        horizon: Nombre de périodes à prédire (ex: 12)
    """
    try:
        warehouse = get_warehouse()
        if table_name not in warehouse:
            return json.dumps({"error": f"Table {table_name} introuvable."})
            
        df = warehouse[table_name]
        
        if len(df) < horizon + 12:
            return json.dumps({"error": "Données insuffisantes pour faire un forecast."})
            
        # Benchmark renvoie l'évaluation, ici on fait juste un wrappper simple
        res = benchmark_timeseries_models(df, n_test=horizon, value_col=target)
        
        return json.dumps({
            "status": "success",
            "benchmark_results": res,
            "note": "Pour avoir les vraies valeurs prédites dans le futur, il faut entrainer sur toutes les données. Ceci est un rapport d'erreur sur l'horizon de test."
        }, default=str)
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
