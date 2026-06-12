"""
tools/business/rfm_tool.py
==========================
Outil LangChain pour extraire la segmentation RFM.
"""
import json
import traceback
from langchain.tools import tool
from ml_engine.phases.phase9_agent import FinanceAIAgent
from connectors.warehouse_connector import get_warehouse

@tool("get_top_clients_rfm")
def get_top_clients_rfm(dummy: str = "") -> str:
    """
    Extrait les meilleurs clients basés sur le chiffre d'affaires et la récence (RFM partiel).
    """
    try:
        warehouse = get_warehouse()
        agent = FinanceAIAgent()
        if hasattr(agent, "answer"):
            res = agent.answer("top_clients", context=warehouse)
            return json.dumps(res, default=str)
        return json.dumps({"error": "Méthode non supportée"})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
