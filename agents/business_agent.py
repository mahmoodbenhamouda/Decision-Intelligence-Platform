"""
agents/business_agent.py
========================
Business Agent — calcul des KPIs financiers directement depuis le warehouse.
"""
import pandas as pd
import numpy as np
from typing import Dict, Any
from graphs.state import AgentState, BusinessInsights
from connectors.warehouse_connector import get_warehouse


class BusinessAgent:
    def analyze(self, state: AgentState) -> BusinessInsights:
        res = BusinessInsights()
        try:
            warehouse = get_warehouse()
            kpis = {}

            # ── KPIs Ventes ───────────────────────────────────────────────────
            fact_v = warehouse.get("Fact_Ventes")
            if fact_v is not None and not fact_v.empty:
                if "ttc_dev" in fact_v.columns:
                    ttc = pd.to_numeric(fact_v["ttc_dev"], errors="coerce")
                    kpis["ca_total_ttc"] = round(float(ttc.sum()), 2)
                if "ht_dev" in fact_v.columns:
                    ht = pd.to_numeric(fact_v["ht_dev"], errors="coerce")
                    kpis["ca_total_ht"] = round(float(ht.sum()), 2)
                if "cle_client" in fact_v.columns:
                    kpis["nb_clients_actifs"] = int(fact_v["cle_client"].nunique())
                kpis["nb_factures_vente"] = len(fact_v)

                # Panier moyen
                if "ca_total_ttc" in kpis and kpis["nb_factures_vente"] > 0:
                    kpis["panier_moyen"] = round(
                        kpis["ca_total_ttc"] / kpis["nb_factures_vente"], 2
                    )

                # Délais de paiement
                if "payment_delay_days" in fact_v.columns:
                    delays = pd.to_numeric(fact_v["payment_delay_days"], errors="coerce").dropna()
                    if not delays.empty:
                        kpis["delai_paiement_moyen_jours"] = round(float(delays.mean()), 1)
                        kpis["retards_critiques_gt90j"] = int((delays > 90).sum())
                        kpis["retards_warning_gt30j"]   = int(((delays > 30) & (delays <= 90)).sum())

            # ── KPIs Achats ───────────────────────────────────────────────────
            fact_a = warehouse.get("Fact_Achats")
            if fact_a is not None and not fact_a.empty:
                if "ttc_dev" in fact_a.columns:
                    ttc_a = pd.to_numeric(fact_a["ttc_dev"], errors="coerce")
                    kpis["achats_total_ttc"] = round(float(ttc_a.sum()), 2)
                if "cle_fournisseur" in fact_a.columns:
                    kpis["nb_fournisseurs_actifs"] = int(fact_a["cle_fournisseur"].nunique())

            # ── Marge brute ───────────────────────────────────────────────────
            if "ca_total_ht" in kpis and "achats_total_ttc" in kpis:
                marge = kpis["ca_total_ht"] - kpis["achats_total_ttc"]
                kpis["marge_brute"] = round(marge, 2)
                if kpis["ca_total_ht"] > 0:
                    kpis["taux_marge_pct"] = round(marge / kpis["ca_total_ht"] * 100, 2)

            # ── Devis ─────────────────────────────────────────────────────────
            fact_d = warehouse.get("Fact_Devis")
            if fact_d is not None and not fact_d.empty:
                kpis["nb_devis"] = len(fact_d)
                if "ttc_dev" in fact_d.columns:
                    kpis["montant_devis_total"] = round(
                        float(pd.to_numeric(fact_d["ttc_dev"], errors="coerce").sum()), 2
                    )

            # ── Bons de Livraison ─────────────────────────────────────────────
            fact_bl = warehouse.get("Fact_BL")
            if fact_bl is not None and not fact_bl.empty:
                kpis["nb_bons_livraison"] = len(fact_bl)

            # ── Top 5 clients ─────────────────────────────────────────────────
            if fact_v is not None and "cle_client" in fact_v.columns and "ttc_dev" in fact_v.columns:
                top5 = (
                    fact_v.assign(ttc_num=pd.to_numeric(fact_v["ttc_dev"], errors="coerce"))
                    .groupby("cle_client")["ttc_num"]
                    .sum()
                    .nlargest(5)
                    .reset_index()
                    .rename(columns={"cle_client": "client", "ttc_num": "ca_ttc"})
                )
                top5["ca_ttc"] = top5["ca_ttc"].round(2)
                kpis["top5_clients"] = [
                    {"client": row["client"], "ca_ttc": float(row["ca_ttc"])}
                    for _, row in top5.iterrows()
                ]

            res["kpis"] = {"status": "success", "data": kpis}

        except Exception as e:
            import traceback
            res["kpis"] = {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

        return res
