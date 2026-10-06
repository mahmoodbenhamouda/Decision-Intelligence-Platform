"""Chiffre d'affaires à venir par client — combien, et qui entrera dans le top 10.

Deux usages, un seul modèle par horizon :

  * le MONTANT attendu sur les H prochains mois, qui chiffre l'enjeu d'une action ;
  * le CLASSEMENT qui en découle, donc le top 10 PRÉDIT, et les entrants et
    sortants par rapport au top 10 constaté.

Pourquoi une régression et non un classement direct : « être dans le top 10 » est
une étiquette dérivée d'un seuil mobile — le 10ᵉ rang change chaque trimestre.
Prédire le montant, puis trier, donne le classement sans inventer de cible.

Ce que ce module ne fait PAS : prédire le chiffre d'affaires DÉJÀ facturé. Celui-là
est connu exactement, il se compte (`kpi_engine.top_clients`). Un modèle qui le
« prédirait » lirait sa propre cible.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"

SEED = 42

#: 3 mois pour l'action commerciale, 12 mois pour la composition du top 10.
HORIZONS = (3, 12)

MIN_FACTURES_12M = 3
MIN_MOIS_HISTORIQUE = 12

# Seuils déclarés AVANT toute mesure.
#
# `GAIN_MINIMAL_RELATIF` porte sur l'erreur absolue médiane, pas sur l'erreur
# moyenne : la distribution du chiffre d'affaires est si asymétrique qu'une
# moyenne se laisse dicter par trois clients.
GAIN_MINIMAL_RELATIF = 0.05
SPEARMAN_MINIMAL = 0.70
ECART_TRAIN_VALID_MAXIMAL_RELATIF = 0.10
ECART_PARCIMONIE_RELATIF = 0.02

CANDIDATS = ["ridge_log", "gradient_boosting"]

REGLAGES: Dict[str, List[Dict[str, Any]]] = {
    "ridge_log": [{"alpha": 1.0}, {"alpha": 10.0}, {"alpha": 100.0}],
    "gradient_boosting": [
        {"max_depth": 3, "min_samples_leaf": 60, "l2_regularization": 3.0,
         "max_iter": 250, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 120, "l2_regularization": 8.0,
         "max_iter": 180, "learning_rate": 0.05},
    ],
}

VARIABLES_VOLUME = [
    "log_ca_1m", "log_ca_3m", "log_ca_6m", "log_ca_12m",
    "n_factures_3m", "n_factures_12m", "panier_moyen",
]

VARIABLES_DYNAMIQUE = [
    "tendance_ca", "croissance_annuelle", "volatilite_ca",
    "mois_actifs_12m", "recence_j",
]

VARIABLES_STRUCTURE = [
    "anciennete_mois", "n_familles_3m", "part_equipement_3m",
    "delai_median_accorde_j",
]

VARIABLES_CONTEXTE = ["mois_calendaire"]

FEATURES = (VARIABLES_VOLUME + VARIABLES_DYNAMIQUE
            + VARIABLES_STRUCTURE + VARIABLES_CONTEXTE)

JEUX_DE_VARIABLES: Dict[str, List[str]] = {
    "tout": FEATURES,
    "volume_seul": VARIABLES_VOLUME + VARIABLES_CONTEXTE,
}

_EPS = 1e-6


def _nom_artefact(horizon: int) -> str:
    return f"ca_client_{horizon}m.joblib"


def _nom_rapport(horizon: int) -> str:
    return f"ca_client_{horizon}m_metrics.json"


# ── Panel ────────────────────────────────────────────────────────────────────

def construire_panel(brut: Optional[pd.DataFrame] = None,
                     delais: Optional[pd.DataFrame] = None,
                     horizon: int = 3,
                     pour_prediction: bool = False) -> pd.DataFrame:
    """Un client × un mois = une ligne. Variables du passé, cible du futur.

    L'agrégat client × mois est celui de `marge_client` : une seule requête SQL
    pour les deux modules, afin qu'ils ne puissent pas diverger sur la définition
    du chiffre d'affaires.
    """
    from ml_engine.analytics.marge_client import (_connect, _delais_par_client,
                                                  charger_brut)

    con = _connect()
    try:
        if brut is None:
            brut = charger_brut(con)
        if delais is None:
            delais = _delais_par_client(con)
    finally:
        con.close()

    if brut is None or brut.empty:
        return pd.DataFrame()

    df = brut.copy()
    df["mois"] = pd.to_datetime(df["mois"])
    if delais is not None and not delais.empty:
        d2 = delais.copy()
        d2["mois"] = pd.to_datetime(d2["mois"])
        df = df.merge(d2, on=["client", "mois"], how="left")
    else:
        df["delai_median"] = np.nan

    # Grille complète : un mois sans facture est un zéro observé, pas une absence.
    mois_tous = pd.DataFrame({"mois": pd.date_range(df["mois"].min(),
                                                    df["mois"].max(), freq="MS")})
    grille = df[["client"]].drop_duplicates().merge(mois_tous, how="cross")
    df = grille.merge(df, on=["client", "mois"], how="left")
    for c in ("montant", "cout", "n_lignes", "n_familles",
              "m_equipement", "m_reactif", "m_service", "m_abs"):
        df[c] = df[c].fillna(0.0)

    df = df.sort_values(["client", "mois"]).reset_index(drop=True)

    def par_client(colonne: str):
        return df.groupby("client", sort=False)[colonne]

    df["rang"] = df.groupby("client", sort=False).cumcount() + 1
    df["anciennete_mois"] = df["rang"].astype(float)

    positif = df["montant"].clip(lower=0.0)
    df["_positif"] = positif

    for f in (1, 3, 6, 12):
        somme = df.groupby("client", sort=False)["_positif"].transform(
            lambda s, f=f: s.rolling(f, min_periods=1).sum())
        df[f"ca_{f}m"] = somme
        df[f"log_ca_{f}m"] = np.log1p(somme)

    for f in (3, 12):
        df[f"n_factures_{f}m"] = par_client("n_lignes").transform(
            lambda s, f=f: s.rolling(f, min_periods=1).sum())

    df["panier_moyen"] = np.where(df["n_factures_12m"] > 0,
                                  df["ca_12m"] / df["n_factures_12m"], 0.0)

    df["tendance_ca"] = df["ca_3m"] / (df["ca_12m"] / 4.0 + _EPS)
    ca_12m_precedent = df.groupby("client", sort=False)["ca_12m"].shift(12)
    df["croissance_annuelle"] = np.where(
        ca_12m_precedent.to_numpy(dtype=float) > _EPS,
        df["ca_12m"] / ca_12m_precedent.replace(0.0, np.nan), 1.0)
    df["croissance_annuelle"] = (df["croissance_annuelle"]
                                 .fillna(1.0).clip(0.0, 10.0))

    df["volatilite_ca"] = df.groupby("client", sort=False)["_positif"].transform(
        lambda s: s.rolling(12, min_periods=3).std()).fillna(0.0)

    df["_actif"] = (df["montant"].abs() > _EPS).astype(int)
    df["mois_actifs_12m"] = par_client("_actif").transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    df["_rang_actif"] = np.where(df["_actif"] == 1, df["rang"], np.nan)
    df["recence_j"] = ((df["rang"]
                        - par_client("_rang_actif").transform(lambda s: s.ffill()))
                       .fillna(df["rang"]) * 30.0)

    df["n_familles_3m"] = par_client("n_familles").transform(
        lambda s: s.rolling(3, min_periods=1).max())
    num = par_client("m_equipement").transform(
        lambda s: s.rolling(3, min_periods=1).sum())
    den = par_client("m_abs").transform(lambda s: s.rolling(3, min_periods=1).sum())
    df["part_equipement_3m"] = np.where(den > _EPS, num / den * 100.0, 0.0)

    df["delai_median_accorde_j"] = par_client("delai_median").transform(
        lambda s: s.ffill()).fillna(0.0)
    df["mois_calendaire"] = df["mois"].dt.month.astype(float)

    # Cible : somme OBSERVÉE des H mois suivants. `_horizon_observe` est faux dès
    # qu'un seul des H mois manque — sans quoi les dernières lignes porteraient un
    # chiffre d'affaires tronqué, systématiquement sous-estimé.
    futur = sum(df.groupby("client", sort=False)["_positif"].shift(-k)
                for k in range(1, horizon + 1))
    df["ca_futur"] = futur
    df["_horizon_observe"] = futur.notna()

    df = df[(df["n_factures_12m"] >= MIN_FACTURES_12M)
            & (df["rang"] >= MIN_MOIS_HISTORIQUE)
            & (df["_actif"] == 1)]

    if not pour_prediction:
        df = df[df["_horizon_observe"] & df["ca_futur"].notna()]

    return df.dropna(subset=FEATURES).reset_index(drop=True)


# ── Références triviales ─────────────────────────────────────────────────────

def references_triviales(te: pd.DataFrame, horizon: int) -> Dict[str, np.ndarray]:
    """Prédictions sans aucun apprentissage.

    `persistance` est la plus dure et la seule qui compte vraiment : le chiffre
    d'affaires des H derniers mois, reporté tel quel sur les H suivants. Un modèle
    de chiffre d'affaires qui ne la bat pas ne sert à rien.
    """
    ca_h = te[f"ca_{horizon}m"].to_numpy(dtype=float) if f"ca_{horizon}m" in te \
        else te["ca_12m"].to_numpy(dtype=float) * horizon / 12.0
    return {
        "persistance": ca_h,
        "moyenne_12m_proratisee": te["ca_12m"].to_numpy(dtype=float) * horizon / 12.0,
        "dernier_mois_extrapole": te["ca_1m"].to_numpy(dtype=float) * horizon,
    }


# ── Mesures ──────────────────────────────────────────────────────────────────

def mesurer(y: np.ndarray, pred: np.ndarray,
            n_top: int = 10) -> Dict[str, Any]:
    """Erreur, qualité de classement, et justesse du top N.

    Trois mesures parce qu'il y a trois usages, et qu'aucune ne couvre les autres :
    l'erreur médiane chiffre l'enjeu, Spearman dit si le classement tient,
    `precision_top_n` dit si les bons clients sont désignés.
    """
    from scipy.stats import spearmanr

    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    erreurs = np.abs(pred - y)

    # Erreur relative sur les clients dont le chiffre d'affaires n'est pas nul :
    # une erreur de 500 DT ne vaut pas la même chose chez un client à 2 000 DT et
    # chez un client à 2 M DT.
    non_nuls = y > 1.0
    erreur_relative = (float(np.median(erreurs[non_nuls] / y[non_nuls]))
                       if non_nuls.any() else None)

    n_top = int(min(n_top, len(y)))
    if n_top > 0:
        vrais = set(np.argsort(-y)[:n_top].tolist())
        predits = set(np.argsort(-pred)[:n_top].tolist())
        precision_top = len(vrais & predits) / n_top
    else:
        precision_top = None

    try:
        rho = float(spearmanr(y, pred).statistic)
    except Exception:
        rho = None

    return {
        "n": int(len(y)),
        "erreur_absolue_medianne_dt": round(float(np.median(erreurs)), 1),
        "erreur_absolue_moyenne_dt": round(float(np.mean(erreurs)), 1),
        "erreur_relative_medianne": (round(erreur_relative, 4)
                                     if erreur_relative is not None else None),
        "spearman": round(rho, 4) if rho is not None else None,
        f"precision_top_{n_top}": (round(precision_top, 3)
                                   if precision_top is not None else None),
    }


# ── Candidats ────────────────────────────────────────────────────────────────

def _modele(nom: str = "ridge_log", reglage: Optional[Dict[str, Any]] = None):
    """Modèle candidat. Les deux voient exactement les mêmes variables.

    `ridge_log` apprend sur `log1p(cible)` : l'erreur d'un client à 2 M DT ne doit
    pas écraser celle de six cents clients à 20 K DT. La prédiction est ramenée en
    dinars par `expm1`, ce qui fait du modèle un prédicteur de la MÉDIANE
    conditionnelle plutôt que de la moyenne — c'est ce que veut un classement.
    """
    r = dict(reglage or {})
    if nom == "ridge_log":
        from sklearn.compose import TransformedTargetRegressor
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return TransformedTargetRegressor(
            regressor=make_pipeline(StandardScaler(),
                                    Ridge(alpha=r.get("alpha", 1.0),
                                          random_state=SEED)),
            func=np.log1p, inverse_func=np.expm1)

    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(
        loss="absolute_error",
        max_iter=r.get("max_iter", 250),
        learning_rate=r.get("learning_rate", 0.05),
        max_depth=r.get("max_depth", 3),
        min_samples_leaf=r.get("min_samples_leaf", 60),
        l2_regularization=r.get("l2_regularization", 3.0),
        early_stopping=True, validation_fraction=0.15,
        random_state=SEED)


def selectionner(tr: pd.DataFrame, horizon: int) -> Dict[str, Any]:
    """Choisit famille, réglage et jeu de variables sur le SEUL entraînement.

    Le surapprentissage est un critère d'ÉLIGIBILITÉ, pas un constat d'après-coup :
    un candidat dont l'écart entraînement/validation dépasse le seuil est
    disqualifié avant toute comparaison.
    """
    from sklearn.model_selection import GroupKFold

    from ml_engine.determinisme import limiter_threads

    essais: List[Dict[str, Any]] = []
    plis = list(GroupKFold(n_splits=4).split(tr, groups=tr["client"].values))

    for nom_jeu, jeu in JEUX_DE_VARIABLES.items():
        for nom in CANDIDATS:
            for reglage in REGLAGES[nom]:
                err_valid, err_train = [], []
                for i_tr, i_va in plis:
                    a, b = tr.iloc[i_tr], tr.iloc[i_va]
                    try:
                        with limiter_threads(1):
                            m = _modele(nom, reglage)
                            m.fit(a[jeu], a["ca_futur"])
                            err_valid.append(float(np.median(
                                np.abs(m.predict(b[jeu]) - b["ca_futur"]))))
                            err_train.append(float(np.median(
                                np.abs(m.predict(a[jeu]) - a["ca_futur"]))))
                    except Exception:
                        continue
                if not err_valid:
                    continue
                ev, et = float(np.mean(err_valid)), float(np.mean(err_train))
                ecart = (ev - et) / (ev or 1.0)
                essais.append({
                    "jeu": nom_jeu, "modele": nom, "reglage": reglage,
                    "erreur_validation_dt": round(ev, 1),
                    "erreur_entrainement_dt": round(et, 1),
                    "ecart_relatif": round(ecart, 4),
                    "disqualifie": bool(ecart > ECART_TRAIN_VALID_MAXIMAL_RELATIF),
                })

    eligibles = [e for e in essais if not e["disqualifie"]]
    if not eligibles:
        return {"applicable": False,
                "motif": ("tous les candidats dépassent l'écart "
                          f"entraînement/validation de "
                          f"{ECART_TRAIN_VALID_MAXIMAL_RELATIF:.0%}"),
                "essais": essais}

    meilleur = min(eligibles, key=lambda e: e["erreur_validation_dt"])

    # Parcimonie, sur la famille ET sur le jeu de variables : le plus simple est
    # conservé tant que le gain reste sous le seuil déclaré.
    simples = [e for e in eligibles
               if e["modele"] == "ridge_log" and e["jeu"] == "volume_seul"]
    retenu = meilleur
    for candidat in sorted(simples, key=lambda e: e["erreur_validation_dt"]):
        gain = ((candidat["erreur_validation_dt"] - meilleur["erreur_validation_dt"])
                / (candidat["erreur_validation_dt"] or 1.0))
        if gain <= ECART_PARCIMONIE_RELATIF:
            retenu = candidat
        break

    return {"applicable": True, "retenu": retenu, "meilleur_brut": meilleur,
            "essais": essais,
            "parcimonie": (
                f"le candidat le plus simple est conservé tant que le gain relatif "
                f"reste sous {ECART_PARCIMONIE_RELATIF:.0%}")}


# ── Évaluation hors période ──────────────────────────────────────────────────

def evaluer(panel: pd.DataFrame, horizon: int) -> Dict[str, Any]:
    """Coupure temporelle, marge anti-fuite, et comparaison aux références."""
    from ml_engine.determinisme import limiter_threads

    if panel.empty:
        return {"applicable": False, "motif": "panneau vide"}

    mois = np.sort(panel["mois"].unique())
    if len(mois) < MIN_MOIS_HISTORIQUE + horizon + 6:
        return {"applicable": False,
                "motif": f"historique trop court ({len(mois)} mois)"}

    coupure = pd.Timestamp(mois[int(len(mois) * 0.80)])
    # Une observation n'entre à l'entraînement que si son horizon est ENTIÈREMENT
    # antérieur à la coupure : sinon sa cible chevauche la période de test.
    marge = coupure - pd.DateOffset(months=horizon)
    tr = panel[panel["mois"] <= marge]
    te = panel[panel["mois"] > coupure]

    if len(tr) < 200 or len(te) < 50:
        return {"applicable": False,
                "motif": f"effectifs insuffisants (train {len(tr)}, test {len(te)})"}

    choix = selectionner(tr, horizon)
    if not choix.get("applicable"):
        return {"applicable": False, "motif": choix["motif"],
                "selection": choix}

    retenu = choix["retenu"]
    jeu = JEUX_DE_VARIABLES[retenu["jeu"]]
    with limiter_threads(1):
        m = _modele(retenu["modele"], retenu["reglage"])
        m.fit(tr[jeu], tr["ca_futur"])
        pred = m.predict(te[jeu])

    y = te["ca_futur"].to_numpy(dtype=float)
    modele = mesurer(y, pred)

    refs = {nom: mesurer(y, p)
            for nom, p in references_triviales(te, horizon).items()}
    meilleure = min(refs, key=lambda n: refs[n]["erreur_absolue_medianne_dt"])
    err_ref = refs[meilleure]["erreur_absolue_medianne_dt"]
    err_mod = modele["erreur_absolue_medianne_dt"]
    gain = (err_ref - err_mod) / (err_ref or 1.0)

    return {
        "applicable": True,
        "coupure": str(coupure.date()),
        "marge_anti_fuite": (
            f"une observation n'entre à l'entraînement que si mois + {horizon} "
            "mois <= coupure"),
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_clients_test": int(te["client"].nunique()),
        "modele_retenu": retenu["modele"],
        "reglage_retenu": retenu["reglage"],
        "variables_retenues": retenu["jeu"],
        "selection": choix,
        "modele": modele,
        "references_triviales": refs,
        "meilleure_reference_triviale": meilleure,
        "erreur_meilleure_reference_dt": err_ref,
        "gain_relatif_sur_reference": round(float(gain), 4),
        "surapprentissage": {
            "erreur_entrainement_dt": retenu["erreur_entrainement_dt"],
            "erreur_validation_dt": retenu["erreur_validation_dt"],
            "ecart_relatif": retenu["ecart_relatif"],
            "seuil": ECART_TRAIN_VALID_MAXIMAL_RELATIF,
        },
    }


# ── Entraînement et décision ─────────────────────────────────────────────────

def train(horizon: int = 3) -> Dict[str, Any]:
    import joblib

    from ml_engine.determinisme import etat as etat_determinisme
    from ml_engine.determinisme import limiter_threads

    panel = construire_panel(horizon=horizon)
    if panel.empty:
        return {"error": "panneau vide — vérifier sales_lines"}

    ev = evaluer(panel, horizon)
    base: Dict[str, Any] = {
        "version": 1,
        "horizon_mois": horizon,
        "question": (f"combien ce client va-t-il acheter au cours des {horizon} "
                     "prochains mois ?"),
        "nature_de_la_cible": (
            "OBSERVÉE — somme des montants réellement facturés sur les "
            f"{horizon} mois suivant l'observation. Aucun seuil inventé, aucune "
            "simulation."),
        "pourquoi_une_regression": (
            "Le besoin est un MONTANT (il chiffre l'enjeu d'une action) et un "
            "CLASSEMENT (le top 10 attendu). « Être dans le top 10 » serait une "
            "étiquette dérivée d'un seuil mobile : le 10ᵉ rang change chaque "
            "trimestre. On prédit le montant, puis on trie."),
        "pourquoi_pas_le_ca_deja_facture": (
            "Le chiffre d'affaires déjà émis est connu exactement : il se compte. "
            "Un modèle entraîné à le reproduire aurait sa propre cible en entrée — "
            "c'est la tautologie qui avait produit une AUC de 1,0000 ailleurs dans "
            "ce projet."),
        "donnees": "100 % réelles — vos lignes de vente facturées",
        "determinisme": etat_determinisme(),
        "n_observations": int(len(panel)),
        "n_clients": int(panel["client"].nunique()),
        "periode": f"{panel['mois'].min().date()} → {panel['mois'].max().date()}",
        "censurage_a_droite": (
            f"les {horizon} derniers mois sont exclus de l'apprentissage : leur "
            "cible serait tronquée, donc systématiquement sous-estimée"),
        "condition_d_activite": (
            f"au moins {MIN_FACTURES_12M} lignes sur 12 mois et "
            f"{MIN_MOIS_HISTORIQUE} mois d'historique"),
        "seuils_declares_avant_mesure": {
            "gain_minimal_relatif_sur_reference": GAIN_MINIMAL_RELATIF,
            "spearman_minimal": SPEARMAN_MINIMAL,
            "ecart_train_valid_maximal_relatif": ECART_TRAIN_VALID_MAXIMAL_RELATIF,
            "ecart_parcimonie_relatif": ECART_PARCIMONIE_RELATIF,
        },
        "variables": {
            "volume": VARIABLES_VOLUME, "dynamique": VARIABLES_DYNAMIQUE,
            "structure": VARIABLES_STRUCTURE, "contexte": VARIABLES_CONTEXTE,
        },
        "pourquoi_erreur_medianne": (
            "La distribution du chiffre d'affaires est trop asymétrique pour une "
            "erreur moyenne : trois clients la dicteraient. La médiane décrit le "
            "client typique ; la moyenne est publiée à côté, non pour décider."),
        "evaluation": ev,
    }

    if not ev.get("applicable"):
        base["decision_deploiement"] = {
            "modele_deploye": False,
            "motif": f"évaluation inapplicable — {ev.get('motif')}"}
        _ecrire(base, horizon)
        return base

    gain = ev["gain_relatif_sur_reference"]
    rho = ev["modele"]["spearman"] or 0.0
    deploye = bool(gain >= GAIN_MINIMAL_RELATIF and rho >= SPEARMAN_MINIMAL)

    if deploye:
        motif = (f"erreur médiane {ev['modele']['erreur_absolue_medianne_dt']:,.0f} DT "
                 f"contre {ev['erreur_meilleure_reference_dt']:,.0f} DT pour "
                 f"« {ev['meilleure_reference_triviale']} », soit {gain:+.1%} ; "
                 f"Spearman {rho:.4f}").replace(",", " ")
    elif gain < GAIN_MINIMAL_RELATIF:
        motif = (f"gain de {gain:+.1%} sur "
                 f"« {ev['meilleure_reference_triviale']} » : sous le seuil de "
                 f"{GAIN_MINIMAL_RELATIF:.0%}. Reporter le chiffre d'affaires "
                 "passé suffit.")
    else:
        motif = (f"Spearman {rho:.4f} sous le seuil de {SPEARMAN_MINIMAL} : le "
                 "classement produit ne tient pas, donc le top 10 prédit non plus")

    base["decision_deploiement"] = {"modele_deploye": deploye, "motif": motif}
    base["portee_et_limite"] = (
        "Le modèle prédit ce qu'un client achètera si rien ne change. Il ignore "
        "les appels d'offres, les ruptures de stock et les décisions budgétaires "
        "des établissements publics — autant d'événements qui dominent un "
        "trimestre et n'apparaissent dans aucune variable disponible.")

    if deploye:
        jeu = JEUX_DE_VARIABLES[ev["variables_retenues"]]
        with limiter_threads(1):
            m = _modele(ev["modele_retenu"], ev["reglage_retenu"])
            m.fit(panel[jeu], panel["ca_futur"])
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"modele": m, "features": jeu, "nom": ev["modele_retenu"],
                     "reglage": ev["reglage_retenu"], "horizon_mois": horizon,
                     "seed": SEED}, MODELS_DIR / _nom_artefact(horizon))
        base["artefact"] = f"models/{_nom_artefact(horizon)}"
    else:
        ancien = MODELS_DIR / _nom_artefact(horizon)
        if ancien.exists():
            try:
                ancien.unlink()
            except Exception:
                pass

    _ecrire(base, horizon)
    return base


def _ecrire(metriques: Dict[str, Any], horizon: int) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques,
              open(REPORTS_DIR / _nom_rapport(horizon), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


def train_tous() -> Dict[int, Dict[str, Any]]:
    """Un modèle par horizon : l'un peut être servi quand l'autre est refusé."""
    return {h: train(h) for h in HORIZONS}


# ── Service ──────────────────────────────────────────────────────────────────

def _charger(horizon: int):
    from ml_engine.registre import est_deploye

    if not est_deploye(f"ca_client_{horizon}m"):
        return None, {"servi": False, "motif": "modèle refusé par le registre"}
    chemin = MODELS_DIR / _nom_artefact(horizon)
    if not chemin.exists():
        return None, {"servi": False, "motif": "artefact absent"}
    import joblib
    return joblib.load(chemin), None


def predire(horizon: int = 3, limite: int = 15,
            clients: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Chiffre d'affaires attendu par client, du plus gros enjeu au plus petit.

    `clients` restreint le calcul (totaux compris) aux clients du filtre."""
    paquet, refus = _charger(horizon)
    if refus:
        return refus

    try:
        from ml_engine.cache_panel import panel as _panel_en_cache
        panel = _panel_en_cache(f"ca_client_{horizon}m",
                                lambda: construire_panel(horizon=horizon, pour_prediction=True),
                                construire_panel)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        dernier = panel.sort_values("mois").groupby("client", as_index=False).tail(1)
        if clients is not None:
            dernier = dernier[dernier["client"].astype(str).isin({str(c) for c in clients})]
            if dernier.empty:
                return {"servi": True, "horizon_mois": horizon, "n_clients": 0,
                        "ca_attendu_total_dt": 0, "top": [],
                        "motif": "aucun client du filtre n'a d'historique suffisant"}
        features = paquet["features"]
        attendu = np.clip(paquet["modele"].predict(dernier[features]), 0.0, None)
        # `ca_passe_dt` est posé comme COLONNE : lire une série alignée sur
        # `dernier` avec l'index positionnel de `top`, qui est trié autrement,
        # attribuerait le passé d'un client à un autre.
        dernier = dernier.assign(
            ca_attendu_dt=attendu,
            ca_passe_dt=(dernier[f"ca_{horizon}m"] if f"ca_{horizon}m" in dernier
                         else dernier["ca_12m"] * horizon / 12.0))
        dernier["ecart_vs_passe_dt"] = (dernier["ca_attendu_dt"]
                                        - dernier["ca_passe_dt"])

        # RYTHME HABITUEL. L'écart seul se lit à contresens quand la fenêtre de
        # comparaison est elle-même anormale : un client qui vient de faire un
        # trimestre exceptionnel affichera un recul brutal alors qu'il revient
        # simplement à la normale. On publie donc son rythme de croisière — les
        # 12 derniers mois ramenés à H mois — et le fait que la base s'en écarte.
        dernier["rythme_habituel_dt"] = dernier["ca_12m"] * horizon / 12.0
        ecart_base = np.where(
            dernier["rythme_habituel_dt"] > _EPS,
            (dernier["ca_passe_dt"] - dernier["rythme_habituel_dt"])
            / dernier["rythme_habituel_dt"] * 100.0, 0.0)
        dernier["base_vs_rythme_pct"] = ecart_base

        top = dernier.sort_values("ca_attendu_dt", ascending=False).head(limite)
        raisons, explication = _raisons(paquet, top, panel)
        noms = _noms_clients(list(top["client"]))
        fenetres = _fenetres(panel, horizon)

        return {
            "servi": True,
            "nature": "modele_appris",
            "horizon_mois": horizon,
            "explication": explication,
            "n_clients": int(len(dernier)),
            "ca_attendu_total_dt": round(float(dernier["ca_attendu_dt"].sum()), 0),
            "fenetres": fenetres,
            "mesure": (
                "montant des LIGNES de vente, signé — les retours viennent en "
                "déduction. La courbe d'évolution du tableau de bord affiche, "
                "elle, le CA TTC des en-têtes de facture : les deux diffèrent "
                "de quelques pour cent et ne se comparent pas directement."),
            "top": [{
                "client": r["client"],
                "nom": noms.get(r["client"], r["client"]),
                "ca_attendu_dt": round(float(r["ca_attendu_dt"]), 0),
                "ca_passe_dt": round(float(r["ca_passe_dt"]), 0),
                "ecart_vs_passe_dt": round(float(r["ecart_vs_passe_dt"]), 0),
                "rythme_habituel_dt": round(float(r["rythme_habituel_dt"]), 0),
                "base_vs_rythme_pct": round(float(r["base_vs_rythme_pct"]), 0),
                "raisons": raisons[i] if i < len(raisons) else [],
            } for i, (_, r) in enumerate(top.iterrows())],
            "lecture": (
                f"montant attendu sur {horizon} mois si rien ne change ; l'écart "
                "se lit contre le même nombre de mois écoulés"),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def predire_top(n: int = 10, horizon: int = 12) -> Dict[str, Any]:
    """Top N PRÉDIT, et mouvements par rapport au top N constaté.

    Les entrants et les sortants sont l'information décisionnelle : un classement
    qui reproduit le passé ne dit rien, les mouvements disent où regarder.
    """
    paquet, refus = _charger(horizon)
    if refus:
        return refus

    try:
        panel = construire_panel(horizon=horizon, pour_prediction=True)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        dernier = panel.sort_values("mois").groupby("client", as_index=False).tail(1)
        features = paquet["features"]
        dernier = dernier.assign(
            ca_attendu_dt=np.clip(paquet["modele"].predict(dernier[features]),
                                  0.0, None))

        constate = dernier.sort_values("ca_12m", ascending=False).head(n)
        predit = dernier.sort_values("ca_attendu_dt", ascending=False).head(n)
        codes_constates = list(constate["client"])
        codes_predits = list(predit["client"])

        noms = _noms_clients(set(codes_constates) | set(codes_predits))
        total_attendu = float(dernier["ca_attendu_dt"].sum()) or 1.0

        return {
            "servi": True,
            "nature": "modele_appris",
            "horizon_mois": horizon,
            "n": n,
            "top_predit": [{
                "rang": i + 1,
                "client": r["client"],
                "nom": noms.get(r["client"], r["client"]),
                "ca_attendu_dt": round(float(r["ca_attendu_dt"]), 0),
                "ca_12m_constate_dt": round(float(r["ca_12m"]), 0),
                "part_attendue_pct": round(
                    float(r["ca_attendu_dt"]) / total_attendu * 100.0, 1),
                "rang_constate": (codes_constates.index(r["client"]) + 1
                                  if r["client"] in codes_constates else None),
            } for i, (_, r) in enumerate(predit.iterrows())],
            "entrants": [{"client": c, "nom": noms.get(c, c)}
                         for c in codes_predits if c not in codes_constates],
            "sortants": [{"client": c, "nom": noms.get(c, c)}
                         for c in codes_constates if c not in codes_predits],
            "lecture": (
                f"classement par chiffre d'affaires attendu sur {horizon} mois. "
                "Le top constaté est un décompte du passé ; celui-ci est une "
                "prévision, et c'est pourquoi les deux peuvent différer."),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _fenetres(panel: pd.DataFrame, horizon: int) -> Dict[str, Any]:
    """Les deux fenêtres comparées, en dates explicites.

    « −66 % vs passé » n'est lisible que si l'on sait contre QUOI. Les deux
    fenêtres sont calculées depuis la dernière ligne de l'entrepôt, jamais
    depuis l'horloge : les données s'arrêtent à l'export.
    """
    if panel.empty:
        return {}
    fin = pd.Timestamp(panel["mois"].max())
    debut_passe = fin - pd.DateOffset(months=horizon - 1)
    debut_futur = fin + pd.DateOffset(months=1)
    fin_futur = fin + pd.DateOffset(months=horizon)

    def mois(d: pd.Timestamp) -> str:
        return d.strftime("%Y-%m")

    return {
        "passe_debut": mois(debut_passe), "passe_fin": mois(fin),
        "futur_debut": mois(debut_futur), "futur_fin": mois(fin_futur),
        "derniere_donnee": mois(fin),
        "lecture": (
            f"comparaison entre {mois(debut_passe)} → {mois(fin)} (mesuré) et "
            f"{mois(debut_futur)} → {mois(fin_futur)} (attendu)"),
    }


def _noms_clients(codes: Sequence[str]) -> Dict[str, str]:
    if not codes:
        return {}
    try:
        from ml_engine.analytics.marge_client import _connect
        con = _connect()
        try:
            lignes = con.execute(
                "SELECT client, any_value(client_name) FROM sales "
                "WHERE client_name IS NOT NULL GROUP BY client").fetchall()
        finally:
            con.close()
        return {str(c): str(n) for c, n in lignes if str(c) in set(codes)}
    except Exception:
        return {}


def _raisons(paquet: Dict[str, Any], top: pd.DataFrame, panel: pd.DataFrame):
    """Attributions locales, et motif explicite en cas d'indisponibilité."""
    from ml_engine.explication import (contributions_lineaires,
                                       extraire_pipeline_lineaire)

    features = paquet["features"]
    X = top[features].to_numpy(dtype=float)
    vide = [[] for _ in range(len(top))]

    interne = getattr(paquet["modele"], "regressor_", None) or paquet["modele"]
    lin = extraire_pipeline_lineaire(interne)
    if lin is None:
        return vide, {"disponible": False,
                      "motif": ("le modèle servi n'est pas linéaire : une "
                                "attribution exacte est impossible")}

    reference = {v: panel[v].to_numpy(dtype=float) for v in features
                 if v in panel.columns}
    raisons = [contributions_lineaires(lin["coefficients"], lin["moyennes"],
                                       lin["ecarts"], X[i], features,
                                       sens=("augmente", "reduit"),
                                       reference=reference)
               for i in range(len(top))]
    return raisons, {
        "disponible": True,
        "methode": "attribution linéaire exacte",
        "origine_des_coefficients": lin["origine"],
        "echelle": ("les contributions portent sur log1p(chiffre d'affaires) : "
                    "elles se lisent en parts relatives, pas en dinars"),
        "n_clients_expliques": int(len(top)),
    }


# ── Affichage ────────────────────────────────────────────────────────────────

def afficher() -> None:
    for horizon in HORIZONS:
        m = train(horizon)
        print("\n" + "=" * 78)
        print(f"  CHIFFRE D'AFFAIRES ATTENDU — HORIZON {horizon} MOIS")
        print("=" * 78)
        if m.get("error"):
            print(f"\n  Erreur : {m['error']}\n")
            continue

        print(f"\n  {m['question']}")
        print(f"  Observations : {m['n_observations']:,}".replace(",", " ")
              + f"  sur {m['n_clients']} clients")
        print(f"  Période      : {m['periode']}")

        ev = m.get("evaluation") or {}
        if not ev.get("applicable"):
            print(f"\n  Évaluation inapplicable : {ev.get('motif')}")
            continue

        mod, refs = ev["modele"], ev["references_triviales"]
        print(f"\n  Coupure {ev['coupure']} — "
              f"{ev['n_test']} observations de test, "
              f"{ev['n_clients_test']} clients")
        print(f"\n  {'Prédicteur':<28} {'err. médiane':>14} {'Spearman':>10} "
              f"{'top 10':>8}")
        print("  " + "-" * 62)
        cle_top = next((k for k in mod if k.startswith("precision_top_")), None)
        print(f"  {ev['modele_retenu']:<28} "
              f"{mod['erreur_absolue_medianne_dt']:>13,.0f} DT "
              f"{mod['spearman'] or 0:>10.4f} "
              f"{mod.get(cle_top) or 0:>8.2f}".replace(",", " "))
        for nom, r in sorted(refs.items(),
                             key=lambda kv: kv[1]["erreur_absolue_medianne_dt"]):
            ct = next((k for k in r if k.startswith("precision_top_")), None)
            print(f"  {nom:<28} {r['erreur_absolue_medianne_dt']:>13,.0f} DT "
                  f"{r['spearman'] or 0:>10.4f} "
                  f"{r.get(ct) or 0:>8.2f}".replace(",", " "))

        d = m["decision_deploiement"]
        print(f"\n  Décision : {'DÉPLOYÉ' if d['modele_deploye'] else 'REFUSÉ'}")
        print(f"  {d['motif']}")
        print("=" * 78)


if __name__ == "__main__":  # pragma: no cover
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
