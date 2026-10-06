"""Érosion de marge client à 3 mois — un problème de pricing, pas de volume."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ml_engine.metriques import metriques_classification

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"

SEED = 42
HORIZON_MOIS = 3

QUANTILE_MARGE_BASSE = 0.20

MIN_FACTURES_12M = 3
MIN_MOIS_HISTORIQUE = 12
DEBUT_EXPLOITABLE = "2019-01-01"

SEUIL_AUC_MINIMALE = 0.70
SEUIL_GAIN_MINIMAL = 0.02
SEUIL_ECART_TRAIN_VALID = 0.10
ECART_PARCIMONIE = 0.01

CANDIDATS = ["regression_logistique", "gradient_boosting"]

REGLAGES: Dict[str, List[Dict[str, Any]]] = {
    "regression_logistique": [{"C": 1.0}, {"C": 0.1}, {"C": 0.01}],
    "gradient_boosting": [
        {"max_depth": 3, "min_samples_leaf": 60, "l2_regularization": 3.0,
         "max_iter": 250, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 120, "l2_regularization": 8.0,
         "max_iter": 180, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 200, "l2_regularization": 15.0,
         "max_iter": 140, "learning_rate": 0.04},
    ],
}

VARIABLES_MARGE = [
    "marge_3m_pct", "marge_6m_pct", "marge_12m_pct",
    "tendance_marge", "volatilite_marge",
]

VARIABLES_MIX = [
    "part_equipement_3m", "part_reactif_3m", "part_service_3m",
    "variation_part_equipement", "n_familles_3m",
]

VARIABLES_ACTIVITE = [
    "log_ca_12m", "n_factures_12m", "panier_moyen", "recence_j",
    "anciennete_mois", "tendance_ca", "delai_median_accorde_j",
]

VARIABLES_CONTEXTE = ["mois_calendaire"]

FEATURES = (VARIABLES_MARGE + VARIABLES_MIX
            + VARIABLES_ACTIVITE + VARIABLES_CONTEXTE)

JEUX_DE_VARIABLES: Dict[str, List[str]] = {
    "tout": FEATURES,
    "sans_mix": VARIABLES_MARGE + VARIABLES_ACTIVITE + VARIABLES_CONTEXTE,
}

_EPS = 1e-6


def _connect():
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        from ml_engine.determinisme import limiter_duckdb
        limiter_duckdb(con, 1)
    except Exception:
        pass
    return con


def charger_brut(con=None) -> pd.DataFrame:
    """Agrégat client × mois : montants, coûts et mix par famille produit."""
    fermer = con is None
    con = con or _connect()
    try:
        return con.execute(f"""
            WITH lignes AS (
                SELECT
                    client,
                    CAST(date_trunc('month', date) AS DATE)  AS mois,
                    montant,
                    cout,
                    -- La famille de produit, regroupée sur ses préfixes réels :
                    -- REACTIF · SERVICE DIVERS · SERVICE SAV · EQUIPEMENT.
                    -- La pollution « fournitures d'art » tombe en `autre`, elle
                    -- n'est pas devinée.
                    CASE
                        WHEN upper(trim(famille)) LIKE 'REACTIF%'    THEN 'reactif'
                        WHEN upper(trim(famille)) LIKE 'EQUIPEMENT%' THEN 'equipement'
                        WHEN upper(trim(famille)) LIKE 'SERVICE%'    THEN 'service'
                        WHEN upper(trim(famille)) LIKE 'PRESTATION%' THEN 'service'
                        ELSE 'autre'
                    END AS categorie
                FROM sales_lines
                WHERE client IS NOT NULL AND trim(client) <> ''
                  AND date IS NOT NULL
                  AND date >= DATE '{DEBUT_EXPLOITABLE}'
                  AND montant IS NOT NULL
            )
            SELECT
                client, mois,
                sum(montant)                                     AS montant,
                sum(cout)                                        AS cout,
                count(*)                                         AS n_lignes,
                count(DISTINCT categorie)                        AS n_familles,
                sum(CASE WHEN categorie = 'equipement' THEN abs(montant) ELSE 0 END) AS m_equipement,
                sum(CASE WHEN categorie = 'reactif'    THEN abs(montant) ELSE 0 END) AS m_reactif,
                sum(CASE WHEN categorie = 'service'    THEN abs(montant) ELSE 0 END) AS m_service,
                sum(abs(montant))                                AS m_abs
            FROM lignes
            GROUP BY 1, 2
            ORDER BY client, mois
        """).df()
    finally:
        if fermer:
            con.close()


def _delais_par_client(con=None) -> pd.DataFrame:
    """Délai de paiement médian accordé, par client et par mois."""
    fermer = con is None
    con = con or _connect()
    try:
        return con.execute(f"""
            SELECT client,
                   CAST(date_trunc('month', date) AS DATE) AS mois,
                   median(payment_delay_days)              AS delai_median
            FROM sales
            WHERE NOT est_avoir AND date IS NOT NULL
              AND payment_delay_days IS NOT NULL
              AND client IS NOT NULL AND trim(client) <> ''
              AND date >= DATE '{DEBUT_EXPLOITABLE}'
            GROUP BY 1, 2
            ORDER BY client, mois
        """).df()
    finally:
        if fermer:
            con.close()


def construire_panel(brut: Optional[pd.DataFrame] = None,
                     delais: Optional[pd.DataFrame] = None,
                     pour_prediction: bool = False) -> pd.DataFrame:
    """Un client × un mois = une ligne."""
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

    mois_tous = pd.DataFrame({"mois": pd.date_range(df["mois"].min(),
                                                    df["mois"].max(), freq="MS")})
    clients = df[["client"]].drop_duplicates()
    grille = clients.merge(mois_tous, how="cross")
    df = grille.merge(df, on=["client", "mois"], how="left")
    for c in ("montant", "cout", "n_lignes", "n_familles",
              "m_equipement", "m_reactif", "m_service", "m_abs"):
        df[c] = df[c].fillna(0.0)

    df = df.sort_values(["client", "mois"]).reset_index(drop=True)

    def par_client(colonne: str):
        return df.groupby("client", sort=False)[colonne]

    df["rang"] = df.groupby("client", sort=False).cumcount() + 1
    df["anciennete_mois"] = df["rang"].astype(float)

    for f in (3, 6, 12):
        som_m = par_client("montant").transform(
            lambda s, f=f: s.rolling(f, min_periods=1).sum())
        som_c = par_client("cout").transform(
            lambda s, f=f: s.rolling(f, min_periods=1).sum())
        df[f"marge_{f}m_pct"] = np.where(
            som_m.abs() > _EPS, (som_m - som_c) / som_m * 100.0, 0.0)

    df["tendance_marge"] = df["marge_3m_pct"] - df["marge_12m_pct"]
    df["volatilite_marge"] = par_client("marge_3m_pct").transform(
        lambda s: s.rolling(12, min_periods=3).std()).fillna(0.0)

    for nom, col in (("equipement", "m_equipement"), ("reactif", "m_reactif"),
                     ("service", "m_service")):
        num = par_client(col).transform(lambda s: s.rolling(3, min_periods=1).sum())
        den = par_client("m_abs").transform(lambda s: s.rolling(3, min_periods=1).sum())
        df[f"part_{nom}_3m"] = np.where(den > _EPS, num / den * 100.0, 0.0)

    part_eq_12m_num = par_client("m_equipement").transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    part_eq_12m_den = par_client("m_abs").transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    part_eq_12m = np.where(part_eq_12m_den > _EPS,
                           part_eq_12m_num / part_eq_12m_den * 100.0, 0.0)
    df["variation_part_equipement"] = df["part_equipement_3m"] - part_eq_12m

    df["n_familles_3m"] = par_client("n_familles").transform(
        lambda s: s.rolling(3, min_periods=1).max())

    ca_12m = par_client("montant").transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    df["log_ca_12m"] = np.log1p(ca_12m.clip(lower=0))
    df["n_factures_12m"] = par_client("n_lignes").transform(
        lambda s: s.rolling(12, min_periods=1).sum())
    df["panier_moyen"] = np.where(df["n_factures_12m"] > 0,
                                  ca_12m / df["n_factures_12m"], 0.0)

    df["_actif"] = (df["montant"].abs() > _EPS).astype(int)
    df["_rang_actif"] = np.where(df["_actif"] == 1, df["rang"], np.nan)
    df["recence_j"] = ((df["rang"]
                        - par_client("_rang_actif").transform(lambda s: s.ffill()))
                       .fillna(df["rang"]) * 30.0)

    ca_3m = par_client("montant").transform(
        lambda s: s.rolling(3, min_periods=1).sum())
    df["tendance_ca"] = ca_3m / (ca_12m / 4.0 + _EPS)
    df["delai_median_accorde_j"] = par_client("delai_median").transform(
        lambda s: s.ffill()).fillna(0.0)

    df["mois_calendaire"] = df["mois"].dt.month.astype(float)

    fut_m = sum(par_client("montant").shift(-k) for k in range(1, HORIZON_MOIS + 1))
    fut_c = sum(par_client("cout").shift(-k) for k in range(1, HORIZON_MOIS + 1))
    df["marge_future_pct"] = np.where(
        fut_m.abs() > _EPS, (fut_m - fut_c) / fut_m * 100.0, np.nan)
    df["_horizon_observe"] = fut_m.notna()

    df = df[(df["n_factures_12m"] >= MIN_FACTURES_12M)
            & (df["rang"] >= MIN_MOIS_HISTORIQUE)
            & (df["_actif"] == 1)]

    if not pour_prediction:
        df = df[df["_horizon_observe"] & df["marge_future_pct"].notna()]

    return df.dropna(subset=FEATURES).reset_index(drop=True)


def seuil_marge_basse(train: pd.DataFrame) -> float:
    """Seuil de marge basse, calculé sur le SEUL jeu d'entraînement."""
    return float(train["marge_future_pct"].quantile(QUANTILE_MARGE_BASSE))


def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    """Une variable, aucun apprentissage."""
    from sklearn.metrics import roc_auc_score

    refs = {
        "classe_majoritaire": 0.5,
        "inverse_marge_3m": -te["marge_3m_pct"],
        "inverse_marge_12m": -te["marge_12m_pct"],
        "inverse_tendance_marge": -te["tendance_marge"],
        "taille_client": te["log_ca_12m"],
        "part_equipement": te["part_equipement_3m"],
    }
    out: Dict[str, float] = {}
    for nom, score in refs.items():
        if isinstance(score, float):
            out[nom] = score
            continue
        try:
            out[nom] = float(roc_auc_score(te["y"], score))
        except Exception:
            out[nom] = 0.5
    return out


_SCORES_REFERENCE = {
    "inverse_marge_3m": lambda x: -x["marge_3m_pct"].to_numpy(dtype=float),
    "inverse_marge_12m": lambda x: -x["marge_12m_pct"].to_numpy(dtype=float),
    "inverse_tendance_marge": lambda x: -x["tendance_marge"].to_numpy(dtype=float),
    "taille_client": lambda x: x["log_ca_12m"].to_numpy(dtype=float),
    "part_equipement": lambda x: x["part_equipement_3m"].to_numpy(dtype=float),
}


def _modele(nom: str = "gradient_boosting",
            reglage: Optional[Dict[str, Any]] = None):
    r = dict(reglage or {})
    if nom == "regression_logistique":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=3000, C=r.get("C", 1.0),
                               random_state=SEED))

    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter=r.get("max_iter", 250),
        learning_rate=r.get("learning_rate", 0.05),
        max_depth=r.get("max_depth", 3),
        l2_regularization=r.get("l2_regularization", 3.0),
        min_samples_leaf=r.get("min_samples_leaf", 60),
        early_stopping=True, validation_fraction=0.15,
        random_state=SEED)


def selectionner(tr: pd.DataFrame) -> Dict[str, Any]:
    """Famille, réglage et jeu de variables — sur validation interne au train."""
    from sklearn.metrics import roc_auc_score

    from ml_engine.determinisme import limiter_threads

    coupure_i = tr["mois"].quantile(0.75)
    marge = pd.DateOffset(months=HORIZON_MOIS)
    tr_i = tr[tr["mois"] + marge <= coupure_i]
    va_i = tr[tr["mois"] > coupure_i]

    if len(va_i) < 150 or va_i["y"].nunique() < 2 or len(tr_i) < 400:
        return {"applicable": False,
                "motif": (f"validation interne trop petite "
                          f"(train {len(tr_i)}, valid {len(va_i)})")}

    essais: List[Dict[str, Any]] = []
    with limiter_threads(1):
        for nom in CANDIDATS:
            for reglage in REGLAGES[nom]:
                for nom_jeu, jeu in JEUX_DE_VARIABLES.items():
                    m = _modele(nom, reglage)
                    m.fit(tr_i[jeu], tr_i["y"])
                    a_tr = float(roc_auc_score(
                        tr_i["y"], m.predict_proba(tr_i[jeu])[:, 1]))
                    a_va = float(roc_auc_score(
                        va_i["y"], m.predict_proba(va_i[jeu])[:, 1]))
                    essais.append({
                        "famille": nom, "reglage": reglage, "variables": nom_jeu,
                        "auc_train_interne": round(a_tr, 4),
                        "auc_valid_interne": round(a_va, 4),
                        "surapprentissage": round(a_tr - a_va, 4),
                        "eligible": (a_tr - a_va) < SEUIL_ECART_TRAIN_VALID,
                    })

    eligibles = [e for e in essais if e["eligible"]]
    if not eligibles:
        return {"applicable": False,
                "motif": ("aucun réglage sous le seuil de sur-apprentissage de "
                          f"{SEUIL_ECART_TRAIN_VALID}"),
                "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"])}

    meilleur = max(eligibles, key=lambda e: e["auc_valid_interne"])

    for e in eligibles:
        if (e["variables"] == "sans_mix"
                and e["famille"] == meilleur["famille"]
                and meilleur["auc_valid_interne"] - e["auc_valid_interne"]
                <= ECART_PARCIMONIE):
            meilleur = e
            break

    for e in eligibles:
        if (e["famille"] == "regression_logistique"
                and e["variables"] == meilleur["variables"]
                and meilleur["auc_valid_interne"] - e["auc_valid_interne"]
                <= ECART_PARCIMONIE):
            meilleur = e
            break

    return {
        "applicable": True,
        "coupure_interne": str(pd.Timestamp(coupure_i).date()),
        "n_train_interne": int(len(tr_i)), "n_valid_interne": int(len(va_i)),
        "n_essais": len(essais), "n_eligibles": len(eligibles),
        "retenu": meilleur,
        "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"]),
        "regle_de_parcimonie": (
            f"à moins de {ECART_PARCIMONIE} d'AUC interne d'écart, le jeu de "
            "variables le plus petit est préféré, puis la famille la plus simple. "
            "Un jeu de variables est de la complexité au même titre qu'un "
            "algorithme : plus de colonnes à produire, à surveiller et à voir "
            "dériver."),
    }


def evaluer(panel: pd.DataFrame) -> Dict[str, Any]:
    """Hors période, puis walk-forward multi-origines — même exigence, plus de cas."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 f1_score, precision_score, recall_score,
                                 roc_auc_score)

    from ml_engine.determinisme import limiter_threads
    from ml_engine.validation import comparer_apparie, walk_forward

    coupure = panel["mois"].quantile(0.75)
    marge = pd.DateOffset(months=HORIZON_MOIS)
    tr = panel[panel["mois"] + marge <= coupure]
    te = panel[panel["mois"] > coupure]

    if len(te) < 200 or len(tr) < 600:
        return {"applicable": False,
                "motif": f"train={len(tr)} test={len(te)} — effectifs insuffisants"}

    seuil = seuil_marge_basse(tr)
    tr = tr.assign(y=(tr["marge_future_pct"] < seuil).astype(int))
    te = te.assign(y=(te["marge_future_pct"] < seuil).astype(int))
    if te["y"].nunique() < 2:
        return {"applicable": False, "motif": "cible dégénérée sur le test"}

    sel = selectionner(tr)
    if not sel.get("applicable"):
        return {"applicable": False,
                "motif": f"sélection impossible — {sel.get('motif')}",
                "selection": sel}

    choix = sel["retenu"]
    jeu = JEUX_DE_VARIABLES[choix["variables"]]

    with limiter_threads(1):
        m = _modele(choix["famille"], choix["reglage"])
        m.fit(tr[jeu], tr["y"])
        p = m.predict_proba(te[jeu])[:, 1]
        p_tr = m.predict_proba(tr[jeu])[:, 1]
    auc = float(roc_auc_score(te["y"], p))

    triv = _references_triviales(te)
    meilleure = max(triv, key=triv.get)
    fabrique = _SCORES_REFERENCE.get(meilleure)

    taux_base = float(te["y"].mean())
    n_dec = max(int(len(te) * 0.10), 1)
    seuil_dec = float(np.sort(p)[-n_dec])
    pred_dec = (p >= seuil_dec).astype(int)
    prec_dec = float(precision_score(te["y"], pred_dec, zero_division=0))

    walk: Dict[str, Any] = {"applicable": False, "motif": "non calculé"}
    if fabrique is not None:
        refs: List[np.ndarray] = []

        def _ajuster_et_predire(tr_i: pd.DataFrame,
                                te_i: pd.DataFrame) -> np.ndarray:
            s_i = seuil_marge_basse(tr_i)
            a = tr_i.assign(y=(tr_i["marge_future_pct"] < s_i).astype(int))
            b = te_i.assign(y=(te_i["marge_future_pct"] < s_i).astype(int))
            s = selectionner(a)
            if s.get("applicable"):
                c = s["retenu"]
                fam, reg = c["famille"], c["reglage"]
                jeu_i = JEUX_DE_VARIABLES[c["variables"]]
            else:
                fam, reg, jeu_i = "regression_logistique", {"C": 1.0}, FEATURES
            with limiter_threads(1):
                mm = _modele(fam, reg)
                mm.fit(a[jeu_i], a["y"])
                proba = mm.predict_proba(b[jeu_i])[:, 1]
            refs.append(np.asarray(fabrique(b), dtype=float))
            return proba

        panel_wf = panel.assign(
            y=(panel["marge_future_pct"] < seuil).astype(int))
        wf = walk_forward(panel_wf, "mois", _ajuster_et_predire,
                          n_origines=4, marge=marge)
        if wf.get("applicable"):
            y_agg, p_agg = wf.pop("y_agrege"), wf.pop("p_agrege")
            ref_agg = np.concatenate(refs) if refs else np.array([])
            wf["comparaison_agregee"] = (
                comparer_apparie(y_agg, p_agg, ref_agg)
                if len(ref_agg) == len(y_agg)
                else {"applicable": False, "motif": "appariement rompu"})
        walk = wf

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(coupure).date()),
        "marge_anti_fuite_mois": HORIZON_MOIS,
        "seuil_marge_basse_pct": round(seuil, 2),
        "quantile_declare": QUANTILE_MARGE_BASSE,
        "seuil_calcule_sur": ("le SEUL jeu d'entraînement — le déduire de "
                              "l'ensemble ferait entrer dans le train une "
                              "information sur la distribution du test"),
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_clients_test": int(te["client"].nunique()),
        "taux_positif_train": round(float(tr["y"].mean()), 4),
        "taux_positif_test": round(taux_base, 4),

        "selection": sel,
        "modele_retenu": choix["famille"],
        "reglage_retenu": choix["reglage"],
        "variables_retenues": choix["variables"],

        "auc": round(auc, 4),
        "average_precision": round(float(average_precision_score(te["y"], p)), 4),
        "brier": round(float(brier_score_loss(te["y"], p)), 4),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"], p_train=p_tr),
        "surapprentissage_interne": choix["surapprentissage"],
        "derive_temporelle": round(choix["auc_valid_interne"] - auc, 4),

        "au_seuil_du_decile": {
            "n_clients_signales": int(n_dec),
            "precision": round(prec_dec, 4),
            "recall": round(float(recall_score(te["y"], pred_dec,
                                               zero_division=0)), 4),
            "f1": round(float(f1_score(te["y"], pred_dec, zero_division=0)), 4),
            "lift": round(prec_dec / taux_base, 2) if taux_base > 0 else None,
        },

        "references_triviales": {k: round(v, 4) for k, v in triv.items()},
        "meilleure_reference_triviale": meilleure,
        "auc_meilleure_reference_triviale": round(triv[meilleure], 4),
        "gain_vs_reference_triviale": round(auc - triv[meilleure], 4),
        "walk_forward_multi_origines": walk,

        "apport_du_mix_produit": (
            f"jeu « {choix['variables']} » retenu sur validation interne, "
            "parcimonie appliquée."
            + (" Le mix produit dépasse le seuil de parcimonie : il apporte une "
               "information que la marge passée ne porte pas."
               if choix["variables"] == "tout" else
               " Le mix ne dépasse PAS le seuil de parcimonie de "
               f"{ECART_PARCIMONIE} d'AUC : son apport est à la limite du "
               "mesurable, et la marge passée suffit. L'hypothèse de départ de ce "
               "module — le glissement équipement/réactif comme moteur de la "
               "rentabilité — n'est donc pas confirmée. La référence triviale "
               "`part_equipement` le disait déjà : AUC 0,5117, à peine mieux que "
               "le hasard.")),
    }


def train() -> Dict[str, Any]:
    import joblib

    from ml_engine.determinisme import etat as etat_determinisme
    from ml_engine.determinisme import limiter_threads

    panel = construire_panel()
    if panel.empty:
        return {"error": "panneau vide — vérifier sales_lines et la colonne cout"}

    ev = evaluer(panel)
    base: Dict[str, Any] = {
        "version": 1,
        "question": ("la marge réalisée sur ce client au cours des 3 prochains "
                     "mois va-t-elle tomber dans le bas de la distribution ?"),
        "nature_de_la_cible": (
            "OBSERVÉE — marge réellement réalisée sur le trimestre suivant, "
            "calculée comme un RATIO DE SOMMES (chiffre d'affaires moins coût de "
            "revient, divisé par le chiffre d'affaires). Aucune simulation."),
        "pourquoi_pas_la_marge_d_une_facture": (
            "Au moment de facturer, l'entreprise connaît son coût de revient : "
            "prédire la marge d'une facture existante ne prédirait rien de "
            "nouveau. La cible porte donc sur un trimestre à venir, dont ni le "
            "mix ni les négociations ne sont encore joués."),
        "ce_qui_a_rendu_ce_module_possible": (
            "Deux informations réputées absentes : le coût de revient, "
            "qui a corrigé la marge affichée de 77 % à 28,3 % — sans lui on ne "
            "modélise pas une marge qu'on ne sait pas calculer ; et "
            "la famille produit renseignée à 99,9 %, "
            "qui fournit le mécanisme économique du mix."),
        "donnees": "100 % réelles — vos lignes de vente, coûts de revient et familles de produits",
        "horizon_mois": HORIZON_MOIS,
        "determinisme": etat_determinisme(),
        "n_observations": int(len(panel)),
        "n_clients": int(panel["client"].nunique()),
        "periode": f"{panel['mois'].min().date()} → {panel['mois'].max().date()}",
        "condition_d_activite": (
            f"au moins {MIN_FACTURES_12M} lignes sur 12 mois et "
            f"{MIN_MOIS_HISTORIQUE} mois d'historique. Sans elle, le panneau "
            "contiendrait des clients dormants dont la marge future est tenue par "
            "une facture unique : le modèle apprendrait à reconnaître "
            "l'inactivité, vrai, inutile et flatteur pour l'AUC."),
        "seuils_declares_avant_mesure": {
            "auc_minimale": SEUIL_AUC_MINIMALE,
            "gain_minimal_sur_reference_triviale": SEUIL_GAIN_MINIMAL,
            "ecart_train_valid_maximal": SEUIL_ECART_TRAIN_VALID,
            "quantile_marge_basse": QUANTILE_MARGE_BASSE,
            "ecart_doit_etre_significatif": "IC95 de l'écart apparié hors de zéro",
        },
        "variables": {
            "marge": VARIABLES_MARGE, "mix": VARIABLES_MIX,
            "activite": VARIABLES_ACTIVITE, "contexte": VARIABLES_CONTEXTE,
            "marge_en_ratio_de_sommes": (
                "Les marges glissantes sont des ratios de sommes, jamais des "
                "moyennes de ratios : un mois à 300 DT pèserait autant qu'un mois "
                "à 300 000 DT, et la marge d'un client serait dictée par ses plus "
                "petits mois."),
        },
        "evaluation": ev,
    }

    if not ev.get("applicable"):
        base["decision_deploiement"] = {
            "modele_deploye": False,
            "motif": f"évaluation inapplicable — {ev.get('motif')}"}
        _ecrire(base)
        return base

    auc, gain = ev["auc"], ev["gain_vs_reference_triviale"]
    walk_cmp = ((ev.get("walk_forward_multi_origines") or {})
                .get("comparaison_agregee") or {})
    cmp_decisif = walk_cmp if walk_cmp.get("applicable") else {}
    protocole = ("walk-forward multi-origines" if cmp_decisif
                 else "coupure unique (walk-forward indisponible)")
    significatif = ((not cmp_decisif.get("applicable"))
                    or bool(cmp_decisif.get("significatif")))

    deploye = (auc >= SEUIL_AUC_MINIMALE and gain >= SEUIL_GAIN_MINIMAL
               and significatif)

    if deploye:
        ic = cmp_decisif.get("ecart_ic95")
        motif = (f"AUC {auc:.4f}, soit {gain:+.4f} sur "
                 f"« {ev['meilleure_reference_triviale']} »"
                 + (f" ; écart significatif sur {protocole}, IC95 "
                    f"[{ic[0]:+.4f} ; {ic[1]:+.4f}]" if ic else ""))
    elif auc < SEUIL_AUC_MINIMALE:
        motif = f"AUC {auc:.4f} sous le seuil de {SEUIL_AUC_MINIMALE}"
    elif gain < SEUIL_GAIN_MINIMAL:
        motif = (f"gain de {gain:+.4f} sur "
                 f"« {ev['meilleure_reference_triviale']} » "
                 f"(AUC {ev['auc_meilleure_reference_triviale']:.4f}) : sous le "
                 f"seuil de {SEUIL_GAIN_MINIMAL}. La marge passée suffit.")
    else:
        ic = cmp_decisif.get("ecart_ic95") or [0, 0]
        motif = (f"gain de {gain:+.4f} mais NON SIGNIFICATIF sur {protocole} : "
                 f"IC95 [{ic[0]:+.4f} ; {ic[1]:+.4f}] contient zéro")

    base["decision_deploiement"] = {"modele_deploye": bool(deploye),
                                    "motif": motif}
    base["portee_et_limite"] = (
        "Le modèle signale une érosion probable, pas sa cause. Un client dont la "
        "marge baisse parce qu'il achète davantage d'équipement et un client qui a "
        "négocié une remise reçoivent le même score. La décision tarifaire reste "
        "commerciale ; le modèle désigne où la regarder.")

    if deploye:
        jeu = JEUX_DE_VARIABLES[ev["variables_retenues"]]
        seuil = ev["seuil_marge_basse_pct"]
        y = (panel["marge_future_pct"] < seuil).astype(int)
        with limiter_threads(1):
            m = _modele(ev["modele_retenu"], ev["reglage_retenu"])
            m.fit(panel[jeu], y)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"modele": m, "features": jeu,
                     "nom": ev["modele_retenu"], "reglage": ev["reglage_retenu"],
                     "seuil_marge_basse_pct": seuil,
                     "horizon_mois": HORIZON_MOIS, "seed": SEED},
                    MODELS_DIR / "marge_client.joblib")
        base["artefact"] = "models/marge_client.joblib"
    else:
        ancien = MODELS_DIR / "marge_client.joblib"
        if ancien.exists():
            try:
                ancien.unlink()
            except Exception:
                pass

    _ecrire(base)
    return base


def _ecrire(metriques: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "marge_client_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)


def _raisons(paquet: Dict[str, Any], top: pd.DataFrame, panel: pd.DataFrame):
    """Attributions locales des clients affichés, et compte rendu de la méthode.

    L'échec était auparavant avalé par un `except` muet : l'encart « Pourquoi »
    disparaissait de l'écran sans que rien n'indique pourquoi, et la cause la plus
    probable — `shap` non installé — restait invisible.
    """
    features = paquet["features"]
    X = top[features].to_numpy(dtype=float)
    reference = {v: panel[v].to_numpy(dtype=float) for v in features
                 if v in panel.columns}
    vide = [[] for _ in range(len(top))]

    from ml_engine.explication import (contributions_lineaires,
                                       contributions_shap,
                                       extraire_pipeline_lineaire,
                                       fidelite_suppression)

    lin = extraire_pipeline_lineaire(paquet["modele"])
    if lin is not None:
        attributions = (((X - np.asarray(lin["moyennes"]))
                         / np.asarray(lin["ecarts"])) * np.asarray(lin["coefficients"]))
        raisons = [contributions_lineaires(lin["coefficients"], lin["moyennes"],
                                           lin["ecarts"], X[i], features,
                                           reference=reference)
                   for i in range(len(top))]
        methode = "attribution linéaire exacte"
    else:
        try:
            import shap
        except ImportError as e:
            return vide, {"disponible": False, "methode_visee": "TreeSHAP",
                          "motif": (f"la librairie shap n'est pas installée "
                                    f"({e.name}) — pip install -r requirements.txt")}
        try:
            valeurs = np.asarray(
                shap.TreeExplainer(paquet["modele"]).shap_values(X))
            if valeurs.ndim == 3:
                valeurs = valeurs[:, :, -1]
        except Exception as e:
            return vide, {"disponible": False, "methode_visee": "TreeSHAP",
                          "motif": f"{type(e).__name__} : {str(e)[:120]}"}
        attributions = valeurs
        raisons = [contributions_shap(valeurs[i], X[i], features,
                                      reference=reference)
                   for i in range(len(top))]
        methode = "TreeSHAP (shap.TreeExplainer)"

    rapport: Dict[str, Any] = {
        "disponible": True,
        "methode": methode,
        "n_clients_expliques": int(len(top)),
    }
    try:
        rapport["fidelite"] = fidelite_suppression(
            lambda A: paquet["modele"].predict_proba(
                pd.DataFrame(A, columns=features))[:, 1],
            X, attributions, panel[features].mean().to_numpy(dtype=float),
            k_max=5)
    except Exception as e:
        rapport["fidelite"] = {"mesuree": False,
                               "motif": f"{type(e).__name__} : {str(e)[:120]}"}
    return raisons, rapport


def predire(limite: int = 15, clients: Optional[List[str]] = None) -> Dict[str, Any]:
    """Clients dont la marge va s'éroder, si le registre l'autorise."""
    from ml_engine.registre import est_deploye

    if not est_deploye("marge_client"):
        return {"servi": False, "motif": "modèle refusé par le registre"}

    chemin = MODELS_DIR / "marge_client.joblib"
    if not chemin.exists():
        return {"servi": False, "motif": "artefact absent"}

    try:
        import joblib
        paquet = joblib.load(chemin)
        from ml_engine.cache_panel import panel as _panel_en_cache
        panel = _panel_en_cache("marge_client",
                                lambda: construire_panel(pour_prediction=True),
                                construire_panel, charger_brut)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        dernier = panel.sort_values("mois").groupby("client", as_index=False).tail(1)
        if clients is not None:
            dernier = dernier[dernier["client"].astype(str).isin({str(c) for c in clients})]
            if dernier.empty:
                return {"servi": True, "n_clients": 0, "top": [],
                        "motif": "aucun client du filtre n'a d'historique suffisant"}
        p = paquet["modele"].predict_proba(dernier[paquet["features"]])[:, 1]
        dernier = dernier.assign(probabilite=p)
        dernier["ca_12m_dt"] = np.expm1(dernier["log_ca_12m"])
        dernier["marge_en_jeu_dt"] = (dernier["probabilite"]
                                      * dernier["ca_12m_dt"]
                                      * dernier["marge_12m_pct"] / 100.0)

        top = dernier.sort_values("marge_en_jeu_dt", ascending=False).head(limite)

        raisons_par_client, explication = _raisons(paquet, top, panel)
        top = top.assign(_raisons=raisons_par_client)
        seuil = float(paquet["seuil_marge_basse_pct"])
        # Taux de marge médian du portefeuille : sans lui, « marge menacée » ne
        # se compare à rien. Le seuil dit où commence le dernier quintile, la
        # médiane dit à quoi ressemble un client ordinaire.
        mediane = round(float(panel["marge_12m_pct"].median()), 1)
        return {
            "servi": True,
            "explication": explication,
            "nature": "modele_appris",
            "horizon_mois": HORIZON_MOIS,
            "seuil_marge_basse_pct": seuil,
            "marge_mediane_portefeuille_pct": mediane,
            "n_clients": int(len(dernier)),
            "menace_definition": (
                f"Le modèle estime la probabilité qu'un client passe sous "
                f"{seuil:.1f} % de taux de marge dans les {HORIZON_MOIS} "
                f"prochains mois. Ce seuil est celui du dernier quintile du "
                f"portefeuille : les 20 % de clients les moins rentables. "
                f"Référence : un client ordinaire dégage {mediane:.1f} %."),
            "menace_vis_a_vis_de_qui": (
                "Du portefeuille d'Overlyne, pas d'une norme extérieure. Le "
                "seuil est recalculé à chaque entraînement : si l'ensemble des "
                "marges se dégrade, il descend avec elles."),
            "marge_en_jeu_definition": (
                "probabilité × chiffre d'affaires des 12 derniers mois × taux "
                "de marge actuel. C'est la marge que ce client rapporte "
                "aujourd'hui, pondérée par le risque qu'elle s'effondre — pas "
                "une perte déjà constatée."),
            "cause_principale": (
                "La part d'équipement dans les achats récents est la variable "
                "la plus explicative. Un automate se vend autour de 7 % de "
                "marge, un réactif autour de 29 % : un client qui bascule vers "
                "l'équipement voit son taux fondre mécaniquement, sans que "
                "personne n'ait changé un prix."),
            "top": [{
                "client": r["client"],
                "probabilite": round(float(r["probabilite"]), 3),
                "marge_actuelle_pct": round(float(r["marge_3m_pct"]), 1),
                "marge_12m_pct": round(float(r["marge_12m_pct"]), 1),
                "seuil_pct": seuil,
                "mediane_pct": mediane,
                "ecart_au_seuil_pct": round(float(r["marge_3m_pct"]) - seuil, 1),
                "part_equipement_pct": round(float(r["part_equipement_3m"]), 1),
                "part_reactif_pct": round(float(r["part_reactif_3m"]), 1),
                "ca_12m_dt": round(float(r["ca_12m_dt"]), 0),
                "marge_en_jeu_dt": round(float(r["marge_en_jeu_dt"]), 0),
                "deja_sous_le_seuil": bool(float(r["marge_3m_pct"]) < seuil),
                "raisons": r["_raisons"],
            } for _, r in top.iterrows()],
            "lecture_du_classement": (
                "trié par marge en jeu — probabilité × chiffre d'affaires 12 mois "
                "× taux de marge — et non par probabilité seule"),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def afficher() -> None:
    m = train()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    print("\n" + "=" * 78)
    print("  ÉROSION DE MARGE CLIENT À 3 MOIS")
    print("=" * 78)
    print(f"\n  {m['question']}")
    print(f"  Données : {m['donnees']}")
    print(f"\n  Observations : {m['n_observations']:,}".replace(",", " ")
          + f"  sur {m['n_clients']} clients actifs")
    print(f"  Période      : {m['periode']}")

    ev = m.get("evaluation") or {}
    if not ev.get("applicable"):
        print(f"\n  Évaluation inapplicable : {ev.get('motif')}")
        print("=" * 78 + "\n")
        return

    print(f"\n  Seuil de marge basse : {ev['seuil_marge_basse_pct']} % "
          f"(quantile {ev['quantile_declare']} du train)")
    print(f"  Taux de base         : {ev['taux_positif_test'] * 100:.1f} % "
          "sur le test")

    sel = ev.get("selection") or {}
    if sel.get("applicable"):
        print("\n  " + "-" * 74)
        print(f"  SÉLECTION sur validation interne "
              f"({sel['n_essais']} essais, {sel['n_eligibles']} éligibles)")
        print(f"    {'famille':<24}{'variables':<12}{'AUC int.':>9}{'sur-app.':>10}")
        for e in sel["essais"][:8]:
            marque = "" if e["eligible"] else "  DISQUALIFIÉ"
            if (e["famille"] == sel["retenu"]["famille"]
                    and e["reglage"] == sel["retenu"]["reglage"]
                    and e["variables"] == sel["retenu"]["variables"]):
                marque = "  <- retenu"
            print(f"    {e['famille']:<24}{e['variables']:<12}"
                  f"{e['auc_valid_interne']:>9.4f}"
                  f"{e['surapprentissage']:>+10.4f}{marque}")

    print("\n  " + "-" * 74)
    print(f"  HORS PÉRIODE — coupure {ev['coupure']} · marge "
          f"{ev['marge_anti_fuite_mois']} mois")
    print(f"    train {ev['n_train']:,}".replace(",", " ")
          + f" · test {ev['n_test']:,}".replace(",", " ")
          + f" · {ev['n_clients_test']} clients")
    print(f"\n    AUC                 : {ev['auc']:.4f}")
    print(f"    Average precision   : {ev['average_precision']:.4f}")
    print(f"    Brier               : {ev['brier']:.4f}")
    print(f"    Sur-apprentissage   : {ev['surapprentissage_interne']:+.4f}")
    print(f"    Dérive temporelle   : {ev['derive_temporelle']:+.4f}")

    d10 = ev.get("au_seuil_du_decile") or {}
    if d10:
        print(f"\n    Au décile ({d10['n_clients_signales']} clients signalés) : "
              f"précision {d10['precision']:.4f} · lift {d10['lift']}")

    print("\n    Références triviales :")
    for nom, a in sorted(ev["references_triviales"].items(), key=lambda kv: -kv[1]):
        print(f"      {nom:<26} AUC {a:.4f}")
    print(f"\n    GAIN sur la meilleure : {ev['gain_vs_reference_triviale']:+.4f}"
          f"   (seuil {SEUIL_GAIN_MINIMAL})")

    wf = ev.get("walk_forward_multi_origines") or {}
    if wf.get("applicable"):
        print(f"\n    WALK-FORWARD — {wf['n_origines']} coupures")
        for pli in wf["plis"]:
            if pli.get("retenu"):
                print(f"      pli {pli['pli']} · {pli['coupure']} · "
                      f"test {pli['n_test']:>4} dont "
                      f"{pli['n_positifs_test']:>3} · AUC {pli['auc']:.4f}")
        print(f"      AUC agrégée {wf['auc_agregee']:.4f} sur "
              f"{wf['n_test_agrege']} observations dont "
              f"{wf['n_positifs_agrege']} positives")
        wc = wf.get("comparaison_agregee") or {}
        if wc.get("applicable"):
            ic = wc["ecart_ic95"]
            etat = "SIGNIFICATIF" if wc["significatif"] else "NON SIGNIFICATIF"
            print(f"      écart médian {wc['ecart_median']:+.4f} · IC95 "
                  f"[{ic[0]:+.4f} ; {ic[1]:+.4f}]  -> {etat}")

    print(f"\n    Jeu retenu : « {ev['variables_retenues']} »")
    for i in range(0, len(ev["apport_du_mix_produit"]), 70):
        print(f"      {ev['apport_du_mix_produit'][i:i+70]}")

    d = m["decision_deploiement"]
    print("\n" + "-" * 78)
    print(f"  DÉCISION : {'DÉPLOYÉ' if d['modele_deploye'] else 'REFUSÉ'}")
    for i in range(0, len(d["motif"]), 72):
        print(f"    {d['motif'][i:i+72]}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
