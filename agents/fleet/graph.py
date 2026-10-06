"""Orchestrateur de la flotte."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .nodes import (
    agent_commercial,
    agent_recouvrement,
    agent_risque,
    agent_stock_approvisionnement,
    agent_tresorerie,
    arbitre,
    collecte_interne,
    collecte_modeles,
    fiabilite_modeles,
    redacteur,
)


_COLLECTEURS = (collecte_interne, collecte_modeles)

_SPECIALISTES = {
    "agent_recouvrement": agent_recouvrement,
    "agent_tresorerie": agent_tresorerie,
    "agent_risque": agent_risque,
    "agent_stock_approvisionnement": agent_stock_approvisionnement,
    "agent_commercial": agent_commercial,
}


_COMPILED = None


def build_graph():
    from langgraph.graph import END, START, StateGraph
    from .state import FleetState

    g = StateGraph(FleetState)
    g.add_node("collecte_interne", collecte_interne)
    g.add_node("collecte_modeles", collecte_modeles)
    for name, fn in _SPECIALISTES.items():
        g.add_node(name, fn)
    g.add_node("fiabilite_modeles", fiabilite_modeles)
    g.add_node("arbitre", arbitre)
    g.add_node("redacteur", redacteur)

    g.add_edge(START, "collecte_interne")
    g.add_edge("collecte_interne", "collecte_modeles")
    for name in _SPECIALISTES:
        g.add_edge("collecte_modeles", name)
        g.add_edge(name, "arbitre")
    g.add_edge("collecte_modeles", "fiabilite_modeles")
    g.add_edge(["arbitre", "fiabilite_modeles"], "redacteur")
    g.add_edge("redacteur", END)
    return g.compile()


def _run_sequential(init: Dict[str, Any]) -> Dict[str, Any]:
    state: Dict[str, Any] = dict(init)

    def merge(update: Dict[str, Any]) -> None:
        for k, v in (update or {}).items():
            if k in ("findings", "trace"):
                state[k] = state.get(k, []) + v
            else:
                state[k] = v

    for collecteur in _COLLECTEURS:
        merge(collecteur(state))
    for fn in _SPECIALISTES.values():
        merge(fn(state))
    merge(fiabilite_modeles(state))
    merge(arbitre(state))
    merge(redacteur(state))
    return state


def run_briefing(filters: Optional[Dict[str, Any]] = None,
                 question: Optional[str] = None) -> Dict[str, Any]:
    """Exécute la flotte et renvoie le briefing, les constats, la trace et le volet fiabilité (absent…"""
    init: Dict[str, Any] = {
        "filters": filters or {}, "question": question or "",
        "findings": [], "trace": [],
    }
    engine = "langgraph"
    try:
        global _COMPILED
        if _COMPILED is None:
            _COMPILED = build_graph()
        result = _COMPILED.invoke(init)
    except Exception:
        engine = "séquentiel (repli)"
        result = _run_sequential(init)

    return {
        "engine": engine,
        "briefing": result.get("briefing", ""),
        "findings": result.get("findings", []),
        "trace": result.get("trace", []),
        "fiabilite": result.get("fiabilite"),
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    out = run_briefing()
    print(f"[flotte] moteur : {out['engine']}\n")
    for t in out["trace"]:
        print(f"  · {t['agent']:28} [{t['status']}] {t.get('detail','')}")
    print("\n" + "=" * 70 + "\n")
    print(out["briefing"])
