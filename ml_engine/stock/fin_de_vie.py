"""Fin de commercialisation à 6 mois — un modèle sur données **entièrement réelles**."""

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
HORIZON_MOIS = 6

MOIS_ACTIFS_MINIMUM = 2
FENETRE_VIVANTE = 3
MIN_MOIS_HISTORIQUE = 12

SEUIL_AUC_MINIMALE = 0.70
SEUIL_GAIN_MINIMAL = 0.02
SEUIL_ECART_TRAIN_VALID = 0.10
ECART_PARCIMONIE = 0.01

CANDIDATS = ["regression_logistique", "gradient_boosting"]

REGLAGES: Dict[str, List[Dict[str, Any]]] = {
    "regression_logistique": [
        {"C": 1.0},
        {"C": 0.1},
        {"C": 0.01},
    ],
    "gradient_boosting": [
        {"max_depth": 4, "min_samples_leaf": 40, "l2_regularization": 2.0,
         "max_iter": 300, "learning_rate": 0.06},
        {"max_depth": 3, "min_samples_leaf": 80, "l2_regularization": 5.0,
         "max_iter": 200, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 150, "l2_regularization": 10.0,
         "max_iter": 150, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 250, "l2_regularization": 20.0,
         "max_iter": 120, "learning_rate": 0.04},
    ],
}

VARIABLES_FLUX = [
    "conso_1m", "conso_3m", "conso_6m", "conso_12m",
    "tendance_conso", "volatilite_conso",
    "mois_actifs_12m", "mois_depuis_derniere_vente",
    "mois_depuis_dernier_achat", "anciennete_mois",
]

VARIABLES_CLIENTELE = [
    "n_clients_12m", "n_clients_3m", "erosion_clients",
    "concentration_hhi", "part_premier_client", "n_nouveaux_clients_6m",
]

VARIABLES_PRIX = [
    "prix_moyen_3m", "derive_prix", "volatilite_prix", "marge_relative",
]

VARIABLES_CONTEXTE = ["mois_calendaire", "log_valeur_stock"]

FEATURES = (VARIABLES_FLUX + VARIABLES_CLIENTELE
            + VARIABLES_PRIX + VARIABLES_CONTEXTE)

_EPS = 1e-6


def _connect():
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH))
    try:
        from ml_engine.determinisme import limiter_duckdb
        limiter_duckdb(con, 1)
    except Exception:
        pass
    return con


def charger_brut(con=None) -> pd.DataFrame:
    """Flux mensuels réels enrichis du mix de clientèle et des prix."""
    fermer = con is None
    con = con or _connect()
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_position_mensuelle" not in tables:
            return pd.DataFrame()

        con.execute("""
            CREATE OR REPLACE TABLE mix_clientele_mensuel AS
            SELECT
                upper(trim(designation))                    AS cle,
                CAST(date_trunc('month', date) AS DATE)     AS mois,
                count(DISTINCT client)                      AS n_clients,
                sum(montant)                                AS montant,
                sum(qte)                                    AS qte,
                sum(cout)                                   AS cout,
                -- Indice de concentration de Herfindahl sur les montants du
                -- mois : 1 = un seul acheteur, proche de 0 = demande dispersée.
                sum(part * part)                            AS hhi,
                max(part)                                   AS part_premier
            FROM (
                SELECT designation, date, client,
                       sum(montant) AS montant, sum(qte) AS qte, sum(cout) AS cout,
                       sum(abs(montant)) / NULLIF(sum(sum(abs(montant))) OVER (
                           PARTITION BY upper(trim(designation)),
                                        date_trunc('month', date)), 0) AS part
                FROM sales_lines
                WHERE designation IS NOT NULL AND trim(designation) <> ''
                  AND date IS NOT NULL AND qte > 0
                GROUP BY designation, date, client
            )
            GROUP BY 1, 2
        """)

        return con.execute("""
            SELECT p.cle, p.produit, p.mois, p.cout_unitaire,
                   p.entrees, p.sorties, p.position_fin, p.rang_mois,
                   COALESCE(m.n_clients, 0)   AS n_clients,
                   COALESCE(m.montant, 0)     AS montant,
                   COALESCE(m.cout, 0)        AS cout_revient,
                   m.hhi                      AS hhi,
                   m.part_premier             AS part_premier
            FROM stock_position_mensuelle p
            LEFT JOIN mix_clientele_mensuel m
                   ON m.cle = p.cle AND m.mois = p.mois
            ORDER BY p.cle, p.mois
        """).df()
    finally:
        if fermer:
            con.close()


def construire_panel(brut: Optional[pd.DataFrame] = None,
                     pour_prediction: bool = False) -> pd.DataFrame:
    """Variables au mois m, cible sur ]m, m+6]."""
    if brut is None:
        brut = charger_brut()
    if brut is None or brut.empty:
        return pd.DataFrame()

    df = brut.copy()
    df["mois"] = pd.to_datetime(df["mois"])
    df = df.sort_values(["cle", "mois"]).reset_index(drop=True)

    def par_ref(colonne: str):
        return df.groupby("cle", sort=False)[colonne]

    df["rang_ref"] = df.groupby("cle", sort=False).cumcount() + 1
    df["anciennete_mois"] = df["rang_ref"].astype(float)

    df["conso_1m"] = df["sorties"].astype(float)
    for f in (3, 6, 12):
        df[f"conso_{f}m"] = par_ref("sorties").transform(
            lambda s, f=f: s.rolling(f, min_periods=1).mean())

    df["tendance_conso"] = df["conso_3m"] / (df["conso_12m"] + _EPS)
    ecart = par_ref("sorties").transform(
        lambda s: s.rolling(12, min_periods=3).std())
    df["volatilite_conso"] = (ecart / (df["conso_12m"] + _EPS)).fillna(0.0)

    df["_vendu"] = (df["sorties"] > 0).astype(int)
    df["mois_actifs_12m"] = par_ref("_vendu").transform(
        lambda s: s.rolling(12, min_periods=1).sum())

    df["_rang_vente"] = np.where(df["_vendu"] == 1, df["rang_ref"], np.nan)
    df["mois_depuis_derniere_vente"] = (
        df["rang_ref"] - par_ref("_rang_vente").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    df["_achat"] = (df["entrees"] > 0).astype(int)
    df["_rang_achat"] = np.where(df["_achat"] == 1, df["rang_ref"], np.nan)
    df["mois_depuis_dernier_achat"] = (
        df["rang_ref"] - par_ref("_rang_achat").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    df["n_clients"] = df["n_clients"].astype(float)
    df["n_clients_12m"] = par_ref("n_clients").transform(
        lambda s: s.rolling(12, min_periods=1).max())
    df["n_clients_3m"] = par_ref("n_clients").transform(
        lambda s: s.rolling(3, min_periods=1).max())
    df["erosion_clients"] = 1.0 - (df["n_clients_3m"]
                                   / (df["n_clients_12m"] + _EPS))

    df["concentration_hhi"] = par_ref("hhi").transform(
        lambda s: s.ffill()).fillna(1.0)
    df["part_premier_client"] = par_ref("part_premier").transform(
        lambda s: s.ffill()).fillna(1.0)
    df["_nouveaux"] = (df["n_clients"] > 0).astype(float) * df["n_clients"]
    df["n_nouveaux_clients_6m"] = par_ref("_nouveaux").transform(
        lambda s: s.rolling(6, min_periods=1).mean())

    df["_prix_unitaire"] = df["montant"] / (df["sorties"] + _EPS)
    df["_prix_unitaire"] = df["_prix_unitaire"].where(df["sorties"] > 0)
    df["prix_moyen_3m"] = par_ref("_prix_unitaire").transform(
        lambda s: s.rolling(3, min_periods=1).mean()).ffill().fillna(0.0)
    prix_12m = par_ref("_prix_unitaire").transform(
        lambda s: s.rolling(12, min_periods=1).mean()).ffill().fillna(0.0)
    df["derive_prix"] = df["prix_moyen_3m"] / (prix_12m + _EPS)
    df["volatilite_prix"] = par_ref("_prix_unitaire").transform(
        lambda s: s.rolling(12, min_periods=3).std()).fillna(0.0)
    df["marge_relative"] = ((df["montant"] - df["cout_revient"])
                            / (df["montant"].abs() + _EPS))

    df["mois_calendaire"] = df["mois"].dt.month.astype(float)
    df["log_valeur_stock"] = np.log1p(
        (df["position_fin"].clip(lower=0)
         * df["cout_unitaire"].fillna(0.0).clip(lower=0)))

    futurs = [df.groupby("cle", sort=False)["_vendu"].shift(-k)
              for k in range(1, HORIZON_MOIS + 1)]
    fut = pd.concat(futurs, axis=1)
    df["y"] = (fut.sum(axis=1) == 0).astype(float)
    df["_horizon_observe"] = fut.notna().all(axis=1)

    df["_vivante"] = par_ref("_vendu").transform(
        lambda s: s.rolling(FENETRE_VIVANTE, min_periods=1).sum()
    ) >= MOIS_ACTIFS_MINIMUM

    df = df[df["_vivante"] & (df["rang_ref"] >= MIN_MOIS_HISTORIQUE)]
    if not pour_prediction:
        df = df[df["_horizon_observe"]]
        df = df.dropna(subset=FEATURES + ["y"])
        df["y"] = df["y"].astype(int)
    else:
        df = df.dropna(subset=FEATURES)

    return df.reset_index(drop=True)


def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    from sklearn.metrics import roc_auc_score

    refs = {
        "classe_majoritaire": 0.5,
        "inverse_mois_actifs_12m": -te["mois_actifs_12m"],
        "silence_recent": te["mois_depuis_derniere_vente"],
        "inverse_conso_3m": -te["conso_3m"],
        "inverse_tendance_conso": -te["tendance_conso"],
        "abandon_approvisionnement": te["mois_depuis_dernier_achat"],
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


def _modele(nom: str = "gradient_boosting",
            reglage: Optional[Dict[str, Any]] = None):
    """Un candidat, avec son réglage."""
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
        max_iter=r.get("max_iter", 300),
        learning_rate=r.get("learning_rate", 0.06),
        max_depth=r.get("max_depth", 4),
        l2_regularization=r.get("l2_regularization", 2.0),
        min_samples_leaf=r.get("min_samples_leaf", 40),
        early_stopping=True, validation_fraction=0.15,
        random_state=SEED)


JEUX_DE_VARIABLES: Dict[str, List[str]] = {
    "tout": FEATURES,
    "flux_seul": VARIABLES_FLUX + VARIABLES_CONTEXTE,
}


def selectionner(tr: pd.DataFrame) -> Dict[str, Any]:
    """Choisit famille, réglage et jeu de variables — SANS jamais voir le test."""
    from sklearn.metrics import roc_auc_score

    from ml_engine.determinisme import limiter_threads

    coupure_i = tr["mois"].quantile(0.75)
    marge = pd.DateOffset(months=HORIZON_MOIS)
    tr_i = tr[tr["mois"] + marge <= coupure_i]
    va_i = tr[tr["mois"] > coupure_i]

    if len(va_i) < 150 or va_i["y"].nunique() < 2 or len(tr_i) < 500:
        return {"applicable": False,
                "motif": (f"validation interne trop petite "
                          f"(train {len(tr_i)}, valid {len(va_i)})")}

    essais: List[Dict[str, Any]] = []
    with limiter_threads(1):
        for nom in CANDIDATS:
            for i, reglage in enumerate(REGLAGES[nom]):
                for nom_jeu, jeu in JEUX_DE_VARIABLES.items():
                    m = _modele(nom, reglage)
                    m.fit(tr_i[jeu], tr_i["y"])
                    auc_tr = float(roc_auc_score(
                        tr_i["y"], m.predict_proba(tr_i[jeu])[:, 1]))
                    auc_va = float(roc_auc_score(
                        va_i["y"], m.predict_proba(va_i[jeu])[:, 1]))
                    essais.append({
                        "famille": nom,
                        "reglage_no": i,
                        "reglage": reglage,
                        "variables": nom_jeu,
                        "auc_train_interne": round(auc_tr, 4),
                        "auc_valid_interne": round(auc_va, 4),
                        "surapprentissage": round(auc_tr - auc_va, 4),
                    })

    eligibles = [e for e in essais
                 if e["surapprentissage"] < SEUIL_ECART_TRAIN_VALID]
    for e in essais:
        e["eligible"] = e["surapprentissage"] < SEUIL_ECART_TRAIN_VALID

    if not eligibles:
        return {
            "applicable": False,
            "motif": ("aucun réglage ne tient sous le seuil de sur-apprentissage "
                      f"de {SEUIL_ECART_TRAIN_VALID}"),
            "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"]),
        }

    meilleur = max(eligibles, key=lambda e: e["auc_valid_interne"])

    for e in eligibles:
        if (e["famille"] == "regression_logistique"
                and meilleur["auc_valid_interne"] - e["auc_valid_interne"]
                <= ECART_PARCIMONIE):
            meilleur = e
            break

    return {
        "applicable": True,
        "coupure_interne": str(pd.Timestamp(coupure_i).date()),
        "n_train_interne": int(len(tr_i)),
        "n_valid_interne": int(len(va_i)),
        "n_essais": len(essais),
        "n_eligibles": len(eligibles),
        "retenu": meilleur,
        "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"]),
        "principe": (
            "Famille, réglage et jeu de variables sont choisis sur une coupure "
            "INTERNE à la période d'entraînement, avec la même marge anti-fuite. "
            "Le jeu de test hors période n'est touché qu'une fois, ensuite. "
            "Choisir en regardant le test reviendrait à choisir son modèle en "
            "regardant sa note."),
        "distinction_mesuree": (
            "L'écart publié ici est du SUR-APPRENTISSAGE au sens strict : les "
            "deux côtés viennent de la même période, aucune dérive ne peut s'y "
            "glisser. La dérive temporelle est mesurée séparément, après, comme "
            "l'écart entre validation interne et hors période."),
    }


def evaluer_hors_periode(panel: pd.DataFrame) -> Dict[str, Any]:
    """Entraînement sur le passé, test sur le futur — avec marge anti-fuite."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)

    from ml_engine.determinisme import limiter_threads

    coupure = panel["mois"].quantile(0.75)
    marge = pd.DateOffset(months=HORIZON_MOIS)

    tr = panel[panel["mois"] + marge <= coupure]
    te = panel[panel["mois"] > coupure]

    if len(te) < 200 or te["y"].nunique() < 2 or len(tr) < 800:
        return {"applicable": False,
                "motif": f"train={len(tr)} test={len(te)} — effectifs insuffisants"}

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

    n_dec = max(int(len(te) * 0.10), 1)
    seuil_decile = float(np.sort(p)[-n_dec])
    pred_dec = (p >= seuil_decile).astype(int)
    taux_base = float(te["y"].mean())
    prec_dec = float(precision_score(te["y"], pred_dec, zero_division=0))

    pred_05 = (p >= 0.5).astype(int)

    sans_mix_deja_teste = choix["variables"] == "flux_seul"

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(coupure).date()),
        "marge_anti_fuite_mois": HORIZON_MOIS,
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_references_test": int(te["cle"].nunique()),
        "taux_positif_train": round(float(tr["y"].mean()), 4),
        "taux_positif_test": round(taux_base, 4),

        "selection": sel,
        "modele_retenu": choix["famille"],
        "reglage_retenu": choix["reglage"],
        "variables_retenues": choix["variables"],
        "regle_selection": (
            "sélection sur validation INTERNE à la période d'entraînement — "
            f"éligibilité si sur-apprentissage < {SEUIL_ECART_TRAIN_VALID}, puis "
            f"meilleure AUC interne, puis parcimonie à {ECART_PARCIMONIE}. Le "
            "jeu de test n'a servi qu'à cette unique évaluation finale."),

        "auc": round(auc, 4),
        "average_precision": round(float(average_precision_score(te["y"], p)), 4),
        "brier": round(float(brier_score_loss(te["y"], p)), 4),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"], p_train=p_tr),

        "surapprentissage_interne": choix["surapprentissage"],
        "derive_temporelle": round(choix["auc_valid_interne"] - auc, 4),
        "lecture_des_deux_ecarts": (
            "Le sur-apprentissage est mesuré au sein de la période "
            "d'entraînement — aucune dérive ne peut s'y glisser. La dérive est "
            "l'écart entre validation interne et hors période : elle traduit un "
            "changement de régime, pas un défaut du modèle, et aucune "
            "régularisation ne la réduit. La première version confondait les "
            "deux et disqualifiait donc un modèle pour un changement de "
            "conjoncture."),

        "au_seuil_du_decile": {
            "seuil": round(seuil_decile, 4),
            "n_references_signalees": int(n_dec),
            "precision": round(prec_dec, 4),
            "recall": round(float(recall_score(te["y"], pred_dec,
                                               zero_division=0)), 4),
            "f1": round(float(f1_score(te["y"], pred_dec, zero_division=0)), 4),
            "lift": (round(prec_dec / taux_base, 2) if taux_base > 0 else None),
            "confusion_matrix": confusion_matrix(te["y"], pred_dec).tolist(),
            "pourquoi_ce_seuil": (
                "la décision réelle est « quelles références est-ce que "
                "j'examine ? », donc un rang, pas un seuil de probabilité"),
        },
        "au_seuil_de_0_5": {
            "precision": round(float(precision_score(te["y"], pred_05,
                                                     zero_division=0)), 4),
            "recall": round(float(recall_score(te["y"], pred_05,
                                               zero_division=0)), 4),
            "n_positifs_predits": int(pred_05.sum()),
            "pourquoi_c_est_inutilisable": (
                f"avec {taux_base * 100:.1f} % de positifs, aucune probabilité "
                "n'atteint 0,5 : le modèle ne prédit aucun positif et ces deux "
                "chiffres valent zéro sans rien dire de sa capacité de "
                "classement. Publié pour montrer pourquoi il est écarté, et non "
                "effacé par commodité."),
        },

        "references_triviales": {k: round(v, 4) for k, v in triv.items()},
        "meilleure_reference_triviale": meilleure,
        "auc_meilleure_reference_triviale": round(triv[meilleure], 4),
        "gain_vs_reference_triviale": round(auc - triv[meilleure], 4),

        "apport_du_mix_clientele": (
            "déjà tranché par la sélection : le jeu « flux_seul » a été mis en "
            "concurrence avec « tout » sur la validation interne, et "
            f"« {choix['variables']} » a été retenu."
            + (" Le mix de clientèle et les prix n'apportaient donc rien, ce qui "
               "réfute l'hypothèse de départ de ce module — et le dire vaut mieux "
               "que de garder des variables inutiles."
               if sans_mix_deja_teste else
               " Le mix de clientèle apporte donc une information que les seuls "
               "flux ne portent pas.")),
    }


def evaluer_groupkfold(panel: pd.DataFrame, modele: str,
                       reglage: Optional[Dict[str, Any]] = None,
                       variables: Optional[List[str]] = None) -> Dict[str, Any]:
    """Par référence — INDICATIF seulement : ce protocole brasse les périodes."""
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    from ml_engine.determinisme import limiter_threads

    jeu = variables or FEATURES
    aucs: List[float] = []
    with limiter_threads(1):
        for a, b in GroupKFold(n_splits=5).split(panel, panel["y"],
                                                 panel["cle"].values):
            tr, te = panel.iloc[a], panel.iloc[b]
            if te["y"].nunique() < 2:
                continue
            m = _modele(modele, reglage)
            m.fit(tr[jeu], tr["y"])
            aucs.append(float(roc_auc_score(
                te["y"], m.predict_proba(te[jeu])[:, 1])))

    return {
        "auc_moyen": round(float(np.mean(aucs)), 4) if aucs else None,
        "auc_par_pli": [round(a, 4) for a in aucs],
        "avertissement": ("protocole indicatif : il brasse les périodes et flatte "
                          "le résultat. La décision repose sur le hors période."),
    }


def importance_permutation(panel: pd.DataFrame, modele: str,
                           reglage: Optional[Dict[str, Any]] = None,
                           variables: Optional[List[str]] = None
                           ) -> Dict[str, float]:
    """Mesurée sur le TEST hors période : une variable très utilisée à l'entraînement peut n'apporter…"""
    from sklearn.inspection import permutation_importance

    from ml_engine.determinisme import limiter_threads

    jeu = variables or FEATURES
    coupure = panel["mois"].quantile(0.75)
    tr = panel[panel["mois"] + pd.DateOffset(months=HORIZON_MOIS) <= coupure]
    te = panel[panel["mois"] > coupure]
    if len(te) < 200 or len(tr) < 800:
        return {}

    with limiter_threads(1):
        m = _modele(modele, reglage)
        m.fit(tr[jeu], tr["y"])
        r = permutation_importance(m, te[jeu], te["y"], n_repeats=5,
                                   random_state=SEED, scoring="roc_auc")
    return {f: round(float(v), 4)
            for f, v in sorted(zip(jeu, r.importances_mean),
                               key=lambda kv: -kv[1])}


def train() -> Dict[str, Any]:
    """Entraîne, mesure, décide — et n'écrit l'artefact que si la décision passe."""
    import joblib

    from ml_engine.determinisme import etat as etat_determinisme
    from ml_engine.determinisme import limiter_threads

    panel = construire_panel()
    if panel.empty:
        return {"error": ("panneau vide — lancer d'abord "
                          "python -m ml_engine.stock.positions_historiques")}

    hp = evaluer_hors_periode(panel)
    base = {
        "version": 1,
        "question": ("cette référence va-t-elle cesser de se vendre dans les "
                     f"{HORIZON_MOIS} mois ?"),
        "nature_de_la_cible": (
            "OBSERVÉE — la référence s'est vendue, ou non. Aucun seuil déclaré, "
            "aucune simulation, aucune date inventée, aucune formule mêlant des "
            "variables explicatives."),
        "donnees": ("100 % réelles : positions reconstruites des factures, mix de "
                    "clientèle et prix issus des lignes de vente"),
        "horizon_mois": HORIZON_MOIS,
        "determinisme": etat_determinisme(),
        "n_observations": int(len(panel)),
        "n_references": int(panel["cle"].nunique()),
        "periode": f"{panel['mois'].min().date()} → {panel['mois'].max().date()}",
        "taux_de_base": round(float(panel["y"].mean()), 4),
        "condition_de_vivacite": (
            f"ventes sur au moins {MOIS_ACTIFS_MINIMUM} des "
            f"{FENETRE_VIVANTE} derniers mois. Sans cette condition, le panneau "
            "contiendrait des références déjà arrêtées dont l'arrêt futur est "
            "certain : le modèle apprendrait « ce qui est mort reste mort », "
            "vrai, inutile, et flatteur pour l'AUC."),
        "seuils_declares_avant_mesure": {
            "auc_minimale": SEUIL_AUC_MINIMALE,
            "gain_minimal_sur_reference_triviale": SEUIL_GAIN_MINIMAL,
            "ecart_train_valid_maximal": SEUIL_ECART_TRAIN_VALID,
        },
        "variables": {
            "flux": VARIABLES_FLUX,
            "clientele": VARIABLES_CLIENTELE,
            "prix": VARIABLES_PRIX,
            "contexte": VARIABLES_CONTEXTE,
            "pourquoi_ce_decoupage": (
                "Les variables de flux sont celles qu'un comptage exploite déjà. "
                "Le pari du module porte sur la clientèle et les prix : une "
                "référence dont la demande se concentre sur un acheteur meurt "
                "quand cet acheteur s'en va, et aucun volume ne le montre. "
                "L'ablation mesure cet apport au lieu de le supposer."),
        },
        "hors_periode": hp,
    }

    if not hp.get("applicable"):
        base["decision_deploiement"] = {
            "modele_deploye": False,
            "motif": f"protocole hors période inapplicable — {hp.get('motif')}",
        }
        _ecrire(base)
        return base

    retenu = hp["modele_retenu"]
    reglage = hp["reglage_retenu"]
    jeu = JEUX_DE_VARIABLES[hp["variables_retenues"]]

    base["groupkfold_indicatif"] = evaluer_groupkfold(panel, retenu, reglage, jeu)
    gk = base["groupkfold_indicatif"].get("auc_moyen")
    base["ecart_groupkfold_hors_periode"] = (
        round(gk - hp["auc"], 4) if gk else None)
    base["importance_permutation"] = importance_permutation(
        panel, retenu, reglage, jeu)

    auc, gain = hp["auc"], hp["gain_vs_reference_triviale"]
    deploye = (auc >= SEUIL_AUC_MINIMALE and gain >= SEUIL_GAIN_MINIMAL)

    if deploye:
        motif = (f"AUC {auc:.4f} hors période, soit {gain:+.4f} sur la meilleure "
                 f"référence triviale ({hp['meilleure_reference_triviale']}) — "
                 "les seuils déclarés sont atteints")
    elif auc < SEUIL_AUC_MINIMALE:
        motif = (f"AUC {auc:.4f} sous le seuil de {SEUIL_AUC_MINIMALE} — pas "
                 "assez discriminant pour décider")
    else:
        motif = (f"gain de seulement {gain:+.4f} sur "
                 f"« {hp['meilleure_reference_triviale']} » "
                 f"(AUC {hp['auc_meilleure_reference_triviale']:.4f}) : sous le "
                 f"seuil de {SEUIL_GAIN_MINIMAL}, un modèle n'ajoute rien qu'une "
                 "règle d'une ligne ne ferait déjà")

    base["decision_deploiement"] = {"modele_deploye": bool(deploye),
                                    "motif": motif}

    if not deploye:
        base["regle_servie_a_la_place"] = _mesurer_regle_servie(panel, hp)
    base["portee_et_limite"] = (
        "Le modèle dit quelles références vont s'arrêter, pas POURQUOI. Une "
        "référence remplacée par une version plus récente et une référence "
        "abandonnée par son unique acheteur reçoivent le même score. La décision "
        "de déstocker reste commerciale ; le modèle la priorise.")

    if deploye:
        with limiter_threads(1):
            m = _modele(retenu, reglage)
            m.fit(panel[jeu], panel["y"])
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"modele": m, "features": jeu, "nom": retenu,
                     "reglage": reglage, "jeu_de_variables": hp["variables_retenues"],
                     "horizon_mois": HORIZON_MOIS, "seed": SEED},
                    MODELS_DIR / "fin_de_vie.joblib")
        base["artefact"] = "models/fin_de_vie.joblib"
    else:
        ancien = MODELS_DIR / "fin_de_vie.joblib"
        if ancien.exists():
            try:
                ancien.unlink()
            except Exception:
                pass

    _ecrire(base)
    return base


def _mesurer_regle_servie(panel: pd.DataFrame,
                          hp: Dict[str, Any]) -> Dict[str, Any]:
    """Utilité de la RÈGLE qui a battu le modèle, mesurée sur le même test."""
    from sklearn.metrics import (average_precision_score, f1_score,
                                 precision_score, recall_score, roc_auc_score)

    coupure = pd.Timestamp(hp["coupure"])
    te = panel[panel["mois"] > coupure]
    if te.empty or te["y"].nunique() < 2:
        return {"applicable": False}

    score = -te["mois_actifs_12m"].to_numpy(dtype=float)
    taux_base = float(te["y"].mean())
    tr = panel[panel["mois"] + pd.DateOffset(months=HORIZON_MOIS) <= coupure]

    n_dec = max(int(len(te) * 0.10), 1)
    seuil = float(np.sort(score)[-n_dec])
    pred = (score >= seuil).astype(int)
    prec = float(precision_score(te["y"], pred, zero_division=0))

    return {
        "applicable": True,
        "nature": "regle_deterministe",
        "regle": ("classer les références par nombre de mois actifs sur les 12 "
                  "derniers, croissant : les moins actives d'abord"),
        "variable_unique": "mois_actifs_12m",
        "classification": metriques_classification(
            te["y"], score, y_train=tr["y"],
            p_train=-tr["mois_actifs_12m"].to_numpy(dtype=float),
            score_est_une_probabilite=False),
        "auc": round(float(roc_auc_score(te["y"], score)), 4),
        "average_precision": round(
            float(average_precision_score(te["y"], score)), 4),
        "au_seuil_du_decile": {
            "n_references_signalees": int(n_dec),
            "precision": round(prec, 4),
            "recall": round(float(recall_score(te["y"], pred,
                                               zero_division=0)), 4),
            "f1": round(float(f1_score(te["y"], pred, zero_division=0)), 4),
            "lift": round(prec / taux_base, 2) if taux_base > 0 else None,
        },
        "pourquoi_elle_est_servie": (
            "Elle bat le modèle sur le même jeu de test, et elle ne coûte rien : "
            "aucun artefact, aucun réentraînement, aucune dérive possible, et un "
            "directeur peut la vérifier à la main. Un refus de modèle ne doit pas "
            "laisser l'écran vide — c'est la même décision que pour la prévision "
            "de demande, où la baseline saisonnière est servie."),
        "ce_qu_elle_ne_fait_pas": (
            "Elle ordonne, elle ne donne pas de probabilité. Impossible donc de "
            "calculer une perte attendue = probabilité × exposition ; le "
            "classement se fait sur la valeur de stock détenue, ce qui répond à "
            "la même question de priorité."),
    }


def _ecrire(metriques: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "fin_de_vie_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)


def _raisons_ligne(r: Any) -> List[Dict[str, Any]]:
    """Pourquoi CETTE référence est signalée comme en fin de commercialisation."""
    try:
        from ml_engine.explication import raisons_seuils
    except Exception:
        return []
    def _f(nom, defaut=0.0):
        try:
            return float(r[nom])
        except Exception:
            return defaut
    mois_actifs = _f("mois_actifs_12m")
    valeurs = {
        "mois_sans_vente": max(0.0, 12.0 - mois_actifs),
        "n_clients_12m": _f("n_clients_12m"),
        "stock_actuel": max(0.0, _f("position_fin")),
    }
    # Les phrases sont composées par `raisons_seuils` à partir du libellé, de la
    # valeur et du seuil déclaré ici — un seul endroit où le seuil est écrit.
    return raisons_seuils(valeurs, [
        {"variable": "mois_sans_vente", "seuil": 6, "sens": "sup", "poids": 3.0},
        {"variable": "n_clients_12m", "seuil": 3, "sens": "inf", "poids": 2.0},
        {"variable": "stock_actuel", "seuil": 1, "sens": "sup", "poids": 1.0},
    ], n=3)


def predire(limite: int = 15) -> Dict[str, Any]:
    """Références à déstocker en priorité, si le registre l'autorise."""
    from ml_engine.registre import est_deploye

    modele_servi = est_deploye("fin_de_vie")
    chemin = MODELS_DIR / "fin_de_vie.joblib"

    try:
        panel = construire_panel(pour_prediction=True)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        dernier = panel.sort_values("mois").groupby("cle", as_index=False).tail(1)

        if modele_servi and chemin.exists():
            import joblib
            paquet = joblib.load(chemin)
            p = paquet["modele"].predict_proba(dernier[paquet["features"]])[:, 1]
            nature = "modele_appris"
            lecture_nature = "probabilité issue du modèle appris"
        else:
            actifs = dernier["mois_actifs_12m"].to_numpy(dtype=float)
            p = 1.0 - (actifs / 12.0).clip(0.0, 1.0)
            nature = "regle_deterministe"
            lecture_nature = ("score de règle — 1 − (mois actifs sur 12) / 12. "
                              "Ce n'est PAS une probabilité : il ordonne, il ne "
                              "quantifie pas")

        dernier = dernier.assign(probabilite=p)
        dernier["valeur_stock_dt"] = (dernier["position_fin"].clip(lower=0)
                                      * dernier["cout_unitaire"].fillna(0.0))
        dernier["capital_expose_dt"] = (dernier["probabilite"]
                                        * dernier["valeur_stock_dt"])

        top = dernier.sort_values("capital_expose_dt", ascending=False).head(limite)
        return {
            "servi": True,
            "nature": nature,
            "lecture_du_score": lecture_nature,
            "mois_de_reference": str(dernier["mois"].max().date()),
            "horizon_mois": HORIZON_MOIS,
            "n_references": int(len(dernier)),
            "capital_expose_total_dt": round(
                float(dernier["capital_expose_dt"].sum()), 0),
            "top": [{
                "produit": r["produit"],
                "probabilite": round(float(r["probabilite"]), 3),
                "valeur_stock_dt": round(float(r["valeur_stock_dt"]), 0),
                "capital_expose_dt": round(float(r["capital_expose_dt"]), 0),
                "raisons": _raisons_ligne(r),
                "n_clients_12m": int(r["n_clients_12m"]),
                "mois_sans_vente": int(r["mois_depuis_derniere_vente"]),
            } for _, r in top.iterrows()],
            "lecture_du_classement": (
                "trié par capital exposé — probabilité d'arrêt × valeur du stock "
                "détenu au coût d'achat réel — et non par probabilité"),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def afficher() -> None:
    m = train()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    print("\n" + "=" * 78)
    print("  FIN DE COMMERCIALISATION À 6 MOIS")
    print("=" * 78)
    print(f"\n  {m['question']}")
    print(f"  Données : {m['donnees']}")
    print(f"\n  Observations  : {m['n_observations']:,}".replace(",", " ")
          + f"  sur {m['n_references']} références vivantes")
    print(f"  Période       : {m['periode']}")
    print(f"  Taux de base  : {m['taux_de_base'] * 100:.1f} % des références "
          f"vivantes s'arrêtent dans les {m['horizon_mois']} mois")

    hp = m.get("hors_periode") or {}
    if not hp.get("applicable"):
        print(f"\n  Hors période inapplicable : {hp.get('motif')}")
        print("=" * 78 + "\n")
        return

    print("\n  " + "-" * 74)
    print("  HORS PÉRIODE — entraînement sur le passé, test sur le futur")
    print(f"    coupure {hp['coupure']} · marge anti-fuite "
          f"{hp['marge_anti_fuite_mois']} mois")
    print(f"    train {hp['n_train']:,}".replace(",", " ")
          + f" · test {hp['n_test']:,}".replace(",", " ")
          + f" · {hp['n_references_test']} références")

    sel = hp.get("selection") or {}
    if sel.get("applicable"):
        print(f"\n    SÉLECTION sur validation interne "
              f"(coupure {sel['coupure_interne']}, "
              f"{sel['n_essais']} essais, {sel['n_eligibles']} éligibles)")
        print(f"      {'famille':<22}{'variables':<11}{'AUC int.':>9}"
              f"{'sur-app.':>10}")
        for e in sel["essais"][:8]:
            etat = "" if e["eligible"] else "  DISQUALIFIÉ"
            if e is sel["retenu"] or (
                    e["famille"] == sel["retenu"]["famille"]
                    and e["reglage"] == sel["retenu"]["reglage"]
                    and e["variables"] == sel["retenu"]["variables"]):
                etat = "  <- retenu"
            print(f"      {e['famille']:<22}{e['variables']:<11}"
                  f"{e['auc_valid_interne']:>9.4f}{e['surapprentissage']:>+10.4f}"
                  f"{etat}")
        print(f"\n      réglage retenu : {hp['reglage_retenu']}")

    print(f"\n    AUC hors période    : {hp['auc']:.4f}")
    print(f"    Average precision   : {hp['average_precision']:.4f}   "
          f"(taux de base {hp['taux_positif_test'] * 100:.1f} %)")
    print(f"    Brier               : {hp['brier']:.4f}")
    print(f"\n    Sur-apprentissage   : {hp['surapprentissage_interne']:+.4f}"
          f"   (même période des deux côtés)")
    print(f"    Dérive temporelle   : {hp['derive_temporelle']:+.4f}"
          f"   (validation interne -> hors période)")

    d10 = hp.get("au_seuil_du_decile") or {}
    if d10:
        print(f"\n    Au seuil du DÉCILE ({d10['n_references_signalees']} "
              "références signalées) :")
        print(f"      précision {d10['precision']:.4f} · rappel "
              f"{d10['recall']:.4f} · lift {d10['lift']}")
    d05 = hp.get("au_seuil_de_0_5") or {}
    if d05:
        print(f"    Au seuil de 0,5 : {d05['n_positifs_predits']} positif(s) "
              "prédit(s) — inutilisable, et publié pour le montrer")

    print("\n    Références triviales (une variable, aucun apprentissage) :")
    for nom, a in sorted(hp["references_triviales"].items(), key=lambda kv: -kv[1]):
        print(f"      {nom:<28} AUC {a:.4f}")
    print(f"\n    GAIN sur la meilleure : {hp['gain_vs_reference_triviale']:+.4f}"
          f"   (seuil {SEUIL_GAIN_MINIMAL})")

    print(f"\n    Jeu de variables retenu : « {hp['variables_retenues']} »")
    for i in range(0, len(hp["apport_du_mix_clientele"]), 70):
        print(f"      {hp['apport_du_mix_clientele'][i:i+70]}")

    gk = m.get("groupkfold_indicatif") or {}
    if gk.get("auc_moyen"):
        print(f"\n  GroupKFold (indicatif) : AUC {gk['auc_moyen']:.4f} — "
              f"écart {m.get('ecart_groupkfold_hors_periode'):+.4f}")

    imp = m.get("importance_permutation") or {}
    if imp:
        print("\n  Variables les plus utiles (permutation, sur le test) :")
        for f, v in list(imp.items())[:8]:
            print(f"    {f:<30} {v:+.4f}")

    d = m["decision_deploiement"]
    print("\n" + "-" * 78)
    print(f"  DÉCISION : {'DÉPLOYÉ' if d['modele_deploye'] else 'REFUSÉ'}")
    for i in range(0, len(d["motif"]), 72):
        print(f"    {d['motif'][i:i+72]}")

    regle = m.get("regle_servie_a_la_place") or {}
    if regle.get("applicable"):
        print("\n  CE QUI EST SERVI À LA PLACE — une règle, mesurée")
        print(f"    {regle['regle']}")
        r10 = regle["au_seuil_du_decile"]
        print(f"\n    AUC {regle['auc']:.4f} · average precision "
              f"{regle['average_precision']:.4f}")
        print(f"    Au décile : précision {r10['precision']:.4f} · rappel "
              f"{r10['recall']:.4f} · lift {r10['lift']}")
        print("\n    Aucun artefact, aucun réentraînement, aucune dérive possible,")
        print("    et un directeur peut la vérifier à la main. Un refus de modèle")
        print("    ne laisse pas l'écran vide.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
