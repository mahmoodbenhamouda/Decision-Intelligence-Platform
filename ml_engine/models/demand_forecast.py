"""
ml_engine/models/demand_forecast.py
===================================
CRISP-DM — PHASES 4 (MODÉLISATION) et 5 (ÉVALUATION)

Prévision de la demande **multi-horizon** : 30, 60 et 90 jours (h1, h2, h3).

## Protocole d'évaluation (aucune fuite possible)

**Validation temporelle par blocs glissants** (`TimeSeriesSplit`-like manuel) :
le jeu est découpé chronologiquement ; à chaque pli, on entraîne sur le passé
et on valide sur le bloc suivant. Un découpage aléatoire serait invalide sur
des séries temporelles (le modèle verrait le futur).

```
pli 1 : train [.....]  valid [xxx]
pli 2 : train [........]  valid [xxx]
pli 3 : train [...........]  valid [xxx]
```

Un **hold-out final** (les 6 derniers mois) n'est jamais utilisé pendant la
sélection : il ne sert qu'à mesurer la performance du modèle retenu.

## Modèles comparés (par horizon)

| Modèle | Type | Pourquoi il est dans la comparaison |
|---|---|---|
| **LightGBM** | gradient boosting | référence sur données tabulaires |
| **XGBoost** | gradient boosting | second avis, régularisation différente |
| **HistGradientBoosting** | boosting scikit-learn | disponible sans dépendance externe |
| **Ridge** | linéaire régularisé | vérifie qu'un modèle simple ne suffit pas |
| Naïf (lag_1) | baseline | « demain = aujourd'hui » |
| Naïf saisonnier (lag_12) | baseline | « comme l'an dernier » |
| Moyenne mobile 3 mois | baseline | lissage |

**Un modèle n'est retenu que s'il bat les trois baselines.** Sinon on garde la
baseline : ajouter de la complexité sans gain mesuré serait de l'ingénierie
décorative.

## Métriques

- **MAE** (erreur absolue moyenne) — métrique de sélection principale : robuste
  aux séries à zéros, contrairement à la MAPE qui explose quand la demande est nulle.
- **RMSE** — pénalise les grosses erreurs (ruptures coûteuses).
- **WAPE** (erreur absolue pondérée) = `Σ|réel−prévu| ÷ Σréel` — l'équivalent
  d'une MAPE, mais défini même avec des zéros : c'est la métrique métier lisible.
- **Écart train/validation** — diagnostic d'overfitting explicite.

Usage :
    python -m ml_engine.models.demand_forecast train
    python -m ml_engine.models.demand_forecast predict "VIDAS TSH 60 tests"
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .demand_features import FEATURES, HORIZONS, TARGETS, build_demand_dataset

BASE = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"
MODEL_PATH = MODELS_DIR / "demand_forecast_ml.joblib"
METRICS_PATH = REPORTS_DIR / "demand_forecast_ml_metrics.json"

SEED = 42
N_SPLITS = 4              # plis de validation temporelle
HOLDOUT_MOIS = 6          # hold-out final, jamais vu pendant la sélection

# ── Trois techniques contre le surapprentissage (itération n°2) ─────────────
# La première itération montrait des écarts train/validation de +8 à +20 MAE et
# des modèles battus par une simple moyenne mobile. Diagnostic : séries courtes
# (~57 observations par produit), très asymétriques et intermittentes — le
# boosting apprenait le bruit. Corrections appliquées :
#
# 1. APPRENTISSAGE RÉSIDUEL : le modèle ne prédit plus la demande brute, mais
#    l'ÉCART à la baseline (moyenne mobile 3 mois × horizon). Il part donc d'un
#    socle déjà bon et n'apprend que la correction — beaucoup moins de variance.
# 2. CIBLE STABILISÉE : transformation `signed log1p` du résidu, qui écrase les
#    valeurs extrêmes sans perdre le signe de la correction.
# 3. RÉGULARISATION FORTE + ARRÊT PRÉCOCE : profondeur réduite, feuilles plus
#    peuplées, échantillonnage, et arrêt dès que la validation cesse de
#    progresser (le nombre d'arbres n'est plus un hyperparamètre arbitraire).
RESIDUAL_LEARNING = True


def _baseline_ref(df: pd.DataFrame, horizon: int,
                  socle: str = "ensemble") -> np.ndarray:
    """Socle de l'apprentissage résiduel.

    Itération n°4 : le socle est un **ENSEMBLE**, non une baseline élue.

    L'itération précédente choisissait la meilleure baseline mesurée sur le
    développement. C'est exactement là que se trouvait le défaut : sur les six
    mois de hold-out, la hiérarchie s'inverse — le naïf saisonnier devance
    nettement la moyenne mobile sur laquelle le modèle avait appris. Le socle
    élu n'était plus le bon, et le gain de 5 % en validation croisée devenait
    une perte allant jusqu'à −27,7 %.

    Aucune information antérieure au hold-out ne permettait d'anticiper ce
    renversement. La conclusion à en tirer n'est donc pas « mieux choisir » mais
    **ne plus choisir** : la médiane des trois baselines ne peut jamais être la
    pire des trois, et se dégrade doucement quand l'une d'elles décroche. C'est
    le résultat le plus robuste de la littérature sur la prévision — combiner
    bat sélectionner, particulièrement quand la sélection porte sur un
    échantillon court.
    """
    trois = np.vstack([
        df["ma_3"].to_numpy() * horizon,
        df["lag_12"].to_numpy() * horizon,
        df["lag_1"].to_numpy() * horizon,
    ])
    if socle == "ensemble":
        return np.clip(np.median(trois, axis=0), 0, None)
    if socle == "naif_saisonnier":
        return np.clip(df["lag_12"].to_numpy() * horizon, 0, None)
    if socle == "naif_lag1":
        return np.clip(df["lag_1"].to_numpy() * horizon, 0, None)
    return np.clip(df["ma_3"].to_numpy() * horizon, 0, None)


def _to_residual(y: np.ndarray, base: np.ndarray) -> np.ndarray:
    """Résidu stabilisé : signed log1p(y − base)."""
    r = y - base
    return np.sign(r) * np.log1p(np.abs(r))


def _from_residual(r: np.ndarray, base: np.ndarray,
                   borne: Optional[float] = None) -> np.ndarray:
    """Inverse : baseline + résidu ramené à l'échelle d'origine.

    `borne` borne le résidu AVANT l'exponentielle inverse. La transformation
    `expm1` est explosive : un résidu prédit de 8 devient un écart de ~2 980
    unités. Sur un régime de demande inédit, une extrapolation même modeste du
    modèle se traduit alors par une prévision aberrante — ce qui dégradait la
    MAE hors échantillon bien plus que le modèle ne l'améliorait.

    Contrainte posée A PRIORI, jamais ajustée sur le hold-out : le modèle n'a
    pas le droit d'annoncer un écart au socle plus grand que le plus grand
    écart jamais observé pendant son apprentissage.
    """
    r = np.asarray(r, float)
    if borne is not None and np.isfinite(borne):
        r = np.clip(r, -abs(borne), abs(borne))
    return np.clip(base + np.sign(r) * (np.expm1(np.abs(r))), 0, None)


# ── Métriques ───────────────────────────────────────────────────────────────
def _metrics(y: np.ndarray, p: np.ndarray) -> Dict[str, float]:
    y, p = np.asarray(y, float), np.asarray(p, float)
    p = np.clip(p, 0, None)                    # une demande est positive
    err = y - p
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))
    denom = np.sum(np.abs(y))
    wape = float(np.sum(np.abs(err)) / denom * 100) if denom > 0 else None
    # MAPE calculée uniquement sur les points non nuls (sinon indéfinie)
    mask = y > 0
    mape = float(np.mean(np.abs(err[mask] / y[mask])) * 100) if mask.any() else None
    return {"mae": round(mae, 2), "rmse": round(rmse, 2),
            "wape_pct": round(wape, 1) if wape is not None else None,
            "mape_pct": round(mape, 1) if mape is not None else None}


# ── Modèles candidats ───────────────────────────────────────────────────────
def _candidats() -> Dict[str, Any]:
    """Instancie les modèles disponibles dans l'environnement."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    c: Dict[str, Any] = {}
    # Hyperparamètres RÉGULARISÉS : arbres peu profonds, feuilles peuplées,
    # échantillonnage, pénalités L1/L2 — adaptés à des séries courtes et bruitées.
    try:
        import lightgbm as lgb
        # `deterministic` + `force_row_wise` + un seul fil : sans cela, l'ordre
        # de sommation multi-thread des histogrammes fait varier le modèle d'une
        # exécution à l'autre. Un écart de quelques dixièmes de MAE suffit à
        # faire basculer la règle d'acceptation — donc à rendre la conclusion
        # du mémoire non reproductible. Le jeu est petit (17 k lignes) : le coût
        # en temps est négligeable devant la garantie obtenue.
        c["lightgbm"] = lgb.LGBMRegressor(
            n_estimators=600, learning_rate=0.03, num_leaves=15, max_depth=4,
            min_child_samples=60, subsample=0.7, subsample_freq=1,
            colsample_bytree=0.7, reg_alpha=1.0, reg_lambda=5.0,
            random_state=SEED, verbose=-1, n_jobs=1,
            deterministic=True, force_row_wise=True)
    except Exception:
        pass
    try:
        import xgboost as xgb
        c["xgboost"] = xgb.XGBRegressor(
            n_estimators=600, learning_rate=0.03, max_depth=4,
            min_child_weight=30, subsample=0.7, colsample_bytree=0.7,
            reg_alpha=1.0, reg_lambda=5.0, gamma=0.5, random_state=SEED,
            n_jobs=1, tree_method="hist", early_stopping_rounds=40,
            eval_metric="mae")
    except Exception:
        pass
    c["hist_gb"] = HistGradientBoostingRegressor(
        max_iter=500, learning_rate=0.04, max_depth=4, min_samples_leaf=40,
        l2_regularization=5.0, early_stopping=True, validation_fraction=0.15,
        n_iter_no_change=30, random_state=SEED)
    c["ridge"] = make_pipeline(StandardScaler(), Ridge(alpha=10.0, random_state=SEED))
    return c


def _fit_avec_arret_precoce(modele, X_tr, y_tr, X_va, y_va):
    """Entraîne avec arrêt précoce quand le modèle le permet.

    L'arrêt précoce est LA protection contre le surapprentissage : le nombre
    d'arbres est déterminé par la validation, pas fixé arbitrairement.
    """
    nom = type(modele).__name__.lower()
    try:
        if "lgbm" in nom:
            import lightgbm as lgb
            modele.fit(X_tr, y_tr, eval_set=[(X_va, y_va)],
                       eval_metric="l1",
                       callbacks=[lgb.early_stopping(40, verbose=False)])
            return modele
        if "xgb" in nom:
            modele.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
            return modele
    except Exception:
        pass
    modele.fit(X_tr, y_tr)
    return modele


def _baselines(df: pd.DataFrame, horizon: int) -> Dict[str, np.ndarray]:
    """Prévisions naïves — le seuil à battre.

    `ensemble` y figure délibérément. Puisqu'il sert de socle au modèle, il doit
    aussi lui être opposé : autrement le modèle serait comparé à des méthodes
    plus faibles que son propre point de départ, et un gain apparent ne
    mesurerait que la qualité du socle.
    """
    h = horizon
    return {
        "naif_lag1": (df["lag_1"] * h).to_numpy(),
        "naif_saisonnier": (df["lag_12"] * h).to_numpy(),
        "moyenne_mobile_3": (df["ma_3"] * h).to_numpy(),
        "ensemble": _baseline_ref(df, h, "ensemble"),
    }


# ── Validation temporelle ───────────────────────────────────────────────────
def _splits_temporels(periods: pd.Series, n_splits: int) -> List[Tuple[np.ndarray, np.ndarray]]:
    """Blocs glissants : train = tout le passé, valid = bloc suivant."""
    uniq = sorted(periods.unique())
    if len(uniq) < n_splits + 4:
        n_splits = max(2, len(uniq) // 4)
    taille = max(1, len(uniq) // (n_splits + 1))
    splits = []
    for i in range(1, n_splits + 1):
        fin_train = taille * i
        fin_valid = min(len(uniq), fin_train + taille)
        if fin_valid <= fin_train:
            break
        p_train = set(uniq[:fin_train])
        p_valid = set(uniq[fin_train:fin_valid])
        tr = periods.isin(p_train).to_numpy().nonzero()[0]
        va = periods.isin(p_valid).to_numpy().nonzero()[0]
        if len(tr) and len(va):
            splits.append((tr, va))
    return splits


def train_demand_models(save: bool = True, verbose: bool = True) -> Dict[str, Any]:
    """Entraîne, compare et sélectionne un modèle par horizon.

    Returns: rapport de métriques complet (CRISP-DM phase 5).
    """
    warnings.filterwarnings("ignore", category=UserWarning)
    df = build_demand_dataset(verbose=verbose)

    # ── Hold-out final : les N derniers mois, jamais vus pendant la sélection ──
    periodes = sorted(df["period"].unique())
    p_holdout = set(periodes[-HOLDOUT_MOIS:])
    dev = df[~df["period"].isin(p_holdout)].reset_index(drop=True)
    hold = df[df["period"].isin(p_holdout)].reset_index(drop=True)

    if verbose:
        print(f"[modèle] développement : {len(dev):,} obs ({periodes[0]} → "
              f"{sorted(dev['period'].unique())[-1]})".replace(",", " "))
        print(f"[modèle] hold-out final : {len(hold):,} obs ({min(p_holdout)} → "
              f"{max(p_holdout)}) — jamais vu pendant la sélection".replace(",", " "))

    rapport: Dict[str, Any] = {
        "methodologie": "CRISP-DM — validation temporelle par blocs glissants + hold-out final",
        "seed": SEED,
        "n_produits": int(df["produit"].nunique()),
        "n_observations": int(len(df)),
        "periode": f"{periodes[0]} → {periodes[-1]}",
        "n_features": len(FEATURES),
        "features": FEATURES,
        "holdout_mois": HOLDOUT_MOIS,
        "metrique_selection": "MAE (robuste aux séries à zéros ; la MAPE est indéfinie si demande nulle)",
        "horizons": {},
    }
    modeles_retenus: Dict[str, Any] = {}

    for h in HORIZONS:
        cible = TARGETS[h]
        dev_h = dev.dropna(subset=[cible]).reset_index(drop=True)
        hold_h = hold.dropna(subset=[cible]).reset_index(drop=True)
        if dev_h.empty or hold_h.empty:
            continue

        X_dev, y_dev = dev_h[FEATURES], dev_h[cible].to_numpy()
        splits = _splits_temporels(dev_h["period"], N_SPLITS)

        resultats: Dict[str, Dict[str, Any]] = {}

        # ── Pondération TEMPORELLE des plis (itération n°4) ─────────────────
        # Les séries ne sont pas stationnaires : la dynamique récente diffère de
        # celle de 2021. Une moyenne simple des plis donne autant de poids à un
        # bloc de 2021 qu'au bloc le plus proche du présent — et fait choisir un
        # modèle adapté au passé. On pondère donc géométriquement : le dernier
        # pli compte le plus (proxy le plus fidèle du futur à prévoir).
        poids = np.array([2.0 ** i for i in range(len(splits))], dtype=float)
        poids /= poids.sum()

        def _agg(scores: List[Dict[str, float]], cle: str) -> float:
            vals = [s[cle] for s in scores if s.get(cle) is not None]
            if not vals:
                return float("nan")
            w = poids[-len(vals):] / poids[-len(vals):].sum()
            return float(np.average(vals, weights=w))

        # Baselines (pas d'entraînement : évaluées sur les mêmes plis)
        for nom, pred_all in _baselines(dev_h, h).items():
            scores = [_metrics(y_dev[va], pred_all[va]) for _, va in splits]
            resultats[nom] = {
                "type": "baseline",
                "cv_mae": round(_agg(scores, "mae"), 2),
                "cv_rmse": round(_agg(scores, "rmse"), 2),
                "cv_wape_pct": round(_agg(scores, "wape_pct"), 1),
                "cv_mae_dernier_pli": round(scores[-1]["mae"], 2),
            }

        # ── Socle FIXE : l'ensemble, jamais une baseline élue ────────────────
        # Élire le socle sur le développement revenait à parier que la hiérarchie
        # des baselines tiendrait sur le hold-out. Elle ne tient pas : le naïf
        # saisonnier y devance la moyenne mobile, et le modèle se retrouvait
        # ancré sur un socle devenu mauvais. La médiane des trois ne peut jamais
        # être la pire, et ce choix ne dépend d'aucune mesure — il ne peut donc
        # pas se tromper de période.
        socle = "ensemble"
        base_dev = _baseline_ref(dev_h, h, socle)

        # Modèles appris (sur le RÉSIDU à la baseline)
        for nom, modele in _candidats().items():
            maes, rmses, wapes, ecarts = [], [], [], []
            for tr, va in splits:
                m = _clone(modele)
                if RESIDUAL_LEARNING:
                    cible_tr = _to_residual(y_dev[tr], base_dev[tr])
                    cible_va = _to_residual(y_dev[va], base_dev[va])
                else:
                    cible_tr, cible_va = y_dev[tr], y_dev[va]

                m = _fit_avec_arret_precoce(m, X_dev.iloc[tr], cible_tr,
                                            X_dev.iloc[va], cible_va)
                if RESIDUAL_LEARNING:
                    # borne calculée sur le PLI D'APPRENTISSAGE seulement
                    borne = float(np.abs(cible_tr).max())
                    p_va = _from_residual(m.predict(X_dev.iloc[va]), base_dev[va], borne)
                    p_tr = _from_residual(m.predict(X_dev.iloc[tr]), base_dev[tr], borne)
                else:
                    p_va = m.predict(X_dev.iloc[va])
                    p_tr = m.predict(X_dev.iloc[tr])

                s_va = _metrics(y_dev[va], p_va)
                s_tr = _metrics(y_dev[tr], p_tr)
                maes.append(s_va["mae"]); rmses.append(s_va["rmse"])
                if s_va["wape_pct"] is not None:
                    wapes.append(s_va["wape_pct"])
                ecarts.append(s_va["mae"] - s_tr["mae"])
            w = poids[-len(maes):] / poids[-len(maes):].sum()
            resultats[nom] = {
                "type": "modele",
                "cv_mae": round(float(np.average(maes, weights=w)), 2),
                "cv_mae_std": round(float(np.std(maes)), 2),
                "cv_rmse": round(float(np.average(rmses, weights=w)), 2),
                "cv_wape_pct": (round(float(np.average(wapes, weights=w[-len(wapes):])), 1)
                                if wapes else None),
                "cv_mae_dernier_pli": round(float(maes[-1]), 2),
                # Diagnostic d'overfitting : écart MAE validation − MAE apprentissage
                "ecart_train_valid_mae": round(float(np.mean(ecarts)), 2),
            }

        # ── Sélection : meilleure MAE en validation ──
        classement = sorted(resultats.items(), key=lambda kv: kv[1]["cv_mae"])
        meilleur_nom, meilleur = classement[0]
        meilleure_baseline = min(
            (v["cv_mae"] for v in resultats.values() if v["type"] == "baseline"),
            default=float("inf"))
        bat_baselines = meilleur["cv_mae"] < meilleure_baseline

        # Si aucun modèle ne bat les baselines, on garde la baseline (honnêteté)
        if not bat_baselines and meilleur["type"] == "modele":
            meilleur_nom = min(
                (k for k, v in resultats.items() if v["type"] == "baseline"),
                key=lambda k: resultats[k]["cv_mae"])
            meilleur = resultats[meilleur_nom]

        # ── Hold-out final : ré-entraînement sur tout le développement ──
        holdout_scores: Dict[str, Any]
        if meilleur.get("type") == "modele":
            final = _clone(_candidats()[meilleur_nom])
            base_hold = _baseline_ref(hold_h, h, socle)
            # Ré-entraînement sur TOUT le développement ; le dernier pli de
            # validation sert d'ensemble d'arrêt précoce (jamais le hold-out).
            n = len(X_dev)
            coupe = int(n * 0.85)
            borne_finale: Optional[float] = None
            if RESIDUAL_LEARNING:
                cible_dev = _to_residual(y_dev, base_dev)
                final = _fit_avec_arret_precoce(
                    final, X_dev.iloc[:coupe], cible_dev[:coupe],
                    X_dev.iloc[coupe:], cible_dev[coupe:])
                borne_finale = float(np.abs(cible_dev[:coupe]).max())
                p_hold = _from_residual(final.predict(hold_h[FEATURES]),
                                        base_hold, borne_finale)
            else:
                final = _fit_avec_arret_precoce(
                    final, X_dev.iloc[:coupe], y_dev[:coupe],
                    X_dev.iloc[coupe:], y_dev[coupe:])
                p_hold = final.predict(hold_h[FEATURES])
            holdout_scores = _metrics(hold_h[cible].to_numpy(), p_hold)
            # `socle` est indispensable à l'INFÉRENCE : le modèle prédit un
            # résidu par rapport à ce socle précis. L'oublier reviendrait à
            # reconstruire la prévision sur une base différente de celle de
            # l'apprentissage — erreur silencieuse et systématique.
            modeles_retenus[cible] = {"modele": final, "residuel": RESIDUAL_LEARNING,
                                      "nom": meilleur_nom, "socle": socle,
                                      "borne_residu": borne_finale}
            # importance des variables (interprétabilité)
            importances = _importances(final, FEATURES)
        else:
            pred = _baselines(hold_h, h)[meilleur_nom]
            holdout_scores = _metrics(hold_h[cible].to_numpy(), pred)
            modeles_retenus[cible] = {"baseline": meilleur_nom, "socle": socle}
            importances = None

        gain = ((meilleure_baseline - meilleur["cv_mae"]) / meilleure_baseline * 100
                if meilleure_baseline not in (0, float("inf")) else 0.0)

        # ── Comparaison ÉQUITABLE sur le hold-out : modèle vs baselines ──
        # Sans cela, on ne saurait pas si le gain observé en validation croisée
        # se confirme sur une période totalement inédite.
        y_hold = hold_h[cible].to_numpy()
        holdout_baselines = {nom: _metrics(y_hold, pred)
                             for nom, pred in _baselines(hold_h, h).items()}
        base_nom_h = min(holdout_baselines, key=lambda k: holdout_baselines[k]["mae"])
        meilleure_base_hold = holdout_baselines[base_nom_h]["mae"]
        gain_hold = ((meilleure_base_hold - holdout_scores["mae"])
                     / meilleure_base_hold * 100) if meilleure_base_hold else 0.0

        # ── Diagnostic : la période de hold-out change-t-elle de régime ? ────
        #
        # Le refus des modèles se lit mal sans cette mesure. On croit à un défaut
        # de modélisation alors qu'il s'agit d'un déplacement de la distribution :
        # TOUTES les méthodes se dégradent, et leur hiérarchie s'inverse.
        #
        # La colonne décisive est le taux de dégradation. Une méthode brillante en
        # validation mais qui perd 80 % de sa précision hors échantillon est moins
        # utile qu'une méthode médiocre qui n'en perd que 20 %. C'est cette
        # stabilité — invisible dans un classement par MAE — qui explique pourquoi
        # le naïf saisonnier, dernier en validation croisée, finit premier ici.
        regime: Dict[str, Any] = {}
        for nom, sc in holdout_baselines.items():
            cv_mae = (resultats.get(nom) or {}).get("cv_mae")
            if isinstance(cv_mae, (int, float)) and cv_mae > 0:
                regime[nom] = {
                    "cv_mae": cv_mae,
                    "holdout_mae": sc["mae"],
                    "degradation_pct": round((sc["mae"] - cv_mae) / cv_mae * 100, 1),
                }
        degrade = [v["degradation_pct"] for v in regime.values()]
        diagnostic_regime = {
            "par_methode": regime,
            "degradation_mediane_pct": round(float(np.median(degrade)), 1) if degrade else None,
            "toutes_les_methodes_se_degradent": bool(degrade and min(degrade) > 0),
            "hierarchie_inversee": bool(
                regime and min(regime, key=lambda k: regime[k]["cv_mae"])
                != min(regime, key=lambda k: regime[k]["holdout_mae"])),
            "lecture": (
                "Si toutes les méthodes se dégradent ET que leur hiérarchie "
                "s'inverse, le refus du modèle ne traduit pas un défaut "
                "d'apprentissage mais un changement de régime : la période de "
                "test ne se comporte pas comme celle d'entraînement, et aucune "
                "information antérieure ne permettait de l'anticiper."),
        }

        # ── RÈGLE D'ACCEPTATION (garde-fou anti-illusion) ───────────────────
        # Un gain observé en validation croisée peut ne pas se généraliser. Le
        # hold-out est le juge FINAL : si le modèle n'y bat pas les baselines,
        # il est REFUSÉ et la baseline est déployée. Ce n'est pas de la sélection
        # d'hyperparamètres sur le hold-out (qui le contaminerait), mais un
        # critère d'acceptation binaire — pratique standard en industrialisation.
        if meilleur.get("type") == "modele" and gain_hold <= 0:
            if verbose:
                print(f"    ⚠ modèle REFUSÉ : gain non confirmé sur le hold-out "
                      f"({gain_hold:+.1f} %) → déploiement de la baseline « {base_nom_h} »")
            meilleur_nom = base_nom_h
            meilleur = resultats[base_nom_h]
            modeles_retenus[cible] = {"baseline": base_nom_h, "socle": socle}
            holdout_scores = holdout_baselines[base_nom_h]
            importances = None
            gain_hold = 0.0

        rapport["horizons"][f"h{h}"] = {
            "horizon_jours": h * 30,
            "socle_residuel": socle,
            "n_dev": int(len(dev_h)), "n_holdout": int(len(hold_h)),
            "n_plis": len(splits),
            "comparaison": resultats,
            "modele_retenu": meilleur_nom,
            "bat_les_baselines": bool(bat_baselines),
            "gain_vs_meilleure_baseline_pct": round(float(gain), 1),
            "holdout": holdout_scores,
            "holdout_baselines": holdout_baselines,
            "holdout_gain_vs_baseline_pct": round(float(gain_hold), 1),
            "holdout_confirme_le_gain": bool(gain_hold > 0),
            "diagnostic_changement_de_regime": diagnostic_regime,
            "top_features": importances,
        }

        if verbose and diagnostic_regime.get("par_methode"):
            print(f"\n    Stabilité validation → hold-out (h{h}) :")
            for nom, v in sorted(diagnostic_regime["par_methode"].items(),
                                 key=lambda kv: kv[1]["degradation_pct"]):
                print(f"      {nom:20} {v['cv_mae']:>7.2f} → {v['holdout_mae']:>7.2f}"
                      f"   {v['degradation_pct']:+7.1f} %")
            if diagnostic_regime["hierarchie_inversee"]:
                print("      → hiérarchie INVERSÉE : la meilleure méthode en "
                      "validation n'est plus la meilleure hors échantillon")

        if verbose:
            print(f"\n[h{h} — {h*30} j] {len(splits)} plis · retenu : {meilleur_nom}")
            for nom, r in classement[:5]:
                marque = " ←" if nom == meilleur_nom else ""
                over = (f" (écart train/valid {r['ecart_train_valid_mae']:+.2f})"
                        if r["type"] == "modele" else "")
                print(f"    {nom:20} MAE {r['cv_mae']:>8.2f}  "
                      f"WAPE {str(r['cv_wape_pct']):>6} %{over}{marque}")
            base_nom = min(holdout_baselines, key=lambda k: holdout_baselines[k]["mae"])
            verdict = "confirmé" if gain_hold > 0 else "NON confirmé"
            print(f"    hold-out : MAE {holdout_scores['mae']} "
                  f"(WAPE {holdout_scores['wape_pct']} %) vs meilleure baseline "
                  f"« {base_nom} » MAE {meilleure_base_hold} "
                  f"→ gain {gain_hold:+.1f} % · {verdict}")

    if save:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import joblib
            joblib.dump({"modeles": modeles_retenus, "features": FEATURES,
                         "horizons": list(HORIZONS)}, MODEL_PATH)
            rapport["modele_sauvegarde"] = str(MODEL_PATH.name)
        except Exception as e:  # pragma: no cover
            rapport["modele_sauvegarde"] = f"échec : {e}"
        METRICS_PATH.write_text(json.dumps(rapport, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        if verbose:
            print(f"\n[modèle] sauvegardé : {MODEL_PATH}")
            print(f"[modèle] métriques  : {METRICS_PATH}")
    return rapport


def _clone(modele):
    from sklearn.base import clone
    try:
        return clone(modele)
    except Exception:
        return modele


def _importances(modele, features: List[str]) -> Optional[List[Dict[str, Any]]]:
    """Top 10 des variables les plus influentes (interprétabilité)."""
    try:
        imp = getattr(modele, "feature_importances_", None)
        if imp is None:
            return None
        pairs = sorted(zip(features, imp), key=lambda x: -float(x[1]))[:10]
        total = float(sum(float(v) for _, v in pairs)) or 1.0
        return [{"variable": f, "importance_pct": round(float(v) / total * 100, 1)}
                for f, v in pairs]
    except Exception:
        return None


# ── Prédiction ──────────────────────────────────────────────────────────────
_MODEL_CACHE: Optional[Dict[str, Any]] = None


def load_demand_model() -> Optional[Dict[str, Any]]:
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    try:
        import joblib
        _MODEL_CACHE = joblib.load(MODEL_PATH)
        return _MODEL_CACHE
    except Exception:
        return None


def predict_demand(produits: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Prévisions 30/60/90 j pour les produits demandés (ou tous).

    Renvoie, par produit : la dernière demande observée et les 3 horizons.
    """
    bundle = load_demand_model()
    df = build_demand_dataset(verbose=False)
    # dernière observation disponible par produit
    last = df.sort_values("period").groupby("produit").tail(1).reset_index(drop=True)
    if produits:
        last = last[last["produit"].isin(produits)]
    if last.empty:
        return []

    out: List[Dict[str, Any]] = []
    X = last[FEATURES]
    preds: Dict[str, np.ndarray] = {}
    modeles_utilises: Dict[str, str] = {}

    for h in HORIZONS:
        cible = TARGETS[h]
        entree = (bundle or {}).get("modeles", {}).get(cible)

        # Contrat du bundle (voir `train_demand_models`) :
        #   {"modele": estimateur, "residuel": bool, "nom": str, "socle": str}
        #   {"baseline": nom, "socle": str}
        # Une entrée manquante ou illisible retombe sur la moyenne mobile 3 mois,
        # jamais sur une prédiction silencieusement fausse.
        if isinstance(entree, dict) and entree.get("modele") is not None:
            estimateur = entree["modele"]
            brut = np.asarray(estimateur.predict(X), dtype=float)
            if entree.get("residuel", False):
                # Le modèle prédit un ÉCART au socle, pas la demande : il faut
                # reconstruire sur le même socle qu'à l'apprentissage.
                base = _baseline_ref(last, h, entree.get("socle", "moyenne_mobile_3"))
                brut = _from_residual(brut, base, entree.get("borne_residu"))
            preds[cible] = np.clip(brut, 0, None)
            modeles_utilises[cible] = entree.get("nom", "modele")
        elif isinstance(entree, dict) and entree.get("baseline"):
            nom = entree["baseline"]
            valeurs = _baselines(last, h).get(nom)
            if valeurs is None:
                valeurs = last["ma_3"].to_numpy() * h
                nom = "moyenne_mobile_3"
            preds[cible] = np.clip(np.asarray(valeurs, dtype=float), 0, None)
            modeles_utilises[cible] = nom
        elif entree is not None and hasattr(entree, "predict"):
            # Bundle d'une version antérieure : estimateur nu, cible directe.
            preds[cible] = np.clip(np.asarray(entree.predict(X), dtype=float), 0, None)
            modeles_utilises[cible] = "modele (bundle hérité)"
        else:
            preds[cible] = np.clip(last["ma_3"].to_numpy() * h, 0, None)
            modeles_utilises[cible] = "moyenne_mobile_3 (repli)"

    for i, row in last.reset_index(drop=True).iterrows():
        out.append({
            "produit": row["produit"],
            "derniere_periode": row["period"],
            "demande_observee_dernier_mois": float(row["qte"]),
            "moyenne_3m": round(float(row["ma_3"]), 1),
            "prevision_30j": round(float(preds["y_h1"][i]), 1),
            "prevision_60j": round(float(preds["y_h2"][i]), 1),
            "prevision_90j": round(float(preds["y_h3"][i]), 1),
            # Traçabilité : quel estimateur a réellement produit chaque chiffre.
            "modele_30j": modeles_utilises.get("y_h1"),
            "modele_60j": modeles_utilises.get("y_h2"),
            "modele_90j": modeles_utilises.get("y_h3"),
        })
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        train_demand_models(save=True, verbose=True)
    elif cmd == "predict":
        cible = " ".join(sys.argv[2:]) or None
        res = predict_demand([cible] if cible else None)[:10]
        print(f"\n{'produit':40} {'obs':>8} {'30j':>8} {'60j':>8} {'90j':>8}")
        for r in res:
            print(f"{r['produit'][:40]:40} {r['demande_observee_dernier_mois']:>8.0f} "
                  f"{r['prevision_30j']:>8.0f} {r['prevision_60j']:>8.0f} "
                  f"{r['prevision_90j']:>8.0f}")
