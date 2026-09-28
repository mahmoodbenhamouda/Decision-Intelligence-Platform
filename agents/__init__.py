"""agents — la couche qui transforme des chiffres en constats lisibles.

- `copilote/` : le copilote FinBot (questions en langage naturel, base
  documentaire, LLM), organisé en graphe LangGraph : collecte → aiguillage →
  documents | rédaction | repli.
- `fleet/`    : la flotte d'agents spécialistes orchestrée par LangGraph
  (recouvrement, trésorerie, risque client, stock & approvisionnement,
  commercial), un arbitre, un volet fiabilité et un rédacteur.

Les deux ont la même forme — un état, des nœuds, un graphe, et un repli
séquentiel si LangGraph est absent. Aucun agent n'importe un modèle
directement : tous passent par `ml_engine.passerelle`, qui consulte le registre
avant de servir un résultat.
"""
