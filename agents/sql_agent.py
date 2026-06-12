"""
agents/sql_agent.py
===================
SQL Agent
"""
from typing import Dict, Any
from graphs.state import AgentState
from tools.data.sql_query_tool import execute_sql, describe_schema

class SQLAgent:
    def execute(self, question: str, state: AgentState) -> Dict[str, Any]:
        """
        Extrait les données. (Version basique sans parsing LLM->SQL pour éviter timeout).
        """
        # Dans un vrai système, on utiliserait le LLM pour text2sql
        # Ici on fait un fallback simple pour le POC
        if "kpi" in question.lower() or "top" in question.lower():
            sql = "SELECT cle_client, sum(ttc_dev) as ca FROM Fact_Ventes GROUP BY cle_client ORDER BY ca DESC LIMIT 5"
            try:
                res = execute_sql(sql)
                return {"query": sql, "result": res}
            except:
                pass
        return {"query": "N/A", "result": "Pas de requête générée"}
