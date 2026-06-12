"""
tools/business/payment_risk_tool.py
===================================
Outil LangChain pour analyser les retards de paiement.
"""
import json
import traceback
from langchain.tools import tool
from ml_engine.phases.phase9_agent import FinanceAIAgent
from connectors.warehouse_connector import get_warehouse

@tool("analyze_payment_risks")
def analyze_payment_risks(dummy: str = "") -> str:
    """
    Analyse les risques de retards de paiement et calcule les indicateurs.
    """
    try:
        warehouse = get_warehouse()
        agent = FinanceAIAgent()
        if hasattr(agent, "answer"):
            res = agent.answer("retard_paiement", context=warehouse)
            return json.dumps(res, default=str)
        return json.dumps({"error": "Méthode non supportée"})
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
