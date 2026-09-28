"""
Orchestrateur de la flotte.

Construit un graphe LangGraph :

                                                  ┌─> agent_recouvrement ─────────────┐
                                                  ├─> agent_tresorerie ───────────────┤
  START ─> collecte_interne ─> collecte_modeles ──┼─> agent_risque ───────────────────┼─> arbitre ─┐
                                        │         ├─> agent_stock_approvisionnement ──┤           │
                                        │         └─> agent_commercial ───────────────┘           ├─> redacteur ─> END
                                        └───────────> fiabilite_modeles ──────────────────────────┘

Deux collecteurs — les indicateurs de l'entrepôt ERP, puis TOUS les modèles
interrogés par la passerelle du registre — puis 5 agents spécialistes en
parallèle (fan-out), un arbitre qui hiérarchise leurs constats, et le rédacteur.
Si `langgraph` n'est pas installé, un repli séquentiel exécute exactement les
mêmes nœuds dans le même ordre.

Les cinq spécialistes n'ont pas la même nature, et le schéma ne le cache plus :

  Modèles appris
    Commercial        conversion des devis · érosion de marge · recommandation
                      (LightGBM servi, Wide & Deep mesuré en challenger)
    Risque client     décrochage (régression logistique) × segmentation (KMeans)
    Trésorerie        échéancier à un mois (carnet, MAPE 1,3 %)
  Règle servie (elle a battu le modèle appris)
    Recouvrement      conditions de crédit (AUC 0,92 hors période)
  Déterministe et statistique, assumé comme tel
    Stock & Approvisionnement
                      flux réels reconstruits des factures · dépendance
                      fournisseur · demande (médiane mobile) · demande par
                      référence (médiane 12 mois servie : elle a battu LightGBM
                      au test). Réappro et fin de vie refusés par le registre,
                      risque stock retiré.

Le volet fiabilité n'est pas un spécialiste
-------------------------------------------
`fiabilite_modeles` lit le registre (métriques, refus, dérive PSI) : il ne
propose aucune action de gestion, il qualifie celles des autres. Il part donc de
`collecte_modeles` en parallèle des spécialistes, écrit dans sa propre clé
d'état `fiabilite` — jamais dans `findings`, que l'arbitre classe — et rejoint
le rédacteur par une JOINTURE : `add_edge(["arbitre", "fiabilite_modeles"],
"redacteur")`. Le rédacteur attend les deux et ne s'exécute qu'une fois. Deux
arêtes séparées l'auraient déclenché deux fois, une par branche.

Pourquoi un arbitre, et pourquoi APRÈS le fan-in
------------------------------------------------
Chaque spécialiste déclare la sévérité de son propre constat selon ses critères
métier. Un « haute » de l'agent Stock et un « haute » de l'agent Recouvrement ne
mesurent donc pas la même chose : le rédacteur les triait à égalité, et l'ordre
entre eux était arbitraire.

Or l'arbitrage inter-domaines — relancer un débiteur ou déstocker ? — est
précisément la question qu'aucun agent ne peut trancher seul, puisqu'aucun ne
voit les constats des autres. Elle ne peut être traitée qu'après le fan-in, par
un nœud qui les voit tous.

L'arbitre ne produit aucun score global de santé : il ordonne, il ne résume pas.

Une lecture croisée, hors graphe
--------------------------------
`agent_tresorerie` consulte directement le module de stock, sans passer par une
arête. Le parallélisme empêche en effet un agent de lire le résultat d'un autre :
tous partent du même état initial.

Ce rapprochement est nécessaire parce que **du stock dormant est de la trésorerie
gelée**. Sans lui, la flotte produisait deux constats juxtaposés — un besoin de
financement d'un côté, un montant immobilisé de l'autre — que le lecteur devait
rapprocher lui-même. C'est la trésorerie qui subit l'effet du surstock, donc c'est
elle qui porte le constat.

Le sens de lecture reste unique (trésorerie → stock) : aucune boucle n'est créée,
et l'ordre d'exécution des agents demeure sans importance.

Périmètre : la plateforme est **entièrement interne à l'ERP**. La veille externe
(appels d'offres, taux de change) a été retirée — aucune dépendance réseau,
aucune source dont la qualité ne pourrait être auditée.
"""

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
    "agent_stock_approvisionnement": agent_stock_approvisionnement,  # déterministe + statistique
    "agent_commercial": agent_commercial,
}


_COMPILED = None


# ── Construction du graphe LangGraph ────────────────────────────────────────
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
        g.add_edge("collecte_modeles", name)   # fan-out (parallèle)
        g.add_edge(name, "arbitre")             # fan-in
    # Le volet fiabilité part du registre collecté, en parallèle des
    # spécialistes, et contourne l'arbitre.
    g.add_edge("collecte_modeles", "fiabilite_modeles")
    # JOINTURE : le rédacteur attend l'arbitre ET le volet fiabilité, et ne
    # s'exécute qu'une fois.
    g.add_edge(["arbitre", "fiabilite_modeles"], "redacteur")
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

    for collecteur in _COLLECTEURS:
        merge(collecteur(state))
    for fn in _SPECIALISTES.values():
        merge(fn(state))
    merge(fiabilite_modeles(state))
    merge(arbitre(state))
    merge(redacteur(state))
    return state



# ── API publique ────────────────────────────────────────────────────────────
def run_briefing(filters: Optional[Dict[str, Any]] = None,
                 question: Optional[str] = None) -> Dict[str, Any]:
    """Exécute la flotte et renvoie le briefing, les constats, la trace et le
    volet fiabilité (absent sur un périmètre client : le registre n'y est pas
    collecté)."""
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
