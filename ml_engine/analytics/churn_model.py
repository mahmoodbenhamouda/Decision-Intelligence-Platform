"""Modèle de **décrochage client** (attrition) — le seul modèle de ce projet dont la cible soit à…"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ml_engine.metriques import metriques_classification

from etl.sources import chemin as chemin_source

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
    DATA_DIR = Path(settings.data_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]
    DATA_DIR = BASE / "data_pfe"

MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"
OUTPUT_DIR = BASE / "output"
SALES_CSV = chemin_source("ventes_entetes", DATA_DIR)

HORIZON_JOURS = 90
MIN_FACTURES_ACTIF = 2
FENETRE_ACTIVITE_J = 365
SEED = 42

DEBUT_EXPLOITABLE = "2021-01-01"

FEATURES = [
    "recence_j", "anciennete_j",
    "freq_3m", "freq_6m", "freq_12m",
    "ca_3m", "ca_6m", "ca_12m", "log_ca_12m",
    "tendance_ca", "tendance_freq",
    "intervalle_moyen_j", "intervalle_ecart_type_j",
    "ratio_recence_intervalle",
    "panier_moyen", "mois",
]


def charger_factures(csv: Optional[Path] = None) -> pd.DataFrame:
    """Factures nettoyées, agrégées par (client, jour)."""
    import duckdb

    csv = csv or SALES_CSV
    con = duckdb.connect()
    con.execute("SET threads=4")
    dp = ("COALESCE(TRY_STRPTIME(DATEPIECE,'%m/%d/%Y'),"
          "TRY_STRPTIME(DATEPIECE,'%Y-%m-%d'))::DATE")
    sig = "TRY_CAST(MONTANTSIGNE_DEV AS DOUBLE)"
    df = con.execute(f"""
        WITH brut AS (
            SELECT trim(TIERS) client, {dp} date,
                   TRY_CAST(TTC_DEV AS DOUBLE) ttc,
                   trim(PIECENOFULL) piece,
                   TRY_CAST(ENT_ID AS BIGINT) ent_id
            FROM read_csv_auto('{csv.as_posix()}', sample_size=5000,
                               ignore_errors=true, all_varchar=true)
            WHERE {dp} IS NOT NULL
              AND TRY_CAST(TTC_DEV AS DOUBLE) IS NOT NULL
              AND ({sig} IS NULL OR {sig} >= 0)      -- exclut les avoirs
              AND trim(TIERS) IS NOT NULL AND trim(TIERS) <> ''
        ),
        dedup AS (
            SELECT *, row_number() OVER (
                PARTITION BY CASE WHEN piece IS NULL OR piece = ''
                                  THEN CAST(ent_id AS VARCHAR) ELSE piece END,
                             client, date, ttc
                ORDER BY ent_id
            ) rang
            FROM brut
        )
        SELECT client, date, count(*) n_factures, sum(ttc) ttc
        FROM dedup WHERE rang = 1
        GROUP BY client, date
        ORDER BY client, date
    """).df()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.reset_index(drop=True)


def _features_client(hist: pd.DataFrame, t: pd.Timestamp) -> Optional[Dict[str, float]]:
    """Variables d'un client à la date d'observation `t`, calculées sur `]-inf, t]`."""
    if hist.empty:
        return None

    dates = hist["date"].to_numpy()
    derniere = pd.Timestamp(dates[-1])
    premiere = pd.Timestamp(dates[0])

    def fenetre(mois: int) -> pd.DataFrame:
        borne = t - pd.Timedelta(days=30 * mois)
        return hist[hist["date"] > borne]

    f3, f6, f12 = fenetre(3), fenetre(6), fenetre(12)

    actif = hist[hist["date"] > t - pd.Timedelta(days=FENETRE_ACTIVITE_J)]
    if len(actif) < MIN_FACTURES_ACTIF:
        return None

    if len(hist) >= 2:
        ecarts = np.diff(dates).astype("timedelta64[D]").astype(float)
        ecarts = ecarts[-20:]
        interv_moy = float(np.mean(ecarts))
        interv_std = float(np.std(ecarts))
    else:
        interv_moy, interv_std = float(FENETRE_ACTIVITE_J), 0.0

    recence = float((t - derniere).days)
    ca12 = float(f12["ttc"].sum())

    ca_prec = float(hist[(hist["date"] > t - pd.Timedelta(days=180))
                         & (hist["date"] <= t - pd.Timedelta(days=90))]["ttc"].sum())
    ca_rec = float(f3["ttc"].sum())
    tendance_ca = float(np.clip(ca_rec / ca_prec, 0, 10)) if ca_prec > 0 else (
        2.0 if ca_rec > 0 else 0.0)

    n_prec = len(hist[(hist["date"] > t - pd.Timedelta(days=180))
                      & (hist["date"] <= t - pd.Timedelta(days=90))])
    tendance_freq = float(np.clip(len(f3) / n_prec, 0, 10)) if n_prec > 0 else (
        2.0 if len(f3) > 0 else 0.0)

    return {
        "recence_j": recence,
        "anciennete_j": float((t - premiere).days),
        "freq_3m": float(len(f3)),
        "freq_6m": float(len(f6)),
        "freq_12m": float(len(f12)),
        "ca_3m": ca_rec,
        "ca_6m": float(f6["ttc"].sum()),
        "ca_12m": ca12,
        "log_ca_12m": float(np.log1p(max(ca12, 0))),
        "tendance_ca": tendance_ca,
        "tendance_freq": tendance_freq,
        "intervalle_moyen_j": interv_moy,
        "intervalle_ecart_type_j": interv_std,
        "ratio_recence_intervalle": float(recence / interv_moy) if interv_moy > 0 else 0.0,
        "panier_moyen": float(hist["ttc"].tail(20).mean()),
        "mois": float(t.month),
    }


def construire_panel(df: pd.DataFrame,
                     horizon: int = HORIZON_JOURS) -> pd.DataFrame:
    """Panel (client, date d'observation) avec variables passées et cible future."""
    df = df[df["date"] >= pd.Timestamp(DEBUT_EXPLOITABLE)].copy()
    fin_donnees = df["date"].max()
    fin_obs = fin_donnees - pd.Timedelta(days=horizon)

    dates_obs = pd.date_range(
        start=pd.Timestamp(DEBUT_EXPLOITABLE) + pd.Timedelta(days=FENETRE_ACTIVITE_J),
        end=fin_obs, freq="ME")

    par_client = {c: g.sort_values("date").reset_index(drop=True)
                  for c, g in df.groupby("client")}

    lignes: List[Dict[str, Any]] = []
    for t in dates_obs:
        borne_haute = t + pd.Timedelta(days=horizon)
        for client, hist_tot in par_client.items():
            passe = hist_tot[hist_tot["date"] <= t]
            if passe.empty:
                continue
            feats = _features_client(passe, t)
            if feats is None:
                continue
            futur = hist_tot[(hist_tot["date"] > t)
                             & (hist_tot["date"] <= borne_haute)]
            feats.update({
                "client": client,
                "date_obs": t,
                "y": int(len(futur) == 0),
            })
            lignes.append(feats)

    panel = pd.DataFrame(lignes)
    return panel.sort_values(["date_obs", "client"]).reset_index(drop=True)


def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    """Une variable, aucun apprentissage."""
    from sklearn.metrics import roc_auc_score

    return {
        "classe_majoritaire": 0.5,
        "recence_seule": float(roc_auc_score(te["y"], te["recence_j"])),
        "ratio_recence_intervalle_seul": float(
            roc_auc_score(te["y"], te["ratio_recence_intervalle"])),
        "inverse_frequence_12m": float(roc_auc_score(te["y"], -te["freq_12m"])),
        "inverse_tendance_ca": float(roc_auc_score(te["y"], -te["tendance_ca"])),
    }


def _modele(nom: str = "gradient_boosting"):
    """Modèle candidat. Les deux voient exactement les mêmes variables."""
    if nom == "regression_logistique":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=2000, C=1.0, random_state=SEED))

    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.06, max_depth=5,
        l2_regularization=1.0, min_samples_leaf=40,
        early_stopping=True, validation_fraction=0.15,
        random_state=SEED)


CANDIDATS = ["regression_logistique", "gradient_boosting"]

ECART_PARCIMONIE = 0.01


def evaluer_hors_periode(panel: pd.DataFrame,
                         horizon: int = HORIZON_JOURS) -> Dict[str, Any]:
    """Protocole de référence : entraînement sur le passé, test sur le futur."""
    from sklearn.metrics import (accuracy_score, average_precision_score,
                                 brier_score_loss, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)

    coupure = panel["date_obs"].quantile(0.75)
    marge = pd.Timedelta(days=horizon)

    tr = panel[panel["date_obs"] + marge <= coupure]
    te = panel[panel["date_obs"] > coupure]

    if len(te) < 200 or te["y"].nunique() < 2 or len(tr) < 500:
        return {"applicable": False,
                "motif": f"train={len(tr)} test={len(te)} — effectifs insuffisants"}

    aucs: Dict[str, float] = {}
    proba: Dict[str, np.ndarray] = {}
    ajustes: Dict[str, Any] = {}
    for nom in CANDIDATS:
        m = _modele(nom)
        m.fit(tr[FEATURES], tr["y"])
        ajustes[nom] = m
        p = m.predict_proba(te[FEATURES])[:, 1]
        proba[nom] = p
        aucs[nom] = float(roc_auc_score(te["y"], p))

    retenu = CANDIDATS[0]
    for nom in CANDIDATS[1:]:
        if aucs[nom] - aucs[retenu] > ECART_PARCIMONIE:
            retenu = nom

    p = proba[retenu]
    pred = (p >= 0.5).astype(int)
    auc = aucs[retenu]

    triv = _references_triviales(te)
    meilleure_triv = max(triv, key=triv.get)

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(coupure).date()),
        "marge_anti_fuite_j": horizon,
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_clients_test": int(te["client"].nunique()),
        "taux_positif_train": float(tr["y"].mean()),
        "taux_positif_test": float(te["y"].mean()),

        "modeles_candidats": aucs,
        "modele_retenu": retenu,
        "regle_selection": (
            f"parcimonie — le modèle le plus simple est conservé sauf si un "
            f"modèle plus complexe gagne plus de {ECART_PARCIMONIE} d'AUC"),

        "auc": auc,
        "average_precision": float(average_precision_score(te["y"], p)),
        "accuracy": float(accuracy_score(te["y"], pred)),
        "precision": float(precision_score(te["y"], pred, zero_division=0)),
        "recall": float(recall_score(te["y"], pred, zero_division=0)),
        "f1": float(f1_score(te["y"], pred, zero_division=0)),
        "brier": float(brier_score_loss(te["y"], p)),
        "confusion_matrix": confusion_matrix(te["y"], pred).tolist(),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"],
            p_train=ajustes[retenu].predict_proba(tr[FEATURES])[:, 1]),

        "references_triviales": triv,
        "meilleure_reference_triviale": meilleure_triv,
        "auc_meilleure_reference_triviale": triv[meilleure_triv],
        "gain_vs_reference_triviale": round(auc - triv[meilleure_triv], 4),
    }


def evaluer_groupkfold(panel: pd.DataFrame,
                       modele: str = "gradient_boosting") -> Dict[str, Any]:
    """GroupKFold par client — reporté à titre INDICATIF seulement."""
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    aucs = []
    for a, b in GroupKFold(n_splits=5).split(panel, panel["y"], panel["client"].values):
        tr, te = panel.iloc[a], panel.iloc[b]
        if te["y"].nunique() < 2:
            continue
        m = _modele(modele)
        m.fit(tr[FEATURES], tr["y"])
        aucs.append(float(roc_auc_score(te["y"], m.predict_proba(te[FEATURES])[:, 1])))
    return {"auc_moyen": float(np.mean(aucs)) if aucs else None,
            "auc_par_pli": aucs,
            "avertissement": ("protocole indicatif : il brasse les périodes et "
                              "flatte le résultat. La décision de déploiement "
                              "repose sur le protocole hors période.")}


def importance_permutation(panel: pd.DataFrame,
                           horizon: int = HORIZON_JOURS,
                           modele: str = "gradient_boosting") -> Dict[str, float]:
    """Importance par permutation, mesurée SUR LE JEU DE TEST hors période."""
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score

    coupure = panel["date_obs"].quantile(0.75)
    tr = panel[panel["date_obs"] + pd.Timedelta(days=horizon) <= coupure]
    te = panel[panel["date_obs"] > coupure]
    if len(te) < 200 or len(tr) < 500:
        return {}

    m = _modele(modele)
    m.fit(tr[FEATURES], tr["y"])
    r = permutation_importance(m, te[FEATURES], te["y"], n_repeats=5,
                               random_state=SEED, scoring="roc_auc")
    return {f: round(float(v), 4)
            for f, v in sorted(zip(FEATURES, r.importances_mean),
                               key=lambda kv: -kv[1])}


def train(csv: Optional[Path] = None) -> Dict[str, Any]:
    import joblib
    from sklearn.calibration import CalibratedClassifierCV

    print("[churn] Chargement des factures…")
    df = charger_factures(csv)
    print(f"[churn] {len(df):,} jours-client | {df.client.nunique()} clients | "
          f"{df.date.min().date()} → {df.date.max().date()}".replace(",", " "))

    print("[churn] Construction du panel (client × fin de mois)…")
    panel = construire_panel(df)
    if panel.empty:
        raise RuntimeError("panel vide — vérifier DEBUT_EXPLOITABLE et les données")
    print(f"[churn] {len(panel):,} observations | {panel.client.nunique()} clients | "
          f"taux de décrochage {panel.y.mean()*100:.1f} %".replace(",", " "))

    print("[churn] Évaluation hors période…")
    hp = evaluer_hors_periode(panel)
    if not hp.get("applicable"):
        raise RuntimeError(f"protocole hors période inapplicable : {hp['motif']}")

    retenu = hp["modele_retenu"]
    print(f"[churn]   candidats : " + " | ".join(
        f"{k}={v:.4f}" for k, v in hp["modeles_candidats"].items()))
    print(f"[churn]   retenu par parcimonie : {retenu}")
    print(f"[churn]   AUC hors période = {hp['auc']:.4f}")
    print(f"[churn]   références triviales : " + " | ".join(
        f"{k}={v:.4f}" for k, v in sorted(hp["references_triviales"].items(),
                                          key=lambda kv: -kv[1])))
    print(f"[churn]   gain sur la meilleure "
          f"({hp['meilleure_reference_triviale']}) = "
          f"{hp['gain_vs_reference_triviale']:+.4f}")

    print("[churn] GroupKFold (indicatif)…")
    gkf = evaluer_groupkfold(panel, retenu)
    print(f"[churn]   AUC GroupKFold = {gkf['auc_moyen']:.4f} "
          f"(écart au hors période : {gkf['auc_moyen'] - hp['auc']:+.4f})")

    print("[churn] Importance par permutation…")
    imp = importance_permutation(panel, modele=retenu)

    MARGE_MIN = 0.02
    AUC_MIN = 0.70
    ECART_MAX = 0.15

    gain_confirme = bool(hp["gain_vs_reference_triviale"] >= MARGE_MIN)
    auc_suffisante = bool(hp["auc"] >= AUC_MIN)
    ecart = float(gkf["auc_moyen"] - hp["auc"]) if gkf["auc_moyen"] else 0.0
    pas_de_fuite = bool(abs(ecart) <= ECART_MAX)
    deploye = bool(gain_confirme and auc_suffisante and pas_de_fuite)

    from sklearn.model_selection import GroupKFold
    final = CalibratedClassifierCV(
        _modele(retenu), method="isotonic",
        cv=list(GroupKFold(n_splits=5).split(panel, panel["y"],
                                             panel["client"].values)))
    final.fit(panel[FEATURES], panel["y"])

    metrics = {
        "version": 1,
        "modele": f"{retenu} calibré (isotonique)",
        "modele_choisi_comment": (
            "Deux candidats voient exactement les mêmes variables : une "
            "régression logistique et un gradient boosting. Le plus simple est "
            f"conservé sauf gain d'AUC supérieur à {ECART_PARCIMONIE}. "
            + ("La régression logistique a été retenue : la non-linéarité "
               "n'apporte rien de significatif ici, et un modèle linéaire est "
               "interprétable par ses coefficients, plus rapide, et moins "
               "sujet à la dérive."
               if retenu == "regression_logistique" else
               "Le gradient boosting a été retenu : son gain sur le modèle "
               "linéaire dépasse le seuil de parcimonie.")),
        "cible": f"aucune commande dans les {HORIZON_JOURS} jours suivant l'observation",
        "pourquoi_cette_cible": (
            "Le modèle de conditions de crédit a été refusé parce que sa cible — "
            "le délai accordé — est une clause contractuelle : écart-type "
            "intra-client de 1,0 j contre 20,7 j au global. Elle était donc "
            "triviale pour un client connu (règle historique AUC 0,99) et "
            "impossible pour un client nouveau (AUC 0,597 hors période). "
            "Le décrochage, lui, est observable dans les factures futures, varie "
            "à l'intérieur d'un même client, et déclenche une action commerciale."),
        "donnees": {
            "n_observations": int(len(panel)),
            "n_clients": int(panel.client.nunique()),
            "periode_observation": f"{panel.date_obs.min().date()} → {panel.date_obs.max().date()}",
            "taux_decrochage": float(panel["y"].mean()),
            "nettoyage": "avoirs exclus, factures dédupliquées sur PIECENOFULL",
            "debut_exploitable": DEBUT_EXPLOITABLE,
            "motif_troncature": (
                "le trou de 27 mois (2018-08 → 2020-10) vient d'un changement "
                "d'outil de gestion, "
                "confirmée absente de toutes les sources ; le traverser avec une "
                "fenêtre de récence produirait des variables aberrantes"),
            "fin_observation": (
                f"max(date) − {HORIZON_JOURS} j : au-delà, la fenêtre cible serait "
                "tronquée et un client paraîtrait décroché faute de données"),
        },
        "variables": FEATURES,
        "hors_periode": hp,
        "groupkfold_indicatif": gkf,
        "ecart_groupkfold_hors_periode": round(ecart, 4),
        "importance_permutation_sur_test": imp,
        "decision_deploiement": {
            "juge": (
                "Le déploiement se juge UNIQUEMENT contre les références "
                "triviales — une variable, aucun apprentissage. Les modèles "
                "candidats servent à choisir l'algorithme, pas à valider "
                "l'utilité : rejeter un bon modèle parce qu'un autre bon modèle "
                "existe n'aurait aucun sens."),
            "seuils": {"marge_min_vs_reference_triviale": MARGE_MIN,
                       "auc_min": AUC_MIN,
                       "ecart_max_groupkfold": ECART_MAX,
                       "ecart_parcimonie": ECART_PARCIMONIE},
            "gain_confirme": gain_confirme,
            "auc_suffisante": auc_suffisante,
            "pas_de_fuite_temporelle": pas_de_fuite,
            "modele_deploye": deploye,
            "motif": (
                f"AUC hors période {hp['auc']:.4f} ({retenu}) contre "
                f"{hp['auc_meilleure_reference_triviale']:.4f} pour la meilleure "
                f"référence triviale ({hp['meilleure_reference_triviale']}), "
                f"gain {hp['gain_vs_reference_triviale']:+.4f} ; "
                f"écart au GroupKFold {ecart:+.4f}. → "
                + ("modèle déployé." if deploye else
                   "seuils non atteints : modèle non déployé.")),
        },
        "garde_fous": {
            "disjonction_fenetres": (
                f"variables sur ]-inf, t], cible sur ]t, t+{HORIZON_JOURS}j] — "
                "fenêtres disjointes, aucune variable ne peut contenir la cible"),
            "marge_anti_fuite_train": (
                f"une observation n'entre à l'entraînement que si "
                f"t + {HORIZON_JOURS} j <= coupure"),
            "filtre_client_actif": (
                f"au moins {MIN_FACTURES_ACTIF} commandes sur {FENETRE_ACTIVITE_J} j — "
                "sans ce filtre on prédirait le départ de clients déjà partis, "
                "tâche triviale qui gonflerait l'AUC sans servir"),
        },
    }

    print(f"[churn] Décision : {'DÉPLOYÉ' if deploye else 'NON DÉPLOYÉ'}")

    derniere = panel["date_obs"].max()
    courant = panel[panel["date_obs"] == derniere].copy()
    courant["p"] = final.predict_proba(courant[FEATURES])[:, 1]

    metrics["explicabilite"], raisons, contrefactuels = expliquer_scores(
        final, panel, courant)

    scores: Dict[str, Any] = {}
    for pos, (_, r) in enumerate(courant.iterrows()):
        scores[str(r["client"])] = {
            "raisons": raisons[pos] if pos < len(raisons) else [],
            "contrefactuel": (contrefactuels[pos]
                              if pos < len(contrefactuels) else None),
            "probabilite_decrochage": round(float(r["p"]), 3),
            "recence_j": int(r["recence_j"]),
            "intervalle_moyen_j": round(float(r["intervalle_moyen_j"]), 1),
            "ca_12m": round(float(r["ca_12m"]), 0),
            "freq_12m": int(r["freq_12m"]),
            "tendance_ca": round(float(r["tendance_ca"]), 2),
            "enjeu_dt": round(float(r["p"]) * float(r["ca_12m"]), 0),
            "source": "modele_churn" if deploye else "non_deploye",
        }

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": FEATURES,
                 "horizon_jours": HORIZON_JOURS, "deploye": deploye,
                 "date_reference": str(derniere.date())},
                MODELS_DIR / "churn_model.joblib")
    json.dump(metrics, open(REPORTS_DIR / "churn_metrics.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(scores, open(OUTPUT_DIR / "client_churn.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    n_risque = sum(1 for v in scores.values() if v["probabilite_decrochage"] >= 0.5)
    print(f"[churn] {len(scores)} clients actifs scorés au {derniere.date()} "
          f"({n_risque} au-dessus de 0,5)")
    print(f"[churn] → {REPORTS_DIR / 'churn_metrics.json'}")
    return metrics


# Ce qu'un commercial peut réellement faire bouger, et dans quel sens. Les bornes
# ne sont pas écrites ici : elles sont relevées sur le panel, pour qu'un
# contrefactuel ne propose jamais une valeur jamais observée.
ACTIONNABLES: Dict[str, str] = {
    "recence_j": "baisse",
    "ratio_recence_intervalle": "baisse",
    "freq_3m": "hausse",
    "freq_6m": "hausse",
    "ca_3m": "hausse",
    "ca_6m": "hausse",
}

SEUIL_RISQUE = 0.5
N_RAISONS = 3


def expliquer_scores(modele, panel: pd.DataFrame, lignes: pd.DataFrame):
    
    from ml_engine.explication import (contrefactuel, contributions_lineaires,
                                       extraire_pipeline_lineaire,
                                       fidelite_suppression)

    vide = ([[] for _ in range(len(lignes))], [None] * len(lignes))

    lin = extraire_pipeline_lineaire(modele)
    if lin is None:
        return ({"disponible": False,
                 "motif": ("le modèle servi n'est pas linéaire : une attribution "
                           "exacte est impossible, il faudrait TreeSHAP")},
                *vide)

    coefs, moyennes, ecarts = (lin["coefficients"], lin["moyennes"],
                               lin["ecarts"])
    X = lignes[FEATURES].to_numpy(dtype=float)
    scores = ((X - np.asarray(moyennes)) / np.asarray(ecarts)) @ np.asarray(coefs)
    reference = {v: panel[v].to_numpy(dtype=float) for v in FEATURES}

    raisons = [contributions_lineaires(coefs, moyennes, ecarts, X[i], FEATURES,
                                       n=N_RAISONS, reference=reference)
               for i in range(len(lignes))]

    # Le score linéaire et la probabilité servie ne vivent pas sur la même
    # échelle : la calibration isotonique est monotone mais non paramétrique. Le
    # seuil est donc RELEVÉ sur la population, pas supposé.
    p = lignes["p"].to_numpy(dtype=float)
    ordre = np.argsort(scores)
    seuil_score = float(np.interp(SEUIL_RISQUE, p[ordre], scores[ordre]))
    bornes = {v: (float(panel[v].min()), float(panel[v].max())) for v in FEATURES}
    actionnables = {v: {"sens": s, "min": bornes[v][0], "max": bornes[v][1]}
                    for v, s in ACTIONNABLES.items() if v in bornes}

    contrefactuels = [
        contrefactuel(coefs, moyennes, ecarts, X[i], FEATURES,
                      float(scores[i]), seuil_score, actionnables)
        if p[i] >= SEUIL_RISQUE else None
        for i in range(len(lignes))]

    from scipy.stats import spearmanr
    monotonie = round(float(spearmanr(scores, p).statistic), 4)

    attributions = ((X - np.asarray(moyennes)) / np.asarray(ecarts)) * np.asarray(coefs)
    fidelite = fidelite_suppression(
        lambda A: modele.predict_proba(pd.DataFrame(A, columns=FEATURES))[:, 1],
        X, attributions, np.asarray(moyennes), k_max=5)

    rapport = {
        "disponible": True,
        "methode": (
            "Attribution additive locale : contribution = coefficient × écart "
            "centré. Sur un modèle linéaire, cette décomposition est EXACTE et "
            "coïncide avec les valeurs de Shapley φⱼ = βⱼ(xⱼ − E[xⱼ])."),
        "origine_des_coefficients": lin["origine"],
        "monotonie_score_lineaire_vs_probabilite_servie": monotonie,
        "lecture_monotonie": (
            "Spearman entre la somme des contributions et la probabilité servie. "
            "Elle vaut 1 lorsque la calibration ne fait que déformer l'échelle "
            "sans changer l'ordre — c'est alors le même modèle qui est expliqué "
            "et qui décide."),
        "fidelite": fidelite,
        "contrefactuel": {
            "methode": ("forme close sur le modèle linéaire : valeur d'une seule "
                        "variable actionnable ramenant le score au seuil, bornée "
                        "aux valeurs observées sur le panel"),
            "seuil_de_score_releve": round(seuil_score, 4),
            "variables_actionnables": sorted(actionnables),
            "n_clients_avec_action": sum(1 for c in contrefactuels if c),
        },
        "facteurs_protecteurs": (
            "Le facteur qui pousse le plus dans le sens inverse est affiché avec "
            "`sens: protege` : masquer ce qui rassure donne une lecture biaisée "
            "d'un score qui en tient compte."),
        "aucun_gabarit_de_phrase": (
            "Les phrases sont composées depuis le libellé de la variable, le "
            "signe appris du coefficient et la position dans la distribution. "
            "Les gabarits précédents affirmaient une direction que le modèle "
            "pouvait contredire."),
    }
    return rapport, raisons, contrefactuels


def load_client_churn() -> Dict[str, Any]:
    """Scores de décrochage (dict vide si le modèle n'a pas tourné)."""
    p = OUTPUT_DIR / "client_churn.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    train()
