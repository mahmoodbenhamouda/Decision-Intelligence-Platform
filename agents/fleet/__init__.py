"""
Flotte multi-agents (LangGraph) — cellule d'intelligence décisionnelle.

Un orchestrateur coordonne des agents spécialisés qui fusionnent les données
internes (ERP / entrepôt DuckDB) et externes (veille : appels d'offres, change,
macro, actualités) pour produire un briefing décisionnel priorisé et chiffré.

Import : `from agents.fleet.graph import run_briefing`
(graph n'est pas importé ici pour éviter le RuntimeWarning de double-chargement
lorsqu'on lance `python -m agents.fleet.graph`.)
"""
