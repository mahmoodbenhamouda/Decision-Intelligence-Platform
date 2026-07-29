"""
Orchestrateur de la flotte.

Construit un graphe LangGraph :

        ┌─> collecte_interne ─> veille_externe ─┬─> agent_opportunites ─┐
  START ┘                                       ├─> agent_recouvrement ─┤
                                                ├─> agent_tresorerie  ──┼─> redacteur ─> END
                                                └─> agent_risque      ──┘

Les 4 agents spécialistes s'exécutent en parallèle (fan-out) puis le rédacteur
agrège leurs constats (fan-in). Si `langgraph` n'est pas installé, un repli
séquentiel exécute exactement les mêmes agents dans l'ordre.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .nodes import (
    agent_approvisionnement,
    agent_opportunites,
    agent_recouvrement,
    agent_risque,
    agent_tresorerie,
    collecte_interne,
    redacteur,
    veille_externe,
)

_SPECIALISTES = {
    "agent_opportunites": agent_opportunites,
    "agent_recouvrement": agent_recouvrement,
    "agent_tresorerie": agent_tresorerie,
    "agent_risque": agent_risque,
    "agent_approvisionnement": agent_approvisionnement,
}

_COMPILED = None


# ── Construction du graphe LangGraph ────────────────────────────────────────
def build_graph():
    from langgraph.graph import END, START, StateGraph
    from .state import FleetState

    g = StateGraph(FleetState)
    g.add_node("collecte_interne", collecte_interne)
    g.add_node("veille_externe", veille_externe)
    for name, fn in _SPECIALISTES.items():
        g.add_node(name, fn)
    g.add_node("redacteur", redacteur)

    g.add_edge(START, "collecte_interne")
    g.add_edge("collecte_interne", "veille_externe")
    for name in _SPECIALISTES:
        g.add_edge("veille_externe", name)   # fan-out (parallèle)
        g.add_edge(name, "redacteur")        # fan-in
    g.add_edge("redacteur", END)
    return g.compile()


# ── Repli séquentiel (si langgraph indisponible) ────────────────────────────
def _run_sequential(init: Dict[str, Any]) -> Dict[str, Any]:
    state: Dict[str, Any] = dict(init)

    def merge(update: Dict[str, Any]) -> None:
        for k, v in (update or {}).items():
            if k in ("findings", "trace"):
                state[k] = state.get(k, []) + v
            else:
                state[k] = v

    merge(collecte_interne(state))
    merge(veille_externe(state))
    for fn in _SPECIALISTES.values():
        merge(fn(state))
    merge(redacteur(state))
    return state


# ── API publique ────────────────────────────────────────────────────────────
def run_briefing(filters: Optional[Dict[str, Any]] = None,
                 question: Optional[str] = None) -> Dict[str, Any]:
    """Exécute la flotte et renvoie le briefing + les constats + la trace."""
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
    }


# ── CLI de démonstration ────────────────────────────────────────────────────
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
