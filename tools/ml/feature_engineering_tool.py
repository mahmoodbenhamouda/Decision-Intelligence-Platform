"""
tools/ml/feature_engineering_tool.py
====================================
Outil LangChain pour le Feature Engineering.
"""
import json
import traceback
from langchain.tools import tool
from ml_engine.phases.phase2_feature_eng import engineer_features, build_timeseries_features
from connectors.warehouse_connector import get_warehouse

@tool("run_feature_engineering")
def run_feature_engineering(table_name: str) -> str:
    """
    Exécute le feature engineering (date, aggregations, lag) sur une table.
    Args:
        table_name: Nom de la table (ex: 'Fact_Ventes')
    """
    try:
        warehouse = get_warehouse()
        if table_name not in warehouse:
            return json.dumps({"error": f"Table {table_name} introuvable."})
            
        df = warehouse[table_name]
        
        # Simple heurisitic pour TS vs standard
        if "ds" in df.columns or "date_facture" in df.columns:
            date_col = "ds" if "ds" in df.columns else "date_facture"
            target_col = "ttc_dev" if "ttc_dev" in df.columns else "y"
            df_fe = build_timeseries_features(df, date_col=date_col, value_col=target_col)
        else:
            df_fe = engineer_features(df, date_col="date_facture" if "date_facture" in df.columns else None)
            
        return json.dumps({
            "status": "success",
            "original_shape": df.shape,
            "new_shape": df_fe.shape,
            "new_features": list(set(df_fe.columns) - set(df.columns))
        })
    except Exception as e:
        return json.dumps({'error': str(e), 'traceback': traceback.format_exc()})
