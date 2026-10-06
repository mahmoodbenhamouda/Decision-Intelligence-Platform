"""Les nœuds du graphe du copilote."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from agents.copilote import llm, outils
from agents.copilote.documents import reponse_documentaire
from agents.copilote.intention import (classer, detect_theme, has_internal_theme,
                                       requete_documentaire)
from agents.copilote.prompt import construire_prompt
from agents.copilote.repli import reponse_deterministe
from agents.copilote.state import EtatCopilote


def _etape(tool: str, label: str, status: str = "ok", t0: float | None = None) -> Dict[str, Any]:
    return {"tool": tool, "label": label, "status": status,
            "ms": int((time.time() - t0) * 1000) if t0 else 0}


def collecte(etat: EtatCopilote) -> Dict[str, Any]:
    filters = etat.get("filters") or {}
    trace: List[Dict[str, Any]] = []

    mode, scope = classer(filters, etat.get("question"))
    trace.append(_etape("router", f"Intention : {mode} · périmètre {scope}"))

    t0 = time.time()
    kpis = outils.indicateurs(filters)
    trace.append(_etape("sql_kpis", "Indicateurs calculés sur vos factures", t0=t0))

    if scope == "client":
        trace.append(_etape("router", "Décision : périmètre client → analyses inter-clients "
                                      "désactivées", status="info"))

    if kpis.get("risk_model_active"):
        trace.append(_etape("ml_risque", f"Outil ML — risque crédit "
                                         f"({kpis.get('nb_clients_risque_predit')} clients à risque élevé)"))
    else:
        trace.append(_etape("ml_risque", "Décision : modèle de risque non entraîné → étape ignorée",
                            status="skip"))

    monthly = kpis.get("monthly_sales") or []
    if len(monthly) >= 3:
        t0 = time.time()
        kpis["forecast_next"] = outils.prevision_lineaire(monthly)
        trace.append(_etape("prevision", "Outil Prévision — projection du CA sur 3 mois", t0=t0))
    else:
        kpis["forecast_next"] = []
        trace.append(_etape("prevision", "Décision : historique < 3 mois → prévision non fiable, "
                                         "ignorée", status="skip"))

    trace.append(_etape("anomalies", f"Outil Anomalies — {kpis.get('anomalies_detectees', 0)} détectée(s)"))

    try:
        radar = outils.radar(filters)
        kpis["finance_radar"] = radar
        if radar:
            trace.append(_etape("radar", f"Radar financier — {len(radar)} action(s) ; "
                                         f"priorité : {radar[0]['titre']}", status="info"))
    except Exception:
        kpis["finance_radar"] = []

    trace.append(_etape("synthese", "Assemblage du tableau de bord décisionnel"))
    return {"mode": mode, "scope": scope, "kpis": kpis, "trace": trace}


def aiguillage(etat: EtatCopilote) -> Dict[str, Any]:
    """Base documentaire si la question commence par « doc: » (échappatoire explicite) ou ne relève…"""
    q = etat["question"]
    force, requete = requete_documentaire(q)
    documentaire = force or not has_internal_theme(q)
    themes = detect_theme(q)
    destination = "base documentaire" if documentaire else "données du périmètre"
    return {"themes": themes, "documentaire": documentaire, "requete_documentaire": requete,
            "trace": [_etape("aiguillage", f"Thèmes : {', '.join(themes)} → {destination}",
                             status="info")]}


def apres_aiguillage(etat: EtatCopilote) -> str:
    return "documents" if etat.get("documentaire") else "redaction"


def documents(etat: EtatCopilote) -> Dict[str, Any]:
    t0 = time.time()
    texte = reponse_documentaire(etat["requete_documentaire"])
    if texte:
        return {"texte": texte, "via": "rag",
                "trace": [_etape("documents", "Réponse tirée de la base documentaire", t0=t0)]}
    return {"trace": [_etape("documents", "Base documentaire : rien de pertinent → données",
                             status="skip", t0=t0)]}


def apres_documents(etat: EtatCopilote) -> str:
    return "fin" if etat.get("texte") else "redaction"


def redaction(etat: EtatCopilote) -> Dict[str, Any]:
    if not llm.cle_disponible():
        return {"trace": [_etape("redaction", "Aucune clé de modèle de langage → règles",
                                 status="skip")]}
    t0 = time.time()
    try:
        prompt = construire_prompt(etat["question"], etat.get("kpis") or {},
                                   etat.get("filters") or {}, etat.get("history") or [])
        texte = llm.rediger(prompt)
    except Exception:
        texte = None
    if texte:
        return {"texte": texte, "via": "llm",
                "trace": [_etape("redaction", "Réponse du modèle de langage, montants vérifiés",
                                 t0=t0)]}
    return {"trace": [_etape("redaction", "Modèle indisponible ou montant non traçable → règles",
                             status="skip", t0=t0)]}


def apres_redaction(etat: EtatCopilote) -> str:
    return "fin" if etat.get("texte") else "repli"


def repli(etat: EtatCopilote) -> Dict[str, Any]:
    texte = reponse_deterministe(etat["question"], etat.get("kpis") or {},
                                 etat.get("filters") or {})
    return {"texte": texte, "via": "regles",
            "trace": [_etape("repli", "Réponse déterministe du thème")]}
