"""
agents/recommendation_agent.py
==============================
Recommendation Agent
"""
from typing import Dict, Any, List
from graphs.state import AgentState, Recommendation
from config.settings import get_llm

class RecommendationAgent:
    def generate(self, state: AgentState) -> List[Recommendation]:
        # Simple rule-based/LLM generation
        recs = []
        if state.get("ml_results", {}).get("anomalies"):
            recs.append(Recommendation(action="Vérifier les anomalies détectées", impact="Haut", priority="Urgent"))
        if not recs:
            recs.append(Recommendation(action="Continuer le monitoring", impact="Faible", priority="Basse"))
        return recs
