"""
agents/ml_agent.py
==================
ML Agent — détection d'anomalies sur les données financières.
"""
import json
import pandas as pd
from typing import Dict, Any
from graphs.state import AgentState, MLResults
from connectors.warehouse_connector import get_warehouse


class MLAgent:
    def analyze(self, state: AgentState) -> MLResults:
        res = MLResults()
        try:
            warehouse = get_warehouse()
            fact_v = warehouse.get("Fact_Ventes")

            if fact_v is None or fact_v.empty:
                res["anomalies"] = {"status": "no_data", "message": "Fact_Ventes introuvable"}
                return res

            anomalies = []
            summary = {}

            # ── Détection par délai de paiement ──────────────────────────────
            if "payment_delay_days" in fact_v.columns:
                delays = pd.to_numeric(fact_v["payment_delay_days"], errors="coerce").dropna()
                critical = int((delays > 90).sum())
                warning  = int(((delays > 30) & (delays <= 90)).sum())
                mean_d   = float(delays.mean())
                summary["delai_moyen_jours"] = round(mean_d, 1)
                summary["retards_critiques_gt90j"] = critical
                summary["retards_warning_gt30j"]   = warning
                if critical > 0:
                    anomalies.append({
                        "type": "RETARD_PAIEMENT_CRITIQUE",
                        "severity": "HIGH",
                        "count": critical,
                        "description": f"{critical} factures dépassent 90 jours de retard",
                    })
                if warning > 0:
                    anomalies.append({
                        "type": "RETARD_PAIEMENT_AVERTISSEMENT",
                        "severity": "MEDIUM",
                        "count": warning,
                        "description": f"{warning} factures entre 30 et 90 jours",
                    })

            # ── Détection valeurs aberrantes (montants négatifs ou nuls) ─────
            if "ttc_dev" in fact_v.columns:
                ttc = pd.to_numeric(fact_v["ttc_dev"], errors="coerce")
                neg = int((ttc < 0).sum())
                zero = int((ttc == 0).sum())
                summary["montants_negatifs"] = neg
                summary["montants_zero"] = zero
                if neg > 0:
                    anomalies.append({
                        "type": "MONTANT_NEGATIF",
                        "severity": "HIGH",
                        "count": neg,
                        "description": f"{neg} factures avec montant TTC négatif",
                    })
                if zero > 10:
                    anomalies.append({
                        "type": "MONTANT_ZERO",
                        "severity": "LOW",
                        "count": zero,
                        "description": f"{zero} factures à montant zéro",
                    })

            res["anomalies"] = {
                "status": "success",
                "nb_anomalies": len(anomalies),
                "anomalies": anomalies,
                "summary": summary,
            }

        except Exception as e:
            import traceback
            res["anomalies"] = {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

        return res
