"""
Domaine stock — quatre modules sur données RÉELLES, un module simulé en repli.

Ce que contient ce paquet
=========================
    flux_reels.py             position reconstruite des factures (AUCUNE simulation)
    positions_historiques.py  la même position, mois par mois
    reappro_model.py          modèle appris sur ces positions réelles
    nomenclature.py           classement produit — autorité unique, mesurée
    generator.py / stock_engine.py   le module (s,S) SIMULÉ, désormais en REPLI

Les chiffres servis à l'utilisateur viennent des quatre premiers. Le module
simulé ne subsiste que si la table `stock_flux_reel` n'a pas été matérialisée, et
pour alimenter les variables de position des deux modèles de `ml_engine/models/`.
Tout l'avertissement ci-dessous ne concerne donc plus que ce volet de repli.

⚠️ AVERTISSEMENT MÉTHODOLOGIQUE — volet simulé uniquement
=========================================================
L'export ERP d'Overlyne ne contient **aucune donnée de stock** (vérifié sur les
32 fichiers : aucune colonne `STOCK`, `QTESTOCK`, `DISPO`, `INVENTAIRE`…).

Ce module **SIMULE** un stock, il ne le mesure pas. La simulation est :
  - **calibrée sur la demande RÉELLE** (volumes facturés par produit et par mois,
    6 ans d'historique, 1 973 produits) ;
  - **régie par un modèle explicite** (politique (s,S), délai fournisseur,
    stock de sécurité, péremption) documenté dans `docs/STOCK_SIMULE.md` ;
  - **reproductible** (graine fixée) ;
  - **marquée** : chaque enregistrement porte `is_simulated = TRUE`, chaque
    réponse d'API porte le drapeau, et l'interface affiche un bandeau.

Objectif : démontrer la chaîne complète de gestion de stock (indicateurs,
alertes, agent décisionnel) sur des données plausibles — **jamais** faire passer
ces chiffres pour des observations.

    from ml_engine.stock import generate_stock, compute_stock_kpis
"""

from typing import TYPE_CHECKING, Any

__all__ = ["generate_stock", "compute_stock_kpis", "stock_available",
           "classer_clients_par_risque", "SIMULATION_SEED"]

if TYPE_CHECKING:  # pragma: no cover
    from .generator import SIMULATION_SEED, generate_stock
    from .stock_engine import (classer_clients_par_risque, compute_stock_kpis,
                               stock_available)


def __getattr__(name: str) -> Any:
    """Import paresseux : évite le double chargement des sous-modules lors d'un
    `python -m ml_engine.stock.generator` (RuntimeWarning de runpy)."""
    if name in ("generate_stock", "SIMULATION_SEED"):
        from . import generator
        return getattr(generator, name)
    if name in ("compute_stock_kpis", "stock_available", "classer_clients_par_risque"):
        from . import stock_engine
        return getattr(stock_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
