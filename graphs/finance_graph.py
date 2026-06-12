"""
graphs/finance_graph.py
=======================
Définition et compilation du StateGraph.
"""
from langgraph.graph import StateGraph, END
try:
    from langgraph.checkpoint.memory import MemorySaver
    HAS_MEM = True
except ImportError:
    HAS_MEM = False
    
from graphs.state import AgentState
from graphs.nodes import (
    intent_classifier_node, router_node, sql_agent_node,
    ml_agent_node, forecast_agent_node, business_agent_node,
    recommendation_node, synthesis_node, report_node
)
from graphs.edges import route_after_intent

def build_finance_graph():
    builder = StateGraph(AgentState)
    
    # Add nodes
    builder.add_node("intent_classifier_node", intent_classifier_node)
    builder.add_node("router_node", router_node)
    builder.add_node("sql_agent_node", sql_agent_node)
    builder.add_node("ml_agent_node", ml_agent_node)
    builder.add_node("forecast_agent_node", forecast_agent_node)
    builder.add_node("business_agent_node", business_agent_node)
    builder.add_node("recommendation_node", recommendation_node)
    builder.add_node("synthesis_node", synthesis_node)
    builder.add_node("report_node", report_node)
    
    # Add edges
    builder.set_entry_point("intent_classifier_node")
    builder.add_edge("intent_classifier_node", "router_node")
    
    # Simplified linear execution for POC
    builder.add_edge("router_node", "sql_agent_node")
    builder.add_edge("sql_agent_node", "ml_agent_node")
    builder.add_edge("ml_agent_node", "forecast_agent_node")
    builder.add_edge("forecast_agent_node", "business_agent_node")
    builder.add_edge("business_agent_node", "recommendation_node")
    builder.add_edge("recommendation_node", "synthesis_node")
    builder.add_edge("synthesis_node", "report_node")
    builder.add_edge("report_node", END)
    
    memory = MemorySaver() if HAS_MEM else None
    return builder.compile(checkpointer=memory)
