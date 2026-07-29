"""ML Engine package — imports PARESSEUX (lazy).

Importer `ml_engine.analytics.kpi_engine` ne doit plus charger tout le pipeline
ML (et ses phases Optuna/SHAP). Les noms `MLEngine` / `run_advanced_pipeline`
restent accessibles à la demande via `__getattr__`.
"""

__all__ = ["MLEngine", "run_advanced_pipeline"]


def __getattr__(name):
    if name in __all__:
        from ml_engine.pipeline import MLEngine, run_advanced_pipeline
        return {"MLEngine": MLEngine, "run_advanced_pipeline": run_advanced_pipeline}[name]
    raise AttributeError(f"module 'ml_engine' has no attribute '{name}'")
