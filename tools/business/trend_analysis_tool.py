"""
tools/business/trend_analysis_tool.py
=====================================
Outil LangChain pour analyser les tendances MoM / YoY.
"""
import json
import traceback
import pandas as pd
from langchain.tools import tool
from connectors.warehouse_connector import get_warehouse

@tool("analyze_trends")
def analyze_trends(table_name: str, metric: str, date_col: str, period: str = "month") -> str:
    """
    Calcule les tendances et la croissance (MoM, YoY).
    Args:
        table_name: Nom de la table
        metric: Métrique à analyser
        date_col: Colonne de date
        period: 'month' ou 'year'
    """
    try:
        warehouse = get_warehouse()
        if table_name not in warehouse:
            return json.dumps({"error": f"Table {table_name} introuvable."})
            
        df = warehouse[table_name].copy()
        if date_col not in df.columns or metric not in df.columns:
            return json.dumps({"error": "Colonnes manquantes."})
            
        df[date_col] = pd.to_datetime(df[date_col])
        if period == "month":
            freq = "M"
        else:
            freq = "Y"
            
        agg = df.set_index(date_col).resample(freq)[metric].sum()
        pct_change = agg.pct_change() * 100
        
        return json.dumps({
            "trend": agg.tail(5).to_dict(),
            "growth_pct": pct_change.tail(5).fillna(0).to_dict()
        }, default=str)
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
