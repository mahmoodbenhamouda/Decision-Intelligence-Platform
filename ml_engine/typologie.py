"""
ml_engine/typologie.py
======================
Typologie des établissements clients, déduite de la raison sociale.

L'ERP ne dit pas si un client est public ou privé : seule sa raison sociale
le laisse deviner. Cette déduction était écrite trois fois (deux modèles de
demande et le radar financier), avec des listes différentes. Elle vit
désormais ici, et une seule fois :

* les modèles de demande l'utilisent comme variable (un hôpital public achète
  par marché annuel, un laboratoire privé au fil de l'eau) ;
* le radar financier l'utilise pour isoler l'exposition des établissements de
  santé publics, qui paient avec des délais structurellement longs.

La comparaison se fait sur la raison sociale en MAJUSCULES, par inclusion de
sous-chaîne : `est_hopital_public` (Python) et `condition_sql_hopital_public`
(DuckDB) donnent le même verdict pour le même nom — un test le vérifie.
"""

from __future__ import annotations

from typing import Optional

#: Mots-clés d'un établissement de santé public (hôpitaux, CHU, hôpital
#: militaire, instituts publics de santé). « C.H.U » est écrit avec ses points
#: dans l'ERP : « CHU » seul ne le reconnaîtrait pas.
#: L'ordre et le contenu sont ceux des modèles de demande déjà entraînés : les
#: modifier changerait leurs variables d'entrée.
MOTS_HOPITAL_PUBLIC = ("C.H.U", "CHU", "HOPITAL", "HÔPITAL", "HOSPITAL",
                       "MILITAIRE", "INSTITUT", "CENTRE HOSPITALIER")


def est_hopital_public(nom: Optional[str]) -> bool:
    """Vrai si la raison sociale désigne un établissement de santé public."""
    u = (nom or "").upper()
    return any(k in u for k in MOTS_HOPITAL_PUBLIC)


def condition_sql_hopital_public(colonne: str = "client_name") -> str:
    """Même règle, en SQL : `upper(<colonne>) LIKE '%<mot>%'` pour chaque mot.

    Aucun mot-clé ne contient `%`, `_` ni apostrophe : la chaîne est sûre telle
    quelle, et `LIKE` y a le sens d'une simple inclusion.
    """
    return "(" + " OR ".join(f"upper({colonne}) LIKE '%{k}%'"
                             for k in MOTS_HOPITAL_PUBLIC) + ")"
