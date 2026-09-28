"""
evaluation_demande/comparer_modeles.py
======================================
Phase 4 et 5 du CRISP-DM « demande par référence » : la compétition complète.

Chaque candidat est évalué dans le MÊME walk-forward que les règles simples de
`ml_engine.forecasting.demande_reference` (mêmes origines, même éligibilité, mêmes
cibles), ce qui rend toutes les WAPE directement comparables.

Deux phases, séparées volontairement :

    python evaluation_demande/comparer_modeles.py --phase validation
        Règles, modèles statistiques, modèles appris réglés par Optuna, deep
        learning — tout est mesuré sur les 12 origines de validation. Les
        réglages retenus et le classement sont figés dans
        `evaluation_demande/resultats/validation.json`.

    python evaluation_demande/comparer_modeles.py --phase test
        Relit les choix figés, puis mesure une seule fois sur les 18 origines de
        test. Aucun réglage n'est modifié à cette étape : le script refuse de
        tourner si `validation.json` est absent.

Pourquoi WAPE et pas la perte d'entraînement
--------------------------------------------
La WAPE est une erreur ABSOLUE : la meilleure prévision ponctuelle, pour elle,
est la MÉDIANE de la demande future, pas sa moyenne. Or une perte Tweedie ou
Poisson apprend une moyenne. Sur une demande en pics (pic / médiane de 3,6 en
médiane, 182 au maximum), l'écart est grand. La perte fait donc partie de
l'espace de recherche d'Optuna : Tweedie, Poisson, L1, quantile 0,5, Huber.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from ml_engine.forecasting import demande_reference as dr  # noqa: E402

RESULTATS = RACINE / "evaluation_demande" / "resultats"
SEED = dr.SEED


# ═══════════════════════════════════════════════════════════════════════════
# Candidats fondés sur les variables (modèles globaux)
# ═══════════════════════════════════════════════════════════════════════════
def _preparer(X: pd.DataFrame, normaliser: bool) -> Tuple[pd.DataFrame, np.ndarray]:
    X = X.copy()
    e = dr.echelle(X) if normaliser else np.ones(len(X))
    if normaliser:
        for c in dr.COLONNES_QUANTITE:
            if c in X:
                X[c] = X[c] / e
    return X, e


def _jeu_entrainement(p, jusqu_a: int, h: int, normaliser: bool):
    X, y, _, _ = dr.jeu(p, range(12, jusqu_a - h + 1), h)
    X, e = _preparer(X, normaliser)
    return X, y / e


def _X_prediction(p, o: int, h: int, masque, normaliser: bool):
    X = dr.variables(p, o, h, masque)
    X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
    return _preparer(X, normaliser)


class ModeleVariables:
    """Adaptateur commun : un estimateur qui apprend sur les variables."""

    def __init__(self, nom: str, fabrique: Callable[[], Any], normaliser: bool,
                 encodage: str = "categorie"):
        self.nom, self.fabrique, self.normaliser, self.encodage = nom, fabrique, normaliser, encodage

    def _enc(self, X: pd.DataFrame) -> Any:
        if self.encodage == "categorie":
            return X
        if self.encodage == "codes":
            X = X.copy(); X["gamme"] = X["gamme"].cat.codes; return X
        if self.encodage == "numerique":           # modèles linéaires / réseaux
            X = X.copy(); X["gamme"] = X["gamme"].cat.codes
            return X.fillna(X.median(numeric_only=True)).fillna(0.0)
        raise ValueError(self.encodage)

    def entrainer(self, p, jusqu_a: int, h: int):
        X, y = _jeu_entrainement(p, jusqu_a, h, self.normaliser)
        m = self.fabrique()
        m.fit(self._enc(X), y)
        return m

    def predire(self, m, p, o: int, h: int, masque) -> np.ndarray:
        X, e = _X_prediction(p, o, h, masque, self.normaliser)
        return np.maximum(np.asarray(m.predict(self._enc(X))).ravel() * e, 0.0)


# ── LightGBM ────────────────────────────────────────────────────────────────
def lgbm_depuis(params: Dict[str, Any]) -> ModeleVariables:
    import lightgbm as lgb
    q = dict(params)
    norm = q.pop("normaliser")
    obj = q.pop("perte")
    extra: Dict[str, Any] = {}
    if obj == "tweedie":
        extra = {"objective": "tweedie", "tweedie_variance_power": q.pop("tweedie_p")}
    elif obj == "quantile":
        extra = {"objective": "quantile", "alpha": 0.5}
    else:
        extra = {"objective": obj}
    q.pop("tweedie_p", None)
    return ModeleVariables(
        f"lightgbm_{obj}", lambda: lgb.LGBMRegressor(
            **q, **extra, subsample_freq=1, random_state=SEED, n_jobs=1,
            deterministic=True, force_row_wise=True, verbose=-1), norm)


def espace_lgbm(t) -> Dict[str, Any]:
    perte = t.suggest_categorical("perte", ["tweedie", "poisson", "l1", "quantile", "huber"])
    d = {"perte": perte,
         "normaliser": t.suggest_categorical("normaliser", [True, False]),
         "learning_rate": t.suggest_float("learning_rate", 0.01, 0.1, log=True),
         "n_estimators": t.suggest_int("n_estimators", 150, 1200, step=50),
         "num_leaves": t.suggest_int("num_leaves", 7, 63),
         "min_child_samples": t.suggest_int("min_child_samples", 10, 300, log=True),
         "subsample": t.suggest_float("subsample", 0.5, 1.0),
         "colsample_bytree": t.suggest_float("colsample_bytree", 0.4, 1.0),
         "reg_lambda": t.suggest_float("reg_lambda", 1e-3, 30.0, log=True)}
    d["tweedie_p"] = t.suggest_float("tweedie_p", 1.05, 1.9) if perte == "tweedie" else 1.5
    return d


# ── XGBoost ─────────────────────────────────────────────────────────────────
def xgb_depuis(params: Dict[str, Any]) -> ModeleVariables:
    import xgboost as xgb
    q = dict(params)
    norm = q.pop("normaliser")
    obj = q.pop("perte")
    tp = q.pop("tweedie_p", 1.5)
    extra = {"objective": obj}
    if obj == "reg:tweedie":
        extra["tweedie_variance_power"] = tp
    if obj == "reg:quantileerror":
        extra["quantile_alpha"] = 0.5
    return ModeleVariables(
        f"xgboost_{obj.split(':')[-1]}", lambda: xgb.XGBRegressor(
            **q, **extra, tree_method="hist", enable_categorical=True,
            random_state=SEED, n_jobs=1, verbosity=0), norm)


def espace_xgb(t) -> Dict[str, Any]:
    perte = t.suggest_categorical("perte", ["reg:tweedie", "count:poisson", "reg:absoluteerror",
                                            "reg:quantileerror", "reg:pseudohubererror"])
    d = {"perte": perte,
         "normaliser": t.suggest_categorical("normaliser", [True, False]),
         "learning_rate": t.suggest_float("learning_rate", 0.01, 0.1, log=True),
         "n_estimators": t.suggest_int("n_estimators", 150, 1200, step=50),
         "max_depth": t.suggest_int("max_depth", 3, 8),
         "min_child_weight": t.suggest_float("min_child_weight", 0.5, 50.0, log=True),
         "subsample": t.suggest_float("subsample", 0.5, 1.0),
         "colsample_bytree": t.suggest_float("colsample_bytree", 0.4, 1.0),
         "reg_lambda": t.suggest_float("reg_lambda", 1e-3, 30.0, log=True)}
    d["tweedie_p"] = t.suggest_float("tweedie_p", 1.05, 1.9) if perte == "reg:tweedie" else 1.5
    return d


# ── CatBoost ────────────────────────────────────────────────────────────────
def cat_depuis(params: Dict[str, Any]) -> ModeleVariables:
    from catboost import CatBoostRegressor
    q = dict(params)
    norm = q.pop("normaliser")
    perte = q.pop("perte")
    tp = q.pop("tweedie_p", 1.5)
    loss = {"tweedie": f"Tweedie:variance_power={tp}", "poisson": "Poisson",
            "mae": "MAE", "quantile": "Quantile:alpha=0.5", "rmse": "RMSE"}[perte]

    class _Cat(CatBoostRegressor):
        def fit(self, X, y, **kw):   # noqa: D401
            X = X.copy(); X["gamme"] = X["gamme"].astype(str)
            return super().fit(X, y, cat_features=["gamme"], verbose=False, **kw)

        def predict(self, X, **kw):
            # CatBoost renvoie déjà l'espérance (exponentielle appliquée) pour
            # les pertes Poisson et Tweedie. Une première version appliquait
            # l'exponentielle une seconde fois : ses essais Poisson et Tweedie
            # donnaient des WAPE absurdes (176 %, 188 %) et la recherche les
            # évitait. Corrigé, puis CatBoost entièrement re-réglé.
            X = X.copy(); X["gamme"] = X["gamme"].astype(str)
            return super().predict(X, **kw)
    return ModeleVariables(f"catboost_{perte}", lambda: _Cat(
        loss_function=loss, random_seed=SEED, thread_count=1, allow_writing_files=False, **q), norm)


def espace_cat(t) -> Dict[str, Any]:
    perte = t.suggest_categorical("perte", ["tweedie", "poisson", "mae", "quantile", "rmse"])
    d = {"perte": perte,
         "normaliser": t.suggest_categorical("normaliser", [True, False]),
         "learning_rate": t.suggest_float("learning_rate", 0.02, 0.15, log=True),
         "iterations": t.suggest_int("iterations", 200, 1000, step=100),
         "depth": t.suggest_int("depth", 3, 8),
         "l2_leaf_reg": t.suggest_float("l2_leaf_reg", 0.5, 30.0, log=True)}
    d["tweedie_p"] = t.suggest_float("tweedie_p", 1.05, 1.9) if perte == "tweedie" else 1.5
    return d


# ── Régression de Poisson (référence linéaire globale) ──────────────────────
def poisson_depuis(params: Dict[str, Any]) -> ModeleVariables:
    from sklearn.linear_model import PoissonRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    a = params["alpha"]
    return ModeleVariables("regression_poisson", lambda: make_pipeline(
        StandardScaler(), PoissonRegressor(alpha=a, max_iter=2000)), True, "numerique")


def espace_poisson(t) -> Dict[str, Any]:
    return {"alpha": t.suggest_float("alpha", 1e-4, 10.0, log=True)}


# ── MLP global (PyTorch) sur les mêmes variables ────────────────────────────
class MLPTorch:
    """Réseau dense sur les variables normalisées, perte L1 (cohérente avec la
    WAPE). Petite taille assumée : ~15 000 lignes d'apprentissage."""

    def __init__(self, cachees: int = 64, couches: int = 2, dropout: float = 0.1,
                 lr: float = 1e-3, epoques: int = 60, poids: float = 1e-4, lot: int = 256):
        self.cfg = dict(cachees=cachees, couches=couches, dropout=dropout, lr=lr,
                        epoques=epoques, poids=poids, lot=lot)

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        import torch
        from torch import nn
        torch.manual_seed(SEED); torch.set_num_threads(1)
        Xn = X.values.astype(np.float32)
        self.mu, self.sd = np.nanmean(Xn, 0), np.nanstd(Xn, 0) + 1e-6
        Xn = np.nan_to_num((Xn - self.mu) / self.sd)
        c = self.cfg
        couches: List[Any] = []
        d_in = Xn.shape[1]
        for _ in range(c["couches"]):
            couches += [nn.Linear(d_in, c["cachees"]), nn.ReLU(), nn.Dropout(c["dropout"])]
            d_in = c["cachees"]
        couches += [nn.Linear(d_in, 1), nn.Softplus()]
        self.net = nn.Sequential(*couches)
        opt = torch.optim.AdamW(self.net.parameters(), lr=c["lr"], weight_decay=c["poids"])
        Xt, yt = torch.tensor(Xn), torch.tensor(y.astype(np.float32)).unsqueeze(1)
        g = torch.Generator().manual_seed(SEED)
        for _ in range(c["epoques"]):
            perm = torch.randperm(len(Xt), generator=g)
            for i in range(0, len(Xt), c["lot"]):
                b = perm[i:i + c["lot"]]
                opt.zero_grad()
                loss = (self.net(Xt[b]) - yt[b]).abs().mean()
                loss.backward(); opt.step()
        self.net.eval()
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        import torch
        Xn = np.nan_to_num((X.values.astype(np.float32) - self.mu) / self.sd)
        with torch.no_grad():
            return self.net(torch.tensor(Xn)).numpy().ravel()


def mlp_depuis(params: Dict[str, Any]) -> ModeleVariables:
    q = dict(params)
    return ModeleVariables("mlp_global", lambda: MLPTorch(**q), True, "numerique")


def espace_mlp(t) -> Dict[str, Any]:
    return {"cachees": t.suggest_categorical("cachees", [32, 64, 128]),
            "couches": t.suggest_int("couches", 1, 3),
            "dropout": t.suggest_float("dropout", 0.0, 0.3),
            "lr": t.suggest_float("lr", 3e-4, 3e-3, log=True),
            "epoques": t.suggest_int("epoques", 20, 80, step=10),
            "poids": t.suggest_float("poids", 1e-6, 1e-2, log=True)}




# ═══════════════════════════════════════════════════════════════════════════
# Modèles par série (statsforecast) et réseaux de séries (neuralforecast)
# ═══════════════════════════════════════════════════════════════════════════
def _long(p, jusqu_a: int, masque: Optional[np.ndarray] = None) -> pd.DataFrame:
    """Format long attendu par Nixtla, séries complètes depuis 2021-01 (zéros
    compris : un mois sans vente est une observation, pas une absence)."""
    idx = np.flatnonzero(masque) if masque is not None else np.arange(len(p.refs))
    Y = p.Y[idx, :jusqu_a + 1]
    return pd.DataFrame({"unique_id": np.repeat([p.refs[i] for i in idx], Y.shape[1]),
                         "ds": np.tile(p.mois[:jusqu_a + 1], len(idx)),
                         "y": Y.ravel().astype(float)})


def _extraire_horizons(fc: pd.DataFrame, p, o: int, masque: np.ndarray, col: str
                       ) -> Dict[int, np.ndarray]:
    """Prévision de chaque référence éligible, alignée sur l'ordre du panel."""
    ordre = [p.refs[i] for i in np.flatnonzero(masque)]
    out = {}
    for h in dr.HORIZONS:
        if o + h >= p.Y.shape[1]:
            continue
        cible = p.mois[o + h]
        v = fc[fc["ds"] == cible].set_index("unique_id")[col]
        out[h] = np.maximum(v.reindex(ordre).fillna(0.0).values, 0.0)
    return out


def walk_forward_series(p, origines_: List[int], ajuster: Callable[[int], Any],
                        prevoir: Callable[[Any, int, np.ndarray], pd.DataFrame],
                        colonnes: Dict[str, str], rafraichissement: int = 1
                        ) -> Dict[str, pd.DataFrame]:
    """Walk-forward pour les modèles qui prévoient h = 1..3 d'un coup.

    `ajuster(o)` renvoie un objet entraîné sur le passé de `o` ; `prevoir`
    renvoie le format long de Nixtla. `colonnes` : nom du candidat → colonne.
    """
    lignes: Dict[str, List[pd.DataFrame]] = {n: [] for n in colonnes}
    etat, depuis = None, None
    for o in origines_:
        if etat is None or o - depuis >= rafraichissement:
            etat, depuis = ajuster(o), o
        m = dr.eligibles(p, o)
        fc = prevoir(etat, o, m)
        for nom, col in colonnes.items():
            for h, v in _extraire_horizons(fc, p, o, m, col).items():
                lignes[nom].append(pd.DataFrame({
                    "h": h, "origine": o, "ref": np.flatnonzero(m),
                    "y": p.Y[m, o + h], "yhat": v}))
    return {n: pd.concat(l, ignore_index=True) for n, l in lignes.items()}


def statistiques(p, origines_: List[int]) -> Dict[str, pd.DataFrame]:
    from statsforecast import StatsForecast
    from statsforecast.models import ADIDA, IMAPA, AutoETS, AutoTheta
    modeles = [AutoETS(season_length=12, alias="ets"), AutoTheta(season_length=12, alias="theta"),
               ADIDA(alias="adida"), IMAPA(alias="imapa")]

    def prevoir(_etat, o, m):
        sf = StatsForecast(models=modeles, freq="MS", n_jobs=1)
        return sf.forecast(df=_long(p, o, m), h=max(dr.HORIZONS))
    return walk_forward_series(p, origines_, lambda o: None, prevoir,
                               {"ets": "ets", "theta": "theta", "adida": "adida", "imapa": "imapa"})


def reseau_series(p, origines_: List[int], genre: str, cfg: Dict[str, Any]
                  ) -> Dict[str, pd.DataFrame]:
    """N-HiTS (perte MAE) ou DeepAR (loi binomiale négative, médiane servie),
    entraînés sur les 830 séries du passé, réentraînés tous les 3 mois."""
    import logging
    logging.getLogger("pytorch_lightning").setLevel(logging.ERROR)
    logging.getLogger("lightning").setLevel(logging.ERROR)
    import torch
    torch.set_num_threads(2)
    from neuralforecast import NeuralForecast
    from neuralforecast.losses.pytorch import MAE, DistributionLoss
    from neuralforecast.models import NHITS, DeepAR

    H = max(dr.HORIZONS)
    commun = dict(h=H, input_size=cfg.get("input_size", 24), max_steps=cfg.get("max_steps", 400),
                  random_seed=SEED, enable_progress_bar=False, enable_model_summary=False,
                  logger=False, accelerator="cpu", devices=1)

    def fabriquer():
        if genre == "nhits":
            return NHITS(**commun, loss=MAE(), scaler_type="robust",
                         learning_rate=cfg.get("lr", 1e-3), batch_size=cfg.get("batch_size", 64),
                         mlp_units=[[cfg.get("largeur", 256)] * 2] * 3, alias="nhits")
        return DeepAR(**commun, loss=DistributionLoss("NegativeBinomial", level=[80]),
                      scaler_type="robust", learning_rate=cfg.get("lr", 1e-3),
                      lstm_hidden_size=cfg.get("largeur", 64), lstm_n_layers=2,
                      trajectory_samples=100, batch_size=cfg.get("batch_size", 64), alias="deepar")

    def ajuster(o):
        nf = NeuralForecast(models=[fabriquer()], freq="MS")
        nf.fit(df=_long(p, o))
        return nf

    def prevoir(nf, o, m):
        return nf.predict(df=_long(p, o, m))

    col = "nhits" if genre == "nhits" else "deepar-median"
    return walk_forward_series(p, origines_, ajuster, prevoir, {genre: col}, rafraichissement=dr.RAFRAICHISSEMENT)


# ═══════════════════════════════════════════════════════════════════════════
# Walk-forward commun des modèles à variables, et des règles
# ═══════════════════════════════════════════════════════════════════════════
def walk_forward_variables(p, origines_: List[int], modele: ModeleVariables,
                           horizons=dr.HORIZONS) -> pd.DataFrame:
    lignes = []
    for h in horizons:
        yh, y, r, o = dr.walk_forward_appris(
            p, origines_, h, entrainer=lambda o_: modele.entrainer(p, o_, h),
            predire=lambda m_, o_, mk: modele.predire(m_, p, o_, h, mk))
        lignes.append(pd.DataFrame({"h": h, "origine": o, "ref": r, "y": y, "yhat": yh}))
    return pd.concat(lignes, ignore_index=True)


def regles_long(p, origines_: List[int]) -> Dict[str, pd.DataFrame]:
    out: Dict[str, List[pd.DataFrame]] = {}
    for h in dr.HORIZONS:
        preds, y, r, o = dr.predictions_regles(p, origines_, h)
        for nom, v in preds.items():
            out.setdefault(nom, []).append(pd.DataFrame({"h": h, "origine": o, "ref": r, "y": y, "yhat": v}))
    return {n: pd.concat(l, ignore_index=True) for n, l in out.items()}


def score(df: pd.DataFrame, h: int = 1) -> float:
    s = df[df["h"] == h]
    return round(dr.wape(s["y"].values, s["yhat"].values), 3)


def cumul_3_mois(df: pd.DataFrame) -> float:
    """WAPE de la quantité cumulée sur trois mois — ce que l'on commande."""
    piv = df.pivot_table(index=["origine", "ref"], columns="h", values=["y", "yhat"])
    piv = piv.dropna()
    if piv.empty:
        return float("nan")
    return round(dr.wape(piv["y"].sum(axis=1).values, piv["yhat"].sum(axis=1).values), 3)


# ═══════════════════════════════════════════════════════════════════════════
# Réglages par Optuna, sur la validation seule
# ═══════════════════════════════════════════════════════════════════════════
FAMILLES = {
    "regression_poisson": (espace_poisson, poisson_depuis, 15),
    "lightgbm": (espace_lgbm, lgbm_depuis, 80),
    "xgboost": (espace_xgb, xgb_depuis, 50),
    "catboost": (espace_cat, cat_depuis, 30),
    "mlp_global": (espace_mlp, mlp_depuis, 20),
}

# Point de départ de chaque recherche : un réglage « raisonnable » par défaut,
# évalué en premier. Sans lui, 60 essais de TPE n'avaient pas retrouvé pour
# LightGBM un réglage aussi bon qu'un choix standard (32,52 contre 31,69 en
# validation) : la recherche dépensait ses essais sur des pertes inadaptées.
# Mettre le défaut en file est la pratique d'Optuna pour ce cas ; il est jugé,
# comme tous les autres essais, sur la seule validation.
DEFAUTS = {
    "regression_poisson": {"alpha": 0.1},
    "lightgbm": {"perte": "l1", "normaliser": True, "learning_rate": 0.03, "n_estimators": 500,
                 "num_leaves": 31, "min_child_samples": 40, "subsample": 0.8,
                 "colsample_bytree": 0.8, "reg_lambda": 1.0},
    "xgboost": {"perte": "reg:absoluteerror", "normaliser": True, "learning_rate": 0.03,
                "n_estimators": 500, "max_depth": 5, "min_child_weight": 5.0, "subsample": 0.8,
                "colsample_bytree": 0.8, "reg_lambda": 1.0},
    "catboost": {"perte": "mae", "normaliser": True, "learning_rate": 0.05, "iterations": 500,
                 "depth": 6, "l2_leaf_reg": 3.0},
    "mlp_global": {"cachees": 64, "couches": 2, "dropout": 0.1, "lr": 1e-3, "epoques": 40,
                   "poids": 1e-4},
}


def regler(p, famille: str, journal: Callable[[str], None]) -> Tuple[Dict[str, Any], float, List[Dict]]:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    espace, fabrique, n_essais = FAMILLES[famille]
    val = dr.origines(p)["validation"]
    essais: List[Dict[str, Any]] = []

    def objectif(t):
        params = espace(t)
        t0 = time.time()
        try:
            df = walk_forward_variables(p, val, fabrique(params), horizons=(1,))
            w = score(df, 1)
        except Exception as e:           # un réglage invalide est simplement écarté
            journal(f"  {famille} essai {t.number} écarté : {type(e).__name__}: {e}")
            return float("inf")
        essais.append({"essai": t.number, "wape_h1": w, "params": params,
                       "secondes": round(time.time() - t0, 1)})
        journal(f"  {famille} essai {t.number:>2} : WAPE {w:.2f}  ({time.time() - t0:.0f}s)")
        return w

    etude = optuna.create_study(direction="minimize",
                                sampler=optuna.samplers.TPESampler(seed=SEED))
    etude.enqueue_trial(DEFAUTS[famille])
    etude.optimize(objectif, n_trials=n_essais)
    meilleur = min(essais, key=lambda e: e["wape_h1"])
    return meilleur["params"], meilleur["wape_h1"], essais


def fabriquer_famille(famille: str, params: Dict[str, Any]) -> ModeleVariables:
    return FAMILLES[famille][1](params)


# ═══════════════════════════════════════════════════════════════════════════
# Phases
# ═══════════════════════════════════════════════════════════════════════════
def _journal_vers(chemin: Path) -> Callable[[str], None]:
    chemin.parent.mkdir(parents=True, exist_ok=True)

    def ecrire(msg: str) -> None:
        ligne = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(ligne, flush=True)
        with open(chemin, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
    return ecrire


def _sauver(obj: Any, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


CATEGORIE_STAT = {"ets", "theta", "adida", "imapa"}
CONFIGS_RESEAUX = {
    "nhits": [{"input_size": 24, "max_steps": 400, "lr": 1e-3, "largeur": 256},
              {"input_size": 12, "max_steps": 400, "lr": 1e-3, "largeur": 128}],
    "deepar": [{"input_size": 24, "max_steps": 300, "lr": 1e-3, "largeur": 64},
               {"input_size": 12, "max_steps": 300, "lr": 1e-3, "largeur": 32}],
}


def _ensemble(preds: Dict[str, pd.DataFrame], membres: List[str]) -> pd.DataFrame:
    """Médiane, ligne à ligne, des prévisions des membres (mêmes clés)."""
    cles = ["h", "origine", "ref"]
    base = preds[membres[0]][cles + ["y"]].copy()
    for nom in membres:
        base = base.merge(preds[nom][cles + ["yhat"]].rename(columns={"yhat": nom}), on=cles, how="inner")
    base["yhat"] = base[membres].median(axis=1)
    return base[cles + ["y", "yhat"]]


def phase_validation(extrait: Optional[str], familles: Optional[List[str]] = None,
                     reseaux: bool = True) -> None:
    journal = _journal_vers(RESULTATS / "journal_validation.log")
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    val = dr.origines(p)["validation"]
    journal(f"panel {p.Y.shape} · validation {p.mois[val[0] + 1].date()} → {p.mois[val[-1] + 1].date()}")
    chemin_preds = RESULTATS / "predictions_validation.parquet"
    preds: Dict[str, pd.DataFrame] = {}
    if chemin_preds.exists():
        tout = pd.read_parquet(chemin_preds)
        preds = {n: g.drop(columns="modele") for n, g in tout.groupby("modele")}
    etat_path = RESULTATS / "validation_etat.json"
    etat = json.loads(etat_path.read_text(encoding="utf-8")) if etat_path.exists() else {"reglages": {}}

    def enregistrer():
        pd.concat([df.assign(modele=n) for n, df in preds.items()], ignore_index=True
                  ).to_parquet(chemin_preds)
        _sauver(etat, etat_path)

    if "mediane_12" not in preds:
        journal("règles simples…")
        preds.update(regles_long(p, val)); enregistrer()
    if "ets" not in preds:
        journal("modèles statistiques (ETS, Theta, ADIDA, IMAPA)…")
        t0 = time.time(); preds.update(statistiques(p, val)); enregistrer()
        journal(f"  fait en {time.time() - t0:.0f}s")
    for fam in (familles or list(FAMILLES)):
        if fam in preds:
            continue
        journal(f"réglage Optuna : {fam} ({FAMILLES[fam][2]} essais)")
        params, w, essais = regler(p, fam, journal)
        journal(f"  meilleur {fam} : WAPE h1 {w:.2f} · {params}")
        preds[fam] = walk_forward_variables(p, val, fabriquer_famille(fam, params))
        etat["reglages"][fam] = {"params": params, "wape_h1_reglage": w, "essais": essais}
        enregistrer()
    if reseaux:
        for genre, cfgs in CONFIGS_RESEAUX.items():
            if genre in preds:
                continue
            meilleur = None
            for i, cfg in enumerate(cfgs):
                t0 = time.time()
                df = reseau_series(p, val, genre, cfg)[genre]
                w = score(df, 1)
                journal(f"  {genre} config {i} : WAPE h1 {w:.2f} ({time.time() - t0:.0f}s) · {cfg}")
                if meilleur is None or w < meilleur[1]:
                    meilleur = (cfg, w, df)
            preds[genre] = meilleur[2]
            etat["reglages"][genre] = {"params": meilleur[0], "wape_h1_reglage": meilleur[1],
                                       "essais": [{"config": c} for c in cfgs]}
            enregistrer()

    # Classement sur la validation
    regles_noms = [n for n in preds if n not in CATEGORIE_STAT and n not in FAMILLES
                   and n not in CONFIGS_RESEAUX and not n.startswith("ensemble")]
    tableau = {n: {"categorie": ("regle" if n in regles_noms else "statistique" if n in CATEGORIE_STAT
                                 else "appris"),
                   "wape_h1": score(df, 1), "wape_h2": score(df, 2), "wape_h3": score(df, 3),
                   "wape_cumul_3_mois": cumul_3_mois(df),
                   "biais_h1_pct": round(dr.biais(df[df.h == 1].y.values, df[df.h == 1].yhat.values), 2)}
               for n, df in preds.items() if not n.startswith("ensemble")}
    reference = min((n for n in tableau if tableau[n]["categorie"] == "regle"),
                    key=lambda n: tableau[n]["wape_h1"])
    candidats = sorted((n for n in tableau if tableau[n]["categorie"] != "regle"),
                       key=lambda n: tableau[n]["wape_h1"])
    membres = candidats[:3]
    preds["ensemble"] = _ensemble(preds, membres)
    tableau["ensemble"] = {"categorie": "appris", "membres": membres,
                           "wape_h1": score(preds["ensemble"], 1), "wape_h2": score(preds["ensemble"], 2),
                           "wape_h3": score(preds["ensemble"], 3),
                           "wape_cumul_3_mois": cumul_3_mois(preds["ensemble"]),
                           "biais_h1_pct": round(dr.biais(*(lambda s: (s.y.values, s.yhat.values))(
                               preds["ensemble"][preds["ensemble"].h == 1])), 2)}
    challenger = min((n for n in tableau if tableau[n]["categorie"] != "regle"),
                     key=lambda n: tableau[n]["wape_h1"])
    s_ref = preds[reference][preds[reference].h == 1].sort_values(["origine", "ref"])
    s_ch = preds[challenger][preds[challenger].h == 1].sort_values(["origine", "ref"])
    cmp_ = dr.ecart_bootstrap(s_ref.y.values, s_ref.yhat.values, s_ch.yhat.values, s_ref.ref.values)
    etat.update({
        "fige_le": time.strftime("%Y-%m-%d %H:%M:%S"),
        "regle_de_reference": reference,
        "challenger": challenger,
        "membres_ensemble": membres,
        "comparaison_validation": cmp_,
        "tableau_validation": dict(sorted(tableau.items(), key=lambda kv: kv[1]["wape_h1"])),
        "protocole": {
            "validation": [str(p.mois[o + 1].date()) for o in val],
            "rafraichissement_mois": dr.RAFRAICHISSEMENT,
            "eligibilite": f">= {dr.MIN_MOIS_ACTIFS_24} mois de vente sur 24, >= 1 sur 12",
            "regle_de_decision": (
                f"le challenger n'est servi que s'il bat la règle de référence d'au moins "
                f"{dr.SEUIL_GAIN_PTS} points de WAPE à 1 mois sur le TEST, avec un IC95 "
                "bootstrap (références rééchantillonnées) entièrement positif")},
    })
    enregistrer()
    _sauver(etat, RESULTATS / "validation.json")
    journal(f"FIGÉ — référence {reference} ({tableau[reference]['wape_h1']}) · challenger "
            f"{challenger} ({tableau[challenger]['wape_h1']}) · écart {cmp_}")



def classe_syntetos_boylan(y: np.ndarray) -> str:
    """Classe de demande (Syntetos & Boylan, 2005), sur les 24 derniers mois."""
    nz = y[y > 0]
    if len(nz) < 2:
        return "insuffisant"
    adi = len(y) / len(nz)
    cv2 = (nz.std() / nz.mean()) ** 2
    if adi < 1.32:
        return "réguliere" if cv2 < 0.49 else "erratique"
    return "intermittente" if cv2 < 0.49 else "irréguliere"


def intervalle_conforme(val: pd.DataFrame, test: pd.DataFrame, p, niveau: float = 0.8
                        ) -> Dict[str, Any]:
    """Borne haute P80 par calibration conforme.

    Sur la validation, on mesure l'écart normalisé e = (y − ŷ) / échelle, où
    l'échelle est la moyenne des 12 derniers mois de la référence à l'origine.
    Le quantile 80 % de e, ajouté à la prévision, donne une borne haute que la
    demande réelle ne dépasse, en validation, que 20 % du temps. Le test dit si
    cette promesse tient hors de l'échantillon qui l'a calibrée.
    """
    def _e(df):
        s = df[df.h == 1]
        ech = np.array([max(p.Y[r, max(0, o - 11):o + 1].mean(), 0.5)
                        for r, o in zip(s.ref.values, s.origine.values)])
        return s, ech
    sv, ev = _e(val)
    q = float(np.quantile((sv.y.values - sv.yhat.values) / ev, niveau))
    st, et = _e(test)
    borne = st.yhat.values + q * et
    return {"niveau_vise": niveau, "quantile_ecart_normalise": round(q, 4),
            "couverture_validation": round(float(np.mean(sv.y.values <= sv.yhat.values + q * ev)), 4),
            "couverture_test": round(float(np.mean(st.y.values <= borne)), 4)}


def phase_test(extrait: Optional[str]) -> None:
    fige = RESULTATS / "validation.json"
    if not fige.exists():
        raise SystemExit("validation.json absent : la phase de validation doit être close "
                         "avant tout regard sur le test.")
    etat = json.loads(fige.read_text(encoding="utf-8"))
    journal = _journal_vers(RESULTATS / "journal_test.log")
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    test = dr.origines(p)["test"]
    journal(f"TEST {p.mois[test[0] + 1].date()} → {p.mois[test[-1] + 1].date()} — choix figés le {etat['fige_le']}")

    preds: Dict[str, pd.DataFrame] = {}
    preds.update(regles_long(p, test))
    journal("statistiques…"); preds.update(statistiques(p, test))
    for fam, r in etat["reglages"].items():
        journal(f"{fam}…")
        if fam in CONFIGS_RESEAUX:
            preds[fam] = reseau_series(p, test, fam, r["params"])[fam]
        else:
            preds[fam] = walk_forward_variables(p, test, fabriquer_famille(fam, r["params"]))
    preds["ensemble"] = _ensemble(preds, etat["membres_ensemble"])

    tableau = {}
    for n, df in preds.items():
        s1 = df[df.h == 1]
        tableau[n] = {"wape_h1": score(df, 1), "wape_h2": score(df, 2), "wape_h3": score(df, 3),
                      "wape_cumul_3_mois": cumul_3_mois(df),
                      "biais_h1_pct": round(dr.biais(s1.y.values, s1.yhat.values), 2),
                      "wape_h1_validation": etat["tableau_validation"].get(n, {}).get("wape_h1")}

    ref, ch = etat["regle_de_reference"], etat["challenger"]
    a = preds[ref][preds[ref].h == 1].sort_values(["origine", "ref"])
    b = preds[ch][preds[ch].h == 1].sort_values(["origine", "ref"])
    assert np.array_equal(a.ref.values, b.ref.values) and np.array_equal(a.origine.values, b.origine.values)
    cmp_ = dr.ecart_bootstrap(a.y.values, a.yhat.values, b.yhat.values, a.ref.values)
    servi = bool(cmp_["ecart_pts"] >= dr.SEUIL_GAIN_PTS and cmp_["ic95"][0] > 0)
    methode = ch if servi else ref

    # Par classe de demande (classe calculée à l'origine, sur le passé)
    cl = np.array([classe_syntetos_boylan(p.Y[r, max(0, o - 23):o + 1]) for r, o in zip(a.ref, a.origine)])
    par_classe = {}
    for c in sorted(set(cl)):
        k = cl == c
        par_classe[c] = {"couples": int(k.sum()), "part_volume_pct": round(100 * a.y.values[k].sum() / a.y.sum(), 1),
                         ref: round(dr.wape(a.y.values[k], a.yhat.values[k]), 2),
                         ch: round(dr.wape(b.y.values[k], b.yhat.values[k]), 2)}

    # Par mois : combien de mois de test le challenger gagne-t-il ?
    par_mois = []
    for o in sorted(set(a.origine)):
        k = a.origine.values == o
        par_mois.append({"mois": str(p.mois[o + 1].date()),
                         ref: round(dr.wape(a.y.values[k], a.yhat.values[k]), 2),
                         ch: round(dr.wape(b.y.values[k], b.yhat.values[k]), 2)})
    mois_gagnes = sum(1 for m in par_mois if m[ch] < m[ref])

    # Total mensuel par sommation (indicatif, périmètre éligible seulement)
    tot = a.groupby("origine").agg(y=("y", "sum"), r=("yhat", "sum")).join(
        b.groupby("origine").agg(c=("yhat", "sum")))
    mape_total = {ref: round(float(np.mean(np.abs(tot.r - tot.y) / tot.y) * 100), 2),
                  ch: round(float(np.mean(np.abs(tot.c - tot.y) / tot.y) * 100), 2)}

    val_preds = pd.read_parquet(RESULTATS / "predictions_validation.parquet")
    val_m = val_preds[val_preds.modele == methode].drop(columns="modele")
    intervalle = intervalle_conforme(val_m, preds[methode], p)

    rapport = {
        "version": time.strftime("%Y-%m-%d"),
        "etude": "comparaison complète — demande par référence (CRISP-DM phases 4-5)",
        "donnees": {"source": d.source, "panel": list(p.Y.shape), **p.exclus,
                    "famille": dr.FAMILLE},
        "protocole": {**etat["protocole"],
                      "test": [str(p.mois[o + 1].date()) for o in test],
                      "choix_figes_le": etat["fige_le"]},
        "validation": {"regle_de_reference": ref, "challenger": ch,
                       "membres_ensemble": etat["membres_ensemble"],
                       "comparaison": etat["comparaison_validation"],
                       "tableau": etat["tableau_validation"],
                       "reglages": {k: v["params"] for k, v in etat["reglages"].items()}},
        "test": {"tableau": dict(sorted(tableau.items(), key=lambda kv: kv[1]["wape_h1"])),
                 "comparaison_challenger_vs_reference": cmp_,
                 "par_classe_de_demande": par_classe,
                 "par_mois": par_mois, "mois_gagnes_par_le_challenger": f"{mois_gagnes}/{len(par_mois)}",
                 "mape_du_total_mensuel_par_sommation_pct": mape_total,
                 "intervalle_p80_de_la_methode_servie": intervalle},
        "decision": {"challenger_servi": servi, "methode_servie": methode,
                     "motif": (f"{ch} bat {ref} de {cmp_['ecart_pts']} points de WAPE sur le test "
                               f"(IC95 {cmp_['ic95']}) : seuil de {dr.SEUIL_GAIN_PTS} points franchi"
                               if servi else
                               f"{ch} fait {cmp_['ecart_pts']:+} points face à {ref} sur le test "
                               f"(IC95 {cmp_['ic95']}) : la règle exige +{dr.SEUIL_GAIN_PTS} points "
                               "avec un intervalle entièrement positif — la règle simple est servie")},
    }
    _sauver(rapport, RESULTATS / "comparaison_test.json")
    pd.concat([df.assign(modele=n) for n, df in preds.items()], ignore_index=True
              ).to_parquet(RESULTATS / "predictions_test.parquet")
    journal(f"DÉCISION — {rapport['decision']['motif']}")


if __name__ == "__main__":  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["validation", "test"], required=True)
    ap.add_argument("--extrait", default=None, help="dossier d'extrait parquet (sinon l'entrepôt)")
    ap.add_argument("--familles", nargs="*", default=None)
    ap.add_argument("--sans-reseaux", action="store_true")
    a = ap.parse_args()
    if a.phase == "validation":
        phase_validation(a.extrait, a.familles, reseaux=not a.sans_reseaux)
    else:
        phase_test(a.extrait)
