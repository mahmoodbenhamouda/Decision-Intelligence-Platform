"""
tools/ml/anomaly_detection_tool.py
==================================
Outil LangChain pour la détection d'anomalies.
"""
import json
import traceback
from langchain.tools import tool
from ml_engine.phases.phase9_agent import FinanceAIAgent

@tool("run_anomaly_detection")
def run_anomaly_detection(table_name: str) -> str:
    """
    Exécute l'algorithme de détection d'anomalies sur les données.
    Args:
        table_name: Nom de la table (ex: 'Fact_Ventes')
    """
    try:
        from connectors.warehouse_connector import get_warehouse
        warehouse = get_warehouse()
        agent = FinanceAIAgent()
        # Le Legacy agent a une méthode detect_anomalies dans la doc originale, on simule l'appel s'il existe
        if hasattr(agent, "answer"):
            res = agent.answer("detect_anomalies", context=warehouse)
            return json.dumps(res, default=str)
        return json.dumps({"error": "Méthode non supportée"})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
