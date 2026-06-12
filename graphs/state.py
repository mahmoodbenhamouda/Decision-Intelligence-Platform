"""
graphs/state.py
===============
Définition de l'AgentState pour LangGraph.
"""
from typing import Annotated, Any, Dict, List, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

class IntentSchema(TypedDict):
    category: str
    confidence: float
    requires_sql: bool
    requires_ml: bool
    requires_forecast: bool
    requires_business: bool
    time_range: str
    entities: List[str]

class MLResults(TypedDict, total=False):
    data_quality: Dict[str, Any]
    anomalies: Dict[str, Any]
    shap_explanation: Dict[str, Any]
    prediction: Dict[str, Any]

class ForecastResults(TypedDict, total=False):
    timeseries_analysis: Dict[str, Any]
    forecast_data: Dict[str, Any]
    confidence_intervals: Dict[str, Any]

class BusinessInsights(TypedDict, total=False):
    kpis: Dict[str, Any]
    trends: Dict[str, Any]
    rfm: Dict[str, Any]
    causal_analysis: str

class Recommendation(TypedDict):
    action: str
    impact: str
    priority: str

class AgentState(TypedDict):
    question: str
    session_id: str
    user_id: str
    timestamp: str
    
    intent: Optional[IntentSchema]
    active_agents: List[str]
    execution_plan: List[str]
    
    business_context: str
    sql_results: Dict[str, Any]
    ml_results: MLResults
    forecast_results: ForecastResults
    business_insights: BusinessInsights
    recommendations: List[Recommendation]
    
    confidence_score: float
    has_critical_anomaly: bool
    
    messages: Annotated[list, add_messages]
    conversation_history: List[Dict[str, str]]
    
    final_answer: str
    structured_output: Dict[str, Any]
    report_url: str
    
    execution_time_ms: int
    agents_used: List[str]
    errors: List[str]
    warnings: List[str]
    
    requires_human_review: bool
    human_feedback: str
    approved: bool
