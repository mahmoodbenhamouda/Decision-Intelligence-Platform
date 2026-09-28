"""
agents/copilote/graph.py
========================
Orchestration du copilote FinBot, sur le modèle de la flotte (`agents/fleet/`) :
un état partagé, des nœuds, un graphe LangGraph — et un repli séquentiel qui
exécute exactement les mêmes nœuds si LangGraph n'est pas installé.

    START ─> collecte ─> aiguillage ─┬─> documents ─┬───────────────> END
                                     │              └─> redaction ─┬─> END
                                     └────────────────> redaction ─┤
                                                                   └─> repli ─> END

* **collecte** exécute la chaîne d'outils du tableau de bord (indicateurs,
  risque ML, prévision, anomalies, radar). C'est aussi, seule, la réponse de
  `tableau_de_bord()`.
* **aiguillage** détecte les thèmes et décide : base documentaire (question
  préfixée « doc: », ou sans thème interne) ou données du périmètre.
* **documents**, **redaction**, **repli** : trois sources de réponse, essayées
  dans cet ordre ; la première qui répond termine le graphe. `via` dit
  laquelle a répondu.

Le périmètre client est déjà imposé par l'API (`api/services/perimetre.py`) ;
le copilote le respecte dans chaque contexte qu'il construit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agents.copilote.noeuds import (aiguillage, apres_aiguillage, apres_documents,
                                    apres_redaction, collecte, documents, redaction,
                                    repli)
from agents.copilote.state import EtatCopilote

QUESTION_PAR_DEFAUT = ("Donne-moi la synthèse financière du moment, avec les actions "
                       "prioritaires chiffrées.")

_COMPILE = None


def build_graph():
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(EtatCopilote)
    g.add_node("collecte", collecte)
    g.add_node("aiguillage", aiguillage)
    g.add_node("documents", documents)
    g.add_node("redaction", redaction)
    g.add_node("repli", repli)

    g.add_edge(START, "collecte")
    g.add_edge("collecte", "aiguillage")
    g.add_conditional_edges("aiguillage", apres_aiguillage,
                            {"documents": "documents", "redaction": "redaction"})
    g.add_conditional_edges("documents", apres_documents,
                            {"fin": END, "redaction": "redaction"})
    g.add_conditional_edges("redaction", apres_redaction, {"fin": END, "repli": "repli"})
    g.add_edge("repli", END)
    return g.compile()


def _run_sequential(init: Dict[str, Any]) -> Dict[str, Any]:
    """Mêmes nœuds, même ordre, mêmes décisions, sans LangGraph."""
    state: Dict[str, Any] = dict(init)

    def merge(update: Dict[str, Any]) -> None:
        for k, v in (update or {}).items():
            state[k] = state.get(k, []) + v if k == "trace" else v

    merge(collecte(state))
    merge(aiguillage(state))
    suivant = apres_aiguillage(state)
    if suivant == "documents":
        merge(documents(state))
        suivant = apres_documents(state)
    if suivant == "redaction":
        merge(redaction(state))
        if apres_redaction(state) == "repli":
            merge(repli(state))
    return state


class Copilote:
    """Le copilote FinBot : tableau de bord commenté et questions en langage naturel."""

    # Identité renvoyée avec le tableau de bord (`agent` dans la réponse de l'API).
    name = "Agent Finance"
    role = "superviseur agentique (routage déterministe + LLM hybride thématique)"
    version = "3.0"
    tools = ["router", "sql_kpis", "ml_risque", "prevision", "anomalies", "synthese"]

    @property
    def meta(self) -> Dict[str, Any]:
        return {"name": self.name, "role": self.role, "version": self.version,
                "tools": self.tools}

    def tableau_de_bord(self, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Indicateurs du périmètre et trace de la chaîne d'outils."""
        out = collecte({"filters": filtres or {}, "question": ""})
        return {"kpis": out["kpis"], "trace": out["trace"], "mode": out["mode"],
                "scope": out["scope"], "meta": self.meta}

    def repondre(self, filtres: Optional[Dict[str, Any]] = None,
                 question: Optional[str] = None,
                 historique: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        """Réponse à une question (ou synthèse du moment si elle est vide)."""
        init: Dict[str, Any] = {"filters": filtres or {},
                                "question": question or QUESTION_PAR_DEFAUT,
                                "history": historique or [], "trace": []}
        moteur = "langgraph"
        try:
            global _COMPILE
            if _COMPILE is None:
                _COMPILE = build_graph()
            etat = _COMPILE.invoke(init)
        except Exception:
            moteur = "séquentiel (repli)"
            etat = _run_sequential(init)
        return {"text": etat.get("texte") or "", "via": etat.get("via", "regles"),
                "kpis": etat.get("kpis") or {}, "trace": etat.get("trace") or [],
                "meta": {**self.meta, "moteur": moteur}}


#: Instance partagée, lue par l'API (`api/core/moteurs.py`).
copilote = Copilote()
