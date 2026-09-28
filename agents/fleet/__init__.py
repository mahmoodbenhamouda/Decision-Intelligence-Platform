"""
Flotte multi-agents (LangGraph) — cellule d'intelligence décisionnelle.

Deux collecteurs (indicateurs de l'entrepôt, sorties des modèles via la
passerelle du registre), cinq spécialistes en parallèle, un arbitre qui
hiérarchise leurs constats, un volet fiabilité et un rédacteur produisent un
briefing décisionnel priorisé et chiffré. Données exclusivement internes à
l'ERP.

Import : `from agents.fleet.graph import run_briefing`
(graph n'est pas importé ici pour éviter le RuntimeWarning de double-chargement
lorsqu'on lance `python -m agents.fleet.graph`.)
"""
