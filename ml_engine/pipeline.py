"""
ml_engine/pipeline.py
=====================
Orchestrateur principal du ML Engine — 9 phases.
Coordonne toutes les phases et expose une API unifiée.

Usage :
    from ml_engine.pipeline import run_advanced_pipeline, MLEngine
    engine = MLEngine()
    results = engine.run(warehouse)
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ml_engine.phases.phase1_data_quality import validate_data_quality
from ml_engine.phases.phase2_feature_eng import build_timeseries_features

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer): return int(obj)
    if isinstance(obj, np.floating): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, pd.Timestamp): return str(obj)
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)): return None
    return obj


def _save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(data), f, indent=2, ensure_ascii=False, default=str)


class MLEngine:
    """
    Moteur ML principal — encapsule les 9 phases du pipeline.
    
    Utilisé par le MLAgent comme backend analytique.
    Chaque phase peut être exécutée individuellement ou en pipeline complet.
    
    Exemple :
        engine = MLEngine(data_dir=Path("data_pfe"), models_dir=Path("models"))
        results = engine.run(warehouse, phases=[1, 2, 3, 4, 5])
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        models_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        n_cv: int = 5,
        n_optuna_trials: int = 30,
        run_dl: bool = True,
        run_optuna: bool = True,
        run_shap: bool = True,
    ):
        from config.settings import settings
        self.data_dir = data_dir or settings.data_dir
        self.models_dir = models_dir or settings.models_dir
        self.output_dir = output_dir or settings.reports_dir
        self.n_cv = n_cv
        self.n_optuna_trials = n_optuna_trials
        self.run_dl = run_dl
        self.run_optuna = run_optuna
        self.run_shap = run_shap
        self._results: Dict[str, Any] = {}
        self._ts_enriched: pd.DataFrame = pd.DataFrame()

    def run_phase1(self, warehouse: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Phase 1 : Validation qualité des données."""
        result = validate_data_quality(warehouse, output_dir=self.output_dir)
        self._results["phase1"] = result
        return result

    def run_phase2(self, warehouse: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Phase 2 : Feature Engineering avancé."""
        ts_enriched = build_timeseries_features(warehouse)
        self._ts_enriched = ts_enriched
        result = {
            "ts_shape": str(ts_enriched.shape) if not ts_enriched.empty else "vide",
            "features": list(ts_enriched.columns) if not ts_enriched.empty else [],
            "n_periods": len(ts_enriched),
        }
        self._results["phase2"] = result
        return result

    def run_phase3(self, warehouse: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Phase 3 : Variance & Feature Analysis."""
        try:
            from ml_engine.phases.phase3_variance import analyze_variance
            fact = warehouse.get("Fact_Ventes", pd.DataFrame())
            if fact.empty:
                return {}
            num_cols = [c for c in fact.columns if pd.api.types.is_numeric_dtype(fact[c])]
            X = fact[num_cols].head(50_000)
            y = fact.get("ttc_dev", None)
            if y is not None:
                y = y.head(50_000)
            result = analyze_variance(X, y=y, output_dir=self.output_dir)
            self._results["phase3"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase4(self, ts_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Phase 4 : Analyse séries temporelles."""
        try:
            from ml_engine.phases.phase4_timeseries import analyze_time_series
            df = ts_df if ts_df is not None else self._ts_enriched
            if df.empty:
                return {"error": "Série temporelle vide"}
            result = analyze_time_series(df, output_dir=self.output_dir)
            self._results["phase4"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase5(
        self,
        warehouse: Dict[str, pd.DataFrame],
        ts_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Phase 5 : Benchmarking des modèles."""
        try:
            from ml_engine.phases.phase5_benchmark import (
                benchmark_regression_models,
                benchmark_classification_models,
                benchmark_timeseries_models,
                benchmark_dl_models,
            )
            from ml_engine.preprocessing.ml_preprocessing import build_ml_datasets

            result: Dict[str, Any] = {}
            datasets = build_ml_datasets(warehouse, data_dir=self.data_dir)

            reg = datasets.get("regression", {})
            if reg:
                X_tr = np.asarray(reg["X_train"], dtype=float)
                X_te = np.asarray(reg["X_test"], dtype=float)
                y_tr = np.asarray(reg["y_train"]).ravel()
                y_te = np.asarray(reg["y_test"]).ravel()
                result["regression"] = benchmark_regression_models(
                    X_tr, X_te, y_tr, y_te, n_cv=self.n_cv, time_aware=True
                )
                self._prepared_datasets = datasets

            cls = datasets.get("classification", {})
            if cls:
                result["classification"] = benchmark_classification_models(
                    np.asarray(cls["X_train"], dtype=float),
                    np.asarray(cls["X_test"], dtype=float),
                    np.asarray(cls["y_train"]).ravel(),
                    np.asarray(cls["y_test"]).ravel(),
                    n_cv=self.n_cv,
                )

            df_ts = ts_df if ts_df is not None else self._ts_enriched
            if not df_ts.empty and len(df_ts) >= 20:
                n_test = max(3, len(df_ts) // 5)
                result["timeseries"] = benchmark_timeseries_models(df_ts, n_test=n_test)
                if self.run_dl:
                    result["deep_learning"] = benchmark_dl_models(df_ts, n_test=n_test)

            _save_json(result, self.output_dir / "phase5_benchmarking.json")
            self._results["phase5"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase6(self, warehouse: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Phase 6 : Optimisation hyperparamètres (Optuna)."""
        if not self.run_optuna:
            return {"note": "Optuna désactivé"}
        try:
            from ml_engine.phases.phase6_optuna import optimize_hyperparameters
            from ml_engine.preprocessing.ml_preprocessing import build_ml_datasets
            datasets = getattr(self, "_prepared_datasets", None) or build_ml_datasets(
                warehouse, data_dir=self.data_dir
            )
            reg = datasets.get("regression", {})
            if not reg:
                return {"error": "Pas de dataset régression"}
            result = optimize_hyperparameters(
                np.asarray(reg["X_train"], dtype=float),
                np.asarray(reg["y_train"]).ravel(),
                task="regression",
                n_trials=self.n_optuna_trials,
                timeout=120,
                output_dir=self.models_dir,
                time_aware=True,
            )
            self._results["phase6"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase7(self, warehouse: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """Phase 7 : Explicabilité SHAP."""
        if not self.run_shap:
            return {"note": "SHAP désactivé"}
        try:
            from ml_engine.phases.phase7_shap import explain_model
            from ml_engine.preprocessing.ml_preprocessing import build_ml_datasets
            from sklearn.ensemble import RandomForestRegressor
            datasets = getattr(self, "_prepared_datasets", None) or build_ml_datasets(
                warehouse, data_dir=self.data_dir
            )
            reg = datasets.get("regression", {})
            if not reg:
                return {"error": "Pas de dataset régression"}
            X_tr = np.asarray(reg["X_train"], dtype=float)
            X_te = np.asarray(reg["X_test"], dtype=float)
            y_tr = np.asarray(reg["y_train"]).ravel()
            model = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42, n_jobs=-1)
            model.fit(X_tr, y_tr)
            result = explain_model(
                model, X_tr, X_te,
                feature_names=list(reg.get("feature_cols", [])),
                task_name="prediction_delai_paiement",
                output_dir=self.output_dir,
            )
            self._results["phase7"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase8(self, ts_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """Phase 8 : Recommandations des meilleurs modèles."""
        try:
            from ml_engine.phases.phase8_selection import recommend_models
            p5 = self._results.get("phase5", {})
            result = recommend_models(
                reg_benchmark=p5.get("regression", {}),
                ts_benchmark=p5.get("timeseries", {}),
                dl_benchmark=p5.get("deep_learning", {}),
                output_dir=self.output_dir,
            )
            self._results["phase8"] = result
            return result
        except Exception as e:
            return {"error": str(e)}

    def run_phase9(self, warehouse: Dict[str, pd.DataFrame]) -> Any:
        """Phase 9 : Finance AI Agent (legacy interface)."""
        try:
            from ml_engine.phases.phase9_agent import FinanceAIAgent
            agent = FinanceAIAgent(models_dir=self.models_dir)
            agent.load()
            agent.save_report(output_dir=self.output_dir)
            self._results["phase9"] = {
                "agent_ready": True,
                "models_loaded": list(agent._models.keys()),
                "supported_queries": agent.SUPPORTED_QUERIES,
            }
            return agent
        except Exception as e:
            return {"error": str(e)}

    def run(
        self,
        warehouse: Dict[str, pd.DataFrame],
        phases: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Exécute le pipeline complet (ou un sous-ensemble de phases).
        
        Args:
            warehouse: Tables du Data Warehouse
            phases: Liste des numéros de phases à exécuter (ex: [1,2,5,7])
                    Si None, exécute toutes les phases.
        
        Returns:
            Dict consolidé des résultats de toutes les phases
        """
        run_all = phases is None
        phases_set = set(phases or range(1, 10))

        print("\n" + "=" * 70)
        print(f"FINANCE AI AGENT — ML ENGINE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 70)

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)

        if 1 in phases_set: self.run_phase1(warehouse)
        if 2 in phases_set: self.run_phase2(warehouse)
        if 3 in phases_set: self.run_phase3(warehouse)
        if 4 in phases_set: self.run_phase4()
        if 5 in phases_set: self.run_phase5(warehouse)
        if 6 in phases_set: self.run_phase6(warehouse)
        if 7 in phases_set: self.run_phase7(warehouse)
        if 8 in phases_set: self.run_phase8()
        if 9 in phases_set: self.run_phase9(warehouse)

        _save_json(
            {k: v for k, v in self._results.items() if k not in ["phase1"]},
            self.output_dir / "ml_engine_summary.json",
        )
        print("\n✅ ML Engine terminé.")
        return self._results

    @property
    def ts_enriched(self) -> pd.DataFrame:
        return self._ts_enriched

    @property
    def results(self) -> Dict[str, Any]:
        return self._results


def run_advanced_pipeline(
    warehouse: Dict[str, pd.DataFrame],
    data_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    models_dir: Optional[Path] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Fonction de compatibilité ascendante avec l'ancien ml_advanced_pipeline.run_advanced_pipeline().
    Délègue vers MLEngine.
    """
    engine = MLEngine(
        data_dir=data_dir,
        models_dir=models_dir,
        output_dir=output_dir,
        **{k: v for k, v in kwargs.items() if k in
           ["n_cv", "n_optuna_trials", "run_dl", "run_optuna", "run_shap"]},
    )
    return engine.run(warehouse)
