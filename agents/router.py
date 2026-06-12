"""
agents/router.py
================
Routeur d'intention.
"""
import json
from typing import Dict, Any
from config.settings import get_llm
from graphs.state import IntentSchema

class IntentRouter:
    def __init__(self):
        self.llm = get_llm()
        
    def classify(self, question: str) -> IntentSchema:
        """
        Classifie l'intention. Mock basique si Pydantic output parsing est complexe avec Gemini.
        """
        q = question.lower()
        res = IntentSchema(
            category="UNKNOWN",
            confidence=0.9,
            requires_sql=False,
            requires_ml=False,
            requires_forecast=False,
            requires_business=False,
            time_range="all",
            entities=[]
        )
        
        if "forecast" in q or "prévision" in q or "futur" in q:
            res["category"] = "FORECAST_REVENUE"
            res["requires_forecast"] = True
            
        if "anomalie" in q or "bizarre" in q:
            res["category"] = "ANOMALY_DETECTION"
            res["requires_ml"] = True
            
        if "kpi" in q or "résumé" in q or "top" in q:
            res["category"] = "KPI_DASHBOARD"
            res["requires_business"] = True
            res["requires_sql"] = True
            
        if not any([res["requires_sql"], res["requires_ml"], res["requires_forecast"], res["requires_business"]]):
            res["requires_sql"] = True # Par défaut
            
        return res
