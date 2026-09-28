"""
api/services/rapport.py
=======================
Synthèse écrite déterministe (« En bref » + « Action prioritaire »).

C'est le texte affiché quand aucun LLM n'est disponible : il ne dépend que des
indicateurs et suit des règles fixes, donc il est toujours exact.
"""

from __future__ import annotations


def format_money(value):
    if value is None:
        return "N/A"
    value = float(value)
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f} M DT"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f} K DT"
    return f"{value:.2f} DT"


def build_dynamic_report(kpis: dict) -> str:
    """Synthèse en Markdown, calculée sur les seuls indicateurs."""
    top_clients = kpis.get("top_clients") or []

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

