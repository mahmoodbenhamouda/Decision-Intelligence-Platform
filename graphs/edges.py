"""
graphs/edges.py
===============
Transitions pour LangGraph.
"""
from graphs.state import AgentState

def route_after_intent(state: AgentState) -> str:
    # Router logic from execution_plan (parallel send is better but we use simplified here)
    plan = state.get("execution_plan", [])
    if "sql_agent_node" in plan: return "sql_agent_node"
    if "ml_agent_node" in plan: return "ml_agent_node"
    if "forecast_agent_node" in plan: return "forecast_agent_node"
    if "business_agent_node" in plan: return "business_agent_node"
    return "synthesis_node"
