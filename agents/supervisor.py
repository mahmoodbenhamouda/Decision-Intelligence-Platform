"""
agents/supervisor.py
====================
Superviseur.
"""
from typing import List, Dict, Any
from config.settings import get_llm
from graphs.state import IntentSchema, AgentState
from agents.router import IntentRouter

class SupervisorAgent:
    def __init__(self):
        self.llm = get_llm()
        self.router = IntentRouter()
        
    def analyze_intent(self, question: str) -> IntentSchema:
        return self.router.classify(question)
        
    def plan_execution(self, intent: IntentSchema) -> List[str]:
        plan = []
        if intent["requires_sql"]: plan.append("sql_agent_node")
        if intent["requires_ml"]: plan.append("ml_agent_node")
        if intent["requires_forecast"]: plan.append("forecast_agent_node")
        if intent["requires_business"]: plan.append("business_agent_node")
        if not plan: plan.append("sql_agent_node")
        return plan
