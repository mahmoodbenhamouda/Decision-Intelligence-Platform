"""
ml_modeling.py
==============
Production-grade modeling module for the PFE Business Intelligence and
decision-AI project.

This module deliberately consumes only datasets already prepared by
``ml_preprocessing.py``. It never rebuilds raw data, creates targets, performs
feature engineering, recalculates train/test splits, or fits new scalers.

Main entry point:
    train_all_models(ml_datasets, output_dir=Path("models"))
"""

from __future__ import annotations

import copy
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, clone
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    f1_score,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import KFold, StratifiedKFold, TimeSeriesSplit

try:  # Optional, used when installed.
    from xgboost import XGBClassifier, XGBRegressor
except Exception:  # pragma: no cover - optional dependency
    XGBClassifier = None  # type: ignore[assignment]
    XGBRegressor = None  # type: ignore[assignment]

try:  # Optional, used when installed.
    from prophet import Prophet
except Exception:  # pragma: no cover - optional dependency
    Prophet = None  # type: ignore[assignment]

try:  # Optional, used when installed.
    from statsmodels.tsa.statespace.sarimax import SARIMAX
except Exception:  # pragma: no cover - optional dependency
    SARIMAX = None  # type: ignore[assignment]


RANDOM_STATE = 42
LOGGER = logging.getLogger(__name__)

HIGH_CORRELATION_WARNING = 0.95
HIGH_CORRELATION_BLOCK = 0.98
OVERFIT_GAP_CLASSIFICATION = 0.12
OVERFIT_GAP_REGRESSION_R2 = 0.15
OVERFIT_GAP_REGRESSION_RMSE_RATIO = 1.35
NEAR_PERFECT_ACCURACY = 0.99
NEAR_PERFECT_R2 = 0.99
NEAR_ZERO_RMSE_RATIO = 0.001


CLASSIFICATION_LEAKAGE_TERMS = (
    "is_late_payment",
    "late_payment",
    "payment_late",
    "retard",
    "delay",
    "delai",
    "overdue",
    "paid_late",
    "impaye",
    "unpaid",
    "target",
    "label",
)

REGRESSION_TARGET_DERIVED_TERMS = (
    "ttc_dev",
    "montant_ttc",
    "total_ttc",
    "amount_ttc",
    "revenue_ttc",
    "ca_ttc",
    "prix_ttc",
    "target",
    "label",
)


@dataclass(frozen=True)
class LeakageReport:
    """Trace of leakage checks applied before model training."""

    target_name: Optional[str]
    initial_features: List[str]
    used_features: List[str]
    removed_features: List[str] = field(default_factory=list)
    suspicious_name_features: List[str] = field(default_factory=list)
    blocked_correlation_features: Dict[str, float] = field(default_factory=dict)
    warned_correlation_features: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass
class CandidateResult:
    """Evaluation result for one model candidate."""

    name: str
    model: Any
    cv_metrics: Dict[str, float]
    train_metrics: Dict[str, float]
    test_metrics: Dict[str, float]
    selection_score: float
    warnings: List[str] = field(default_factory=list)
    status: str = "ok"
    error: Optional[str] = None


def configure_logging(level: int = logging.INFO) -> None:
    """Configure module logging when the host application has not done it."""

    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )


def _as_dataframe(data: Any, feature_names: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Convert prepared feature matrices to DataFrames without changing values."""

    if isinstance(data, pd.DataFrame):
        return data.copy()
    if data is None:
        raise ValueError("Feature matrix is missing.")
    names = list(feature_names or [f"feature_{idx}" for idx in range(np.asarray(data).shape[1])])
    return pd.DataFrame(data, columns=names)


def _as_series(data: Any, name: Optional[str] = None) -> pd.Series:
    """Convert prepared targets to Series without deriving new targets."""

    if isinstance(data, pd.DataFrame):
        if data.shape[1] != 1:
            raise ValueError("Target DataFrame must contain exactly one column.")
        series = data.iloc[:, 0]
        return pd.Series(series.to_numpy(), name=name or str(series.name))
    if isinstance(data, pd.Series):
        return data.copy()
    if data is None:
        raise ValueError("Target vector is missing.")
    return pd.Series(np.asarray(data).ravel(), name=name)


def _safe_float(value: Any) -> Optional[float]:
    """JSON-safe float conversion."""

    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(val) or math.isinf(val):
        return None
    return val


def _json_ready(value: Any) -> Any:
    """Convert numpy, pandas and dataclass-like values into JSON-safe objects."""

    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return _safe_float(value)
    if isinstance(value, np.ndarray):
        return [_json_ready(v) for v in value.tolist()]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _target_name(y: pd.Series, default: str) -> str:
    return str(y.name) if y.name is not None else default


def _feature_terms_for_task(task: str, target_name: str) -> Tuple[str, ...]:
    tokens = [target_name.lower()]
    if task == "classification":
        tokens.extend(CLASSIFICATION_LEAKAGE_TERMS)
    elif task == "regression":
        tokens.extend(REGRESSION_TARGET_DERIVED_TERMS)
    return tuple(dict.fromkeys(t for t in tokens if t))


def _drop_non_numeric(X: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    non_numeric = [col for col in X.columns if not pd.api.types.is_numeric_dtype(X[col])]
    return X.drop(columns=non_numeric, errors="ignore"), non_numeric


def data_quality_report(X: pd.DataFrame, y: Optional[pd.Series] = None) -> Dict[str, Any]:
    """Summarize prepared data quality without mutating or reconstructing data."""

    numeric = X.select_dtypes(include=[np.number])
    report: Dict[str, Any] = {
        "n_rows": int(len(X)),
        "n_features": int(X.shape[1]),
        "missing_values_by_feature": {str(k): int(v) for k, v in X.isna().sum().items() if int(v) > 0},
        "infinite_values_by_feature": {
            str(col): int(np.isinf(pd.to_numeric(X[col], errors="coerce")).sum())
            for col in numeric.columns
            if int(np.isinf(pd.to_numeric(X[col], errors="coerce")).sum()) > 0
        },
        "duplicated_rows": int(X.duplicated().sum()),
        "constant_features": [str(col) for col in X.columns if X[col].nunique(dropna=False) <= 1],
        "numeric_distribution": {},
    }
    for col in numeric.columns:
        series = pd.to_numeric(numeric[col], errors="coerce").dropna()
        if series.empty:
            continue
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        iqr = q3 - q1
        report["numeric_distribution"][str(col)] = {
            "mean": float(series.mean()),
            "std": float(series.std(ddof=0)),
            "min": float(series.min()),
            "p25": q1,
            "median": float(series.median()),
            "p75": q3,
            "max": float(series.max()),
            "iqr_outlier_count": int(((series < q1 - 3.0 * iqr) | (series > q3 + 3.0 * iqr)).sum()) if iqr > 0 else 0,
        }
    if y is not None:
        report["target"] = {
            "name": _target_name(y, "target"),
            "missing_values": int(y.isna().sum()),
            "unique_values": int(y.nunique(dropna=True)),
        }
        if pd.api.types.is_numeric_dtype(y):
            y_num = pd.to_numeric(y, errors="coerce").dropna()
            if not y_num.empty:
                report["target"].update(
                    {
                        "mean": float(y_num.mean()),
                        "std": float(y_num.std(ddof=0)),
                        "min": float(y_num.min()),
                        "median": float(y_num.median()),
                        "max": float(y_num.max()),
                    }
                )
        else:
            report["target"]["class_distribution"] = {str(k): int(v) for k, v in y.value_counts().items()}
    return report


def feature_importance_report(model: Any, feature_names: Sequence[str], limit: int = 25) -> List[Dict[str, float]]:
    """Extract model importance in a uniform report-friendly shape."""

    values: Optional[np.ndarray] = None
    if hasattr(model, "feature_importances_"):
        values = np.asarray(model.feature_importances_, dtype=float).ravel()
    elif hasattr(model, "coef_"):
        coef = np.asarray(model.coef_, dtype=float)
        values = np.mean(np.abs(coef), axis=0) if coef.ndim > 1 else np.abs(coef).ravel()
    if values is None or len(values) != len(feature_names):
        return []
    total = float(np.sum(np.abs(values)))
    rows = []
    for name, value in zip(feature_names, values):
        normalized = float(abs(value) / total) if total > 0 else 0.0
        rows.append({"feature": str(name), "importance": float(value), "normalized_importance": normalized})
    return sorted(rows, key=lambda row: abs(row["importance"]), reverse=True)[:limit]


def _ranking(results: Mapping[str, "CandidateResult"], *, higher_is_better: bool) -> List[Dict[str, Any]]:
    valid_rows = [
        {
            "rank": 0,
            "model": result.name,
            "status": result.status,
            "selection_score": result.selection_score,
            "test_metrics": result.test_metrics,
            "warnings": result.warnings,
        }
        for result in results.values()
        if result.status == "ok"
    ]
    valid_rows.sort(key=lambda row: row["selection_score"], reverse=higher_is_better)
    for idx, row in enumerate(valid_rows, start=1):
        row["rank"] = idx
    return valid_rows


def guard_against_leakage(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    y_train: pd.Series,
    *,
    task: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, LeakageReport]:
    """
    Remove direct leakage features and flag abnormal target correlations.

    The input matrices come from preprocessing; this function only narrows the
    feature set used for modeling. It does not create or transform features.
    """

    target = _target_name(y_train, task)
    initial_features = [str(col) for col in X_train.columns]
    X_train_numeric, non_numeric = _drop_non_numeric(X_train)
    X_test_numeric = X_test[X_train_numeric.columns].copy()

    terms = _feature_terms_for_task(task, target)
    suspicious = [
        col for col in X_train_numeric.columns
        if any(term in str(col).lower() for term in terms)
    ]

    blocked_corr: Dict[str, float] = {}
    warned_corr: Dict[str, float] = {}
    y_numeric = pd.to_numeric(y_train, errors="coerce")
    for col in X_train_numeric.columns:
        series = pd.to_numeric(X_train_numeric[col], errors="coerce")
        valid = ~(series.isna() | y_numeric.isna())
        if valid.sum() < 3 or series[valid].nunique() <= 1 or y_numeric[valid].nunique() <= 1:
            continue
        corr = abs(float(series[valid].corr(y_numeric[valid])))
        if math.isnan(corr):
            continue
        if corr >= HIGH_CORRELATION_BLOCK:
            blocked_corr[str(col)] = corr
        elif corr >= HIGH_CORRELATION_WARNING:
            warned_corr[str(col)] = corr

    to_remove = sorted(set(non_numeric) | set(suspicious) | set(blocked_corr))
    X_train_guarded = X_train_numeric.drop(columns=to_remove, errors="ignore")
    X_test_guarded = X_test_numeric.drop(columns=to_remove, errors="ignore")

    notes = []
    if non_numeric:
        notes.append("Non-numeric prepared features removed because model candidates require numeric matrices.")
    if suspicious:
        notes.append("Features with target-like names removed to prevent direct or indirect target leakage.")
    if blocked_corr:
        notes.append(f"Features with absolute target correlation >= {HIGH_CORRELATION_BLOCK:.2f} removed.")
    if warned_corr:
        notes.append(f"Features with absolute target correlation >= {HIGH_CORRELATION_WARNING:.2f} flagged for review.")

    if X_train_guarded.empty:
        raise ValueError(
            f"No usable features remain for {task} after leakage checks. "
            "Review ml_preprocessing.py feature selection."
        )

    report = LeakageReport(
        target_name=target,
        initial_features=initial_features,
        used_features=[str(col) for col in X_train_guarded.columns],
        removed_features=to_remove,
        suspicious_name_features=[str(col) for col in suspicious],
        blocked_correlation_features=blocked_corr,
        warned_correlation_features=warned_corr,
        notes=notes,
    )
    return X_train_guarded, X_test_guarded, report


def _classification_candidates(n_classes: int) -> Dict[str, BaseEstimator]:
    candidates: Dict[str, BaseEstimator] = {
        "logistic_regression": LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=250,
            max_depth=8,
            min_samples_leaf=4,
            class_weight="balanced",
            n_jobs=-1,
            random_state=RANDOM_STATE,
        ),
        "gradient_boosting": GradientBoostingClassifier(random_state=RANDOM_STATE),
    }
    if XGBClassifier is not None:
        objective = "binary:logistic" if n_classes <= 2 else "multi:softprob"
        candidates["xgboost"] = XGBClassifier(
            n_estimators=250,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            objective=objective,
            eval_metric="logloss",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
    return candidates


def _regression_candidates() -> Dict[str, BaseEstimator]:
    candidates: Dict[str, BaseEstimator] = {
        "ridge": Ridge(alpha=2.0, random_state=RANDOM_STATE),
        "random_forest": RandomForestRegressor(
            n_estimators=250,
            max_depth=10,
            min_samples_leaf=4,
            n_jobs=-1,
            random_state=RANDOM_STATE,
        ),
        "gradient_boosting": GradientBoostingRegressor(
            n_estimators=250,
            learning_rate=0.05,
            max_depth=3,
            random_state=RANDOM_STATE,
        ),
    }
    if XGBRegressor is not None:
        candidates["xgboost"] = XGBRegressor(
            n_estimators=250,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            objective="reg:squarederror",
            random_state=RANDOM_STATE,
            n_jobs=-1,
        )
    return candidates


def _classification_metrics(model: BaseEstimator, X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
    pred = model.predict(X)
    metrics = {
        "accuracy": accuracy_score(y, pred),
        "f1_macro": f1_score(y, pred, average="macro", zero_division=0),
        "precision_macro": precision_score(y, pred, average="macro", zero_division=0),
        "recall_macro": recall_score(y, pred, average="macro", zero_division=0),
    }
    if hasattr(model, "predict_proba"):
        try:
            proba = model.predict_proba(X)
            if proba.shape[1] == 2:
                metrics["roc_auc"] = roc_auc_score(y, proba[:, 1])
            else:
                metrics["roc_auc_ovr"] = roc_auc_score(y, proba, multi_class="ovr", average="macro")
        except Exception as exc:
            LOGGER.debug("ROC-AUC unavailable: %s", exc)
    return {key: float(value) for key, value in metrics.items()}


def _regression_metrics(model: BaseEstimator, X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
    pred = np.asarray(model.predict(X)).ravel()
    y_arr = np.asarray(y).ravel()
    rmse = math.sqrt(float(mean_squared_error(y_arr, pred)))
    metrics = {
        "rmse": rmse,
        "mae": mean_absolute_error(y_arr, pred),
        "r2": r2_score(y_arr, pred),
    }
    if np.all(np.asarray(y_arr) != 0):
        metrics["mape"] = mean_absolute_percentage_error(y_arr, pred)
    return {key: float(value) for key, value in metrics.items()}


def _cv_classification(
    model: BaseEstimator,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int,
) -> Dict[str, float]:
    class_counts = y.value_counts()
    feasible_splits = min(n_splits, int(class_counts.min())) if not class_counts.empty else 0
    if feasible_splits < 2:
        return {"cv_f1_macro_mean": float("nan"), "cv_f1_macro_std": float("nan")}

    splitter = StratifiedKFold(n_splits=feasible_splits, shuffle=True, random_state=RANDOM_STATE)
    fold_metrics: List[Dict[str, float]] = []
    for train_idx, val_idx in splitter.split(X, y):
        fold_model = clone(model)
        fold_model.fit(X.iloc[train_idx], y.iloc[train_idx])
        fold_metrics.append(_classification_metrics(fold_model, X.iloc[val_idx], y.iloc[val_idx]))
    return _aggregate_cv(fold_metrics)


def _cv_regression(
    model: BaseEstimator,
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int,
) -> Dict[str, float]:
    feasible_splits = min(n_splits, len(X))
    if feasible_splits < 2:
        return {"cv_rmse_mean": float("nan"), "cv_rmse_std": float("nan")}

    splitter = KFold(n_splits=feasible_splits, shuffle=True, random_state=RANDOM_STATE)
    fold_metrics: List[Dict[str, float]] = []
    for train_idx, val_idx in splitter.split(X):
        fold_model = clone(model)
        fold_model.fit(X.iloc[train_idx], y.iloc[train_idx])
        fold_metrics.append(_regression_metrics(fold_model, X.iloc[val_idx], y.iloc[val_idx]))
    return _aggregate_cv(fold_metrics)


def _aggregate_cv(fold_metrics: Sequence[Mapping[str, float]]) -> Dict[str, float]:
    if not fold_metrics:
        return {}
    keys = sorted({key for metrics in fold_metrics for key in metrics})
    aggregated: Dict[str, float] = {}
    for key in keys:
        values = np.asarray([metrics[key] for metrics in fold_metrics if key in metrics], dtype=float)
        aggregated[f"cv_{key}_mean"] = float(np.nanmean(values))
        aggregated[f"cv_{key}_std"] = float(np.nanstd(values))
    return aggregated


def _classification_warnings(train_metrics: Mapping[str, float], test_metrics: Mapping[str, float]) -> List[str]:
    warnings: List[str] = []
    gap = train_metrics.get("f1_macro", 0.0) - test_metrics.get("f1_macro", 0.0)
    if gap > OVERFIT_GAP_CLASSIFICATION:
        warnings.append(f"Potential overfitting: train/test F1 macro gap is {gap:.3f}.")
    accuracy_gap = train_metrics.get("accuracy", 0.0) - test_metrics.get("accuracy", 0.0)
    if accuracy_gap > OVERFIT_GAP_CLASSIFICATION:
        warnings.append(f"Potential overfitting: train/test accuracy gap is {accuracy_gap:.3f}.")
    if test_metrics.get("accuracy", 0.0) > NEAR_PERFECT_ACCURACY or test_metrics.get("f1_macro", 0.0) > NEAR_PERFECT_ACCURACY:
        warnings.append("Near-perfect classification test score detected; review leakage warnings and business plausibility.")
    return warnings


def _regression_warnings(train_metrics: Mapping[str, float], test_metrics: Mapping[str, float]) -> List[str]:
    warnings: List[str] = []
    r2_gap = train_metrics.get("r2", 0.0) - test_metrics.get("r2", 0.0)
    if r2_gap > OVERFIT_GAP_REGRESSION_R2:
        warnings.append(f"Potential overfitting: train/test R2 gap is {r2_gap:.3f}.")
    train_rmse = train_metrics.get("rmse", 0.0)
    test_rmse = test_metrics.get("rmse", 0.0)
    if train_rmse > 0 and test_rmse / train_rmse > OVERFIT_GAP_REGRESSION_RMSE_RATIO:
        warnings.append(f"Potential overfitting: test/train RMSE ratio is {test_rmse / train_rmse:.3f}.")
    if test_metrics.get("r2", 0.0) > NEAR_PERFECT_R2:
        warnings.append("Near-perfect test R2 detected; review leakage warnings and business plausibility.")
    target_scale = max(abs(test_metrics.get("mae", 0.0)), abs(test_metrics.get("rmse", 0.0)), 1.0)
    if test_rmse / target_scale < NEAR_ZERO_RMSE_RATIO:
        warnings.append("Near-zero RMSE detected; verify target-derived variables and business plausibility.")
    return warnings


def train_classification_models(dataset: Mapping[str, Any], n_splits: int = 5) -> Dict[str, Any]:
    """Train and compare classification candidates using prepared splits only."""

    X_train = _as_dataframe(dataset.get("X_train"), dataset.get("feature_cols"))
    X_test = _as_dataframe(dataset.get("X_test"), dataset.get("feature_cols"))
    y_train = _as_series(dataset.get("y_train"), "classification_target")
    y_test = _as_series(dataset.get("y_test"), _target_name(y_train, "classification_target"))
    X_train, X_test, leakage = guard_against_leakage(X_train, X_test, y_train, task="classification")
    quality = {
        "train": data_quality_report(X_train, y_train),
        "test": data_quality_report(X_test, y_test),
    }

    candidates = _classification_candidates(n_classes=int(y_train.nunique()))
    results: Dict[str, CandidateResult] = {}

    for name, candidate in candidates.items():
        LOGGER.info("Training classification candidate: %s", name)
        try:
            model = clone(candidate)
            cv_metrics = _cv_classification(model, X_train, y_train, n_splits)
            model.fit(X_train, y_train)
            train_metrics = _classification_metrics(model, X_train, y_train)
            test_metrics = _classification_metrics(model, X_test, y_test)
            warnings = _classification_warnings(train_metrics, test_metrics)
            results[name] = CandidateResult(
                name=name,
                model=model,
                cv_metrics=cv_metrics,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                selection_score=float(test_metrics["f1_macro"]),
                warnings=warnings,
            )
        except Exception as exc:
            LOGGER.exception("Classification candidate failed: %s", name)
            results[name] = CandidateResult(
                name=name,
                model=None,
                cv_metrics={},
                train_metrics={},
                test_metrics={},
                selection_score=-np.inf,
                status="failed",
                error=str(exc),
            )

    best = _select_best(results, higher_is_better=True)
    return _task_payload(
        best,
        results,
        leakage,
        dataset.get("scaler"),
        "test_f1_macro",
        data_quality=quality,
        feature_importance=feature_importance_report(best.model, X_train.columns),
        ranking_higher_is_better=True,
    )


def train_regression_models(dataset: Mapping[str, Any], n_splits: int = 5) -> Dict[str, Any]:
    """Train and compare regression candidates using prepared splits only."""

    X_train = _as_dataframe(dataset.get("X_train"), dataset.get("feature_cols"))
    X_test = _as_dataframe(dataset.get("X_test"), dataset.get("feature_cols"))
    y_train = _as_series(dataset.get("y_train"), "regression_target")
    y_test = _as_series(dataset.get("y_test"), _target_name(y_train, "regression_target"))
    X_train, X_test, leakage = guard_against_leakage(X_train, X_test, y_train, task="regression")
    quality = {
        "train": data_quality_report(X_train, y_train),
        "test": data_quality_report(X_test, y_test),
    }

    candidates = _regression_candidates()
    results: Dict[str, CandidateResult] = {}

    for name, candidate in candidates.items():
        LOGGER.info("Training regression candidate: %s", name)
        try:
            model = clone(candidate)
            cv_metrics = _cv_regression(model, X_train, y_train, n_splits)
            model.fit(X_train, y_train)
            train_metrics = _regression_metrics(model, X_train, y_train)
            test_metrics = _regression_metrics(model, X_test, y_test)
            warnings = _regression_warnings(train_metrics, test_metrics)
            results[name] = CandidateResult(
                name=name,
                model=model,
                cv_metrics=cv_metrics,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                selection_score=-float(test_metrics["rmse"]),
                warnings=warnings,
            )
        except Exception as exc:
            LOGGER.exception("Regression candidate failed: %s", name)
            results[name] = CandidateResult(
                name=name,
                model=None,
                cv_metrics={},
                train_metrics={},
                test_metrics={},
                selection_score=-np.inf,
                status="failed",
                error=str(exc),
            )

    best = _select_best(results, higher_is_better=True)
    return _task_payload(
        best,
        results,
        leakage,
        dataset.get("scaler"),
        "test_rmse_lowest",
        data_quality=quality,
        feature_importance=feature_importance_report(best.model, X_train.columns),
        ranking_higher_is_better=True,
    )


def train_clustering_models(dataset: Mapping[str, Any]) -> Dict[str, Any]:
    """Train and compare clustering candidates on the prepared clustering matrix."""

    feature_cols = list(dataset.get("feature_cols") or [])
    df_model = dataset.get("df_model")
    if not isinstance(df_model, pd.DataFrame) or df_model.empty:
        raise ValueError("Prepared clustering dataset must contain a non-empty df_model.")
    if not feature_cols:
        feature_cols = [col for col in df_model.columns if pd.api.types.is_numeric_dtype(df_model[col])]
    X = df_model[feature_cols].copy()
    X, removed = _drop_non_numeric(X)
    if X.empty:
        raise ValueError("No numeric clustering features available after validation.")
    quality = {"all": data_quality_report(X)}

    candidates: Dict[str, Callable[[pd.DataFrame], Tuple[Any, np.ndarray]]] = {
        "kmeans_k3": lambda data: _fit_predict(KMeans(n_clusters=3, n_init=20, random_state=RANDOM_STATE), data),
        "kmeans_k5": lambda data: _fit_predict(KMeans(n_clusters=5, n_init=20, random_state=RANDOM_STATE), data),
        "agglomerative_k5": lambda data: _fit_predict(AgglomerativeClustering(n_clusters=5, linkage="ward"), data),
        "gaussian_mixture_k5": lambda data: _fit_gaussian_mixture(data, 5),
        "dbscan": lambda data: _fit_predict(DBSCAN(eps=0.35, min_samples=5), data),
    }

    results: Dict[str, CandidateResult] = {}
    for name, fit_fn in candidates.items():
        LOGGER.info("Training clustering candidate: %s", name)
        try:
            model, labels = fit_fn(X)
            metrics = _clustering_metrics(X, labels)
            warnings = []
            if metrics.get("n_clusters", 0) < 2:
                warnings.append("Candidate produced fewer than two clusters; metrics are not reliable.")
            results[name] = CandidateResult(
                name=name,
                model=model,
                cv_metrics={},
                train_metrics={},
                test_metrics=metrics,
                selection_score=_clustering_selection_score(metrics),
                warnings=warnings,
            )
        except Exception as exc:
            LOGGER.exception("Clustering candidate failed: %s", name)
            results[name] = CandidateResult(
                name=name,
                model=None,
                cv_metrics={},
                train_metrics={},
                test_metrics={},
                selection_score=-np.inf,
                status="failed",
                error=str(exc),
            )

    leakage = LeakageReport(
        target_name=None,
        initial_features=[str(col) for col in feature_cols],
        used_features=[str(col) for col in X.columns],
        removed_features=[str(col) for col in removed],
        notes=["Clustering is unsupervised; no target-correlation leakage check is applicable."],
    )
    best = _select_best(results, higher_is_better=True)
    return _task_payload(
        best,
        results,
        leakage,
        dataset.get("scaler"),
        "clustering_compromise_silhouette_davies_bouldin_business_coherence",
        data_quality=quality,
        feature_importance=[],
        ranking_higher_is_better=True,
    )


def _fit_predict(model: Any, X: pd.DataFrame) -> Tuple[Any, np.ndarray]:
    labels = model.fit_predict(X)
    return model, np.asarray(labels)


def _fit_gaussian_mixture(X: pd.DataFrame, n_components: int) -> Tuple[Any, np.ndarray]:
    model = GaussianMixture(n_components=n_components, covariance_type="full", random_state=RANDOM_STATE)
    labels = model.fit_predict(X)
    return model, np.asarray(labels)


def _clustering_metrics(X: pd.DataFrame, labels: np.ndarray) -> Dict[str, float]:
    unique_labels = set(labels.tolist())
    n_clusters = len(unique_labels - {-1})
    metrics = {"n_clusters": float(n_clusters), "noise_ratio": float(np.mean(labels == -1))}
    if n_clusters >= 2 and len(unique_labels) < len(X):
        metrics["silhouette"] = float(silhouette_score(X, labels))
        metrics["calinski_harabasz"] = float(calinski_harabasz_score(X, labels))
        metrics["davies_bouldin"] = float(davies_bouldin_score(X, labels))
    else:
        metrics["silhouette"] = -1.0
        metrics["calinski_harabasz"] = 0.0
        metrics["davies_bouldin"] = float("inf")
    return metrics


def _clustering_selection_score(metrics: Mapping[str, float]) -> float:
    """Balance silhouette, Davies-Bouldin and basic segment usability."""

    silhouette = float(metrics.get("silhouette", -1.0))
    davies = float(metrics.get("davies_bouldin", float("inf")))
    n_clusters = int(metrics.get("n_clusters", 0))
    noise_ratio = float(metrics.get("noise_ratio", 0.0))
    if n_clusters < 2 or math.isinf(davies):
        return -np.inf
    business_penalty = 0.0
    if n_clusters > 12:
        business_penalty += 0.20
    if noise_ratio > 0.35:
        business_penalty += 0.20
    return silhouette - 0.05 * davies - business_penalty


def train_timeseries_models(dataset: Mapping[str, Any], n_splits: int = 3) -> Dict[str, Any]:
    """Train lag-feature time-series models using prepared chronological split."""

    df_train = dataset.get("df_train")
    df_test = dataset.get("df_test")
    if not isinstance(df_train, pd.DataFrame) or not isinstance(df_test, pd.DataFrame):
        raise ValueError("Prepared timeseries dataset must contain df_train and df_test.")
    if df_train.empty or df_test.empty:
        raise ValueError("Prepared timeseries train and test sets must be non-empty.")

    target_col = "revenue_ttc"
    if target_col not in df_train.columns or target_col not in df_test.columns:
        raise ValueError("Prepared timeseries dataset must contain revenue_ttc target.")

    feature_cols = [
        col for col in df_train.columns
        if col != target_col and col != "period" and pd.api.types.is_numeric_dtype(df_train[col])
    ]
    if not feature_cols:
        raise ValueError("No prepared numeric time-series features found.")

    X_train = df_train[feature_cols].copy()
    y_train = df_train[target_col].copy()
    X_test = df_test[feature_cols].copy()
    y_test = df_test[target_col].copy()
    quality = {
        "train": data_quality_report(X_train, y_train),
        "test": data_quality_report(X_test, y_test),
    }

    candidates = _regression_candidates()
    if "xgboost" in candidates:
        candidates["xgboost_forecasting"] = candidates.pop("xgboost")
    candidates["naive_lag1_baseline"] = _NaiveLagOneRegressor()
    results: Dict[str, CandidateResult] = {}

    for name, candidate in candidates.items():
        LOGGER.info("Training time-series candidate: %s", name)
        try:
            model = clone(candidate) if isinstance(candidate, BaseEstimator) else copy.deepcopy(candidate)
            cv_metrics = _cv_timeseries(model, X_train, y_train, n_splits)
            model.fit(X_train, y_train)
            train_metrics = _regression_metrics(model, X_train, y_train)
            test_metrics = _regression_metrics(model, X_test, y_test)
            warnings = _regression_warnings(train_metrics, test_metrics)
            results[name] = CandidateResult(
                name=name,
                model=model,
                cv_metrics=cv_metrics,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                selection_score=-float(test_metrics["rmse"]),
                warnings=warnings,
            )
        except Exception as exc:
            LOGGER.exception("Time-series candidate failed: %s", name)
            results[name] = CandidateResult(
                name=name,
                model=None,
                cv_metrics={},
                train_metrics={},
                test_metrics={},
                selection_score=-np.inf,
                status="failed",
                error=str(exc),
            )

    for name, fit_predict_fn in {
        "sarima": _fit_predict_sarima,
        "prophet": _fit_predict_prophet,
    }.items():
        LOGGER.info("Training time-series statistical candidate: %s", name)
        try:
            model, train_pred, test_pred, cv_metrics = fit_predict_fn(df_train, df_test, target_col, n_splits)
            train_metrics = _regression_metrics_from_predictions(y_train, train_pred)
            test_metrics = _regression_metrics_from_predictions(y_test, test_pred)
            warnings = _regression_warnings(train_metrics, test_metrics)
            results[name] = CandidateResult(
                name=name,
                model=model,
                cv_metrics=cv_metrics,
                train_metrics=train_metrics,
                test_metrics=test_metrics,
                selection_score=-float(test_metrics["rmse"]),
                warnings=warnings,
            )
        except Exception as exc:
            LOGGER.exception("Time-series statistical candidate failed: %s", name)
            results[name] = CandidateResult(
                name=name,
                model=None,
                cv_metrics={},
                train_metrics={},
                test_metrics={},
                selection_score=-np.inf,
                status="failed",
                error=str(exc),
            )

    leakage = LeakageReport(
        target_name=target_col,
        initial_features=[str(col) for col in feature_cols],
        used_features=[str(col) for col in feature_cols],
        warned_correlation_features=_timeseries_feature_correlations(X_train, y_train),
        notes=[
            "Time-series split is consumed as prepared by ml_preprocessing.py.",
            "Lag features are allowed for forecasting because they represent historical target values.",
        ],
    )
    best = _select_best(results, higher_is_better=True)
    return _task_payload(
        best,
        results,
        leakage,
        dataset.get("scaler"),
        "test_rmse_lowest_chronological",
        data_quality=quality,
        feature_importance=feature_importance_report(best.model, feature_cols),
        ranking_higher_is_better=True,
    )


class _NaiveLagOneRegressor(BaseEstimator):
    """Simple benchmark that predicts from the prepared lag-1 revenue feature."""

    def __init__(self, lag_column: str = "revenue_ttc_lag1") -> None:
        self.lag_column = lag_column
        self.fallback_: float = 0.0

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "_NaiveLagOneRegressor":
        self.fallback_ = float(np.mean(y))
        if self.lag_column not in X.columns:
            raise ValueError(f"Required prepared lag column missing: {self.lag_column}")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        values = pd.to_numeric(X[self.lag_column], errors="coerce").fillna(self.fallback_)
        return values.to_numpy(dtype=float)


def _regression_metrics_from_predictions(y_true: pd.Series, y_pred: Sequence[float]) -> Dict[str, float]:
    y_arr = np.asarray(y_true).ravel()
    pred = np.asarray(y_pred, dtype=float).ravel()
    rmse = math.sqrt(float(mean_squared_error(y_arr, pred)))
    metrics = {
        "rmse": rmse,
        "mae": float(mean_absolute_error(y_arr, pred)),
        "r2": float(r2_score(y_arr, pred)),
    }
    if np.all(y_arr != 0):
        metrics["mape"] = float(mean_absolute_percentage_error(y_arr, pred))
    return metrics


def _fit_predict_sarima(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    target_col: str,
    n_splits: int,
) -> Tuple[Any, np.ndarray, np.ndarray, Dict[str, float]]:
    if SARIMAX is None:
        raise ImportError("statsmodels SARIMAX is not installed.")
    y_train = pd.to_numeric(df_train[target_col], errors="coerce").astype(float)
    seasonal_period = 12 if len(y_train) >= 24 else 0
    seasonal_order = (1, 1, 1, seasonal_period) if seasonal_period else (0, 0, 0, 0)
    model = SARIMAX(
        y_train,
        order=(1, 1, 1),
        seasonal_order=seasonal_order,
        enforce_stationarity=False,
        enforce_invertibility=False,
    ).fit(disp=False)
    train_pred = np.asarray(model.fittedvalues).ravel()
    test_pred = np.asarray(model.forecast(steps=len(df_test))).ravel()
    cv_metrics = _cv_statistical_timeseries(df_train, target_col, n_splits, "sarima")
    return model, train_pred, test_pred, cv_metrics


def _fit_predict_prophet(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    target_col: str,
    n_splits: int,
) -> Tuple[Any, np.ndarray, np.ndarray, Dict[str, float]]:
    if Prophet is None:
        raise ImportError("prophet is not installed.")
    if "period" not in df_train.columns or "period" not in df_test.columns:
        raise ValueError("Prophet requires the prepared period column.")
    train_prophet = df_train[["period", target_col]].rename(columns={"period": "ds", target_col: "y"})
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model.fit(train_prophet)
    train_pred = model.predict(train_prophet[["ds"]])["yhat"].to_numpy(dtype=float)
    test_dates = df_test[["period"]].rename(columns={"period": "ds"})
    test_pred = model.predict(test_dates)["yhat"].to_numpy(dtype=float)
    cv_metrics = _cv_statistical_timeseries(df_train, target_col, n_splits, "prophet")
    return model, train_pred, test_pred, cv_metrics


def _cv_statistical_timeseries(
    df_train: pd.DataFrame,
    target_col: str,
    n_splits: int,
    model_name: str,
) -> Dict[str, float]:
    if len(df_train) < 8:
        return {"cv_rmse_mean": float("nan"), "cv_rmse_std": float("nan")}
    splitter = TimeSeriesSplit(n_splits=min(n_splits, max(2, len(df_train) - 1)))
    fold_metrics: List[Dict[str, float]] = []
    for train_idx, val_idx in splitter.split(df_train):
        fold_train = df_train.iloc[train_idx].copy()
        fold_val = df_train.iloc[val_idx].copy()
        try:
            if model_name == "sarima":
                _, _, pred, _ = _fit_predict_sarima_no_cv(fold_train, fold_val, target_col)
            elif model_name == "prophet":
                _, _, pred, _ = _fit_predict_prophet_no_cv(fold_train, fold_val, target_col)
            else:
                continue
            fold_metrics.append(_regression_metrics_from_predictions(fold_val[target_col], pred))
        except Exception as exc:
            LOGGER.debug("%s CV fold failed: %s", model_name, exc)
    return _aggregate_cv(fold_metrics)


def _fit_predict_sarima_no_cv(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    target_col: str,
) -> Tuple[Any, np.ndarray, np.ndarray, Dict[str, float]]:
    if SARIMAX is None:
        raise ImportError("statsmodels SARIMAX is not installed.")
    y_train = pd.to_numeric(df_train[target_col], errors="coerce").astype(float)
    seasonal_period = 12 if len(y_train) >= 24 else 0
    seasonal_order = (1, 1, 1, seasonal_period) if seasonal_period else (0, 0, 0, 0)
    model = SARIMAX(
        y_train,
        order=(1, 1, 1),
        seasonal_order=seasonal_order,
        enforce_stationarity=False,
        enforce_invertibility=False,
    ).fit(disp=False)
    return model, np.asarray(model.fittedvalues).ravel(), np.asarray(model.forecast(steps=len(df_test))).ravel(), {}


def _fit_predict_prophet_no_cv(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    target_col: str,
) -> Tuple[Any, np.ndarray, np.ndarray, Dict[str, float]]:
    if Prophet is None:
        raise ImportError("prophet is not installed.")
    train_prophet = df_train[["period", target_col]].rename(columns={"period": "ds", target_col: "y"})
    model = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
    model.fit(train_prophet)
    train_pred = model.predict(train_prophet[["ds"]])["yhat"].to_numpy(dtype=float)
    test_dates = df_test[["period"]].rename(columns={"period": "ds"})
    test_pred = model.predict(test_dates)["yhat"].to_numpy(dtype=float)
    return model, train_pred, test_pred, {}


def _cv_timeseries(model: Any, X: pd.DataFrame, y: pd.Series, n_splits: int) -> Dict[str, float]:
    feasible_splits = min(n_splits, max(2, len(X) - 1))
    if len(X) < 4 or feasible_splits < 2:
        return {"cv_rmse_mean": float("nan"), "cv_rmse_std": float("nan")}

    splitter = TimeSeriesSplit(n_splits=feasible_splits)
    fold_metrics: List[Dict[str, float]] = []
    for train_idx, val_idx in splitter.split(X):
        fold_model = clone(model) if isinstance(model, BaseEstimator) else copy.deepcopy(model)
        fold_model.fit(X.iloc[train_idx], y.iloc[train_idx])
        fold_metrics.append(_regression_metrics(fold_model, X.iloc[val_idx], y.iloc[val_idx]))
    return _aggregate_cv(fold_metrics)


def _timeseries_feature_correlations(X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
    correlations: Dict[str, float] = {}
    for col in X.columns:
        series = pd.to_numeric(X[col], errors="coerce")
        corr = abs(float(series.corr(pd.to_numeric(y, errors="coerce"))))
        if not math.isnan(corr) and corr >= HIGH_CORRELATION_WARNING:
            correlations[str(col)] = corr
    return correlations


def _select_best(results: Mapping[str, CandidateResult], *, higher_is_better: bool) -> CandidateResult:
    valid = [result for result in results.values() if result.status == "ok" and result.model is not None]
    if not valid:
        raise RuntimeError("No valid model candidate was trained successfully.")
    reverse = higher_is_better
    return sorted(valid, key=lambda result: result.selection_score, reverse=reverse)[0]


def _task_payload(
    best: CandidateResult,
    results: Mapping[str, CandidateResult],
    leakage: LeakageReport,
    scaler: Any,
    selection_metric: str,
    *,
    data_quality: Mapping[str, Any],
    feature_importance: Sequence[Mapping[str, Any]],
    ranking_higher_is_better: bool,
) -> Dict[str, Any]:
    overfitting_alerts = {
        name: result.warnings
        for name, result in results.items()
        if result.warnings
    }
    return {
        "best_model_name": best.name,
        "best_model": best.model,
        "scaler": scaler,
        "selection_metric": selection_metric,
        "selection_justification": (
            f"{best.name} selected by independent test-set performance "
            f"using {selection_metric}; CV metrics were used for comparison only."
        ),
        "data_quality_report": data_quality,
        "leakage_report": leakage.__dict__,
        "overfitting_analysis": {
            "alerts_by_model": overfitting_alerts,
            "best_model_alerts": best.warnings,
        },
        "feature_importance": list(feature_importance),
        "final_ranking": _ranking(results, higher_is_better=ranking_higher_is_better),
        "models": {
            name: {
                "status": result.status,
                "cv_metrics": result.cv_metrics,
                "train_metrics": result.train_metrics,
                "test_metrics": result.test_metrics,
                "selection_score": result.selection_score,
                "warnings": result.warnings,
                "error": result.error,
            }
            for name, result in results.items()
        },
    }


def save_task_artifacts(task_name: str, task_result: Mapping[str, Any], output_dir: Path) -> Dict[str, str]:
    """Persist the selected model, associated scaler and feature metadata."""

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}

    model = task_result.get("best_model")
    if model is not None:
        model_path = output_dir / f"{task_name}_best.pkl"
        joblib.dump(model, model_path)
        paths["model"] = str(model_path)

    scaler = task_result.get("scaler")
    if scaler is not None:
        scaler_path = output_dir / f"{task_name}_scaler.pkl"
        joblib.dump(scaler, scaler_path)
        paths["scaler"] = str(scaler_path)

    return paths


def build_decision_signals(task_results: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Create architecture-friendly signals for downstream decision agents."""

    signals: Dict[str, Any] = {}
    for task_name, result in task_results.items():
        ranking = result.get("final_ranking", [])
        best_rank = ranking[0] if ranking else {}
        alerts = []
        alerts.extend(result.get("overfitting_analysis", {}).get("best_model_alerts", []))
        alerts.extend(result.get("leakage_report", {}).get("notes", []))
        test_metrics = best_rank.get("test_metrics", {})
        confidence = _signal_confidence(task_name, test_metrics, alerts)
        signals[task_name] = {
            "signal_type": {
                "classification": "Risk",
                "regression": "Prediction",
                "timeseries": "Prediction",
                "clustering": "Segmentation",
            }.get(task_name, "Prediction"),
            "best_model": result.get("best_model_name"),
            "selection_metric": result.get("selection_metric"),
            "confidence_score": confidence,
            "test_metrics": test_metrics,
            "alerts": alerts,
            "agent_usage": (
                "Use this signal as model-governance metadata before generating financial, stock, "
                "cash-flow or benchmark recommendations. Do not aggregate raw tenant data; aggregate "
                "only anonymized metrics and alert counts."
            ),
        }
    return signals


def _signal_confidence(task_name: str, test_metrics: Mapping[str, float], alerts: Sequence[str]) -> float:
    if task_name == "classification":
        base = float(test_metrics.get("f1_macro", 0.0))
    elif task_name in {"regression", "timeseries"}:
        r2 = float(test_metrics.get("r2", 0.0))
        base = max(0.0, min(1.0, (r2 + 1.0) / 2.0))
    elif task_name == "clustering":
        base = max(0.0, min(1.0, float(test_metrics.get("silhouette", 0.0))))
    else:
        base = 0.5
    penalty = min(0.4, 0.08 * len(alerts))
    return round(max(0.0, min(1.0, base - penalty)), 4)


def train_all_models(
    ml_datasets: Mapping[str, Any],
    output_dir: Optional[Path] = None,
    *,
    n_splits: int = 5,
) -> Dict[str, Any]:
    """
    Train, evaluate, select and persist models for all prepared ML tasks.

    Parameters
    ----------
    ml_datasets:
        Output of ``ml_preprocessing.build_ml_datasets``. Passing a warehouse
        dictionary is intentionally unsupported to avoid rebuilding data here.
    output_dir:
        Directory where joblib artifacts and the JSON report are written.
    n_splits:
        Maximum number of CV folds. Feasible folds are lowered automatically
        for small datasets.
    """

    configure_logging()
    if output_dir is None:
        output_dir = Path("models")
    output_dir = Path(output_dir)

    required_tasks = ("clustering", "classification", "regression", "timeseries")
    missing = [task for task in required_tasks if task not in ml_datasets or not ml_datasets.get(task)]
    if missing:
        raise ValueError(
            "train_all_models expects prepared datasets from ml_preprocessing.build_ml_datasets; "
            f"missing or empty task datasets: {missing}"
        )

    LOGGER.info("Starting modeling pipeline from prepared ml_preprocessing datasets.")

    task_trainers: Dict[str, Callable[..., Dict[str, Any]]] = {
        "clustering": lambda data: train_clustering_models(data),
        "classification": lambda data: train_classification_models(data, n_splits=n_splits),
        "regression": lambda data: train_regression_models(data, n_splits=n_splits),
        "timeseries": lambda data: train_timeseries_models(data, n_splits=min(3, n_splits)),
    }

    task_results: Dict[str, Any] = {}
    artifact_paths: Dict[str, Dict[str, str]] = {}

    for task_name, trainer in task_trainers.items():
        LOGGER.info("Running task: %s", task_name)
        task_result = trainer(ml_datasets[task_name])
        artifact_paths[task_name] = save_task_artifacts(task_name, task_result, output_dir)
        sanitized = {key: value for key, value in task_result.items() if key not in {"best_model", "scaler"}}
        task_results[task_name] = sanitized

    decision_signals = build_decision_signals(task_results)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_state": RANDOM_STATE,
        "source_contract": "Only consumes prepared datasets returned by ml_preprocessing.build_ml_datasets.",
        "architecture_alignment": {
            "platform": "Decision Intelligence Platform",
            "agent_ready_signal_contract": "tasks.<task>.decision_signal-compatible metadata exposed under decision_signals.",
            "tenant_isolation_note": "Report contains metrics and model-governance metadata only; raw tenant records are not exported.",
            "aggregation_note": "Downstream stock/cash-flow agents should aggregate anonymized signals, confidence scores and alert counts, not raw features.",
        },
        "evaluation_policy": {
            "cv_role": "Validation cross-validation is used only to compare candidates.",
            "selection_role": "Final model selection is based on independent prepared test-set metrics.",
            "test_set_policy": "The test set is never merged back into training before persistence.",
        },
        "artifacts": artifact_paths,
        "decision_signals": decision_signals,
        "tasks": task_results,
    }

    report_path = output_dir / "comparison_report.json"
    report_path.write_text(
        json.dumps(_json_ready(report), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    LOGGER.info("Modeling report written to %s", report_path)

    return {
        "report": report,
        "artifact_paths": artifact_paths,
        "report_path": str(report_path),
    }


def load_model_artifact(model_path: Path, scaler_path: Optional[Path] = None) -> Tuple[Any, Any]:
    """Load a persisted model and optional scaler with Joblib."""

    model = joblib.load(model_path)
    scaler = joblib.load(scaler_path) if scaler_path is not None and scaler_path.exists() else None
    return model, scaler


if __name__ == "__main__":
    from data_preparation_pipeline import prepare_data_layer
    from ml_preprocessing import build_ml_datasets

    configure_logging()
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data_pfe"
    prepared_output_dir = base_dir / "output"
    models_dir = base_dir / "models"

    LOGGER.info("Preparing BI warehouse and ML datasets.")
    _, warehouse = prepare_data_layer(data_dir, prepared_output_dir)
    datasets = build_ml_datasets(warehouse, data_dir=data_dir, load_mouv=False)
    train_all_models(datasets, output_dir=models_dir)
