from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd
import streamlit as st

from data_preparation_pipeline import prepare_data_layer
from ml_advanced_pipeline import FinanceAIAgent

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data_pfe"
DEFAULT_MODELS_DIR = BASE_DIR / "models"


@st.cache_resource(show_spinner=False)
def load_context(data_dir: str, models_dir: str) -> Dict[str, Any]:
    """Load warehouse + finance agent once and reuse across interactions."""
    data_path = Path(data_dir)
    model_path = Path(models_dir)

    if not data_path.exists():
        raise FileNotFoundError(f"Data folder not found: {data_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Models folder not found: {model_path}")

    _, warehouse = prepare_data_layer(data_path)
    agent = FinanceAIAgent(models_dir=model_path).load()
    return {"warehouse": warehouse, "agent": agent}


def _summarize_result(result: Dict[str, Any]) -> None:
    if "error" in result:
        st.error(result["error"])
        return

    if result.get("status") == "not_implemented":
        st.warning("Query not implemented in FinanceAIAgent yet.")

    st.json(result)


st.set_page_config(page_title="Finance Agent Demo", page_icon=":bar_chart:", layout="wide")
st.title("Finance AI Agent - Streamlit Demo")
st.caption("Quick local deployment to test your FinanceAIAgent.")

with st.sidebar:
    st.header("Configuration")
    data_dir = st.text_input("Data folder", value=str(DEFAULT_DATA_DIR))
    models_dir = st.text_input("Models folder", value=str(DEFAULT_MODELS_DIR))

    st.markdown("---")
    st.write("Tip: run your advanced pipeline first to generate model artifacts in models/.")

try:
    with st.spinner("Loading warehouse and agent..."):
        context = load_context(data_dir=data_dir, models_dir=models_dir)
except Exception as e:
    st.error(f"Initialization failed: {e}")
    st.stop()

warehouse = context["warehouse"]
agent: FinanceAIAgent = context["agent"]

col1, col2 = st.columns([1, 1])
with col1:
    st.subheader("Agent Queries")
    query = st.selectbox("Choose query", options=agent.SUPPORTED_QUERIES, index=5)
    if st.button("Run Query", type="primary"):
        with st.spinner("Agent is thinking..."):
            result = agent.answer(query=query, context=warehouse)
        _summarize_result(result)

with col2:
    st.subheader("Quick Context")
    st.write("Loaded warehouse tables:")
    st.write(sorted(list(warehouse.keys())))

    if "Fact_Ventes" in warehouse and isinstance(warehouse["Fact_Ventes"], pd.DataFrame):
        st.write("Fact_Ventes preview")
        st.dataframe(warehouse["Fact_Ventes"].head(10), use_container_width=True)

st.markdown("---")
st.info("Supported query keys are exposed from FinanceAIAgent.SUPPORTED_QUERIES.")
