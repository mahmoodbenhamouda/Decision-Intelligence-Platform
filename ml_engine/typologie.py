"""Typologie des établissements clients, déduite de la raison sociale."""

from __future__ import annotations

from typing import Optional

MOTS_HOPITAL_PUBLIC = ("C.H.U", "CHU", "HOPITAL", "HÔPITAL", "HOSPITAL",
                       "MILITAIRE", "INSTITUT", "CENTRE HOSPITALIER")


def est_hopital_public(nom: Optional[str]) -> bool:
    """Vrai si la raison sociale désigne un établissement de santé public."""
    u = (nom or "").upper()
    return any(k in u for k in MOTS_HOPITAL_PUBLIC)


def condition_sql_hopital_public(colonne: str = "client_name") -> str:
    """Même règle, en SQL : `upper(<colonne>) LIKE '%<mot>%'` pour chaque mot."""
    return "(" + " OR ".join(f"upper({colonne}) LIKE '%{k}%'"
                             for k in MOTS_HOPITAL_PUBLIC) + ")"
