"""All Langchain tools."""
from tools.data import data_quality_tool, execute_sql, describe_schema, get_warehouse_summary
from tools.ml import run_feature_engineering, run_anomaly_detection, explain_predictions_shap, predict_with_model
from tools.forecast import analyze_time_series_tool, generate_forecast
from tools.business import get_financial_kpis, get_top_clients_rfm, analyze_payment_risks, analyze_trends
from tools.report import generate_narrative, generate_chart

ALL_TOOLS = [
    data_quality_tool,
    execute_sql,
    describe_schema,
    get_warehouse_summary,
    run_feature_engineering,
    run_anomaly_detection,
    explain_predictions_shap,
    predict_with_model,
    analyze_time_series_tool,
    generate_forecast,
    get_financial_kpis,
    get_top_clients_rfm,
    analyze_payment_risks,
    analyze_trends,
    generate_narrative,
    generate_chart
]
