"""
tools/report/narrative_tool.py
==============================
Outil LangChain pour générer une narration à partir de JSON.
"""
import json
import traceback
from langchain.tools import tool
from config.settings import get_llm

@tool("generate_narrative")
def generate_narrative(data_json: str, context: str = "") -> str:
    """
    Génère un résumé textuel naturel en français à partir de données JSON.
    Args:
        data_json: Chaine JSON représentant les données à résumer.
        context: Contexte optionnel (ex: 'Analyse des ventes').
    """
    try:
        llm = get_llm()
        if not llm:
            return "Les données brutes sont : " + data_json
            
        prompt = f"Génère un résumé exécutif clair en français pour les données suivantes. Contexte: {context}. Données: {data_json}"
        response = llm.invoke(prompt)
        return str(response.content) if hasattr(response, "content") else str(response)
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
