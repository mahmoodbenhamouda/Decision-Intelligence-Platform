"""Modèles ML du module Stock — démarche CRISP-DM complète."""

from typing import TYPE_CHECKING, Any

__all__ = [
    "build_demand_dataset", "FEATURES",
    "train_demand_models", "predict_demand", "load_demand_model",
    "train_stock_risk", "score_stock_risk",
]

if TYPE_CHECKING:  # pragma: no cover
    from .demand_features import FEATURES, build_demand_dataset
    from .demand_forecast import load_demand_model, predict_demand, train_demand_models
    from .stock_risk import score_stock_risk, train_stock_risk


def __getattr__(name: str) -> Any:
    """Import paresseux : évite de charger LightGBM/XGBoost au démarrage de l'API."""
    if name in ("build_demand_dataset", "FEATURES"):
        from . import demand_features
        return getattr(demand_features, name)
    if name in ("train_demand_models", "predict_demand", "load_demand_model"):
        from . import demand_forecast
        return getattr(demand_forecast, name)
    if name in ("train_stock_risk", "score_stock_risk"):
        from . import stock_risk
        return getattr(stock_risk, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
