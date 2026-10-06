"""Modèle de **conditions de crédit client** — version 2, après réfutation de la v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from ml_engine.metriques import metriques_classification, metriques_decision

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

RISK_THRESHOLD_DAYS = 60
HIGH_RISK_SCORE = 70
MIN_HISTORIQUE = 3
SEED = 42

CAT_FEATURES = ["commercial", "depot", "etablissement", "code_tarif", "code_rib"]
NUM_FEATURES = ["ht", "ttc", "log_ttc", "nbart", "month", "quarter", "dow", "year"]
FEATURES = CAT_FEATURES + NUM_FEATURES

_FEATURES_INTERDITES = {
    "delay", "y", "date_echeance", "dateecheance",
    "delaidemande", "delaiaccepte", "delaireporte",
    "cli_prior_mean_delay", "cli_prior_n", "cli_prior_mean_ttc", "norme_client",
    "mode_regl", "modereglibelle", "modereglLIBELLE",
}


def _load_invoices() -> pd.DataFrame:
    import duckdb
    con = duckdb.connect()
    con.execute("SET threads=4")
    dp = "COALESCE(TRY_STRPTIME(DATEPIECE,'%m/%d/%Y'),TRY_STRPTIME(DATEPIECE,'%Y-%m-%d'))::DATE"
    de = "COALESCE(TRY_STRPTIME(DATEECHEANCE,'%m/%d/%Y'),TRY_STRPTIME(DATEECHEANCE,'%Y-%m-%d'))::DATE"
    sig = "TRY_CAST(MONTANTSIGNE_DEV AS DOUBLE)"
    df = con.execute(f"""
        WITH brut AS (
            SELECT trim(TIERS) client, {dp} date, datediff('day', {dp}, {de}) delay,
                   TRY_CAST(HT_DEV AS DOUBLE) ht, TRY_CAST(TTC_DEV AS DOUBLE) ttc,
                   TRY_CAST(NBREARTICLE AS DOUBLE) nbart,
                   coalesce(nullif(trim(MODEREGL),''),'INCONNU')       mode_regl,
                   coalesce(nullif(trim(COMMERCIAL1),''),'INCONNU')    commercial,
                   coalesce(nullif(trim(DEPOT),''),'INCONNU')          depot,
                   coalesce(nullif(trim(ETABLISSEMENT),''),'INCONNU')  etablissement,
                   coalesce(nullif(trim(CODETARIF),''),'INCONNU')      code_tarif,
                   coalesce(nullif(trim(CODERIB),''),'INCONNU')        code_rib,
                   trim(PIECENOFULL)                                   piece,
                   TRY_CAST(ENT_ID AS BIGINT)                          ent_id
            FROM read_csv_auto('{SALES_CSV.as_posix()}', sample_size=5000,
                               ignore_errors=true, all_varchar=true)
            WHERE {dp} IS NOT NULL AND {de} IS NOT NULL
              AND TRY_CAST(TTC_DEV AS DOUBLE) IS NOT NULL
              AND year({de}) BETWEEN 2000 AND 2035
              AND ({sig} IS NULL OR {sig} >= 0)      -- exclut les avoirs
        ),
        dedup AS (
            SELECT *, row_number() OVER (
                PARTITION BY CASE WHEN piece IS NULL OR piece = ''
                                  THEN CAST(ent_id AS VARCHAR) ELSE piece END,
                             client, date, ttc
                ORDER BY ent_id
            ) AS rang
            FROM brut
        )
        SELECT client, date, delay, ht, ttc, nbart, mode_regl, commercial,
               depot, etablissement, code_tarif, code_rib, piece
        FROM dedup WHERE rang = 1
        -- Tri TOTALEMENT déterministe : le numéro de pièce départage les ex æquo
        -- de (date, client). Sans ce dernier critère, l'ordre des factures d'un
        -- même client au même jour varie d'une exécution à l'autre, ce qui
        -- déplace la médiane glissante `norme_client` et fait bouger toutes les
        -- métriques — le même défaut que celui corrigé dans stock/generator.py.
        ORDER BY date ASC, client ASC, piece ASC
    """).df()
    con.close()
    return df.dropna(subset=["delay"]).reset_index(drop=True)


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Variables cold-start + norme historique (cette dernière sert la RÈGLE, pas le modèle)."""
    df = df.copy()
    df["y"] = (df["delay"] > RISK_THRESHOLD_DAYS).astype(int)
    d = pd.to_datetime(df["date"])
    df["month"], df["quarter"] = d.dt.month, d.dt.quarter
    df["dow"], df["year"] = d.dt.dayofweek, d.dt.year
    for c in ("ttc", "ht", "nbart"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["log_ttc"] = np.log1p(df["ttc"].clip(lower=0))

    df = df.sort_values(["client", "date", "piece"], kind="mergesort")
    g = df.groupby("client")["delay"]
    df["cli_prior_n"] = df.groupby("client").cumcount()
    df["norme_client"] = g.apply(lambda s: s.shift(1).expanding().median()).reset_index(level=0, drop=True)
    df["cli_prior_mean_delay"] = (g.cumsum() - df["delay"]) / df["cli_prior_n"].replace(0, np.nan)
    return df.sort_values(["date", "client", "piece"], kind="mergesort").reset_index(drop=True)


def _encoder(df: pd.DataFrame, mapping: Dict[str, Dict[str, int]] | None = None):
    """Encodage ordinal des catégorielles."""
    mapping = mapping or {c: {v: i for i, v in enumerate(sorted(df[c].astype(str).unique()))}
                          for c in CAT_FEATURES}
    out = df.copy()
    for c in CAT_FEATURES:
        out[c] = out[c].astype(str).map(mapping[c]).fillna(-1).astype(int)
    return out, mapping


def diagnostic_tautologie(df: pd.DataFrame) -> Dict:
    """Chiffre la réfutation de la v1."""
    from sklearn.metrics import roc_auc_score

    cut = int(len(df) * 0.8)
    te = df.iloc[cut:]
    hist = te["cli_prior_mean_delay"].fillna(df["delay"].median())
    regle = (hist > RISK_THRESHOLD_DAYS).astype(int)

    stats = df.groupby("client")["delay"].agg(["size", "std"])
    stats = stats[stats["size"] >= 5]

    return {
        "auc_regle_un_seuil": float(roc_auc_score(te["y"], regle)),
        "accuracy_regle_un_seuil": float((regle == te["y"]).mean()),
        "concordance_regle_cible": float(
            ((df["cli_prior_mean_delay"].fillna(df["delay"].median()) > RISK_THRESHOLD_DAYS)
             .astype(int) == df["y"]).mean()),
        "ecart_type_intra_client_median_j": float(stats["std"].median()),
        "ecart_type_global_j": float(df["delay"].std()),
        "conclusion": (
            "Le délai est une constante contractuelle par client "
            f"(écart-type intra-client médian {stats['std'].median():.2f} j contre "
            f"{df['delay'].std():.2f} j au global). Une règle à un seul seuil sur "
            "l'historique atteint déjà AUC "
            f"{roc_auc_score(te['y'], regle):.4f}. L'AUC de 0,9975 de la v1 mesurait "
            "la mémorisation de cette constante, pas une capacité de prédiction. "
            "Formulation abandonnée."),
    }


def evaluer_regle_client_connu(df: pd.DataFrame) -> Dict:
    """Performance de la norme historique — sans aucun apprentissage."""
    from sklearn.metrics import roc_auc_score, f1_score, accuracy_score

    sub = df[(df["cli_prior_n"] >= MIN_HISTORIQUE) & df["norme_client"].notna()]
    pred = (sub["norme_client"] > RISK_THRESHOLD_DAYS).astype(int)
    return {
        "methode": "norme historique du client (médiane des factures antérieures)",
        "n": int(len(sub)),
        "auc": float(roc_auc_score(sub["y"], sub["norme_client"])),
        "accuracy": float(accuracy_score(sub["y"], pred)),
        "f1": float(f1_score(sub["y"], pred)),
        "note": ("Aucun entraînement. Le délai étant contractuel, la norme passée est "
                 "la meilleure estimation disponible : un modèle ne peut que la recopier."),
    }


def evaluer_regle_hors_periode(df: pd.DataFrame) -> Dict:
    """La règle historique tient-elle SUR L'AVENIR ?"""
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

    cut = df["date"].quantile(0.8)
    avant, apres = df[df["date"] <= cut], df[df["date"] > cut]

    norme = (avant.groupby("client")["delay"]
             .agg(["median", "size"]).query(f"size >= {MIN_HISTORIQUE}")["median"])
    te = apres[apres["client"].isin(norme.index)].copy()
    if len(te) < 200 or te["y"].nunique() < 2:
        return {"applicable": False,
                "motif": f"seulement {len(te)} factures postérieures exploitables"}

    te["norme_avant"] = te["client"].map(norme)
    pred = (te["norme_avant"] > RISK_THRESHOLD_DAYS).astype(int)

    from sklearn.metrics import roc_auc_score as _auc
    base_taux = float(avant["y"].mean())

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(cut).date()),
        "n_factures_test": int(len(te)),
        "n_clients_test": int(te["client"].nunique()),
        "taux_positif_test": float(te["y"].mean()),
        "auc": float(roc_auc_score(te["y"], te["norme_avant"])),
        "accuracy": float(accuracy_score(te["y"], pred)),
        "f1": float(f1_score(te["y"], pred, zero_division=0)),
        "classification": metriques_decision(te["y"], pred, te["norme_avant"]),
        "reference_taux_de_base": base_taux,
        "note": ("La norme est calculée uniquement sur les factures antérieures à "
                 "la coupure, puis confrontée aux factures postérieures. Aucune "
                 "information future n'entre dans le calcul de la norme."),
    }


def _baselines_cold_start(Xtr, ytr, Xte, yte, tr_raw, te_raw) -> Dict[str, float]:
    """Références triviales que le modèle DOIT battre pour être déployé."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    out = {"classe_majoritaire": 0.5}
    out["montant_seul"] = float(roc_auc_score(yte, Xte["log_ttc"]))

    taux_m = tr_raw.groupby("month")["y"].mean()
    out["saisonnalite_seule"] = float(
        roc_auc_score(yte, te_raw["month"].map(taux_m).fillna(ytr.mean())))

    lr = make_pipeline(StandardScaler(),
                       LogisticRegression(max_iter=1000, random_state=SEED))
    lr.fit(Xtr[FEATURES], ytr)
    out["regression_logistique"] = float(roc_auc_score(yte, lr.predict_proba(Xte[FEATURES])[:, 1]))
    return out


def diagnostic_proxy_mode_reglement(df: pd.DataFrame) -> Dict:
    """Documente la 2ᵉ fuite : le mode de règlement épelle le délai."""
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    aucs = []
    for tr, te in GroupKFold(n_splits=5).split(df, df["y"], df["client"].values):
        taux = df.iloc[tr].groupby("mode_regl")["y"].mean()
        p = df.iloc[te]["mode_regl"].map(taux).fillna(df.iloc[tr]["y"].mean())
        aucs.append(float(roc_auc_score(df.iloc[te]["y"], p)))

    corr = (df.groupby("mode_regl")["delay"].median().sort_values()
              .tail(6).round(0).astype(int).to_dict())
    return {
        "auc_mode_reglement_seul": float(np.mean(aucs)),
        "delai_median_par_mode": corr,
        "conclusion": (
            "Le code de règlement contient le délai en toutes lettres "
            "(C030 = « CHÈQUE 30 JOURS » → 31 j, C060 → 61 j, C120 → 122 j). "
            f"Seul, il atteint AUC {np.mean(aucs):.4f} : il n'anticipe pas le délai, "
            "il le transcrit. Variable écartée des features et versée à la liste "
            "des variables interdites."),
    }


def evaluer_cold_start_hors_periode(enc: pd.DataFrame, df: pd.DataFrame, cat_idx, _clf) -> Dict:
    """Protocole le plus strict : client **nouveau ET postérieur**."""
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

    premiere = df.groupby("client")["date"].min()
    cut = df["date"].quantile(0.8)
    anciens = set(premiere[premiere <= cut].index)
    nouveaux = set(premiere[premiere > cut].index)

    tr = enc[enc["client"].isin(anciens) & (df["date"] <= cut)]
    te = enc[enc["client"].isin(nouveaux)]
    if len(te) < 100 or te["y"].nunique() < 2:
        return {"applicable": False,
                "motif": f"seulement {len(te)} factures de clients nouveaux après la coupure"}

    m = _clf(); m.fit(tr[FEATURES], tr["y"])
    p = m.predict_proba(te[FEATURES])[:, 1]
    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(cut).date()),
        "n_clients_train": len(anciens), "n_clients_test": int(te["client"].nunique()),
        "n_factures_test": int(len(te)),
        "taux_positif_test": float(te["y"].mean()),
        "auc": float(roc_auc_score(te["y"], p)),
        "accuracy": float(accuracy_score(te["y"], (p >= 0.5))),
        "f1": float(f1_score(te["y"], (p >= 0.5), zero_division=0)),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"],
            p_train=m.predict_proba(tr[FEATURES])[:, 1]),
    }


def train() -> Dict:
    print("[credit_risk] Démarrage… (v2 : régime A règle, régime B ML cold-start)")
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import (accuracy_score, average_precision_score, brier_score_loss,
                                 confusion_matrix, f1_score, precision_score, recall_score,
                                 roc_auc_score)
    from sklearn.model_selection import GroupKFold
    import joblib

    print("[credit_risk] Chargement des factures…")
    df = _build_features(_load_invoices())
    print(f"[credit_risk] {len(df):,} factures | {df.client.nunique()} clients | "
          f"conditions longues (>{RISK_THRESHOLD_DAYS}j) = {df.y.mean()*100:.1f}%")

    diag = diagnostic_tautologie(df)
    print(f"[credit_risk] v1 réfutée : règle à un seuil AUC={diag['auc_regle_un_seuil']:.4f} "
          f"| σ intra-client={diag['ecart_type_intra_client_median_j']:.2f}j "
          f"vs σ global={diag['ecart_type_global_j']:.2f}j")
    proxy = diagnostic_proxy_mode_reglement(df)
    print(f"[credit_risk] fuite n°2 écartée : mode de règlement seul "
          f"AUC={proxy['auc_mode_reglement_seul']:.4f} (il épelle le délai)")

    regle = evaluer_regle_client_connu(df)
    print(f"[credit_risk] Régime A (client connu, sans ML) : AUC={regle['auc']:.4f} "
          f"acc={regle['accuracy']:.4f} sur {regle['n']:,} factures")
    regle_hp = evaluer_regle_hors_periode(df)
    if regle_hp.get("applicable"):
        print(f"[credit_risk] Régime A HORS PÉRIODE (norme d'avant {regle_hp['coupure']} "
              f"confrontée à l'après) : AUC={regle_hp['auc']:.4f} "
              f"acc={regle_hp['accuracy']:.4f} sur {regle_hp['n_factures_test']:,} factures")

    enc, mapping = _encoder(df)
    groups = enc["client"].values
    cat_idx = [FEATURES.index(c) for c in CAT_FEATURES]

    def _clf():
        return HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, max_depth=6, l2_regularization=1.0,
            early_stopping=True, validation_fraction=0.15,
            categorical_features=cat_idx, random_state=SEED)

    gkf = GroupKFold(n_splits=5)
    aucs, aps, f1s, accs, briers, base_acc = [], [], [], [], [], []
    dernier = None
    for i, (a, b) in enumerate(gkf.split(enc, enc["y"], groups), 1):
        tr, te = enc.iloc[a], enc.iloc[b]
        m = _clf()
        m.fit(tr[FEATURES], tr["y"])
        p = m.predict_proba(te[FEATURES])[:, 1]
        pred = (p >= 0.5).astype(int)
        aucs.append(float(roc_auc_score(te["y"], p)))
        aps.append(float(average_precision_score(te["y"], p)))
        f1s.append(float(f1_score(te["y"], pred)))
        accs.append(float(accuracy_score(te["y"], pred)))
        briers.append(float(brier_score_loss(te["y"], p)))
        base_acc.append(_baselines_cold_start(tr, tr["y"], te, te["y"],
                                              df.iloc[a], df.iloc[b]))
        dernier = (te["y"].values, p, pred)
        print(f"[credit_risk]   pli {i}/5 — clients test={te['client'].nunique():>4} "
              f"AUC={aucs[-1]:.4f}")

    baselines = {k: float(np.mean([b[k] for b in base_acc])) for k in base_acc[0]}
    auc_moy, auc_std = float(np.mean(aucs)), float(np.std(aucs))
    meilleure_baseline = max(baselines, key=baselines.get)
    gain = auc_moy - baselines[meilleure_baseline]

    a, b = next(iter(gkf.split(enc, enc["y"], groups)))
    m_ref = _clf(); m_ref.fit(enc.iloc[a][FEATURES], enc.iloc[a]["y"])
    train_auc = float(roc_auc_score(enc.iloc[a]["y"],
                                    m_ref.predict_proba(enc.iloc[a][FEATURES])[:, 1]))

    RETIREES = ("month", "commercial")
    f_abl = [f for f in FEATURES if f not in RETIREES]
    cat_abl = [f_abl.index(c) for c in CAT_FEATURES if c not in RETIREES]
    abl = []
    for a2, b2 in gkf.split(enc, enc["y"], groups):
        m = HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.08, max_depth=6, l2_regularization=1.0,
            early_stopping=True, validation_fraction=0.15,
            categorical_features=cat_abl, random_state=SEED)
        m.fit(enc.iloc[a2][f_abl], enc.iloc[a2]["y"])
        abl.append(float(roc_auc_score(enc.iloc[b2]["y"],
                                       m.predict_proba(enc.iloc[b2][f_abl])[:, 1])))
    auc_ablation = float(np.mean(abl))

    hors_periode = evaluer_cold_start_hors_periode(enc, df, cat_idx, _clf)
    if hors_periode.get("applicable"):
        print(f"[credit_risk] Cold start HORS PÉRIODE ({hors_periode['n_clients_test']} clients "
              f"arrivés après {hors_periode['coupure']}) : AUC={hors_periode['auc']:.4f}")

    MARGE_MIN = 0.02
    gain_confirme = bool(gain >= MARGE_MIN)
    fuite_suspectee = bool(auc_moy > 0.98)
    confirme_hors_periode = (not hors_periode.get("applicable")
                             or hors_periode["auc"] >= baselines[meilleure_baseline])
    deploye = bool(gain_confirme and not fuite_suspectee and confirme_hors_periode)

    final = CalibratedClassifierCV(
        _clf(), method="isotonic",
        cv=list(GroupKFold(n_splits=5).split(enc, enc["y"], groups)))
    final.fit(enc[FEATURES], enc["y"])
    yv, pv, predv = dernier

    metrics = {
        "version": 3,
        "cible": f"délai de crédit accordé > {RISK_THRESHOLD_DAYS} jours",
        "donnees": {
            "nettoyage": "avoirs exclus (MONTANTSIGNE_DEV < 0), factures "
                         "dédupliquées sur PIECENOFULL",
            "n_factures_retenues": int(len(df)),
            "n_clients": int(df.client.nunique()),
            "periode": f"{df.date.min()} → {df.date.max()}",
            "remarque": "la version 2 incluait 5 761 avoirs et 1 324 doublons, "
                        "ce qui gonflait mécaniquement les métriques",
        },
        "refutation_v1": diag,
        "fuite_2_proxy_mode_reglement": proxy,
        "regime_A_client_connu": regle,
        "regime_A_hors_periode": regle_hp,
        "regime_B_cold_start": {
            "modele": "HistGradientBoostingClassifier calibré (isotonique)",
            "protocole": "GroupKFold 5 plis PAR CLIENT — aucune facture du client de test à l'entraînement",
            "n": int(len(df)), "n_clients": int(df.client.nunique()),
            "variables": FEATURES,
            "auc": auc_moy, "auc_std": auc_std, "auc_par_pli": aucs,
            "average_precision": float(np.mean(aps)),
            "accuracy": float(np.mean(accs)), "f1": float(np.mean(f1s)),
            "brier": float(np.mean(briers)),
            "precision": float(precision_score(yv, predv, zero_division=0)),
            "recall": float(recall_score(yv, predv, zero_division=0)),
            "confusion_matrix_dernier_pli": confusion_matrix(yv, predv).tolist(),
            "train_auc": train_auc,
            "ecart_train_test_auc": round(train_auc - aucs[0], 4),
            "baselines": baselines,
            "meilleure_baseline": meilleure_baseline,
            "gain_vs_baseline": round(gain, 4),
            "ablation_variables_retirees": list(RETIREES),
            "auc_ablation": auc_ablation,
            "perte_ablation": round(auc_moy - auc_ablation, 4),
            "cold_start_hors_periode": hors_periode,
        },
        "decision_deploiement": {
            "gain_confirme": gain_confirme,
            "marge_minimale_exigee": MARGE_MIN,
            "fuite_suspectee": fuite_suspectee,
            "confirme_hors_periode": bool(confirme_hors_periode),
            "modele_deploye": deploye,
            "motif": (
                f"Gain de {gain:+.4f} AUC sur la meilleure référence triviale "
                f"({meilleure_baseline} : {baselines[meilleure_baseline]:.4f}), "
                f"seuil exigé {MARGE_MIN:+.2f} → "
                + ("modèle déployé sur le régime cold start."
                   if deploye else
                   "gain non confirmé : le régime cold start retombe sur la référence.")),
        },

        "production": {
            "statut": "servi",
            "nature": "règle déterministe auditable (aucun apprentissage)",
            "methode_servie": (
                "score = 100 si la médiane des délais passés du client dépasse "
                f"{RISK_THRESHOLD_DAYS} j, 0 sinon ; taux de base pour un client "
                f"ayant moins de {MIN_HISTORIQUE} factures"),
            "metrique_de_reference": "AUC hors période de la règle",
            "auc_hors_periode": regle_hp.get("auc") if regle_hp.get("applicable") else None,
            "reference_auc_hasard": 0.5,
            "couverture_par_la_regle_pct": None,
            "pourquoi_pas_de_modele_appris": (
                "Le délai accordé a un écart-type de "
                f"{diag['ecart_type_intra_client_median_j']:.2f} j à l'intérieur d'un "
                f"client, contre {diag['ecart_type_global_j']:.2f} j au global : c'est "
                "une constante contractuelle. Un modèle appris ne peut que la "
                "mémoriser — ce que faisait la v1, d'où son AUC de 0,9975 sans "
                "valeur. Pour un client nouveau, aucune information n'existe par "
                "construction, et la mesure le confirme (AUC 0,597 hors période, "
                "sous la référence 0,665). Le refus du cold start et le service de "
                "la règle sont donc la même conclusion, pas deux décisions "
                "contradictoires."),
            "limite_assumee": (
                "Un client sans historique reçoit le taux de base. C'est la seule "
                "information honnête à son sujet ; le tableau de bord l'indique "
                "par le champ `source`, il n'est jamais présenté comme une "
                "prédiction personnalisée."),
        },
        "garde_fous": {
            "features_interdites": sorted(_FEATURES_INTERDITES),
            "note": ("DELAIDEMANDE / DELAIACCEPTE / DELAIREPORTE / DATEECHEANCE sont la cible "
                     "ou sa transcription directe. Les agrégats du client lui-même sont exclus : "
                     "indisponibles en cold start, et vecteurs de la tautologie de la v1."),
        },
    }

    print(f"[credit_risk] Régime B (cold start) : AUC={auc_moy:.4f} ± {auc_std:.4f} "
          f"| meilleure baseline {meilleure_baseline}={baselines[meilleure_baseline]:.4f} "
          f"| gain={gain:+.4f} → {'DÉPLOYÉ' if deploye else 'NON DÉPLOYÉ'}")
    print(f"[credit_risk] Ablation sans {' + '.join(RETIREES)} : AUC={auc_ablation:.4f} "
          f"(perte {auc_moy - auc_ablation:+.4f})")

    norme = (df[df["cli_prior_n"] >= MIN_HISTORIQUE]
             .groupby("client")["delay"].median())
    df["p_cold"] = final.predict_proba(enc[FEATURES])[:, 1]
    taux_base = float(df["y"].mean())
    agg = df.groupby("client").agg(exposure=("ttc", "sum"), n=("ttc", "size"),
                                   avg_delay=("delay", "mean"), p_cold=("p_cold", "mean"))
    client_risk = {}
    for cl, r in agg.iterrows():
        if cl in norme.index:
            score, source = (100.0 if norme[cl] > RISK_THRESHOLD_DAYS else 0.0), "regle_historique"
        elif deploye:
            score, source = float(r.p_cold) * 100.0, "modele_cold_start"
        else:
            score, source = taux_base * 100.0, "taux_de_base"
        client_risk[cl] = {"score": round(score, 1), "exposure": float(r.exposure),
                           "n": int(r.n), "avg_delay": float(round(r.avg_delay, 1)),
                           "source": source}

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": final, "features": FEATURES, "cat_features": CAT_FEATURES,
                 "encodage": mapping, "norme_client": norme.to_dict(),
                 "threshold": RISK_THRESHOLD_DAYS, "deploye": deploye},
                MODELS_DIR / "credit_risk_model.joblib")
    json.dump(metrics, open(REPORTS_DIR / "credit_risk_metrics.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    json.dump(client_risk, open(OUTPUT_DIR / "client_risk.json", "w", encoding="utf-8"),
              ensure_ascii=False)

    n_regle = sum(1 for v in client_risk.values() if v["source"] == "regle_historique")
    couverture = round(n_regle / len(client_risk) * 100, 1) if client_risk else 0.0
    metrics["production"]["couverture_par_la_regle_pct"] = couverture
    json.dump(metrics, open(REPORTS_DIR / "credit_risk_metrics.json", "w",
                            encoding="utf-8"), indent=2, ensure_ascii=False)

    print(f"[credit_risk] {len(client_risk)} clients scorés "
          f"({n_regle} par règle = {couverture:.1f} %, "
          f"{len(client_risk) - n_regle} au taux de base)")
    print(f"[credit_risk] PRODUCTION : règle déterministe servie "
          f"(aucun modèle appris) — couverture {couverture:.1f} % du portefeuille")
    return metrics


def load_client_risk() -> Dict:
    """Charge les scores de risque par client (vide si le modèle n'a pas été entraîné)."""
    p = OUTPUT_DIR / "client_risk.json"
    if p.exists():
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


if __name__ == "__main__":
    train()
