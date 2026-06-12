"""
tools/business/kpi_tool.py
==========================
Outil LangChain pour extraire les KPIs financiers.
"""
import json
import traceback
from langchain.tools import tool
from ml_engine.phases.phase9_agent import FinanceAIAgent
from connectors.warehouse_connector import get_warehouse

@tool("get_financial_kpis")
def get_financial_kpis(dummy: str = "") -> str:
    """
    Extrait les KPIs financiers clés (ventes totales, nombre de clients, etc.).
    """
    try:
        warehouse = get_warehouse()
        agent = FinanceAIAgent()
        if hasattr(agent, "answer"):
            res = agent.answer("kpi_summary", context=warehouse)
            return json.dumps(res, default=str)
        return json.dumps({"error": "Méthode non supportée"})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
