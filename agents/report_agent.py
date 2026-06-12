"""
agents/report_agent.py
======================
Report Agent — génère le rapport final.
Tente d'abord le LLM configuré ; si indisponible,
produit une synthèse analytique complète basée sur les données calculées.
"""
from typing import Dict, Any
from graphs.state import AgentState
from config.settings import get_llm


def _fmt(v, unit="DT"):
    """Format monétaire lisible."""
    if v is None:
        return "N/A"
    try:
        v = float(v)
    except Exception:
        return str(v)
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f} M {unit}"
    elif abs(v) >= 1_000:
        return f"{v/1_000:.1f} K {unit}"
    return f"{v:.2f} {unit}"


class ReportAgent:
    def compose(self, state: AgentState) -> str:
        llm = get_llm()
        is_mock = type(llm).__name__ == "MockChatModel"

        # ── Données calculées par les agents ─────────────────────────────────
        biz      = state.get("business_insights") or {}
        ml_res   = state.get("ml_results") or {}
        fc_res   = state.get("forecast_results") or {}
        sql_res  = state.get("sql_results") or {}

        kpis     = (biz.get("kpis") or {}).get("data", {})
        anomalies_raw = (ml_res.get("anomalies") or {})
        anomalies_list = anomalies_raw.get("anomalies", [])
        fc_data  = fc_res.get("forecast_data") or {}

        # ── Essai LLM ────────────────────────────────────────────────────────
        if not is_mock:
            # Prépare un résumé compact pour le LLM
            kpi_summary = "\n".join(
                f"- {k}: {v}" for k, v in kpis.items()
                if not isinstance(v, list)
            )
            anom_summary = "\n".join(
                f"- [{a.get('severity','?')}] {a.get('description','')}"
                for a in anomalies_list
            ) or "Aucune anomalie critique détectée."
            fc_summary = ""
            if fc_data.get("status") == "success":
                fc_summary = (
                    f"Tendance : {fc_data.get('trend_label')}, "
                    f"Croissance mensuelle : {fc_data.get('monthly_growth_rate_pct')}%, "
                    f"Prévisions 3 mois : {fc_data.get('forecasts_next_3m')}"
                )

            prompt = (
                "Tu es un analyste financier expert. Génère un rapport professionnel en français.\n\n"
                f"KPIs calculés :\n{kpi_summary}\n\n"
                f"Anomalies détectées :\n{anom_summary}\n\n"
                f"Prévisions :\n{fc_summary or 'Non disponible'}\n\n"
                "Rédige une synthèse structurée avec : "
                "(1) Performance commerciale et marge, "
                "(2) Risques et anomalies détectés, "
                "(3) Prévisions de tendance, "
                "(4) Recommandations stratégiques prioritaires. "
                "Sois précis, professionnel et concis (max 400 mots)."
            )
            try:
                res = llm.invoke(prompt)
                content = str(res.content) if hasattr(res, "content") else str(res)
                if content and "Mode mock" not in content and len(content) > 80:
                    return content
            except Exception:
                pass  # tomber sur la synthèse locale

        # ── Synthèse locale complète (sans LLM) ──────────────────────────────
        lines = [
            "### 📋 Rapport Analytique Automatisé — Finance AI Agent\n",
            "_Synthèse générée par le pipeline LangGraph_\n\n",
            "---\n\n",
        ]

        # 1. Performance commerciale
        lines.append("**📊 Performance Commerciale**\n\n")
        ca = kpis.get("ca_total_ttc")
        ca_ht = kpis.get("ca_total_ht")
        clients = kpis.get("nb_clients_actifs")
        nb_f = kpis.get("nb_factures_vente")
        panier = kpis.get("panier_moyen")
        marge = kpis.get("marge_brute")
        taux = kpis.get("taux_marge_pct")

        if ca:
            lines.append(f"- **CA Total TTC** : {_fmt(ca)} | **HT** : {_fmt(ca_ht)}\n")
        if clients:
            lines.append(f"- **Clients actifs** : {int(clients):,} | **Factures** : {int(nb_f or 0):,}\n")
        if panier:
            lines.append(f"- **Panier moyen** : {_fmt(panier)}\n")
        if marge is not None:
            marge_icon = "✅" if marge > 0 else "❌"
            lines.append(f"- **Marge brute** : {marge_icon} {_fmt(marge)}")
            if taux is not None:
                taux_icon = "🟢" if taux > 20 else ("🟡" if taux > 10 else "🔴")
                lines.append(f" (taux : {taux_icon} **{taux:.1f}%**)")
            lines.append("\n")

        achats = kpis.get("achats_total_ttc")
        nb_four = kpis.get("nb_fournisseurs_actifs")
        if achats:
            lines.append(f"- **Achats totaux TTC** : {_fmt(achats)} ({int(nb_four or 0)} fournisseurs)\n")

        lines.append("\n")

        # 2. Risques & Anomalies
        lines.append("**⚠️ Risques & Anomalies Détectés**\n\n")
        if anomalies_list:
            for a in anomalies_list:
                sev = a.get("severity", "INFO")
                icon = "🔴" if sev == "HIGH" else ("🟡" if sev == "MEDIUM" else "🔵")
                lines.append(f"- {icon} **[{sev}]** {a.get('description', '')}\n")
        else:
            lines.append("- ✅ Aucune anomalie critique détectée\n")

        delai = kpis.get("delai_paiement_moyen_jours")
        retards90 = kpis.get("retards_critiques_gt90j")
        if delai is not None:
            d_icon = "✅" if delai < 30 else ("🟡" if delai < 60 else "🔴")
            lines.append(f"- {d_icon} **Délai paiement moyen** : {delai:.0f} jours\n")
        if retards90:
            lines.append(f"- 🔴 **{int(retards90):,} factures critiques** (>90j) nécessitent un recouvrement urgent\n")

        lines.append("\n")

        # 3. Prévisions
        lines.append("**📈 Prévisions de Tendance**\n\n")
        if fc_data.get("status") == "success":
            trend = fc_data.get("trend_label", "")
            growth = fc_data.get("monthly_growth_rate_pct", 0)
            forecasts = fc_data.get("forecasts_next_3m", [])
            t_icon = "↗️" if "Hauss" in trend else "↘️"
            lines.append(f"- **Tendance** : {t_icon} {trend} ({growth:+.1f}%/mois)\n")
            if forecasts:
                lines.append("- **Prévisions 3 prochains mois** :\n")
                for f in forecasts:
                    lines.append(f"  - {f['period']} → {_fmt(f['predicted_ttc'])}\n")
        else:
            lines.append("- Données insuffisantes pour une prévision fiable\n")

        lines.append("\n")

        # 4. Recommandations
        lines.append("**🎯 Recommandations Stratégiques**\n\n")
        recs = []
        if taux is not None and taux < 15:
            recs.append("🔴 Revoir la structure des coûts d'achat — taux de marge sous 15%")
        if delai is not None and delai > 45:
            recs.append("🟡 Mettre en place un système de relance automatique des paiements")
        if retards90 and retards90 > 10:
            recs.append(f"🔴 Action de recouvrement urgente sur {int(retards90):,} créances critiques")
        if fc_data.get("monthly_growth_rate_pct", 0) < 0:
            recs.append("🟡 Baisse mensuelle détectée — analyser les causes et activer des promotions ciblées")
        else:
            recs.append("🟢 Consolider la dynamique commerciale positive sur les comptes clés")
        if clients:
            recs.append(f"🟢 Capitaliser sur les {int(clients):,} clients actifs — programme de fidélisation recommandé")

        for r in recs:
            lines.append(f"- {r}\n")

        lines.append(
            "\n---\n"
            "_💡 Pour une synthèse IA en langage naturel enrichie, "
            "assurez-vous que `GROQ_API_KEY` est renseignée dans `.env` et redémarrez l'application._"
        )

        return "".join(lines)
