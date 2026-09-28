"""
Copilote FinBot — organisé comme la flotte : état, nœuds, graphe LangGraph.

    state.py         état partagé (EtatCopilote)
    intention.py     mode, périmètre, thèmes de la question, aiguillage documentaire
    glossaire.py     définitions financières citées telles quelles
    outils.py        indicateurs, radar, prévision, stock, fournisseurs
    contexte.py      contexte PERTINENT pour la question (par thème, via la passerelle)
    prompt.py        les prompts, à un seul endroit
    verification.py  aucun montant cité qui ne vienne du contexte
    llm.py           appels au modèle de langage, replis de modèle
    documents.py     réponses tirées de la base documentaire (RAG)
    repli.py         réponses déterministes par thème
    fichier.py       réponse sur un fichier joint
    noeuds.py        les nœuds du graphe
    graph.py         le graphe, le repli séquentiel, la classe Copilote

Voir docs/ARCHITECTURE_AGENTS.md.
"""

from agents.copilote.fichier import analyser_fichier
from agents.copilote.graph import Copilote, copilote

__all__ = ["Copilote", "copilote", "analyser_fichier"]
