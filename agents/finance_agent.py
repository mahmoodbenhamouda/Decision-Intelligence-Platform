"""
agents/finance_agent.py
=======================
Superviseur agentique unifié — plateforme « Agent Finance » (Option B, hybride).

Principe : UN seul agent superviseur qui
  1. CLASSIFIE l'intention de la demande (tableau de bord vs question NL ;
     périmètre global vs client) ;
  2. DÉTECTE le THÈME financier de la question (recouvrement, change,
     trésorerie, marge, prévision, opportunités, client spécifique, glossaire) ;
  3. DÉCIDE dynamiquement quels outils exécuter (routage déterministe) ;
  4. EXÉCUTE les outils déterministes (KPIs DuckDB, ML risque, prévision,
     anomalies) — les MÊMES briques que le reste de la plateforme ;
  5. ASSEMBLE le résultat + une TRACE de ses décisions ;
  6. en mode « question » (hybride), construit un prompt THÉMATIQUE ancré sur
     les KPIs les plus pertinents + glossaire financier intégré + historique de
     conversation → réponse LLM précise, chiffrée et non répétitive.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ml_engine.analytics import kpi_engine


# ── Glossaire financier bilingue (FR/AR) utilisé dans le système-prompt ──────
FINANCIAL_GLOSSARY: Dict[str, str] = {
    "DSO": (
        "Days Sales Outstanding (Délai Moyen de Recouvrement) : nombre de jours "
        "moyen que met un client à payer ses factures après émission. "
        "Formule : (Créances clients / CA) × 365. Un DSO faible = encaissement rapide."
    ),
    "DPO": (
        "Days Payable Outstanding (Délai Moyen de Paiement Fournisseurs) : nombre "
        "de jours moyen pour payer les fournisseurs. Un DPO élevé améliore la "
        "trésorerie mais peut fragiliser la relation fournisseur."
    ),
    "BFR": (
        "Besoin en Fonds de Roulement : ressources nécessaires pour financer le "
        "cycle d'exploitation (stocks + créances - dettes fournisseurs). "
        "BFR = Créances + Stocks - Dettes fournisseurs."
    ),
    "FRNG": (
        "Fonds de Roulement Net Global : excédent des ressources permanentes sur "
        "les emplois stables. FRNG positif = sécurité financière à long terme."
    ),
    "TRÉ": (
        "Trésorerie nette : FRNG - BFR. Indique la position de liquidité immédiate."
    ),
    "VaR": (
        "Value at Risk (Valeur à Risque) : perte maximale estimée sur une position "
        "financière (ici le portefeuille de change) avec un niveau de confiance "
        "donné (ex : 95% sur 1 mois)."
    ),
    "EBITDA": (
        "Earnings Before Interest, Taxes, Depreciation and Amortization : bénéfice "
        "avant intérêts, impôts, dépréciations et amortissements. Mesure la "
        "performance opérationnelle brute."
    ),
    "DTA": (
        "Délai de Traitement des Avoirs : temps moyen entre l'émission d'un avoir "
        "(note de crédit) et son traitement effectif. Un DTA long crée des "
        "distorsions dans le solde des créances."
    ),
    "HHI": (
        "Indice Herfindahl-Hirschman : mesure la concentration d'un portefeuille. "
        "HHI > 0.25 = forte concentration (risque élevé si un client clé disparaît)."
    ),
    "FOREX / FX": (
        "Foreign Exchange (Marché des changes) : en Tunisie, les achats importés "
        "sont libellés en EUR ou USD mais facturés en Dinars Tunisiens (TND/DT). "
        "Une dépréciation du dinar augmente le coût d'achat et réduit la marge."
    ),
    "TND": (
        "Dinar Tunisien (DT) : monnaie nationale. Cours de référence : "
        "1 EUR ≈ 3.30 DT, 1 USD ≈ 3.10 DT (à vérifier sur les données temps réel)."
    ),
    "Ratio de liquidité": (
        "Actif court terme / Passif court terme. Un ratio > 1 indique que "
        "l'entreprise peut honorer ses dettes à court terme. "
        "< 1 = risque de cessation de paiements."
    ),
    "Couverture de change": (
        "Opération financière (forward, option) qui protège contre la variation "
        "du taux de change sur un flux futur en devises. Recommandée quand "
        "l'exposition dépasse 5% du CA annuel."
    ),
    "Aging des créances": (
        "Ventilation des créances clients par tranche d'ancienneté : 0-30j, 31-60j, "
        "61-90j, >90j. Permet d'identifier les factures critiques à recouvrer "
        "en priorité."
    ),
    "Marge brute": (
        "CA HT − Coût des achats. Exprimée en % du CA HT, elle mesure la "
        "rentabilité commerciale avant les frais fixes."
    ),
    "Taux de conversion devis": (
        "Ratio Devis acceptés / Devis émis. Un taux faible (<40%) peut indiquer "
        "un problème de prix ou de proposition commerciale."
    ),
    "Encours clients": (
        "Total des factures émises non encore encaissées à une date donnée. "
        "Synonyme de créances clients."
    ),
    "Recouvrement": (
        "Processus de relance et d'encaissement des factures impayées. "
        "Priorité : factures > 90 jours (risque d'irrecouvrabilité)."
    ),
    "Factoring / Affacturage": (
        "Cession des créances clients à un organisme financier (factor) qui avance "
        "les fonds immédiatement. Permet d'améliorer la trésorerie court terme "
        "en échange d'une commission."
    ),
    "Escompte commercial": (
        "Réduction accordée au client s'il paie avant l'échéance. "
        "Ex : 2% escompte si paiement sous 10 jours au lieu de 30."
    ),
    "Appel d'offres / AO": (
        "Procédure d'achat public (marchés publics tunisiens) par laquelle un "
        "organisme public (hôpital, ministère) sollicite des offres commerciales. "
        "Publié sur TUNEPS (www.tuneps.tn)."
    ),
    "TUNEPS": (
        "Système tunisien d'achats publics électroniques. Portail officiel des "
        "marchés publics tunisiens. Source principale des appels d'offres."
    ),
    "Pareto clients": (
        "Loi 80/20 appliquée aux clients : les 20% de clients les plus importants "
        "génèrent 80% du CA. Identifier ce groupe est prioritaire pour la fidélisation."
    ),
    "Cash conversion cycle": (
        "Cycle de conversion de trésorerie : DSO + DIO (jours de stock) - DPO. "
        "Mesure le délai entre le décaissement fournisseur et l'encaissement client."
    ),
}


# ── Détection thématique de la question ─────────────────────────────────────
THEME_KEYWORDS: Dict[str, List[str]] = {
    "recouvrement": [
        "recouvrement", "relance", "impayé", "retard", "créance", "facture",
        "aging", "délai", "encaissement", "dso", "60 j", "90 j", "critique",
        "client à risque", "encours",
    ],
    "change": [
        "change", "forex", "fx", "devise", "dinar", "eur", "usd", "tnd",
        "taux de change", "dépréciation", "couverture", "risque de change",
        "var", "sensibilité", "impact change",
    ],
    "tresorerie": [
        "trésorerie", "cash", "liquidité", "frng", "bfr", "flux", "cashflow",
        "encaissement", "décaissement", "solde", "paiement", "dpo",
        "cycle de conversion",
    ],
    "marge": [
        "marge", "rentabilité", "profit", "coût", "achat", "revient", "ebitda",
        "résultat", "bénéfice", "taux de marge", "marge brute", "marge commerciale",
    ],
    "prevision": [
        "prévision", "forecast", "projection", "projeté", "futur", "prochain",
        "anticiper", "tendance", "mois prochain", "trimestre",
    ],
    "opportunites": [
        "opportunité", "opportunites", "opportunité commerciale", "appel d'offres", "appels d'offres", "appel offre", "appels offres", "ao", "marché public", "marches publics", "tuneps",
        "prospect", "croissance", "développement", "nouveau client",
    ],
    "glossaire": [
        "c'est quoi", "que veut dire", "définition", "expliquer", "signifie",
        "définir", "qu'est-ce que", "terme", "dso", "bfr", "frng", "var",
        "ebitda", "hhi", "dta", "factoring", "escompte",
    ],
    "fidelite": [
        "fidèle", "fidèles", "fidele", "fideles", "fidélité", "fidelite",
        "récurrent", "recurrent", "récurrents", "réguliers", "reguliers", "régulier",
        "meilleurs clients", "clients réguliers", "clients récurrents", "client fidèle",
        "loyal", "loyaux", "loyauté", "rétention", "retention", "clients historiques",
    ],
    "palmares": [
        "top 3", "top 5", "top 10", "top client", "top clients", "plus gros client",
        "plus gros clients", "principaux clients", "gros clients", "classement client",
        "classement des clients", "palmarès", "palmares", "clients les plus importants",
        "clients importants", "premiers clients", "liste des clients", "plus importants clients",
    ],
    "attrition": [
        "décroche", "decroche", "décrochent", "decrochent", "décrochage", "decrochage",
        "churn", "attrition", "perdre des clients", "perte de client", "clients perdus",
        "clients dormants", "dormant", "inactif", "inactifs", "ne commandent plus",
        "qui partent", "s'essouffl", "essouffl", "clients qui baissent", "perdent du terrain",
    ],
    "concentration": [
        "concentration", "concentré", "concentre", "dépendance", "dependance",
        "pareto", "80/20", "diversification", "diversifié", "diversifie",
        "poids des clients", "répartition du ca", "repartition du ca", "hhi",
        "trop dépendant", "dépendant de", "risque de dépendance",
    ],
    "approvisionnement": [
        "approvisionnement", "appro", "fournisseur", "fournisseurs", "dépendance fournisseur",
        "dependance fournisseur", "rupture", "rupture d'appro", "rupture de stock", "stock",
        "réappro", "reappro", "commande fournisseur", "biomérieux", "biomerieux",
        "prévision de demande", "prevision de demande", "demande d'articles", "volume d'articles",
        "achat", "achats", "sourcing", "chaîne d'approvisionnement",
    ],
    "performance": [
        "performance", "ca", "chiffre d'affaires", "vente", "croissance",
        "yoy", "mom", "hausse", "baisse", "évolution", "top client",
    ],
}


def detect_theme(question: str) -> List[str]:
    """Retourne la liste des thèmes détectés dans la question (ordre priorité)."""
    q_lower = question.lower()
    themes = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            themes.append(theme)
    return themes or ["performance"]


def has_internal_theme(question: str) -> bool:
    """Vrai si la question correspond à un thème 'données internes' (ERP/finance).
    Sinon la question est considérée comme 'externe' → candidate au RAG documentaire."""
    q_lower = question.lower()
    return any(any(kw in q_lower for kw in kws) for kws in THEME_KEYWORDS.values())


def detect_glossary_terms(question: str) -> List[str]:
    """Retourne les termes du glossaire mentionnés dans la question."""
    q_lower = question.lower()
    terms = []
    for term in FINANCIAL_GLOSSARY:
        if term.lower() in q_lower:
            terms.append(term)
    return terms


def build_thematic_context(themes: List[str], kpis: Dict[str, Any]) -> str:
    """Construit le contexte KPI minimal et pertinent selon les thèmes détectés."""
    parts: List[str] = []

    def fmt(v, suffix="DT") -> str:
        if v is None:
            return "N/D"
        v = float(v)
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.2f} M {suffix}"
        if abs(v) >= 1_000:
            return f"{v / 1_000:.1f} K {suffix}"
        return f"{v:.2f} {suffix}"

    if "recouvrement" in themes:
        top_risk = kpis.get("clients_relance") or kpis.get("clients_a_risque") or kpis.get("top_clients") or []
        top_client_name = ""
        if top_risk:
            c = top_risk[0]
            top_client_name = c.get("nom") or c.get("client") or ""
        parts.append(
            f"📌 RECOUVREMENT :\n"
            f"  - Exposition RÉCENTE en retard >60j ({kpis.get('exposition_recente_periode', '6 mois')}) : "
            f"{fmt(kpis.get('exposition_recente_dt'))} sur {kpis.get('exposition_recente_count', 0)} facture(s)\n"
            f"  - dont critique (>90j) : {fmt(kpis.get('exposition_recente_critique_dt'))}\n"
            f"  - DSO (délai encaissement moyen) : {kpis.get('dso_jours', 0):.0f} jours\n"
            f"  - Client prioritaire à relancer : {top_client_name or 'N/D'}\n"
            f"  - Repère historique (comportement de paiement, PAS un encours dû) : "
            f"{fmt(kpis.get('ca_retard_historique_ttc'))} de CA réglé avec >60j de retard sur tout l'historique"
        )

    if "change" in themes:
        mi = kpis.get("market_intel") or {}
        fx = mi.get("fx") or {}
        fxs = mi.get("fx_sensitivity") or {}
        parts.append(
            f"💱 CHANGE / FOREX :\n"
            f"  - EUR/TND : {fx.get('eur_tnd', 'N/D')}\n"
            f"  - USD/TND : {fx.get('usd_tnd', 'N/D')}\n"
            f"  - Variation EUR/TND (récente) : {fx.get('eur_tnd_var_pct', 'N/D')}%\n"
            f"  - Exposition annuelle aux achats en devises : {fmt(fxs.get('annual_fx_base_dt'))}\n"
            f"  - Impact par ±1% du dinar : {fmt(fxs.get('impact_per_1pct_dt'))}\n"
            f"  - VaR change estimée : {fmt(fxs.get('var_impact_dt'))}\n"
            f"  - Hypothèse de variation : {fxs.get('assumption', 'N/D')}"
        )

    if "tresorerie" in themes:
        cf = kpis.get("cash_forecast") or []
        cf_str = ", ".join(f"{p['period']} : {fmt(p['montant'])}" for p in cf[:3]) or "N/D"
        parts.append(
            f"💰 TRÉSORERIE :\n"
            f"  - DSO : {kpis.get('dso_jours', 0):.0f} jours\n"
            f"  - DPO : {kpis.get('dpo_jours', 0):.0f} jours\n"
            f"  - Cycle de conversion cash : {kpis.get('cash_conversion_cycle', 0):.0f} jours\n"
            f"  - Prévision cashflow : {cf_str}\n"
            f"  - Achats total TTC : {fmt(kpis.get('achats_total_ttc'))}\n"
            f"  - CA total TTC : {fmt(kpis.get('ca_total_ttc'))}"
        )

    if "marge" in themes:
        parts.append(
            f"📊 MARGE / RENTABILITÉ :\n"
            f"  - CA HT : {fmt(kpis.get('ca_total_ht'))}\n"
            f"  - Achats TTC : {fmt(kpis.get('achats_total_ttc'))}\n"
            f"  - Marge brute : {fmt(kpis.get('marge_brute'))}\n"
            f"  - Taux de marge : {kpis.get('taux_marge', 0):.1f}%\n"
            f"  - Note qualité marge : {kpis.get('marge_note', 'N/D')}"
        )

    if "prevision" in themes:
        fc = kpis.get("forecast_next") or []
        fc_str = "\n".join(
            f"    {p['period']} → {fmt(p['montant'])}" for p in fc
        ) or "  Données insuffisantes"
        monthly = kpis.get("monthly_sales") or []
        growth = kpis.get("yoy_growth")
        parts.append(
            f"🔮 PRÉVISION :\n"
            f"  - Croissance YoY : {growth:.1f}%" if growth else "  - Croissance YoY : N/D"
        )
        parts[-1] += f"\n  - CA mensuel (12 derniers mois) : {len(monthly)} points\n  - Projection CA :\n{fc_str}"

    if "fidelite" in themes:
        fideles = kpis.get("clients_fideles") or []
        fid_str = "\n".join(
            f"    {i+1}. {c.get('nom')} — {c.get('mois_actifs',0)} mois actifs, "
            f"{c.get('invoices',0)} factures, {fmt(c.get('revenue'))} CA "
            f"(depuis {c.get('premier','N/D')}, dernier achat {c.get('dernier','N/D')})"
            for i, c in enumerate(fideles[:6])
        ) or "  Aucun client récurrent (>=2 achats) sur ce périmètre."
        parts.append(
            f"🤝 CLIENTS FIDÈLES (récurrence = nb de mois d'achat distincts, "
            f"marqueur de fidélité) :\n{fid_str}"
        )

    if "attrition" in themes:
        dec = kpis.get("clients_decrochent") or []
        dec_str = "\n".join(
            f"    {i+1}. {c.get('nom')} — {fmt(c.get('ca_prev'))} → {fmt(c.get('ca_recent'))} sur 90j "
            f"(-{c.get('chute_pct',0):.0f}%), dernier achat {c.get('dernier','N/D')} ({c.get('jours_inactif',0)} j)"
            for i, c in enumerate(dec[:6])
        ) or "  Aucun décrochage marqué (clients établis stables)."
        parts.append(
            f"📉 CLIENTS QUI DÉCROCHENT (CA 90 derniers jours vs 90 précédents, "
            f"clients établis >=6 mois, chute >60%) :\n{dec_str}"
        )

    if "concentration" in themes:
        n80 = kpis.get("clients_pour_80pct") or 0
        ntot = kpis.get("nb_clients_ca") or kpis.get("nb_clients") or 0
        top5 = kpis.get("top_clients") or []
        top5_str = ", ".join(
            f"{c.get('nom') or c.get('client')} ({c.get('share',0):.0f}%)" for c in top5[:5]
        ) or "N/D"
        parts.append(
            f"🎯 CONCENTRATION CLIENTS :\n"
            f"  - {n80} clients font 80% du CA (sur {ntot} clients)\n"
            f"  - Part du Top 5 : {kpis.get('top_clients_revenue_share', 0):.0f}% du CA\n"
            f"  - HHI : {kpis.get('hhi_clients', 0):.0f}/10000\n"
            f"  - Principaux poids : {top5_str}"
        )

    if "approvisionnement" in themes:
        try:
            from ml_engine.analytics.demand_engine import compute_supply_demand
            d = compute_supply_demand()
        except Exception:
            d = {}
        top = (d.get("fournisseurs_top") or [{}])
        fc = d.get("demande_prevision") or []
        fc_str = ", ".join(f"{p['period']}≈{int(p['qte'])}" for p in fc) or "N/D"
        parts.append(
            f"📦 DEMANDE & APPROVISIONNEMENT (pas de données de stock ERP → demande + risque fournisseur) :\n"
            f"  - Dépendance fournisseur : {d.get('dependance_fournisseur', 'n/d')} "
            f"({top[0].get('fournisseur', 'N/D')} = {d.get('fournisseur_top1_pct', 0)}% des achats, "
            f"top 3 = {d.get('fournisseurs_top3_pct', 0)}%, HHI {d.get('fournisseurs_hhi', 0):.0f})\n"
            f"  - Prévision de demande (articles/mois, MAPE {d.get('demande_mape')}%) : {fc_str}"
        )

    if "opportunites" in themes:
        mi = kpis.get("market_intel") or {}
        news = mi.get("news") or []
        news_str = "\n".join(
            f"    • [{n.get('type','?')}] {n.get('title','')[:80]} (score:{n.get('relevance','?')})"
            for n in news[:5]
        ) or "  Aucun appel d'offres récupéré"
        signals = mi.get("signals") or []
        sig_str = "\n".join(f"    - {s}" for s in signals[:3]) or "  Aucun signal"
        parts.append(
            f"🎯 OPPORTUNITÉS / MARCHÉS PUBLICS :\n"
            f"  Signaux externes :\n{sig_str}\n"
            f"  Appels d'offres détectés :\n{news_str}"
        )

    if "performance" in themes or not parts:
        top5 = kpis.get("top_clients") or []
        top5_str = "\n".join(
            f"    {i+1}. {c.get('nom') or c.get('client')} — {fmt(c.get('revenue'))} "
            f"({c.get('share', 0):.1f}% du CA)"
            for i, c in enumerate(top5[:5])
        ) or "  N/D"
        parts.append(
            f"📈 PERFORMANCE GLOBALE :\n"
            f"  - CA TTC : {fmt(kpis.get('ca_total_ttc'))}\n"
            f"  - Croissance YoY : {kpis.get('yoy_growth', 0):.1f}%\n"
            f"  - Nb clients actifs : {kpis.get('nb_clients', 0)}\n"
            f"  - Panier moyen : {fmt(kpis.get('panier_moyen'))}\n"
            f"  - Tendance : {kpis.get('tendance', 'N/D')}\n"
            f"  Top 5 clients :\n{top5_str}"
        )

    return "\n\n".join(parts)


def build_glossary_section(terms: List[str], question_themes: List[str]) -> str:
    """Construit la section glossaire à injecter dans le prompt."""
    # Termes explicitement demandés
    relevant = set(terms)
    # Termes liés aux thèmes détectés (automatique)
    theme_to_terms = {
        "change": ["FOREX / FX", "VaR", "Couverture de change", "TND"],
        "recouvrement": ["DSO", "Aging des créances", "Recouvrement", "Encours clients"],
        "tresorerie": ["BFR", "FRNG", "TRÉ", "Cash conversion cycle", "DPO"],
        "marge": ["Marge brute", "EBITDA", "Taux de conversion devis"],
        "opportunites": ["Appel d'offres / AO", "TUNEPS", "Pareto clients"],
    }
    for theme in question_themes:
        for t in theme_to_terms.get(theme, []):
            relevant.add(t)

    if not relevant:
        return ""

    lines = ["📚 GLOSSAIRE FINANCIER (à utiliser dans la réponse si pertinent) :"]
    for term in sorted(relevant):
        defn = FINANCIAL_GLOSSARY.get(term)
        if defn:
            lines.append(f"  • {term} : {defn}")
    return "\n".join(lines)


def build_history_context(history: List[Dict[str, str]], max_turns: int = 8) -> str:
    """Formate les N derniers échanges de la conversation pour le contexte LLM."""
    if not history:
        return ""
    recent = history[-(max_turns * 2):]  # max_turns aller-retours
    lines = ["💬 HISTORIQUE DE CONVERSATION (contexte, ne pas répéter) :"]
    for msg in recent:
        role = msg.get("role", "user")
        text = (msg.get("text") or msg.get("content") or "").strip()
        if not text:
            continue
        prefix = "Utilisateur" if role == "user" else "Copilote"
        # Tronquer les réponses longues dans l'historique
        if len(text) > 300:
            text = text[:300] + "…"
        lines.append(f"  [{prefix}] : {text}")
    return "\n".join(lines)


def build_client_context(filters: Dict[str, Any], kpis: Dict[str, Any]) -> str:
    """Construit le contexte spécifique si un client est sélectionné."""
    clients = filters.get("selected_clients") or []
    if not clients:
        return ""

    def fmt(v, suffix="DT") -> str:
        if v is None:
            return "N/D"
        v = float(v)
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.2f} M {suffix}"
        if abs(v) >= 1_000:
            return f"{v / 1_000:.1f} K {suffix}"
        return f"{v:.2f} {suffix}"

    top_clients = kpis.get("top_clients") or []
    client_names = [str(c) for c in clients[:5]]
    client_details = []
    for c in top_clients:
        c_id = str(c.get("client", ""))
        c_nom = c.get("nom") or c_id
        if c_id in client_names or c_nom in client_names:
            client_details.append(
                f"  • {c_nom} : CA={fmt(c.get('revenue'))}, "
                f"Factures={c.get('invoices', 0)}, "
                f"Part CA={c.get('share', 0):.1f}%, "
                f"Score risque={c.get('risk_score', 'N/D')}"
            )

    clients_at_risk = kpis.get("clients_a_risque") or []
    risk_details = []
    for r in clients_at_risk:
        r_id = str(r.get("client", ""))
        r_nom = r.get("nom") or r_id
        if r_id in client_names or r_nom in client_names:
            risk_details.append(
                f"  • {r_nom} : Montant à risque={fmt(r.get('montant_risque'))}, "
                f"Nb factures en retard={r.get('factures', 0)}"
            )

    scope_lines = [
        f"🎯 PÉRIMÈTRE CLIENT SÉLECTIONNÉ : {', '.join(client_names[:3])}"
        + (f" (+{len(clients)-3} autres)" if len(clients) > 3 else ""),
        "  ⚠️ Ta réponse doit se concentrer UNIQUEMENT sur ce(s) client(s).",
        "  Ne fais PAS de comparaisons avec d'autres clients non sélectionnés.",
    ]
    if client_details:
        scope_lines.append("  Données client(s) :")
        scope_lines.extend(client_details)
    if risk_details:
        scope_lines.append("  Risque client(s) :")
        scope_lines.extend(risk_details)

    return "\n".join(scope_lines)


class FinanceSupervisor:
    name = "Agent Finance"
    role = "superviseur agentique (routage déterministe + LLM hybride thématique)"
    version = "3.0"
    tools = ["router", "sql_kpis", "ml_risque", "prevision", "anomalies", "synthese"]

    # ── Classification d'intention ──────────────────────────────────────────
    def _classify(self, filters: Dict[str, Any], question: Optional[str]) -> Tuple[str, str]:
        mode = "qa" if (question and str(question).strip()) else "dashboard"
        scope = "client" if filters.get("selected_clients") else "global"
        return mode, scope

    # ── Outil : prévision (régression linéaire 12 mois → 3 mois) ────────────
    def _tool_forecast(self, monthly: List[Dict[str, Any]], horizon: int = 3) -> List[Dict[str, Any]]:
        pts = [float(m.get("revenue") or 0) for m in (monthly or [])][-12:]
        periods = [m.get("period") for m in (monthly or [])][-12:]
        if len(pts) < 3:
            return []
        n = len(pts)
        xs = list(range(n))
        sx, sy = sum(xs), sum(pts)
        sxy = sum(x * y for x, y in zip(xs, pts))
        sxx = sum(x * x for x in xs)
        denom = (n * sxx - sx * sx) or 1
        a = (n * sxy - sx * sy) / denom
        b = (sy - a * sx) / n
        try:
            y, mo = map(int, str(periods[-1]).split("-")[:2])
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        for k in range(1, horizon + 1):
            m2 = mo + k
            y2 = y + (m2 - 1) // 12
            m2 = ((m2 - 1) % 12) + 1
            out.append({"period": f"{y2:04d}-{m2:02d}", "montant": float(max(0.0, a * (n - 1 + k) + b))})
        return out

    # ── Orchestration (dashboard) ───────────────────────────────────────────
    def run(self, filters: Dict[str, Any] | None = None, question: Optional[str] = None) -> Dict[str, Any]:
        filters = filters or {}
        trace: List[Dict[str, Any]] = []

        def step(tool: str, label: str, status: str = "ok", t0: float | None = None):
            trace.append({"tool": tool, "label": label, "status": status,
                          "ms": int((time.time() - t0) * 1000) if t0 else 0})

        mode, scope = self._classify(filters, question)
        step("router", f"Intention : {mode} · périmètre {scope}")

        # Outil KPIs (toujours requis)
        t0 = time.time()
        kpis = kpi_engine.compute_dashboard(filters)
        if not isinstance(kpis, dict):
            kpis = {}
        step("sql_kpis", "Outil SQL — KPIs calculés sur l'entrepôt DuckDB", t0=t0)

        # DÉCISION : périmètre client → comparaisons inter-clients désactivées
        if scope == "client":
            step("router", "Décision : périmètre client → analyses inter-clients désactivées", status="info")

        # DÉCISION : scoring ML seulement si le modèle est entraîné
        if kpis.get("risk_model_active"):
            step("ml_risque", f"Outil ML — risque crédit ({kpis.get('nb_clients_risque_predit')} clients à risque élevé)")
        else:
            step("ml_risque", "Décision : modèle de risque non entraîné → étape ignorée", status="skip")

        # DÉCISION : prévision seulement si l'historique est suffisant (>= 3 mois)
        monthly = kpis.get("monthly_sales") or []
        if len(monthly) >= 3:
            t0 = time.time()
            kpis["forecast_next"] = self._tool_forecast(monthly)
            step("prevision", "Outil Prévision — projection du CA sur 3 mois", t0=t0)
        else:
            kpis["forecast_next"] = []
            step("prevision", "Décision : historique < 3 mois → prévision non fiable, ignorée", status="skip")

        # Outil Anomalies
        step("anomalies", f"Outil Anomalies — {kpis.get('anomalies_detectees', 0)} détectée(s)")

        # Agent de veille externe (change/marché) — optionnel, lecture rapide du cache
        try:
            from agents.veille_agent import load_market_intel
            mi = load_market_intel()
        except Exception:
            mi = None
        if mi:
            # Aide à la décision : croiser les opportunités avec les clients existants (CA + reco)
            try:
                if mi.get("news"):
                    mi["news"] = kpi_engine.enrich_opportunities(mi["news"])
                    nb_cli = sum(1 for o in mi["news"] if o.get("type") == "Client existant")
                    if nb_cli:
                        mi.setdefault("signals", []).insert(
                            0, f"{nb_cli} opportunité(s) concernent des clients existants → priorité commerciale.")
            except Exception:
                pass
            # FX → impact CHIFFRÉ sur le coût d'achat annuel (branché sur les achats réels)
            try:
                if mi.get("fx"):
                    fxs = kpi_engine.fx_margin_sensitivity(mi["fx"])
                    if fxs:
                        mi["fx_sensitivity"] = fxs
                        base_txt = f"{fxs['annual_fx_base_dt']:,.0f}".replace(",", " ")
                        if fxs.get("var_impact_dt"):
                            imp_txt = f"{fxs['var_impact_dt']:+,.0f}".replace(",", " ")
                            mi.setdefault("signals", []).insert(
                                0, f"Impact change estimé : {imp_txt} DT sur le coût d'achat annuel "
                                   f"(base exposée {base_txt} DT).")
                        else:
                            p1_txt = f"{fxs['impact_per_1pct_dt']:,.0f}".replace(",", " ")
                            mi.setdefault("signals", []).append(
                                f"Sensibilité change : ±1% du dinar ≈ ±{p1_txt} DT sur le coût d'achat annuel.")
            except Exception:
                pass
            # Budget santé → part réelle du CA adossée au secteur public
            try:
                if mi.get("macro"):
                    mc = kpi_engine.macro_market_context(mi["macro"])
                    if mc:
                        mi["macro_context"] = mc
                        mi.setdefault("signals", []).append(mc["note"])
            except Exception:
                pass
            # RADAR FINANCIER : signaux externes → actions finance priorisées et chiffrées
            try:
                radar = kpi_engine.finance_radar(mi, filters)
                kpis["finance_radar"] = radar
                if radar:
                    top = radar[0]
                    step("radar", f"Radar financier — {len(radar)} action(s) ; priorité : {top['titre']}",
                         status="info")
            except Exception:
                kpis["finance_radar"] = []
            kpis["market_intel"] = mi
            sig = (mi.get("signals") or [None])[0]
            step("veille", f"Agent Veille — {sig[:80]}" if sig else "Agent Veille — signaux externes chargés", status="info")

        # Assemblage
        step("synthese", "Assemblage du tableau de bord décisionnel")

        return {
            "kpis": kpis, "trace": trace, "mode": mode, "scope": scope,
            "meta": {"name": self.name, "role": self.role, "version": self.version, "tools": self.tools},
        }

    # ── Couche LLM thématique (hybride) ─────────────────────────────────────
    def _llm_text(
        self,
        question: str,
        kpis: Dict[str, Any],
        filters: Dict[str, Any] | None = None,
        history: List[Dict[str, str]] | None = None,
    ) -> Optional[str]:
        """Renvoie une réponse LLM thématique et personnalisée, ou None si aucune clé."""
        if not (os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            return None
        filters = filters or {}
        history = history or []

        try:
            from config.settings import get_llm
            llm = get_llm()

            # 1. Détection thématique
            themes = detect_theme(question)
            glossary_terms = detect_glossary_terms(question)

            # 2. Radar financier (actions prioritaires chiffrées)
            radar = kpis.get("finance_radar") or []
            radar_txt = "\n".join(
                f"  - [{c.get('severite','')}] {c.get('titre','')} : {c.get('montant_dt',0):,.0f} DT "
                f"({c.get('montant_label','')}) — {c.get('action','')}"
                .replace(",", " ")
                for c in radar[:5]
            ) or "  Aucune action prioritaire détectée."

            # 3. Contexte thématique (KPIs pertinents)
            thematic_ctx = build_thematic_context(themes, kpis)

            # 4. Contexte client (si périmètre client)
            client_ctx = build_client_context(filters, kpis)

            # 5. Glossaire financier pertinent
            glossary_ctx = build_glossary_section(glossary_terms, themes)

            # 6. Historique de conversation
            history_ctx = build_history_context(history, max_turns=8)

            # 7. Construction du prompt système enrichi
            system_prompt = (
                "Tu es FinBot, le copilote financier expert d'Overlyne (distributeur de matériel "
                "de diagnostic médical en Tunisie). Tu maîtrises parfaitement la comptabilité "
                "analytique, la gestion de trésorerie, le recouvrement de créances, le risque de "
                "change sur les marchés émergents, les marchés publics tunisiens (TUNEPS), et "
                "l'analyse financière des PME.\n\n"
                "RÈGLES ABSOLUES :\n"
                "1. Réponds UNIQUEMENT en français, de manière concise, chiffrée et actionnable.\n"
                "2. Cite TOUJOURS des montants précis en DT (dinars tunisiens) issus des données.\n"
                "3. NE JAMAIS répéter le même paragraphe générique — chaque réponse est unique "
                "   et spécifique à la question posée.\n"
                "4. Si la question concerne un client spécifique, parle UNIQUEMENT de ce client.\n"
                "5. Si un terme financier est utilisé, explique-le brièvement (1 phrase max).\n"
                "6. Structure ta réponse avec des émojis et du Markdown (titres ##, listes - , **gras**).\n"
                "7. Termine par une recommendation concrète et chiffrée.\n"
                "8. Si tu détectes une demande de définition, fournis une explication claire et "
                "   illustrée par un exemple chiffré tiré des données disponibles.\n"
            )

            # 8. Construction du prompt utilisateur complet
            user_prompt_parts = [
                f"## QUESTION POSÉE\n{question}\n",
                f"## THÈMES DÉTECTÉS\n{', '.join(themes)}\n",
            ]
            if client_ctx:
                user_prompt_parts.append(f"\n{client_ctx}\n")
            user_prompt_parts.append(f"\n## DONNÉES FINANCIÈRES PERTINENTES\n{thematic_ctx}\n")
            user_prompt_parts.append(f"\n## ACTIONS PRIORITAIRES (RADAR)\n{radar_txt}\n")
            if glossary_ctx:
                user_prompt_parts.append(f"\n{glossary_ctx}\n")
            if history_ctx:
                user_prompt_parts.append(f"\n{history_ctx}\n")
            user_prompt_parts.append(
                "\n## INSTRUCTION\n"
                "Réponds à la question de manière précise, chiffrée et actionnable. "
                "Utilise les données ci-dessus. Ne génère PAS un rapport générique. "
                "Ta réponse doit être différente des réponses précédentes dans l'historique."
            )

            full_prompt = system_prompt + "\n\n" + "\n".join(user_prompt_parts)

            # Essai résilient : modèle configuré, puis replis automatiques si un
            # modèle est déprécié côté Groq (ex. retrait des llama-3.x en 2026).
            for _m in (None, "openai/gpt-oss-20b", "gemma2-9b-it"):
                try:
                    _llm = get_llm(model=_m) if _m else llm
                    res = _llm.invoke(full_prompt)
                    txt = getattr(res, "content", str(res))
                    if txt and "[Mode mock" not in txt:
                        return txt.strip()
                except Exception:
                    continue
            return None
        except Exception:
            return None

    def _fallback_answer(self, question: str, kpis: Dict[str, Any], filters: Dict[str, Any]) -> str:
        """Repli déterministe thématique — répond différemment selon le thème (sans LLM)."""
        themes = detect_theme(question)
        lines = []

        def fmt(v, suffix="DT") -> str:
            if v is None:
                return "N/D"
            v = float(v)
            if abs(v) >= 1_000_000:
                return f"{v / 1_000_000:.2f} M {suffix}"
            if abs(v) >= 1_000:
                return f"{v / 1_000:.1f} K {suffix}"
            return f"{v:.2f} {suffix}"

        if "glossaire" in themes or any(
            kw in question.lower() for kw in ["c'est quoi", "définition", "signifie", "expliquer"]
        ):
            glossary_terms = detect_glossary_terms(question)
            if glossary_terms:
                lines.append("## 📚 Définitions financières\n")
                for term in glossary_terms:
                    defn = FINANCIAL_GLOSSARY.get(term, "Terme non trouvé dans le glossaire.")
                    lines.append(f"**{term}** : {defn}\n")
            else:
                lines.append("## 📚 Glossaire financier\n")
                lines.append("Je n'ai pas détecté de terme financier spécifique dans votre question. "
                             "Essayez par exemple : *DSO*, *BFR*, *marge brute*, *FOREX*, etc.\n")

        elif "recouvrement" in themes:
            top_risk = kpis.get("clients_relance") or kpis.get("clients_a_risque") or []
            periode = kpis.get("exposition_recente_periode", "6 derniers mois")
            lines.append("## 📋 Clients à relancer en priorité\n")
            lines.append(f"- **Exposition récente (>60j)** : **{fmt(kpis.get('exposition_recente_dt'))}** "
                         f"({periode}) — dont **{fmt(kpis.get('exposition_recente_critique_dt'))}** critique (>90j) "
                         f"sur **{kpis.get('exposition_recente_count', 0)}** facture(s)")
            lines.append(f"- **DSO** : **{kpis.get('dso_jours', 0):.0f} jours**\n")
            if top_risk:
                lines.append("**À relancer, par exposition récente décroissante :**")
                for i, c in enumerate(top_risk[:5]):
                    lines.append(f"{i+1}. **{c.get('nom') or c.get('client')}** — "
                                 f"{fmt(c.get('montant_risque'))} sur {c.get('factures', 0)} facture(s) en retard")
                leader = top_risk[0]
                lines.append(f"\n**Action** : commencer par **{leader.get('nom') or leader.get('client')}** "
                             f"({fmt(leader.get('montant_risque'))}) — appel + relance écrite, puis proposer un "
                             f"échéancier si la créance dépasse 90 jours.")
            else:
                lines.append("Aucune créance récente significative en retard (>60j) sur ce périmètre. 👍")
            lines.append(f"\n_À titre indicatif, **{fmt(kpis.get('ca_retard_historique_ttc'))}** de CA a été "
                         f"historiquement réglé avec >60j de retard (comportement de paiement, pas un encours dû)._")

        elif "change" in themes:
            mi = kpis.get("market_intel") or {}
            fx = mi.get("fx") or {}
            fxs = mi.get("fx_sensitivity") or {}
            lines.append("## 💱 Risque de change\n")
            if fx:
                lines.append(f"- **EUR/TND** : {fx.get('eur_tnd', 'N/D')} | **USD/TND** : {fx.get('usd_tnd', 'N/D')}")
                lines.append(f"- **Variation récente** : {fx.get('eur_tnd_var_pct', 'N/D')}%")
            if fxs:
                lines.append(f"- **Exposition aux devises** : {fmt(fxs.get('annual_fx_base_dt'))}/an")
                lines.append(f"- **Sensibilité ±1%** : {fmt(fxs.get('impact_per_1pct_dt'))} d'impact sur les achats")
            else:
                lines.append("- Données de change non disponibles (agent de veille non actualisé).")
            lines.append("\n**Recommandation** : Envisager une couverture forward si l'exposition dépasse 5% du CA.")

        elif "tresorerie" in themes:
            cf = kpis.get("cash_forecast") or []
            lines.append("## 💰 Position de trésorerie\n")
            lines.append(f"- **DSO** : {kpis.get('dso_jours', 0):.0f} jours (délai encaissement client)")
            lines.append(f"- **DPO** : {kpis.get('dpo_jours', 0):.0f} jours (délai paiement fournisseur)")
            lines.append(f"- **Cycle cash** : {kpis.get('cash_conversion_cycle', 0):.0f} jours")
            if cf:
                lines.append("\n**Prévisions d'encaissement** :")
                for p in cf[:3]:
                    lines.append(f"  - {p['period']} : {fmt(p['montant'])}")

        elif "marge" in themes:
            lines.append("## 📊 Analyse de rentabilité\n")
            lines.append(f"- **CA HT** : {fmt(kpis.get('ca_total_ht'))}")
            lines.append(f"- **Achats TTC** : {fmt(kpis.get('achats_total_ttc'))}")
            lines.append(f"- **Marge brute** : {fmt(kpis.get('marge_brute'))}")
            lines.append(f"- **Taux de marge** : **{kpis.get('taux_marge', 0):.1f}%**")
            if kpis.get("marge_note"):
                lines.append(f"\n⚠️ {kpis['marge_note']}")

        elif "prevision" in themes:
            fc = kpis.get("forecast_next") or []
            lines.append("## 🔮 Prévision de chiffre d'affaires\n")
            if fc:
                for p in fc:
                    lines.append(f"- **{p['period']}** : {fmt(p['montant'])} (projection)")
                lines.append(f"\nBase : tendance sur {len(kpis.get('monthly_sales') or [])} mois d'historique.")
            else:
                lines.append("Historique insuffisant pour générer une prévision fiable.")

        elif "fidelite" in themes:
            fideles = kpis.get("clients_fideles") or []
            lines.append("## 🤝 Vos clients les plus fidèles\n")
            if fideles:
                lines.append("Classés par **récurrence** (nombre de mois d'achat), le vrai marqueur de fidélité :\n")
                for i, c in enumerate(fideles[:5]):
                    lines.append(
                        f"{i+1}. **{c.get('nom')}** — {c.get('mois_actifs', 0)} mois actifs, "
                        f"{c.get('invoices', 0)} factures, {fmt(c.get('revenue'))} de CA "
                        f"(client depuis {c.get('premier', 'N/D')}, dernier achat {c.get('dernier', 'N/D')})"
                    )
                leader = fideles[0]
                lines.append(
                    f"\n**Recommandation** : **{leader.get('nom')}** est votre relation la plus régulière "
                    f"({leader.get('mois_actifs', 0)} mois d'activité). Sécurisez-la avec un contrat-cadre ou "
                    f"des conditions préférentielles, et répliquez ce profil sur vos prospects."
                )
            else:
                lines.append("Pas assez d'historique multi-mois sur ce périmètre pour identifier des clients "
                             "récurrents. Élargissez la période ou retirez les filtres client.")

        elif "opportunites" in themes:
            mi = kpis.get("market_intel") or {}
            news = mi.get("news") or []
            lines.append("## 🎯 Opportunités commerciales\n")
            if news:
                for n in news[:5]:
                    lines.append(f"- **[{n.get('type','?')}]** {n.get('title','')[:100]}")
                    if n.get("reco"):
                        lines.append(f"  → {n['reco']}")
            else:
                lines.append("Aucun appel d'offres récent détecté. Vérifiez la connectivité de l'agent de veille.")

        elif "palmares" in themes:
            tops = kpis.get("top_clients") or []
            lines.append("## 🏆 Vos principaux clients (par chiffre d'affaires)\n")
            if tops:
                for i, c in enumerate(tops[:5]):
                    lines.append(
                        f"{i+1}. **{c.get('nom') or c.get('client')}** — {fmt(c.get('revenue'))} "
                        f"({c.get('share', 0):.1f}% du CA, {c.get('invoices', 0)} factures)"
                    )
                share5 = kpis.get("top_clients_revenue_share")
                if share5 is not None:
                    lines.append(f"\nÀ eux seuls, ces 5 clients pèsent **{share5:.0f}%** de votre chiffre d'affaires.")
            else:
                lines.append("Aucun client sur ce périmètre.")

        elif "attrition" in themes:
            dec = kpis.get("clients_decrochent") or []
            lines.append("## 📉 Clients qui décrochent\n")
            if dec:
                lines.append("Clients établis dont le CA des 90 derniers jours s'est effondré (>60% de baisse) — "
                             "à recontacter vite :\n")
                for i, c in enumerate(dec[:5]):
                    lines.append(
                        f"{i+1}. **{c.get('nom')}** — CA passé de {fmt(c.get('ca_prev'))} à {fmt(c.get('ca_recent'))} "
                        f"sur 90j (**-{c.get('chute_pct', 0):.0f}%**), dernier achat {c.get('dernier', 'N/D')} "
                        f"({c.get('jours_inactif', 0)} j)"
                    )
                leader = dec[0]
                lines.append(
                    f"\n**Action** : prioriser **{leader.get('nom')}** (perte de "
                    f"{fmt((leader.get('ca_prev') or 0) - (leader.get('ca_recent') or 0))} sur le trimestre). "
                    f"Appel commercial pour comprendre la cause (prix, concurrence, satisfaction) avant de perdre le compte."
                )
            else:
                lines.append("Aucun décrochage marqué détecté : les clients établis maintiennent leur niveau d'achat. 👍")

        elif "concentration" in themes:
            n80 = kpis.get("clients_pour_80pct") or 0
            ntot = kpis.get("nb_clients_ca") or kpis.get("nb_clients") or 0
            share5 = kpis.get("top_clients_revenue_share")
            hhi = kpis.get("hhi_clients")
            top5 = kpis.get("top_clients") or []
            pct = (n80 / ntot * 100) if ntot else 0
            niveau = ("très concentré (dépendance forte)" if pct < 15 else
                      "concentré (surveiller la dépendance)" if pct < 30 else
                      "bien diversifié (risque de dépendance faible)")
            lines.append("## 🎯 Concentration du portefeuille clients\n")
            lines.append(f"- **{n80}** clients réalisent **80% du CA** (sur {ntot}), soit **{pct:.0f}%** du portefeuille → **{niveau}**")
            if share5 is not None:
                lines.append(f"- **Top 5 clients** = **{share5:.0f}%** du CA")
            if hhi is not None:
                lines.append(f"- **Indice HHI** : {hhi:.0f}/10000 ({'concentré' if hhi > 2500 else 'peu concentré'})")
            if top5:
                lines.append("\n**Principaux poids :** " + ", ".join(
                    f"{c.get('nom') or c.get('client')} ({c.get('share', 0):.0f}%)" for c in top5[:3]))
            lines.append("\n**Lecture** : plus le CA repose sur peu de clients, plus la perte d'un compte est risquée. "
                         "Objectif : élargir la base et réduire le poids des tout premiers clients.")

        elif "approvisionnement" in themes:
            try:
                from ml_engine.analytics.demand_engine import compute_supply_demand
                d = compute_supply_demand()
            except Exception:
                d = {}
            top = (d.get("fournisseurs_top") or [{}])
            dep = d.get("dependance_fournisseur", "n/d")
            lines.append("## 📦 Demande & approvisionnement\n")
            lines.append(f"- **Dépendance fournisseur** : **{dep}** — "
                         f"**{top[0].get('fournisseur', 'N/D')}** = **{d.get('fournisseur_top1_pct', 0)}%** "
                         f"des achats (top 3 = {d.get('fournisseurs_top3_pct', 0)}%, "
                         f"{d.get('fournisseurs_nb', 0)} fournisseurs, HHI {d.get('fournisseurs_hhi', 0):.0f})")
            fc = d.get("demande_prevision") or []
            if fc:
                lines.append(f"- **Prévision de demande** (articles/mois, erreur MAPE {d.get('demande_mape')}%) : "
                             + ", ".join(f"{p['period']} ≈ {int(p['qte'])}" for p in fc))
            lines.append(f"\n**Action** : sécuriser une 2ᵉ source d'approvisionnement pour réduire la "
                         f"dépendance à **{top[0].get('fournisseur', 'ce fournisseur')}** ; caler les commandes "
                         f"sur la prévision et anticiper les pics saisonniers.")
            lines.append("\n_Note : faute de données de stock dans l'ERP, il s'agit d'une analyse de la "
                         "demande et du risque fournisseur — pas d'une gestion de stock par référence._")

        else:
            # Performance générale
            lines.append("## 📈 Synthèse de performance\n")
            lines.append(f"- **CA TTC** : {fmt(kpis.get('ca_total_ttc'))}")
            lines.append(f"- **Croissance YoY** : {kpis.get('yoy_growth', 0):.1f}%")
            lines.append(f"- **Nb clients** : {kpis.get('nb_clients', 0)}")
            lines.append(f"- **Factures critiques** : {kpis.get('retards_critiques', 0)}")

        return "\n".join(lines)

    def _rag_answer(self, question: str) -> Optional[str]:
        """Répond à une question 'externe' via la base documentaire (RAG).
        Synthèse LLM si une clé est disponible, sinon extraits sourcés. None si rien de pertinent."""
        try:
            from rag.rag_engine import search as rag_search
        except Exception:
            return None
        try:
            hits = rag_search(question, k=4)
        except Exception:
            hits = []
        if not hits:
            return None

        context = "\n\n".join(f"[{h['source']}]\n{h['text']}" for h in hits)
        sources = ", ".join(sorted({h["source"] for h in hits}))

        # 1) Synthèse LLM si clé disponible
        if os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            try:
                from config.settings import get_llm
                llm = get_llm()
                prompt = (
                    "Tu es FinBot, copilote financier. Réponds en français, de façon concise et "
                    "structurée (Markdown), en te basant UNIQUEMENT sur les extraits de documents "
                    "ci-dessous. Si l'information n'y figure pas, dis-le clairement.\n\n"
                    f"## QUESTION\n{question}\n\n## EXTRAITS DE DOCUMENTS\n{context}\n\n"
                    "## RÉPONSE (cite les sources entre parenthèses)"
                )
                res = llm.invoke(prompt)
                txt = getattr(res, "content", str(res))
                if txt and "[Mode mock" not in txt:
                    return f"{txt.strip()}\n\n*Sources : {sources}*"
            except Exception:
                pass

        # 2) Repli sans LLM : extraits les plus pertinents, sourcés
        lines = ["## 📚 D'après votre base documentaire\n"]
        for h in hits[:3]:
            snippet = " ".join(h["text"].split())
            if len(snippet) > 340:
                snippet = snippet[:340] + "…"
            lines.append(f"- {snippet}\n  *(source : {h['source']})*")
        lines.append("\n_Réponse issue des documents (RAG). Ajoutez des fichiers dans `rag/documents/` "
                     "puis relancez `python -m rag.rag_engine build` pour enrichir la base._")
        return "\n".join(lines)

    def synthesize(
        self,
        filters: Dict[str, Any] | None = None,
        question: Optional[str] = None,
        history: List[Dict[str, str]] | None = None,
    ) -> Dict[str, Any]:
        """Mode hybride : routage interne (données ERP) + repli RAG pour les questions externes."""
        q = question or "Donne-moi la synthèse financière du moment, avec les actions prioritaires chiffrées."
        filters = filters or {}
        history = history or []
        out = self.run(filters, question=q)

        # Base documentaire RAG :
        #  - forcée si la question commence par "doc:" / "docs:" (échappatoire explicite)
        #  - sinon en repli automatique pour les questions 'externes' (hors données internes)
        ql = q.strip().lower()
        force_rag = ql.startswith("doc:") or ql.startswith("docs:")
        rag_query = q.split(":", 1)[1].strip() if force_rag else q
        if force_rag or not has_internal_theme(q):
            rag_text = self._rag_answer(rag_query)
            if rag_text:
                return {
                    "text": rag_text, "via": "rag",
                    "kpis": out["kpis"], "trace": out["trace"], "meta": out["meta"],
                }

        text = self._llm_text(q, out["kpis"], filters=filters, history=history)
        if not text:
            text = self._fallback_answer(q, out["kpis"], filters)
        return {
            "text": text,
            "via": "llm" if os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") else "regles",
            "kpis": out["kpis"],
            "trace": out["trace"],
            "meta": out["meta"],
        }


# Instance partagée (compatibilité : l'API importe `finance_agent`)
finance_agent = FinanceSupervisor()

