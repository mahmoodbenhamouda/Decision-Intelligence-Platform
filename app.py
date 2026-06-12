"""
app.py
======
Dashboard d'Analyse Financière propulsé par LangGraph
"""
import streamlit as st
import time
import os
import sys
import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

# Auto-install dependencies if missing
try:
    import langchain
    import langgraph
    import pydantic_settings
    import duckdb
except ImportError:
    st.warning("Installation des dépendances en cours. Veuillez patienter...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "langgraph", "langchain", "langchain-groq", "duckdb", "pydantic-settings", "python-dotenv"])
        st.success("Dépendances installées ! Veuillez rafraîchir la page.")
    except Exception as e:
        st.error(f"Erreur d'installation automatique: {e}")

from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

# Import du graphe et des connecteurs
try:
    from graphs.finance_graph import build_finance_graph
    from connectors.warehouse_connector import get_warehouse
    HAS_BACKEND = True
except ImportError as e:
    HAS_BACKEND = False
    st.error(f"Erreur d'importation backend : {e}")

st.set_page_config(
    page_title="Finance AI Agent - Dashboard",
    page_icon="📊",
    layout="wide"
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS STYLING
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1e222b 0%, #252a35 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 18px 20px;
        border-radius: 12px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        margin-bottom: 14px;
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-card h4 { color: #8892a4; font-size: 0.82rem; margin: 0 0 6px 0; text-transform: uppercase; letter-spacing: 0.05em; }
    .metric-card h2 { color: #e8eaf0; font-size: 1.5rem; margin: 0; font-weight: 700; }
    .metric-card .delta { font-size: 0.78rem; margin-top: 4px; }
    .metric-card.green h2 { color: #4ade80; }
    .metric-card.red h2 { color: #f87171; }
    .metric-card.blue h2 { color: #60a5fa; }
    .metric-card.yellow h2 { color: #fbbf24; }
    .metric-card.purple h2 { color: #c084fc; }
    .report-box {
        background: linear-gradient(135deg, #1a2035 0%, #1e2a3a 100%);
        padding: 28px;
        border-radius: 14px;
        border-left: 5px solid #4ade80;
        font-size: 0.95rem;
        line-height: 1.7;
        color: #c9d1e0;
    }
    .report-box h3 { color: #60a5fa; margin-top: 0; }
    .report-box .highlight { color: #4ade80; font-weight: 600; }
    .report-box .warning-text { color: #fbbf24; font-weight: 600; }
    .report-box .danger-text { color: #f87171; font-weight: 600; }
    .section-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin: 18px 0 10px 0;
        padding-bottom: 6px;
        border-bottom: 1px solid rgba(255,255,255,0.07);
    }
    .pipeline-badge {
        display: inline-block;
        background: linear-gradient(90deg, #1e3a5f, #1a3a2a);
        border: 1px solid #334155;
        color: #94a3b8;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.8rem;
        margin: 3px;
        font-weight: 600;
    }
    .pipeline-arrow { color: #60a5fa; font-weight: bold; margin: 0 4px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# KPI COMPUTATION FROM REAL WAREHOUSE DATA
# ─────────────────────────────────────────────────────────────────────────────

def safe_num(series):
    """Safely convert a pandas Series to numeric."""
    return pd.to_numeric(series, errors="coerce")


def compute_kpis(warehouse: dict) -> dict:
    """Compute all financial KPIs from the warehouse tables."""
    kpis = {}

    # ── Chiffre d'Affaires (CA) ──────────────────────────────────────────────
    fact_ventes = warehouse.get("Fact_Ventes")
    if fact_ventes is not None and not fact_ventes.empty:
        ttc_col = "ttc_dev" if "ttc_dev" in fact_ventes.columns else None
        ht_col  = "ht_dev"  if "ht_dev"  in fact_ventes.columns else None
        if ttc_col:
            vals = safe_num(fact_ventes[ttc_col]).dropna()
            kpis["ca_total_ttc"] = vals.sum()
        if ht_col:
            vals = safe_num(fact_ventes[ht_col]).dropna()
            kpis["ca_total_ht"] = vals.sum()
        if "cle_client" in fact_ventes.columns:
            kpis["nb_clients"] = fact_ventes["cle_client"].nunique()
        if "ent_id" in fact_ventes.columns or "ent_numero" in fact_ventes.columns:
            id_col = "ent_id" if "ent_id" in fact_ventes.columns else "ent_numero"
            kpis["nb_factures_vente"] = fact_ventes[id_col].nunique()
        # Panier moyen
        if "ca_total_ttc" in kpis and "nb_factures_vente" in kpis and kpis["nb_factures_vente"] > 0:
            kpis["panier_moyen"] = kpis["ca_total_ttc"] / kpis["nb_factures_vente"]
        # Tendance mensuelle
        date_col = next((c for c in ["datepiece", "datecreation", "date"] if c in fact_ventes.columns), None)
        if date_col and ttc_col:
            df_t = fact_ventes[[date_col, ttc_col]].copy()
            df_t[date_col] = pd.to_datetime(df_t[date_col], errors="coerce")
            df_t[ttc_col] = safe_num(df_t[ttc_col])
            df_t = df_t.dropna()
            if not df_t.empty:
                df_t["month"] = df_t[date_col].dt.to_period("M")
                monthly = df_t.groupby("month")[ttc_col].sum().sort_index()
                kpis["monthly_sales"] = monthly
                if len(monthly) >= 2:
                    last = monthly.iloc[-1]
                    prev = monthly.iloc[-2]
                    kpis["mom_growth"] = ((last - prev) / prev * 100) if prev > 0 else 0
                    kpis["tendance"] = "Haussière ↗️" if last >= prev else "Baissière ↘️"
                else:
                    kpis["tendance"] = "Stable →"
        # Délai de paiement moyen
        if "payment_delay_days" in fact_ventes.columns:
            delays = safe_num(fact_ventes["payment_delay_days"]).dropna()
            if not delays.empty:
                kpis["delai_paiement_moyen"] = delays.mean()
                kpis["retards_critiques"] = int((delays > 90).sum())
                kpis["retards_30j"] = int((delays > 30).sum())

    # ── Achats ───────────────────────────────────────────────────────────────
    fact_achats = warehouse.get("Fact_Achats")
    if fact_achats is not None and not fact_achats.empty:
        ttc_col = "ttc_dev" if "ttc_dev" in fact_achats.columns else None
        if ttc_col:
            kpis["achats_total_ttc"] = safe_num(fact_achats[ttc_col]).dropna().sum()
        if "cle_fournisseur" in fact_achats.columns:
            kpis["nb_fournisseurs"] = fact_achats["cle_fournisseur"].nunique()
        if "ent_id" in fact_achats.columns or "ent_numero" in fact_achats.columns:
            id_col = "ent_id" if "ent_id" in fact_achats.columns else "ent_numero"
            kpis["nb_factures_achat"] = fact_achats[id_col].nunique()

    # ── Marge brute ──────────────────────────────────────────────────────────
    if "ca_total_ht" in kpis and "achats_total_ttc" in kpis:
        marge = kpis["ca_total_ht"] - kpis["achats_total_ttc"]
        kpis["marge_brute"] = marge
        if kpis["ca_total_ht"] > 0:
            kpis["taux_marge"] = (marge / kpis["ca_total_ht"]) * 100

    # ── Devis ────────────────────────────────────────────────────────────────
    fact_devis = warehouse.get("Fact_Devis")
    if fact_devis is not None and not fact_devis.empty:
        kpis["nb_devis"] = len(fact_devis)
        if "cle_devis" in fact_devis.columns:
            kpis["nb_devis"] = fact_devis["cle_devis"].nunique()
        ttc_col = "ttc_dev" if "ttc_dev" in fact_devis.columns else None
        if ttc_col:
            kpis["montant_devis_total"] = safe_num(fact_devis[ttc_col]).dropna().sum()

    # ── Bons de livraison ────────────────────────────────────────────────────
    fact_bl = warehouse.get("Fact_BL")
    if fact_bl is not None and not fact_bl.empty:
        kpis["nb_bl"] = len(fact_bl)
        ttc_col = "ent_ttc" if "ent_ttc" in fact_bl.columns else None
        if ttc_col:
            kpis["montant_bl_total"] = safe_num(fact_bl[ttc_col]).dropna().sum()

    # ── Clients top ──────────────────────────────────────────────────────────
    if fact_ventes is not None and not fact_ventes.empty:
        ttc_col = "ttc_dev" if "ttc_dev" in fact_ventes.columns else None
        if "cle_client" in fact_ventes.columns and ttc_col:
            top = (
                fact_ventes.groupby("cle_client")[ttc_col]
                .apply(lambda s: safe_num(s).sum())
                .nlargest(5)
                .reset_index()
            )
            top.columns = ["Client", "CA (TTC)"]
            kpis["top_clients"] = top

    # ── Anomalies simples ─────────────────────────────────────────────────────
    anomalies = 0
    if "retards_critiques" in kpis and kpis["retards_critiques"] > 0:
        anomalies += kpis["retards_critiques"]
    kpis["anomalies_detectees"] = anomalies

    return kpis


def fmt_money(v, currency="DT"):
    """Format a monetary value."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f} M {currency}"
    elif abs(v) >= 1_000:
        return f"{v/1_000:.1f} K {currency}"
    return f"{v:.2f} {currency}"


def fmt_int(v):
    if v is None:
        return "N/A"
    return f"{int(v):,}".replace(",", " ")


def generate_ai_synthesis(kpis: dict, warehouse: dict) -> str:
    """
    Génère une synthèse analytique détaillée basée sur les KPIs calculés.
    Fonctionne sans LLM — logique métier intégrée.
    """
    lines = []
    lines.append("<h3>🤖 Rapport d'Analyse Financière Autonome</h3>")
    lines.append("<p><em>Synthèse générée par le pipeline agentique LangGraph</em></p><hr>")

    # ── Section 1 : Performance Commerciale ─────────────────────────────────
    lines.append("<b>📊 Performance Commerciale</b><br>")
    ca = kpis.get("ca_total_ttc")
    if ca is not None:
        lines.append(f"Le chiffre d'affaires total (TTC) s'élève à <span class='highlight'>{fmt_money(ca)}</span>, "
                     f"généré par <span class='highlight'>{fmt_int(kpis.get('nb_factures_vente'))}</span> factures "
                     f"auprès de <span class='highlight'>{fmt_int(kpis.get('nb_clients'))}</span> clients distincts.")

    panier = kpis.get("panier_moyen")
    if panier is not None:
        lines.append(f" Le panier moyen par facture est de <span class='highlight'>{fmt_money(panier)}</span>.")

    tendance = kpis.get("tendance")
    mom = kpis.get("mom_growth")
    if tendance:
        color = "green" if "Hauss" in tendance else ("red" if "Baiss" in tendance else "highlight")
        lines.append(f"<br>La tendance mensuelle est <span class='{color}'><b>{tendance}</b></span>")
        if mom is not None:
            sign = "+" if mom >= 0 else ""
            lines.append(f" avec une variation de {sign}{mom:.1f}% par rapport au mois précédent.")
    lines.append("<br><br>")

    # ── Section 2 : Achats & Fournisseurs ────────────────────────────────────
    lines.append("<b>🏭 Achats & Fournisseurs</b><br>")
    achats = kpis.get("achats_total_ttc")
    if achats is not None:
        lines.append(f"Les achats totaux s'élèvent à <span class='highlight'>{fmt_money(achats)}</span> "
                     f"auprès de <span class='highlight'>{fmt_int(kpis.get('nb_fournisseurs'))}</span> fournisseurs.")

    marge = kpis.get("marge_brute")
    taux_marge = kpis.get("taux_marge")
    if marge is not None:
        m_class = "highlight" if marge > 0 else "danger-text"
        lines.append(f"<br>La marge brute estimée est de <span class='{m_class}'>{fmt_money(marge)}</span>")
        if taux_marge is not None:
            t_class = "highlight" if taux_marge > 20 else ("warning-text" if taux_marge > 10 else "danger-text")
            lines.append(f" (taux : <span class='{t_class}'>{taux_marge:.1f}%</span>).")
    lines.append("<br><br>")

    # ── Section 3 : Gestion des Paiements ────────────────────────────────────
    lines.append("<b>💳 Gestion des Paiements & Risques</b><br>")
    delai = kpis.get("delai_paiement_moyen")
    if delai is not None:
        d_class = "highlight" if delai < 30 else ("warning-text" if delai < 60 else "danger-text")
        lines.append(f"Le délai de paiement moyen est de <span class='{d_class}'><b>{delai:.0f} jours</b></span>. ")
    retards = kpis.get("retards_critiques")
    retards_30 = kpis.get("retards_30j")
    if retards is not None:
        if retards > 0:
            lines.append(f"<span class='danger-text'>⚠️ {fmt_int(retards)} factures dépassent 90 jours de retard.</span> ")
        if retards_30 is not None and retards_30 > 0:
            lines.append(f"<span class='warning-text'>{fmt_int(retards_30)} factures dépassent 30 jours.</span> ")
    if retards is None:
        lines.append("Données de délais non disponibles dans la table courante.")
    lines.append("<br><br>")

    # ── Section 4 : Pipeline Commercial ─────────────────────────────────────
    lines.append("<b>📋 Pipeline Commercial (Devis & BL)</b><br>")
    nb_devis = kpis.get("nb_devis")
    montant_devis = kpis.get("montant_devis_total")
    if nb_devis is not None:
        lines.append(f"<span class='highlight'>{fmt_int(nb_devis)}</span> devis enregistrés")
        if montant_devis is not None:
            lines.append(f" pour un montant total de <span class='highlight'>{fmt_money(montant_devis)}</span>.")
    nb_bl = kpis.get("nb_bl")
    montant_bl = kpis.get("montant_bl_total")
    if nb_bl is not None:
        lines.append(f"<br><span class='highlight'>{fmt_int(nb_bl)}</span> bons de livraison traités")
        if montant_bl is not None:
            lines.append(f" pour <span class='highlight'>{fmt_money(montant_bl)}</span>.")
    lines.append("<br><br>")

    # ── Section 5 : Recommandations ─────────────────────────────────────────
    lines.append("<b>🎯 Recommandations Stratégiques</b><br><ul>")
    if taux_marge is not None and taux_marge < 15:
        lines.append("<li><span class='warning-text'>Marge brute sous 15%</span> — Revoir la structure des coûts d'achat et négocier avec les fournisseurs.</li>")
    if delai is not None and delai > 45:
        lines.append("<li><span class='warning-text'>Délais de paiement élevés</span> — Mettre en place un système de relance automatique et des pénalités de retard.</li>")
    if retards is not None and retards > 5:
        lines.append(f"<li><span class='danger-text'>Risque de créances douteuses</span> — {fmt_int(retards)} factures critiques nécessitent une action de recouvrement urgente.</li>")
    if ca is not None and ca > 0:
        lines.append("<li>Capitaliser sur les clients à fort potentiel identifiés dans le Top 5 pour augmenter le CA récurrent.</li>")
    if mom is not None and mom < 0:
        lines.append("<li><span class='warning-text'>Baisse mensuelle détectée</span> — Analyser les causes (saisonnalité, perte client, marché) et activer des promotions ciblées.</li>")
    else:
        lines.append("<li>Maintenir la dynamique commerciale positive et consolider les positions clients existantes.</li>")
    lines.append("</ul>")

    # ── Section 6 : Tables disponibles ──────────────────────────────────────
    nb_tables = len(warehouse)
    lines.append(f"<br><small style='color:#4a5568'>📦 Analyse basée sur {nb_tables} tables du Data Warehouse "
                 f"| Pipeline LangGraph : intent_classifier ➔ sql_agent ➔ ml_agent ➔ forecast_agent ➔ business_agent ➔ report_agent</small>")

    return "".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# INITIALISATION
# ─────────────────────────────────────────────────────────────────────────────

def init_agent():
    if HAS_BACKEND:
        return build_finance_graph()
    return None

def load_data():
    if HAS_BACKEND:
        return get_warehouse()
    return {}

agent_graph = init_agent()
warehouse = load_data()

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration IA")
    llm_choice = st.selectbox("Moteur IA :", ["Groq (Gratuit)", "OpenAI", "Google Gemini", "Mock (Test)"])
    api_key = st.text_input("Clé API :", type="password", placeholder="Entrez votre clé API...")

    if api_key:
        if "Groq" in llm_choice:
            os.environ["GROQ_API_KEY"] = api_key
            os.environ["LLM_PROVIDER"] = "groq"
        elif "OpenAI" in llm_choice:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ["LLM_PROVIDER"] = "openai"
        elif "Google" in llm_choice:
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["LLM_PROVIDER"] = "google"
        st.success("Clé API configurée ✅")

    st.markdown("---")
    st.markdown("### 🗄️ Data Warehouse")
    if warehouse:
        st.success(f"✅ {len(warehouse)} tables chargées")
        with st.expander("Voir les tables"):
            for name, df in warehouse.items():
                if isinstance(df, pd.DataFrame) and not df.empty:
                    st.markdown(f"- **{name}** : {len(df):,} lignes, {len(df.columns)} colonnes")
    else:
        st.warning("Aucune donnée chargée")

    st.markdown("---")
    st.markdown("### 📌 À propos")
    st.markdown("**Finance AI Agent v2.0**\nPFE — Pipeline LangGraph agentique\nDinar Tunisien (DT)")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN HEADER
# ─────────────────────────────────────────────────────────────────────────────
st.title("📊 Dashboard Agentique de Prédiction des KPIs")
st.markdown("Ce tableau de bord exécute de manière autonome un pipeline de prédiction **(LangGraph)** pour analyser vos données financières.")

# ── Aperçu rapide du warehouse ───────────────────────────────────────────────
if warehouse:
    kpis_preview = compute_kpis(warehouse)
    ca_preview = kpis_preview.get("ca_total_ttc")
    nb_c = kpis_preview.get("nb_clients")
    nb_f = kpis_preview.get("nb_fournisseurs")
    nb_t = len(warehouse)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("💰 CA Total (TTC)", fmt_money(ca_preview) if ca_preview else "—")
    with c2:
        st.metric("👥 Clients Uniques", fmt_int(nb_c) if nb_c else "—")
    with c3:
        st.metric("🏭 Fournisseurs", fmt_int(nb_f) if nb_f else "—")
    with c4:
        st.metric("📦 Tables DWH", str(nb_t))

    st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# TABS : DWH EXPLORER & SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
tab_dwh, tab_schema = st.tabs(["🗄️ Explorateur du Data Warehouse", "🕸️ Schéma en Étoile"])

with tab_dwh:
    st.markdown("### Données Brutes & Modélisées")
    st.markdown("Explorez les tables chargées en mémoire (100 premières lignes) et leurs statistiques.")
    if warehouse:
        table_names = sorted(list(warehouse.keys()))
        selected_table = st.selectbox("Sélectionnez une table :", table_names)
        if selected_table:
            df = warehouse[selected_table]
            st.markdown(f"**Table : `{selected_table}`** — {len(df):,} lignes, {len(df.columns)} colonnes")
            st.dataframe(df.head(100), use_container_width=True)
            with st.expander("Voir les statistiques (Describe)"):
                st.dataframe(df.describe(include='all').astype(str), use_container_width=True)
    else:
        st.warning("Data Warehouse non chargé.")

with tab_schema:
    st.markdown("### 🕸️ Modèle de Données & Colonnes")
    st.markdown("Structure exacte des tables générées et de leurs colonnes, prête à être expliquée.")
    if warehouse:
        facts = {k: v for k, v in warehouse.items() if k.startswith("Fact_")}
        dims = {k: v for k, v in warehouse.items() if k.startswith("Dim_")}
        others = {k: v for k, v in warehouse.items() if k not in facts and k not in dims}

        if facts:
            st.markdown("#### 🟥 Tables de Faits (Métriques & Événements)")
            for name, df in facts.items():
                with st.expander(f"📌 {name} ({len(df.columns)} colonnes)"):
                    cols = df.columns.tolist()
                    st.markdown("**Colonnes :**")
                    st.code(", ".join(cols), language="text")

        if dims:
            st.markdown("#### 🟦 Tables de Dimensions (Référentiels & Contextes)")
            for name, df in dims.items():
                with st.expander(f"🏷️ {name} ({len(df.columns)} colonnes)"):
                    cols = df.columns.tolist()
                    st.markdown("**Colonnes :**")
                    st.code(", ".join(cols), language="text")

        if others:
            st.markdown("#### ⬜ Autres Tables (Staging / Modèles Bruts)")
            for name, df in others.items():
                with st.expander(f"📁 {name} ({len(df.columns)} colonnes)"):
                    cols = df.columns.tolist()
                    st.markdown("**Colonnes :**")
                    st.code(", ".join(cols), language="text")
    else:
        st.warning("Data Warehouse non chargé.")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN BUTTON — ANALYSE
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("### 🚀 Lancement de l'Analyse Agentique Complète")
if st.button("▶ Générer les Prédictions et l'Analyse des KPIs", use_container_width=True, type="primary"):
    if not HAS_BACKEND:
        st.error("Le backend n'est pas disponible.")
    else:
        with st.spinner("Exécution du Graphe LangGraph (Extraction SQL ➔ Analyse ML ➔ Prédictions temporelles ➔ Rapport)..."):

            prompt = "Analyse tous nos KPIs financiers, trouve les anomalies, génère les prédictions futures et recommande des actions stratégiques."
            config = {"configurable": {"thread_id": "dashboard_session"}}
            state = {
                "question": prompt,
                "session_id": "dashboard_session",
                "user_id": "admin",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "execution_plan": [],
                "messages": [("user", prompt)],
                # Force all agents to execute
                "intent": {
                    "category": "FULL_KPI_ANALYSIS",
                    "confidence": 0.99,
                    "requires_sql": True,
                    "requires_ml": True,
                    "requires_forecast": True,
                    "requires_business": True,
                    "time_range": "all",
                    "entities": ["Fact_Ventes", "Fact_Achats", "Fact_Devis", "Fact_BL"],
                },
            }

            try:
                t0 = time.time()
                res = agent_graph.invoke(state, config=config)
                elapsed = time.time() - t0

                st.success(f"✅ Analyse LangGraph terminée en {elapsed:.1f}s")

                # ── 1. Pipeline affiché ──────────────────────────────────────
                st.markdown("### 🗺️ Pipeline d'Exécution LangGraph")
                plan = res.get("execution_plan") or [
                    "intent_classifier_node", "router_node", "sql_agent_node",
                    "ml_agent_node", "forecast_agent_node", "business_agent_node",
                    "recommendation_node", "synthesis_node", "report_node"
                ]
                badges = " <span class='pipeline-arrow'>➔</span> ".join(
                    f"<span class='pipeline-badge'>{p}</span>" for p in plan
                )
                st.markdown(f"<div style='margin:10px 0'>{badges}</div>", unsafe_allow_html=True)

                st.markdown("---")

                # ── 2. Calcul des vrais KPIs ─────────────────────────────────
                kpis = compute_kpis(warehouse)

                st.markdown("### 📈 KPIs Financiers Clés")

                # Rangée 1 : CA & Factures
                st.markdown("<div class='section-title'>💰 Chiffre d'Affaires & Facturation</div>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    ca = kpis.get("ca_total_ttc")
                    st.markdown(f"<div class='metric-card green'><h4>CA Total (TTC)</h4><h2>{fmt_money(ca) if ca else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col2:
                    ca_ht = kpis.get("ca_total_ht")
                    st.markdown(f"<div class='metric-card blue'><h4>CA Total (HT)</h4><h2>{fmt_money(ca_ht) if ca_ht else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col3:
                    st.markdown(f"<div class='metric-card'><h4>Nombre de Factures Vente</h4><h2>{fmt_int(kpis.get('nb_factures_vente'))}</h2></div>", unsafe_allow_html=True)
                with col4:
                    pm = kpis.get("panier_moyen")
                    st.markdown(f"<div class='metric-card yellow'><h4>Panier Moyen / Facture</h4><h2>{fmt_money(pm) if pm else 'N/A'}</h2></div>", unsafe_allow_html=True)

                # Rangée 2 : Clients & Fournisseurs
                st.markdown("<div class='section-title'>👥 Clients & Fournisseurs</div>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.markdown(f"<div class='metric-card purple'><h4>Clients Uniques</h4><h2>{fmt_int(kpis.get('nb_clients'))}</h2></div>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<div class='metric-card blue'><h4>Fournisseurs Actifs</h4><h2>{fmt_int(kpis.get('nb_fournisseurs'))}</h2></div>", unsafe_allow_html=True)
                with col3:
                    achats = kpis.get("achats_total_ttc")
                    st.markdown(f"<div class='metric-card red'><h4>Achats Totaux (TTC)</h4><h2>{fmt_money(achats) if achats else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col4:
                    nb_fa = kpis.get("nb_factures_achat")
                    st.markdown(f"<div class='metric-card'><h4>Factures Achat</h4><h2>{fmt_int(nb_fa)}</h2></div>", unsafe_allow_html=True)

                # Rangée 3 : Marge & Paiements
                st.markdown("<div class='section-title'>📊 Marge & Paiements</div>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    marge = kpis.get("marge_brute")
                    mc = "green" if marge and marge > 0 else "red"
                    st.markdown(f"<div class='metric-card {mc}'><h4>Marge Brute</h4><h2>{fmt_money(marge) if marge else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col2:
                    tm = kpis.get("taux_marge")
                    tc = "green" if tm and tm > 20 else ("yellow" if tm and tm > 10 else "red")
                    st.markdown(f"<div class='metric-card {tc}'><h4>Taux de Marge</h4><h2>{f'{tm:.1f}%' if tm else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col3:
                    dp = kpis.get("delai_paiement_moyen")
                    dc = "green" if dp and dp < 30 else ("yellow" if dp and dp < 60 else "red")
                    st.markdown(f"<div class='metric-card {dc}'><h4>Délai Paiement Moy.</h4><h2>{f'{dp:.0f} j' if dp else 'N/A'}</h2></div>", unsafe_allow_html=True)
                with col4:
                    anom = kpis.get("anomalies_detectees", 0)
                    ac = "red" if anom > 0 else "green"
                    st.markdown(f"<div class='metric-card {ac}'><h4>Retards Critiques (>90j)</h4><h2>{fmt_int(anom)}</h2></div>", unsafe_allow_html=True)

                # Rangée 4 : Tendance & Pipeline
                st.markdown("<div class='section-title'>📋 Tendance & Pipeline Commercial</div>", unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    tend = kpis.get("tendance", "—")
                    tc2 = "green" if "Hauss" in tend else ("red" if "Baiss" in tend else "")
                    st.markdown(f"<div class='metric-card {tc2}'><h4>Tendance Prédictive</h4><h2>{tend}</h2></div>", unsafe_allow_html=True)
                with col2:
                    mom = kpis.get("mom_growth")
                    mc2 = "green" if mom and mom >= 0 else "red"
                    if mom is not None:
                        mom_str = f"+{mom:.1f}%" if mom >= 0 else f"{mom:.1f}%"
                    else:
                        mom_str = "N/A"
                    st.markdown(f"<div class='metric-card {mc2}'><h4>Variation Mensuelle</h4><h2>{mom_str}</h2></div>", unsafe_allow_html=True)
                with col3:
                    nb_d = kpis.get("nb_devis")
                    st.markdown(f"<div class='metric-card purple'><h4>Devis Enregistrés</h4><h2>{fmt_int(nb_d)}</h2></div>", unsafe_allow_html=True)
                with col4:
                    nb_bl = kpis.get("nb_bl")
                    st.markdown(f"<div class='metric-card blue'><h4>Bons de Livraison</h4><h2>{fmt_int(nb_bl)}</h2></div>", unsafe_allow_html=True)

                # ── 3. Graphique des ventes mensuelles ────────────────────────
                monthly = kpis.get("monthly_sales")
                if monthly is not None and len(monthly) > 1:
                    st.markdown("### 📉 Évolution Mensuelle du CA (TTC)")
                    chart_df = pd.DataFrame({
                        "Période": [str(p) for p in monthly.index],
                        "CA TTC": monthly.values
                    }).set_index("Période")
                    st.area_chart(chart_df, use_container_width=True, height=260)

                # ── 4. Top 5 clients ──────────────────────────────────────────
                top_clients = kpis.get("top_clients")
                if top_clients is not None and not top_clients.empty:
                    st.markdown("### 🏆 Top 5 Clients par CA")
                    top_clients_display = top_clients.copy()
                    top_clients_display["CA (TTC)"] = top_clients_display["CA (TTC)"].apply(fmt_money)
                    st.dataframe(top_clients_display, use_container_width=True, hide_index=True)

                # ── 5. Synthèse IA ─────────────────────────────────────────────
                st.markdown("### 🤖 Synthèse de l'Agent IA")

                # D'abord essayer le rapport de l'agent LangGraph (LLM)
                agent_report = res.get("final_answer", "")
                if agent_report and "Mode mock" not in agent_report and "LLM non disponible" not in agent_report and len(agent_report) > 50:
                    st.markdown(f"<div class='report-box'>{agent_report}</div>", unsafe_allow_html=True)
                else:
                    # Synthèse calculée (toujours disponible, sans LLM)
                    synthesis = generate_ai_synthesis(kpis, warehouse)
                    st.markdown(f"<div class='report-box'>{synthesis}</div>", unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erreur d'exécution: {e}")
                import traceback
                st.code(traceback.format_exc())
