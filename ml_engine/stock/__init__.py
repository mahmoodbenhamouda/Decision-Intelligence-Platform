"""Domaine stock — quatre modules sur données RÉELLES, un module simulé en repli."""

from typing import TYPE_CHECKING, Any

__all__ = ["generate_stock", "compute_stock_kpis", "stock_available",
           "classer_clients_par_risque", "SIMULATION_SEED"]

if TYPE_CHECKING:  # pragma: no cover
    from .generator import SIMULATION_SEED, generate_stock
    from .stock_engine import (classer_clients_par_risque, compute_stock_kpis,
                               stock_available)


def __getattr__(name: str) -> Any:
    """Import paresseux : évite le double chargement des sous-modules lors d'un `python -m…"""
    if name in ("generate_stock", "SIMULATION_SEED"):
        from . import generator
        return getattr(generator, name)
    if name in ("compute_stock_kpis", "stock_available", "classer_clients_par_risque"):
        from . import stock_engine
        return getattr(stock_engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
