"""
ml_engine/phases/phase9_agent.py
================================
Phase 9 : Agent IA Finance legacy.
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import joblib
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

from ml_engine.phases.phase1_data_quality import save_json


class FinanceAIAgent:
    """
    Agent IA Finance (Legacy / Base).
    Sert de fallback ou d'outil pour la nouvelle architecture LangGraph.
    """
    
    SUPPORTED_QUERIES = [
        "forecast_ventes", "forecast_achats", "forecast_tresorerie",
        "detect_anomalies", "explain_prediction", "kpi_summary",
        "top_clients", "top_fournisseurs", "retard_paiement",
    ]

    def __init__(self, models_dir: Optional[Path] = None):
        self.models_dir = models_dir or Path("models")
        self._models: Dict[str, Any] = {}
        self._scalers: Dict[str, Any] = {}
        self._is_loaded = False

    def load(self) -> FinanceAIAgent:
        if not HAS_JOBLIB:
            print("Joblib non installé")
            return self
            
        if not self.models_dir.exists():
            return self
            
        artifacts = sorted(self.models_dir.glob("*.joblib"))
        for artifact in artifacts:
            try:
                name = artifact.stem
                obj = joblib.load(artifact)
                if "scaler" in name:
                    self._scalers[name.replace("_scaler", "")] = obj
                else:
                    self._models[name] = obj
            except Exception:
                pass
                
        self._is_loaded = True
        return self

    def answer(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self._is_loaded:
            self.load()
            
        ctx = context or {}
        if query == "kpi_summary":
            return self._kpi_summary(ctx)
        elif query == "top_clients":
            return self._top_clients(ctx)
        elif query == "retard_paiement":
            return self._retard_paiement_analysis(ctx)
        return {"error": f"Query {query} non implémentée (utilisez les nouveaux outils LangChain)"}

    def _kpi_summary(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty: return {"error": "Fact_Ventes manquante"}
        return {
            "total_ventes": float(fact.get("ttc_dev", pd.Series([0])).sum()),
            "nb_factures": len(fact),
            "nb_clients": int(fact.get("cle_client", pd.Series([0])).nunique())
        }

    def _top_clients(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty: return {"error": "Fact_Ventes manquante"}
        if "cle_client" not in fact.columns or "ttc_dev" not in fact.columns:
            return {"error": "Colonnes manquantes"}
            
        top = fact.groupby("cle_client")["ttc_dev"].sum().sort_values(ascending=False).head(10)
        return {"top_clients": top.to_dict()}
        
    def _retard_paiement_analysis(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        fact = ctx.get("Fact_Ventes", pd.DataFrame())
        if fact.empty: return {"error": "Fact_Ventes manquante"}
        if "payment_delay_days" not in fact.columns:
            return {"error": "payment_delay_days manquante"}
            
        return {
            "mean_delay": float(fact["payment_delay_days"].mean()),
            "pct_late": float((fact["payment_delay_days"] > 30).mean() * 100)
        }
        
    def save_report(self, output_dir: Path) -> None:
        pass
