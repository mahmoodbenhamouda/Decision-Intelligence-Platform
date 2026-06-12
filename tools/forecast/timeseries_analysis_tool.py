"""
tools/forecast/timeseries_analysis_tool.py
==========================================
Outil LangChain pour analyser statistiquement une série temporelle.
"""
import json
import traceback
from langchain.tools import tool
from connectors.warehouse_connector import get_warehouse
from ml_engine.phases.phase4_timeseries import analyze_time_series, get_ts_summary

@tool("analyze_time_series")
def analyze_time_series_tool(table_name: str, value_col: str, date_col: str) -> str:
    """
    Analyse statistique complète d'une série temporelle (stationnarité, ADF, ACF, PACF, Saisonnalité).
    Args:
        table_name: Nom de la table dans le warehouse.
        value_col: Nom de la colonne à analyser (la métrique).
        date_col: Nom de la colonne date temporelle.
    """
    try:
        warehouse = get_warehouse()
        if table_name not in warehouse:
            return json.dumps({"error": f"Table {table_name} introuvable."})
            
        df = warehouse[table_name]
        
        # Sort values
        if date_col in df.columns:
            df = df.sort_values(date_col)
            
        report = analyze_time_series(df, value_col=value_col, date_col=date_col)
        summary = get_ts_summary(report)
        
        return json.dumps({
            "summary": summary,
            "report": report
        }, default=str)
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
