"""
agents/forecast_agent.py
========================
Forecast Agent — prévision de tendance mensuelle sur les ventes.
"""
import json
import pandas as pd
import numpy as np
from typing import Dict, Any
from graphs.state import AgentState, ForecastResults
from connectors.warehouse_connector import get_warehouse


class ForecastAgent:
    def forecast(self, state: AgentState) -> ForecastResults:
        res = ForecastResults()
        try:
            warehouse = get_warehouse()
            fact_v = warehouse.get("Fact_Ventes")

            if fact_v is None or fact_v.empty:
                res["forecast_data"] = {"status": "no_data"}
                return res

            # ── Série temporelle mensuelle ────────────────────────────────────
            date_col = next(
                (c for c in ["datepiece", "datecreation", "date"] if c in fact_v.columns), None
            )
            ttc_col = "ttc_dev" if "ttc_dev" in fact_v.columns else None

            if date_col is None or ttc_col is None:
                res["forecast_data"] = {"status": "missing_columns"}
                return res

            df = fact_v[[date_col, ttc_col]].copy()
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df[ttc_col]  = pd.to_numeric(df[ttc_col], errors="coerce")
            df = df.dropna()

            if df.empty:
                res["forecast_data"] = {"status": "no_valid_data"}
                return res

            df["month"] = df[date_col].dt.to_period("M")
            monthly = df.groupby("month")[ttc_col].sum().sort_index()

            # ── Prévision simple : moyenne mobile + tendance linéaire ─────────
            values = monthly.values.astype(float)
            n = len(values)
            horizon = 3  # prévoir 3 mois

            if n >= 3:
                # Tendance linéaire (OLS simple)
                x = np.arange(n)
                slope, intercept = np.polyfit(x, values, 1)

                forecasts = []
                last_period = monthly.index[-1]
                for i in range(1, horizon + 1):
                    pred_val = float(intercept + slope * (n + i - 1))
                    pred_val = max(pred_val, 0)  # pas de ventes négatives
                    next_period = last_period + i
                    forecasts.append({
                        "period": str(next_period),
                        "predicted_ttc": round(pred_val, 2),
                    })

                # Métriques de tendance
                growth_rate = float(slope / values.mean() * 100) if values.mean() != 0 else 0
                last_3_avg = float(np.mean(values[-3:])) if n >= 3 else float(np.mean(values))
                last_6_avg = float(np.mean(values[-6:])) if n >= 6 else float(np.mean(values))

                res["forecast_data"] = {
                    "status": "success",
                    "method": "Linear Trend + Moving Average",
                    "n_months_analyzed": n,
                    "slope_per_month": round(float(slope), 2),
                    "monthly_growth_rate_pct": round(growth_rate, 2),
                    "last_3m_avg": round(last_3_avg, 2),
                    "last_6m_avg": round(last_6_avg, 2),
                    "forecasts_next_3m": forecasts,
                    "trend_label": "Haussière ↗️" if slope > 0 else "Baissière ↘️",
                }
            else:
                res["forecast_data"] = {
                    "status": "insufficient_data",
                    "n_months": n,
                    "message": "Moins de 3 mois de données — prévision non disponible",
                }

        except Exception as e:
            import traceback
            res["forecast_data"] = {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

        return res
