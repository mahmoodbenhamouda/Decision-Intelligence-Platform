"""D'où vient la marge brute : décomposition par catégorie, par produit, dans le temps.

Contrairement aux panneaux de prévision, cette analyse est un COMPTAGE de ce qui
a été facturé. Aucun modèle n'y intervient, donc la règle de portée des filtres
(`ml_engine.portee`) ne s'applique pas : tous les filtres du tableau de bord
sont légitimes ici, y compris une période passée ou une sélection de clients.

La RÉDACTION destinée au directeur vit ici et non dans `ml_engine` : un module
de calcul ne porte pas de tables de phrases (garde-fou de
`tests/test_explication.py`). Le moteur renvoie des codes et des nombres, cette
couche les met en mots.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.services.serialisation import json_safe
from ml_engine.analytics import marge_decomposee as md

#: Ce que chaque catégorie pèse dans la décision du directeur.
#:
#: Overlyne distribue du diagnostic in vitro : l'automate consomme les réactifs
#: qu'elle vend. Ces phrases disent pourquoi un taux de 7 % sur l'équipement
#: n'est pas une anomalie à corriger mais une stratégie à vérifier.
ROLE_CATEGORIE: Dict[str, str] = {
    "reactif": ("Consommables récurrents. C'est la marge qui fait vivre "
                "l'entreprise, et elle suit le parc installé."),
    "equipement": ("Automates et analyseurs. Vendus à faible marge pour "
                   "installer le parc : la rentabilité vient ensuite, par les "
                   "réactifs que ces machines consomment."),
    "service": ("Maintenance, SAV et formation. Peu de volume, presque pas de "
                "coût de revient : la marge y est mécaniquement élevée."),
    "autre": ("Familles résiduelles du catalogue, hors activité de "
              "diagnostic. "
              "Moins de 1 % du chiffre d'affaires."),
}


def decomposition(limite: int = md.N_PRODUITS,
                  filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Marge brute décomposée sur le périmètre filtré, rôles compris."""
    n = max(3, min(50, limite))
    try:
        data = md.analyser(filtres, limite=n)
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}

    for c in (data.get("par_categorie") or {}).get("categories") or []:
        c["role"] = ROLE_CATEGORIE.get(c.get("code"), "")
    return json_safe(data)
