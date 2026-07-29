import os
import sys
import time
from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from connectors.warehouse_connector import get_warehouse

# Moteur KPI DuckDB (exploite TOUTES les datasets, haute performance)
try:
    from ml_engine.analytics import kpi_engine
    HAS_ENGINE = True
    ENGINE_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    kpi_engine = None
    HAS_ENGINE = False
    ENGINE_IMPORT_ERROR = str(exc)

# Agent Finance (chef d'orchestre à outils : KPIs + ML risque + prévision + anomalies)
try:
    from agents.finance_agent import finance_agent
    HAS_AGENT = True
    AGENT_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover
    finance_agent = None
    HAS_AGENT = False
    AGENT_IMPORT_ERROR = str(exc)

app = FastAPI(title="Finance Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Router Upload (fichiers CSV/PDF/images) ────────────────────────────────
try:
    from api.routers.upload import router as upload_router
    app.include_router(upload_router)
except ImportError:
    try:
        from routers.upload import router as upload_router
        app.include_router(upload_router)
    except ImportError as e:
        print(f"[upload] router non chargé : {e}")

class FilterRequest(BaseModel):
    selected_years: List[int] = []
    selected_clients: List[str] = []
    fidelity_filter: str = "Tous"
    date_start: str | None = None
    date_end: str | None = None
    payment_modes: List[str] = []
    risk_level: str = "Tous"
    min_amount: float | None = None
    max_amount: float | None = None


def safe_num(series):
    return pd.to_numeric(series, errors="coerce")


def json_safe(value: Any):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def filter_summary(req: FilterRequest) -> Dict[str, Any]:
    return {
        "years": req.selected_years or "Toutes",
        "clients": req.selected_clients or "Tous",
        "client_count": len(req.selected_clients),
        "fidelity": req.fidelity_filter,
    }


def compute_kpis(warehouse: dict, req: FilterRequest | None = None) -> dict:
    is_client_scope = bool(req and req.selected_clients)

    kpis: Dict[str, Any] = {
        "monthly_sales": [],
        "top_clients": [],
        "anomalies_details": [],
    }

    fact_ventes = warehouse.get("Fact_Ventes")
    if fact_ventes is not None and not fact_ventes.empty:
        ttc_col = "ttc_dev" if "ttc_dev" in fact_ventes.columns else None
        ht_col = "ht_dev" if "ht_dev" in fact_ventes.columns else None

        if ttc_col:
            vals = safe_num(fact_ventes[ttc_col]).dropna()
            kpis["ca_total_ttc"] = float(vals.sum())
        if ht_col:
            vals = safe_num(fact_ventes[ht_col]).dropna()
            kpis["ca_total_ht"] = float(vals.sum())
        if "cle_client" in fact_ventes.columns:
            kpis["nb_clients"] = int(fact_ventes["cle_client"].nunique())

        id_col = "ent_id" if "ent_id" in fact_ventes.columns else ("ent_numero" if "ent_numero" in fact_ventes.columns else None)
        if id_col:
            kpis["nb_factures_vente"] = int(fact_ventes[id_col].nunique())
        else:
            kpis["nb_factures_vente"] = int(len(fact_ventes))

        if kpis.get("ca_total_ttc", 0) > 0 and kpis.get("nb_factures_vente", 0) > 0:
            kpis["panier_moyen"] = kpis["ca_total_ttc"] / kpis["nb_factures_vente"]

        date_col = next((c for c in ["datepiece", "datecreation", "date", "ent_date"] if c in fact_ventes.columns), None)
        if date_col and ttc_col:
            df_t = fact_ventes[[date_col, ttc_col]].copy()
            df_t[date_col] = pd.to_datetime(df_t[date_col], errors="coerce")
            df_t[ttc_col] = safe_num(df_t[ttc_col])
            df_t = df_t.dropna()
            if not df_t.empty:
                df_t["month"] = df_t[date_col].dt.to_period("M").astype(str)
                monthly = df_t.groupby("month")[ttc_col].sum().sort_index()
                kpis["monthly_sales"] = [{"period": k, "revenue": float(v)} for k, v in monthly.items()]
                if len(monthly) >= 2:
                    last = float(monthly.iloc[-1])
                    prev = float(monthly.iloc[-2])
                    kpis["mom_growth"] = ((last - prev) / prev * 100) if prev > 0 else 0
                    kpis["tendance"] = "Haussiere" if last >= prev else "Baissiere"
                else:
                    kpis["tendance"] = "Stable"
                    kpis["mom_growth"] = 0

        if "payment_delay_days" in fact_ventes.columns:
            delays = safe_num(fact_ventes["payment_delay_days"]).dropna()
            if not delays.empty:
                kpis["delai_paiement_moyen"] = float(delays.mean())
                kpis["retards_critiques"] = int((delays > 90).sum())
                kpis["retards_30j"] = int((delays > 30).sum())
                risk_mask = delays > 30
                kpis["paiements_a_risque_pct"] = float(risk_mask.mean() * 100)
                kpis["paiements_a_risque_count"] = int(risk_mask.sum())
                kpis["paiements_total_analyses"] = int(len(delays))
                if kpis["retards_critiques"] > 0:
                    kpis["anomalies_details"].append(f"{kpis['retards_critiques']} facture(s) avec plus de 90 jours de retard.")
                warning = int(((delays > 30) & (delays <= 90)).sum())
                if warning > 0:
                    kpis["anomalies_details"].append(f"{warning} facture(s) avec 30 a 90 jours de retard.")

        if ttc_col:
            ttc_vals = safe_num(fact_ventes[ttc_col]).fillna(0)
            neg = int((ttc_vals < 0).sum())
            zero = int((ttc_vals == 0).sum())
            if neg > 0:
                kpis["anomalies_details"].append(f"{neg} facture(s) avec montant negatif.")
            if zero > 0:
                kpis["anomalies_details"].append(f"{zero} facture(s) avec montant nul.")

        if "cle_client" in fact_ventes.columns and ttc_col:
            group_cols = ["cle_client"]
            grouped = fact_ventes.assign(ttc_num=safe_num(fact_ventes[ttc_col]).fillna(0)).groupby(group_cols)
            top = grouped.agg(revenue=("ttc_num", "sum"), invoices=("ttc_num", "size")).sort_values("revenue", ascending=False).head(5).reset_index()
            total_revenue = float(top["revenue"].sum()) if not top.empty else 0
            global_revenue = float(kpis.get("ca_total_ttc") or 0)
            kpis["top_clients"] = [
                {
                    "client": str(row["cle_client"]),
                    "revenue": float(row["revenue"]),
                    "invoices": int(row["invoices"]),
                    "share": float(row["revenue"] / global_revenue * 100) if global_revenue > 0 else 0,
                    "rank": int(idx + 1),
                }
                for idx, row in top.iterrows()
            ]
            kpis["top_clients_revenue_share"] = float(total_revenue / global_revenue * 100) if global_revenue > 0 else 0

    fact_achats = warehouse.get("Fact_Achats")
    if fact_achats is not None and not fact_achats.empty:
        ttc_col = "ttc_dev" if "ttc_dev" in fact_achats.columns else None
        if ttc_col:
            kpis["achats_total_ttc"] = float(safe_num(fact_achats[ttc_col]).dropna().sum())
        if "cle_fournisseur" in fact_achats.columns:
            kpis["nb_fournisseurs"] = int(fact_achats["cle_fournisseur"].nunique())
        id_col = "ent_id" if "ent_id" in fact_achats.columns else ("ent_numero" if "ent_numero" in fact_achats.columns else None)
        kpis["nb_factures_achat"] = int(fact_achats[id_col].nunique()) if id_col else int(len(fact_achats))

    if "ca_total_ht" in kpis and "achats_total_ttc" in kpis:
        achats_client_col = None
        if fact_achats is not None and not fact_achats.empty:
            achats_client_col = next((c for c in ["cle_client", "ent_client_code"] if c in fact_achats.columns), None)

        if is_client_scope and not achats_client_col:
            kpis["marge_brute"] = None
            kpis["taux_marge"] = None
            kpis["marge_quality_score"] = None
            kpis["marge_note"] = "Marge non attribuable: les achats ne sont pas relies aux clients selectionnes."
        else:
            marge = kpis["ca_total_ht"] - kpis["achats_total_ttc"]
            kpis["marge_brute"] = float(marge)
            if kpis["ca_total_ht"] > 0:
                taux = float((marge / kpis["ca_total_ht"]) * 100)
                kpis["taux_marge"] = taux
                kpis["marge_quality_score"] = float(max(0, min(100, taux)))
                if taux > 100 or taux < -100:
                    kpis["marge_note"] = "Taux de marge atypique: verifier les avoirs, achats negatifs ou donnees de cout."

    fact_devis = warehouse.get("Fact_Devis")
    if fact_devis is not None and not fact_devis.empty:
        kpis["nb_devis"] = int(fact_devis["cle_devis"].nunique()) if "cle_devis" in fact_devis.columns else int(len(fact_devis))
        ttc_col = "ttc_dev" if "ttc_dev" in fact_devis.columns else None
        if ttc_col:
            kpis["montant_devis_total"] = float(safe_num(fact_devis[ttc_col]).dropna().sum())

    fact_bl = warehouse.get("Fact_BL")
    if fact_bl is not None and not fact_bl.empty:
        kpis["nb_bl"] = int(len(fact_bl))
        ttc_col = "ent_ttc" if "ent_ttc" in fact_bl.columns else None
        if ttc_col:
            kpis["montant_bl_total"] = float(safe_num(fact_bl[ttc_col]).dropna().sum())

    anomaly_count = int(kpis.get("retards_critiques", 0))
    if fact_ventes is not None and not fact_ventes.empty and "ttc_dev" in fact_ventes.columns:
        ttc_vals = safe_num(fact_ventes["ttc_dev"]).fillna(0)
        anomaly_count += int((ttc_vals < 0).sum()) + int((ttc_vals == 0).sum())
    kpis["anomalies_detectees"] = anomaly_count
    if not kpis["anomalies_details"]:
        kpis["anomalies_details"] = ["Aucune anomalie majeure detectee."]

    return json_safe(kpis)


def filter_warehouse(warehouse: dict, req: FilterRequest) -> dict:
    if not warehouse:
        return warehouse

    filtered = {}
    for name, df in warehouse.items():
        if df is None or df.empty:
            filtered[name] = df
            continue

        f_df = df.copy()
        date_col = next((c for c in ["datepiece", "datecreation", "date", "ent_date"] if c in f_df.columns), None)
        if date_col:
            f_df[date_col] = pd.to_datetime(f_df[date_col], errors="coerce")
            if req.selected_years:
                f_df = f_df[f_df[date_col].dt.year.isin(req.selected_years)]
            if req.date_start:
                f_df = f_df[f_df[date_col] >= pd.to_datetime(req.date_start)]
            if req.date_end:
                f_df = f_df[f_df[date_col] <= pd.to_datetime(req.date_end)]

        client_col = next((c for c in ["cle_client", "ent_client_code"] if c in f_df.columns), None)
        if client_col:
            if req.selected_clients:
                f_df = f_df[f_df[client_col].astype(str).isin([str(c) for c in req.selected_clients])]

            if req.fidelity_filter != "Tous" and req.fidelity_filter != "Tous":
                id_col = "ent_id" if "ent_id" in f_df.columns else ("ent_numero" if "ent_numero" in f_df.columns else None)
                if id_col:
                    client_counts = f_df.groupby(client_col)[id_col].nunique()
                    if req.fidelity_filter == "Fideles (> 5 achats)" or req.fidelity_filter == "Fidèles (> 5 achats)":
                        valid_clients = client_counts[client_counts > 5].index
                    elif req.fidelity_filter == "Reguliers (2-5 achats)" or req.fidelity_filter == "Réguliers (2-5 achats)":
                        valid_clients = client_counts[(client_counts >= 2) & (client_counts <= 5)].index
                    else:
                        valid_clients = client_counts[client_counts == 1].index
                    f_df = f_df[f_df[client_col].isin(valid_clients)]

        if req.payment_modes:
            pm_col = next((c for c in ["ent_mode_reglement_libelle", "modereglementlibelle"] if c in f_df.columns), None)
            if pm_col:
                f_df = f_df[f_df[pm_col].astype(str).isin(req.payment_modes)]

        if req.min_amount is not None or req.max_amount is not None:
            amt_col = next((c for c in ["ttc_dev", "ent_ttc", "ht_dev"] if c in f_df.columns), None)
            if amt_col:
                f_df[amt_col] = pd.to_numeric(f_df[amt_col], errors="coerce")
                if req.min_amount is not None:
                    f_df = f_df[f_df[amt_col] >= req.min_amount]
                if req.max_amount is not None:
                    f_df = f_df[f_df[amt_col] <= req.max_amount]

        if req.risk_level != "Tous":
            delay_col = "payment_delay_days"
            if delay_col in f_df.columns:
                f_df[delay_col] = pd.to_numeric(f_df[delay_col], errors="coerce")
                if "heure" in req.risk_level:
                    f_df = f_df[f_df[delay_col] <= 0]
                elif "30j" in req.risk_level:
                    f_df = f_df[f_df[delay_col] > 30]
                elif "90j" in req.risk_level:
                    f_df = f_df[f_df[delay_col] > 90]

        filtered[name] = f_df
    return filtered


def get_available_filters(warehouse: dict) -> Dict[str, Any]:
    all_years: List[int] = []
    all_clients: List[str] = []
    all_payment_modes: List[str] = []
    max_amount = 0.0

    fv = warehouse.get("Fact_Ventes") if warehouse else None
    if fv is not None and not fv.empty:
        date_col = next((c for c in ["datepiece", "datecreation", "date", "ent_date"] if c in fv.columns), None)
        if date_col:
            dates = pd.to_datetime(fv[date_col], errors="coerce")
            all_years = sorted(dates.dt.year.dropna().unique().astype(int).tolist())
        client_col = next((c for c in ["cle_client", "ent_client_code"] if c in fv.columns), None)
        if client_col:
            all_clients = sorted(fv[client_col].dropna().astype(str).unique().tolist())
            
        pm_col = next((c for c in ["ent_mode_reglement_libelle", "modereglementlibelle"] if c in fv.columns), None)
        if pm_col:
            all_payment_modes = sorted(fv[pm_col].dropna().astype(str).unique().tolist())
            
        amt_col = "ttc_dev" if "ttc_dev" in fv.columns else None
        if amt_col:
            nums = pd.to_numeric(fv[amt_col], errors="coerce").dropna()
            if not nums.empty:
                max_amount = float(nums.max())

    return {
        "available_years": all_years,
        "available_clients": all_clients,
        "fidelity_options": ["Tous", "Fidèles (> 5 achats)", "Réguliers (2-5 achats)", "Occasionnels (1 achat)"],
        "available_payment_modes": all_payment_modes,
        "risk_levels": ["Tous", "Payé à l'heure", "Retard > 30j", "Critique > 90j"],
        "max_amount_possible": max_amount,
    }


def format_money(value):
    if value is None:
        return "N/A"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f} M DT"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f} K DT"
    return f"{value:.2f} DT"


def build_dynamic_report(kpis: dict, req: FilterRequest, graph_note: str = "") -> str:
    fs = filter_summary(req)
    top_clients = kpis.get("top_clients") or []
    anomalies = kpis.get("anomalies_details") or []
    selected_clients_text = "Tous" if fs["clients"] == "Tous" else ", ".join(map(str, fs["clients"][:6]))
    if isinstance(fs["clients"], list) and len(fs["clients"]) > 6:
        selected_clients_text += f" (+{len(fs['clients']) - 6})"

    risk_level = "faible"
    if kpis.get("retards_critiques", 0) > 0 or (kpis.get("taux_marge") is not None and kpis.get("taux_marge") < 10):
        risk_level = "eleve"
    elif kpis.get("retards_30j", 0) > 0 or (kpis.get("taux_marge") is not None and kpis.get("taux_marge") < 20):
        risk_level = "modere"

    ca = kpis.get("ca_total_ttc")
    tx = kpis.get("taux_marge")
    dso = kpis.get("dso_jours") or 0
    yoy = kpis.get("yoy_growth") or 0
    tend = "en hausse" if yoy >= 0 else "en baisse"
    expo = kpis.get("montant_risque_ttc")
    risk_pct = kpis.get("paiements_a_risque_pct") or 0
    forecast = kpis.get("forecast_next") or []
    topname = None
    if top_clients:
        topname = top_clients[0].get("nom") or top_clients[0].get("client")

    lines = ["### En bref\n"]
    lines.append(f"- **Activité** : chiffre d'affaires de **{format_money(ca)}**, {tend} de **{abs(yoy):.1f}%** sur 12 mois.\n")
    if tx is not None:
        lines.append(f"- **Rentabilité** : marge commerciale estimée à **{tx:.0f}%**.\n")
    else:
        lines.append("- **Rentabilité** : marge non attribuable sur ce périmètre filtré.\n")
    lines.append(f"- **Trésorerie** : délai d'encaissement moyen de **{dso:.0f} jours**.\n")
    lines.append(f"- **Risque crédit** : **{format_money(expo)}** exposés sur des délais longs (> 60 j), soit **{risk_pct:.0f}%** des factures.\n")
    if forecast:
        lines.append(f"- **Prévision** : CA projeté à **{format_money(forecast[0].get('montant'))}** le mois prochain.\n")

    lines.append("\n### Action prioritaire\n")
    if kpis.get("retards_critiques", 0) > 0:
        action = f"Lancer le recouvrement sur les **{kpis['retards_critiques']} factures critiques (> 90 jours)**"
        action += f", en commençant par **{topname}**.\n" if topname else ".\n"
        lines.append(action)
    elif tx is not None and tx < 15:
        lines.append("Revoir prix et coûts d'achat : la marge est sous le seuil de 15 %.\n")
    elif yoy < 0:
        lines.append("Relancer la dynamique commerciale : le chiffre d'affaires est en recul sur 12 mois.\n")
    else:
        lines.append("Consolider la dynamique : suivi hebdomadaire du CA, de la marge et des encaissements.\n")

    return "".join(lines)


def _filters_dict(req: FilterRequest) -> Dict[str, Any]:
    """Convertit la requête en dictionnaire de filtres pour le moteur DuckDB."""
    return {
        "selected_years": req.selected_years,
        "selected_clients": req.selected_clients,
        "fidelity_filter": req.fidelity_filter,
        "date_start": req.date_start,
        "date_end": req.date_end,
        "payment_modes": req.payment_modes,
        "risk_level": req.risk_level,
        "min_amount": req.min_amount,
        "max_amount": req.max_amount,
    }


@app.get("/api/health")
def health():
    return {"engine": HAS_ENGINE, "engine_error": ENGINE_IMPORT_ERROR,
            "agent": HAS_AGENT, "agent_error": AGENT_IMPORT_ERROR}


@app.post("/api/dashboard")
def get_dashboard_data(req: FilterRequest):
    # Chemin privilégié : l'AGENT FINANCE orchestre les outils et produit tout
    # (KPIs, scoring ML, prévision, anomalies) + une trace d'exécution visible.
    if HAS_AGENT and finance_agent is not None:
        try:
            out = finance_agent.run(_filters_dict(req))
            return {
                "kpis": json_safe(out["kpis"]),
                "filters": kpi_engine.get_filter_options(),
                "active_filters": filter_summary(req),
                "agent_trace": out["trace"],
                "agent": out["meta"],
            }
        except Exception as e:
            print(f"[dashboard] agent indisponible ({e}); repli moteur direct.")

    # Repli 1 : moteur DuckDB direct (sans orchestration agent)
    if HAS_ENGINE and kpi_engine is not None:
        try:
            kpis = kpi_engine.compute_dashboard(_filters_dict(req))
            return {
                "kpis": json_safe(kpis),
                "filters": kpi_engine.get_filter_options(),
                "active_filters": filter_summary(req),
            }
        except Exception as e:
            print(f"[dashboard] moteur DuckDB indisponible ({e}); repli pandas.")

    warehouse = get_warehouse()
    if not warehouse:
        return {"error": f"Warehouse vide. Moteur: {ENGINE_IMPORT_ERROR or 'OK'}"}
    filtered_warehouse = filter_warehouse(warehouse, req)
    return {
        "kpis": compute_kpis(filtered_warehouse, req),
        "filters": get_available_filters(warehouse),
        "active_filters": filter_summary(req),
    }


@app.post("/api/ai_insight")
def get_ai_insight(req: FilterRequest):
    # Mode HYBRIDE : l'agent superviseur produit la synthèse.
    #  - couche LLM (Groq) si une clé est présente → réponse en langage naturel
    #  - sinon repli déterministe (build_dynamic_report) → synthèse fiable codée
    if HAS_AGENT and finance_agent is not None:
        try:
            res = finance_agent.synthesize(_filters_dict(req))
            kpis = json_safe(res["kpis"])
            insight = res["text"] or build_dynamic_report(kpis, req)
            return {"insight": insight, "kpis_used": kpis,
                    "via": res["via"], "active_filters": filter_summary(req)}
        except Exception as e:
            print(f"[ai_insight] agent indisponible ({e}); repli moteur direct.")

    # Repli : moteur direct + synthèse déterministe
    kpis = None
    if HAS_ENGINE and kpi_engine is not None:
        try:
            kpis = json_safe(kpi_engine.compute_dashboard(_filters_dict(req)))
        except Exception as e:
            print(f"[ai_insight] moteur indisponible ({e}); repli pandas.")
    if kpis is None:
        warehouse = get_warehouse()
        if not warehouse:
            return {"error": "Warehouse vide ou non initialise."}
        kpis = compute_kpis(filter_warehouse(warehouse, req), req)

    insight = build_dynamic_report(kpis, req)
    return {"insight": insight, "kpis_used": kpis, "via": "regles", "active_filters": filter_summary(req)}


class CopilotRequest(FilterRequest):
    question: str = ""
    # Historique de conversation : liste de {role: 'user'|'assistant', text: str}
    # Les N derniers messages sont envoyés au LLM pour maintenir le contexte.
    history: List[Dict[str, str]] = []


@app.post("/api/forecast")
def get_forecast(req: FilterRequest):
    """Prévision d'encaissements (deep learning LSTM, avec repli) + bande de confiance."""
    try:
        from ml_engine.forecasting.lstm_cashflow import load_or_forecast
        fc = load_or_forecast(horizon=6)
        if not fc:
            return {"error": "Série d'échéances insuffisante pour la prévision."}
        return {"forecast": json_safe(fc)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/copilot")
def copilot(req: CopilotRequest):
    """Copilote conversationnel : répond en langage naturel THÉMATIQUE, ancré
    sur les KPIs du périmètre filtré + historique de conversation.
    - LLM (Groq) si clé disponible → réponse précise et non répétitive
    - Sinon repli déterministe thématique (selon le thème de la question)"""
    q = (req.question or "").strip() or "Quelles sont mes priorités financières du moment ?"
    history = req.history or []
    if HAS_AGENT and finance_agent is not None:
        try:
            res = finance_agent.synthesize(
                _filters_dict(req),
                question=q,
                history=history,
            )
            kpis = json_safe(res["kpis"])
            answer = res["text"]
            # Anti-repli : si l'agent retourne vide (rare), ne pas afficher le rapport générique
            if not answer:
                answer = "Je n'ai pas pu générer une réponse. Vérifiez que l'agent de veille est actif."
            return {
                "answer": answer,
                "via": res["via"],
                "radar": kpis.get("finance_radar", []),
                "question": q,
                "active_filters": filter_summary(req),
            }
        except Exception as e:
            return {"answer": f"Désolé, une erreur est survenue : {e}", "via": "error"}
    return {"answer": "L'agent finance est indisponible.", "via": "error"}


@app.post("/api/fleet/briefing")
def fleet_briefing(req: CopilotRequest):
    """Flotte multi-agents (LangGraph) : orchestration Veille + Opportunités +
    Recouvrement + Trésorerie + Risque → briefing décisionnel priorisé."""
    try:
        from agents.fleet.graph import run_briefing
        out = run_briefing(_filters_dict(req), question=(req.question or None))
        return {
            "briefing": out.get("briefing", ""),
            "findings": out.get("findings", []),
            "trace": out.get("trace", []),
            "engine": out.get("engine", ""),
            "active_filters": filter_summary(req),
        }
    except Exception as e:
        return {"briefing": f"Erreur flotte : {e}", "findings": [], "trace": [], "engine": "erreur"}


@app.get("/api/supply")
def supply_demand():
    """Analyse Demande & Approvisionnement : prévision de demande (MAPE) +
    concentration/dépendance fournisseur."""
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        return compute_supply_demand()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/fleet/opportunities")
def fleet_opportunities(refresh: bool = False):
    """Dernier scan d'appels d'offres (scrapés + classés + matchés).
    ?refresh=true force un nouveau scan immédiat."""
    try:
        from agents.fleet.opportunities import load_latest, scan_and_save
        data = scan_and_save() if refresh else (load_latest() or scan_and_save())
        return data
    except Exception as e:
        return {"error": str(e), "opportunities": [], "n_scanned": 0, "n_relevant": 0}


# ── Agent de veille : collecte automatique (au démarrage + chaque matin 7h) ──
@app.on_event("startup")
def _schedule_veille():
    import threading
    from datetime import datetime, timedelta

    def collect_once():
        try:
            from agents.veille_agent import veille_agent
            veille_agent.collect()
            print("[veille] collecte automatique effectuée")
        except Exception as e:  # pragma: no cover
            print(f"[veille] collecte échouée : {e}")

    def scan_once():
        try:
            from agents.fleet.opportunities import scan_and_save
            d = scan_and_save()
            print(f"[opportunités] scan quotidien : {d.get('n_relevant')}/{d.get('n_scanned')} pertinents")
        except Exception as e:  # pragma: no cover
            print(f"[opportunités] scan échoué : {e}")

    def daily():
        collect_once()
        scan_once()
        _plan()

    def _plan(hour: int = 7):
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        timer = threading.Timer(max(1.0, (nxt - now).total_seconds()), daily)
        timer.daemon = True
        timer.start()

    # 1re collecte + 1er scan peu après le démarrage (non bloquant) + planification quotidienne
    threading.Thread(target=collect_once, daemon=True).start()
    threading.Thread(target=scan_once, daemon=True).start()
    _plan()


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
