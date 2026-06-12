"""
graphs/nodes.py
===============
Nœuds pour LangGraph.
"""
from graphs.state import AgentState
from agents import SupervisorAgent, SQLAgent, MLAgent, ForecastAgent, BusinessAgent, RecommendationAgent, ReportAgent

supervisor = SupervisorAgent()
sql_agent = SQLAgent()
ml_agent = MLAgent()
forecast_agent = ForecastAgent()
biz_agent = BusinessAgent()
rec_agent = RecommendationAgent()
rep_agent = ReportAgent()

def intent_classifier_node(state: AgentState) -> AgentState:
    intent = supervisor.analyze_intent(state["question"])
    return {"intent": intent}
    
def router_node(state: AgentState) -> AgentState:
    plan = supervisor.plan_execution(state["intent"])
    return {"execution_plan": plan}

def sql_agent_node(state: AgentState) -> AgentState:
    res = sql_agent.execute(state["question"], state)
    return {"sql_results": res}

def ml_agent_node(state: AgentState) -> AgentState:
    res = ml_agent.analyze(state)
    return {"ml_results": res}
    
def forecast_agent_node(state: AgentState) -> AgentState:
    res = forecast_agent.forecast(state)
    return {"forecast_results": res}
    
def business_agent_node(state: AgentState) -> AgentState:
    res = biz_agent.analyze(state)
    return {"business_insights": res}

def recommendation_node(state: AgentState) -> AgentState:
    res = rec_agent.generate(state)
    return {"recommendations": res}
    
def synthesis_node(state: AgentState) -> AgentState:
    # Compile
    return state
    
def report_node(state: AgentState) -> AgentState:
    res = rep_agent.compose(state)
    return {"final_answer": res}
