"""
ml_engine/phases/phase6_optuna.py
=================================
Phase 6 : Optimisation bayésienne des hyperparamètres (Optuna).
Extrait de ml_advanced_pipeline.py — refactorisé en module indépendant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import optuna
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

try:
    from xgboost import XGBRegressor
    from sklearn.metrics import mean_squared_error
    from sklearn.model_selection import KFold
    import joblib
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


def optimize_hyperparameters(
    X_train: np.ndarray,
    y_train: np.ndarray,
    task: str = "regression",
    n_trials: int = 30,
    timeout: int = 120,
    output_dir: Optional[Path] = None,
    time_aware: bool = False,
) -> Dict[str, Any]:
    print("\n  [Phase 6] Optimisation des hyperparamètres (Optuna)...")

    if not HAS_OPTUNA or not HAS_XGB:
        return {"error": "Optuna ou XGBoost non installés"}

    report: Dict[str, Any] = {}
    
    def objective(trial):
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 50, 300),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        }
        model = XGBRegressor(random_state=42, n_jobs=-1, **params)
        kf = KFold(n_splits=3, shuffle=True, random_state=42)
        scores = []
        for train_idx, val_idx in kf.split(X_train):
            model.fit(X_train[train_idx], y_train[train_idx])
            pred = model.predict(X_train[val_idx])
            scores.append(mean_squared_error(y_train[val_idx], pred))
        return np.mean(scores)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, timeout=timeout)
    
    best_params = study.best_params
    report["best_params"] = best_params
    report["best_score_mse"] = study.best_value
    
    # Train best model
    best_model = XGBRegressor(random_state=42, n_jobs=-1, **best_params)
    best_model.fit(X_train, y_train)
    
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(best_model, output_dir / f"{task}_best.joblib")
        report["saved_model"] = f"{task}_best.joblib"
        
    return report
