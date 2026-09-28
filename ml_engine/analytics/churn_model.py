"""
ml_engine/analytics/churn_model.py
===================================
Modèle de **décrochage client** (attrition) — le seul modèle de ce projet dont la
cible soit à la fois observable, non triviale et utile.

Pourquoi ce modèle existe
-------------------------
Le modèle de conditions de crédit (`credit_risk_model.py`) a été refusé deux fois,
et son diagnostic explique pourquoi aucune optimisation ne pouvait le sauver : le
délai de paiement accordé est une **clause contractuelle**, pas un comportement.
Son écart-type À L'INTÉRIEUR d'un client vaut 1,0 jour contre 20,7 jours au
global. La cible était donc :

  * **triviale** pour un client connu — il suffit de lire son contrat passé
    (la règle historique atteint AUC 0,99 sans aucun apprentissage) ;
  * **impossible** pour un client nouveau — AUC 0,597 hors période, sous la
    référence triviale de 0,665.

Un modèle ne crée pas d'information. Changer d'algorithme, ajouter des variables
ou régler des hyperparamètres ne pouvait rien y faire : l'information n'était pas
dans les données. Il fallait changer de question.

La question posée ici
--------------------
« Ce client actif va-t-il **cesser de commander** dans les 90 prochains jours ? »

Elle est meilleure sur les trois critères qui font échouer la précédente :

  * **Observable** — la cible se lit dans les factures futures, sans
    interprétation : le client a commandé, ou il n'a pas commandé. Aucune colonne
    manquante, aucune hypothèse.
  * **Non triviale** — contrairement au délai, le comportement d'achat varie
    fortement à l'intérieur d'un même client. Il y a donc quelque chose à
    apprendre.
  * **Utile** — retenir un client coûte moins cher que d'en acquérir un. Un
    directeur commercial agit sur cette information dès qu'il la reçoit.

Protocole d'évaluation
----------------------
**Hors période stricte**, le seul protocole qui reproduise l'usage : on
n'entraîne que sur des observations dont la fenêtre cible est ENTIÈREMENT
antérieure à la coupure, et on teste sur des observations postérieures. Un
GroupKFold par client est aussi calculé, mais il est reporté à titre indicatif :
il brasse les périodes et flatte systématiquement le résultat — c'est précisément
l'écart entre les deux qui avait révélé la fuite du modèle de crédit.

La référence à battre est **la récence seule** (« il n'a rien commandé depuis
N jours »). C'est une référence exigeante, et c'est le point important : sur une
tâche d'attrition, la récence explique déjà l'essentiel. Un modèle qui ne la bat
pas n'apporte rien, quelle que soit son AUC absolue.

Absence de fuite — par construction
-----------------------------------
Toutes les variables sont calculées sur la fenêtre `]-inf, T]` où T est la date
d'observation ; la cible se lit sur `]T, T+90j]`. Les deux fenêtres sont
disjointes, donc aucune variable ne peut contenir d'information sur la cible.
`tests/test_ml_churn.py` vérifie cette disjonction sur des données synthétiques
où toute fuite serait détectable.

Sortie
------
- `models/churn_model.joblib`        : modèle + seuil + métadonnées
- `reports/churn_metrics.json`       : métriques, baselines, décision
- `output/client_churn.json`         : probabilité de décrochage par client actif

Lancement :
    python -m ml_engine.analytics.churn_model
"""

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
# Jeu d'apprentissage construit sur la source brute, avec ses propres règles
# (voir docs/DATA_WAREHOUSE.md, « Ce qui lit encore les CSV ») ; le chemin vient
# du catalogue de l'ETL, seul endroit qui nomme un fichier source.
SALES_CSV = chemin_source("ventes_entetes", DATA_DIR)

# ── Paramètres métier ───────────────────────────────────────────────────────
HORIZON_JOURS = 90        # fenêtre d'observation de la cible
MIN_FACTURES_ACTIF = 2    # un client doit avoir commandé au moins 2 fois sur 12 mois
FENETRE_ACTIVITE_J = 365  # pour être jugé « actif » à la date d'observation
SEED = 42

# Le trou de 27 mois (2018-08 → 2020-10) est une bascule d'ERP, pas un défaut
# d'export : il est absent de TOUTES les sources (cf. scripts/audit_trou_temporel.py).
# Le faire traverser par une fenêtre de récence produirait des variables
# aberrantes — un client « absent depuis 800 jours » qui commandait normalement.
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


# ── Chargement ──────────────────────────────────────────────────────────────
def charger_factures(csv: Optional[Path] = None) -> pd.DataFrame:
    """Factures nettoyées, agrégées par (client, jour).

    Même nettoyage que partout ailleurs dans le projet : les avoirs sont exclus
    (un avoir n'est pas une commande — le compter comme telle ferait passer une
    annulation pour un signe de vitalité), et les factures sont dédupliquées sur
    PIECENOFULL, la vraie clé métier.
    """
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


# ── Construction du panel (client × date d'observation) ─────────────────────
def _features_client(hist: pd.DataFrame, t: pd.Timestamp) -> Optional[Dict[str, float]]:
    """Variables d'un client à la date d'observation `t`, calculées sur `]-inf, t]`.

    `hist` ne contient QUE des lignes de date <= t : la sélection est faite par
    l'appelant, et c'est là que repose la garantie d'absence de fuite.
    """
    if hist.empty:
        return None

    dates = hist["date"].to_numpy()
    derniere = pd.Timestamp(dates[-1])
    premiere = pd.Timestamp(dates[0])

    # Fenêtres glissantes
    def fenetre(mois: int) -> pd.DataFrame:
        borne = t - pd.Timedelta(days=30 * mois)
        return hist[hist["date"] > borne]

    f3, f6, f12 = fenetre(3), fenetre(6), fenetre(12)

    # Un client est « actif » s'il a commandé au moins MIN_FACTURES_ACTIF fois
    # sur la fenêtre d'activité. Sans ce filtre, on prédirait le décrochage de
    # clients déjà partis — une tâche triviale qui gonflerait l'AUC sans servir.
    actif = hist[hist["date"] > t - pd.Timedelta(days=FENETRE_ACTIVITE_J)]
    if len(actif) < MIN_FACTURES_ACTIF:
        return None

    # Intervalles entre commandes : la régularité est le socle du signal.
    if len(hist) >= 2:
        ecarts = np.diff(dates).astype("timedelta64[D]").astype(float)
        # On borne la fenêtre d'estimation aux 20 derniers intervalles : un
        # rythme d'achat d'il y a quatre ans ne dit rien du rythme actuel.
        ecarts = ecarts[-20:]
        interv_moy = float(np.mean(ecarts))
        interv_std = float(np.std(ecarts))
    else:
        interv_moy, interv_std = float(FENETRE_ACTIVITE_J), 0.0

    recence = float((t - derniere).days)
    ca12 = float(f12["ttc"].sum())

    # Tendance : dynamique récente contre dynamique précédente. Bornée pour que
    # quelques valeurs extrêmes ne dominent pas l'apprentissage.
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
        # LA variable clé : un client qui commande tous les 20 jours et n'a rien
        # commandé depuis 80 jours est anormal ; un client trimestriel ne l'est
        # pas. C'est le rapport, pas la récence brute, qui porte le signal.
        "ratio_recence_intervalle": float(recence / interv_moy) if interv_moy > 0 else 0.0,
        "panier_moyen": float(hist["ttc"].tail(20).mean()),
        "mois": float(t.month),
    }


def construire_panel(df: pd.DataFrame,
                     horizon: int = HORIZON_JOURS) -> pd.DataFrame:
    """Panel (client, date d'observation) avec variables passées et cible future.

    Une observation par client et par fin de mois. La cible vaut 1 si le client
    n'a **aucune** facture dans `]t, t+horizon]`.

    La dernière date d'observation retenue est `max(date) - horizon` : au-delà, la
    fenêtre cible serait tronquée et un client apparaîtrait décroché simplement
    parce que les données s'arrêtent. C'est le même garde-fou que celui appliqué
    à l'échéancier de trésorerie.
    """
    df = df[df["date"] >= pd.Timestamp(DEBUT_EXPLOITABLE)].copy()
    fin_donnees = df["date"].max()
    fin_obs = fin_donnees - pd.Timedelta(days=horizon)

    # Fins de mois servant de dates d'observation
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
                "y": int(len(futur) == 0),      # 1 = décroche
            })
            lignes.append(feats)

    panel = pd.DataFrame(lignes)
    return panel.sort_values(["date_obs", "client"]).reset_index(drop=True)


# ── Deux familles de comparaison, à ne pas confondre ────────────────────────
#
# La distinction est méthodologique et elle décide de tout :
#
#   * une RÉFÉRENCE TRIVIALE n'utilise qu'une seule variable brute et n'apprend
#     rien. Elle mesure la VALEUR AJOUTÉE du modèle : si « il n'a rien commandé
#     depuis N jours » suffit, le modèle n'apporte rien, quelle que soit son AUC.
#     C'est cette famille, et elle seule, qui décide du déploiement.
#
#   * un MODÈLE CANDIDAT utilise les mêmes variables et apprend. Le comparer au
#     modèle principal ne dit rien de la valeur ajoutée — cela répond à une autre
#     question : « la non-linéarité est-elle nécessaire ? ». Si un modèle linéaire
#     fait aussi bien, c'est LUI qu'il faut servir : plus simple, plus rapide,
#     interprétable par ses coefficients, et moins sujet à la dérive.
#
# Mélanger les deux familles fait rejeter un bon modèle parce qu'un autre bon
# modèle existe — ce qui n'a aucun sens.

def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    """Une variable, aucun apprentissage. C'est le juge du déploiement."""
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

# Écart d'AUC en dessous duquel deux modèles sont jugés équivalents. En cas
# d'équivalence, on retient le plus simple — ici la régression logistique, qui
# est en tête de `CANDIDATS`. Un demi-point d'AUC ne justifie pas de renoncer à
# l'interprétabilité d'un modèle linéaire.
ECART_PARCIMONIE = 0.01


def evaluer_hors_periode(panel: pd.DataFrame,
                         horizon: int = HORIZON_JOURS) -> Dict[str, Any]:
    """Protocole de référence : entraînement sur le passé, test sur le futur.

    Point délicat, et c'est lui qui rend la mesure honnête : la cible d'une
    observation d'entraînement se lit sur `]t, t+horizon]`. Pour qu'aucune
    information postérieure à la coupure n'entre dans l'entraînement, on exige
    `t + horizon <= coupure`. Sans cette marge, les dernières observations du
    train « verraient » le début de la période de test.
    """
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

    # 1) Les deux candidats, sur exactement les mêmes données
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

    # 2) Sélection par PARCIMONIE : on part du plus simple et on ne change que si
    #    un modèle plus complexe apporte un gain d'AUC réellement significatif.
    retenu = CANDIDATS[0]
    for nom in CANDIDATS[1:]:
        if aucs[nom] - aucs[retenu] > ECART_PARCIMONIE:
            retenu = nom

    p = proba[retenu]
    pred = (p >= 0.5).astype(int)
    auc = aucs[retenu]

    # 3) Le déploiement se juge UNIQUEMENT contre les références triviales
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
        # Métriques complètes et homogènes entre modèles (accuracy, balanced
        # accuracy, MCC, spécificité...) au seuil 0,5 ET au seuil choisi sur le
        # seul entraînement — cf. ml_engine/metriques.py.
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
    """GroupKFold par client — reporté à titre INDICATIF seulement.

    Ce protocole garantit qu'un client de test est inconnu, mais il brasse les
    périodes : le modèle peut apprendre la conjoncture d'une année sur d'autres
    clients de la même année. C'est exactement l'écart entre ce chiffre et celui
    hors période qui avait révélé la fuite du modèle de crédit (0,811 → 0,597).
    Le conserver rend l'écart visible au lieu de le masquer.
    """
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
    """Importance par permutation, mesurée SUR LE JEU DE TEST hors période.

    Mesurée sur le test et non sur le train : une variable peut être très
    utilisée à l'entraînement sans rien apporter en généralisation.
    """
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


# ── Entraînement complet ────────────────────────────────────────────────────
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

    # ── Règle d'acceptation ─────────────────────────────────────────────────
    # Trois conditions, et chacune répond à un échec constaté ailleurs dans ce
    # projet :
    #   1. gain réel sur la meilleure référence triviale (le crédit échouait ici) ;
    #   2. AUC absolue décente — un gain sur une référence faible ne suffit pas ;
    #   3. écart GroupKFold / hors période contenu : un écart large est la
    #      signature d'une fuite temporelle (0,811 → 0,597 pour le crédit).
    MARGE_MIN = 0.02
    AUC_MIN = 0.70
    ECART_MAX = 0.15

    gain_confirme = bool(hp["gain_vs_reference_triviale"] >= MARGE_MIN)
    auc_suffisante = bool(hp["auc"] >= AUC_MIN)
    ecart = float(gkf["auc_moyen"] - hp["auc"]) if gkf["auc_moyen"] else 0.0
    pas_de_fuite = bool(abs(ecart) <= ECART_MAX)
    deploye = bool(gain_confirme and auc_suffisante and pas_de_fuite)

    # ── Modèle final calibré ────────────────────────────────────────────────
    # Calibré parce que la sortie est lue comme une probabilité : « 0,8 » doit
    # signifier « 8 chances sur 10 », sinon le seuil d'alerte n'a pas de sens.
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
                "le trou de 27 mois (2018-08 → 2020-10) est une bascule d'ERP "
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

    # ── Scores par client (dernière observation disponible) ─────────────────
    derniere = panel["date_obs"].max()
    courant = panel[panel["date_obs"] == derniere].copy()
    courant["p"] = final.predict_proba(courant[FEATURES])[:, 1]

    # ── Modèle d'explication ────────────────────────────────────────────────
    #
    # Le modèle servi est CALIBRÉ : il agrège plusieurs estimateurs, et ses
    # coefficients ne sont pas directement lisibles. On ajuste donc une
    # régression logistique simple sur les mêmes données, uniquement pour
    # expliquer — les scores servis restent ceux du modèle calibré.
    #
    # La cohérence entre les deux est VÉRIFIÉE et publiée : si leurs classements
    # divergeaient, l'explication décrirait un autre modèle que celui qui décide.
    raisons: List[List[Dict[str, Any]]] = [[] for _ in range(len(courant))]
    accord_explication = None
    try:
        from scipy.stats import spearmanr
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        sc = StandardScaler().fit(panel[FEATURES].to_numpy(dtype=float))
        lr = LogisticRegression(max_iter=2000, C=1.0, random_state=SEED)
        lr.fit(sc.transform(panel[FEATURES].to_numpy(dtype=float)), panel["y"])

        p_expl = lr.predict_proba(
            sc.transform(courant[FEATURES].to_numpy(dtype=float)))[:, 1]
        accord_explication = round(float(spearmanr(courant["p"], p_expl).statistic), 4)

        raisons = expliquer(lr, (lr.coef_[0], sc.mean_, sc.scale_), panel, courant)
    except Exception:
        pass

    if accord_explication is not None:
        print(f"[churn] Accord modèle servi / modèle d'explication : "
              f"{accord_explication:.4f} (Spearman)")

    # Renseigné ici et non dans le bloc `metrics` : l'explication ne peut être
    # calculée qu'une fois le modèle final ajusté et les clients courants extraits.
    metrics["explicabilite"] = {
        "methode": (
            "Contribution de chaque variable = coefficient × valeur normalisée. "
            "Sur une régression logistique, cette décomposition est EXACTE : la "
            "somme des contributions et de l'ordonnée à l'origine reconstitue "
            "exactement le logit. Un modèle d'ensemble aurait exigé une "
            "attribution approchée — c'est un argument rétrospectif en faveur du "
            "choix de parcimonie."),
        "accord_avec_le_modele_servi": accord_explication,
        "lecture_accord": (
            "Corrélation de Spearman entre les scores du modèle servi (calibré) "
            "et ceux du modèle d'explication. Une valeur basse signifierait que "
            "l'explication décrit un autre modèle que celui qui décide."),
        "seules_contributions_positives": (
            "Un commercial veut savoir ce qui inquiète, pas ce qui rassure : les "
            "facteurs protecteurs ne sont pas affichés."),
    }

    scores: Dict[str, Any] = {}
    for pos, (_, r) in enumerate(courant.iterrows()):
        scores[str(r["client"])] = {
            # Pourquoi CE client est signalé. C'est ce qui transforme un score en
            # argument d'appel : un commercial ne décroche pas son téléphone sur
            # un nombre, mais sur « il n'a rien commandé depuis 80 jours alors
            # qu'il commandait toutes les trois semaines ».
            "raisons": raisons[pos] if pos < len(raisons) else [],
            "probabilite_decrochage": round(float(r["p"]), 3),
            "recence_j": int(r["recence_j"]),
            "intervalle_moyen_j": round(float(r["intervalle_moyen_j"]), 1),
            "ca_12m": round(float(r["ca_12m"]), 0),
            "freq_12m": int(r["freq_12m"]),
            "tendance_ca": round(float(r["tendance_ca"]), 2),
            # L'enjeu financier est ce qui permet de PRIORISER : une probabilité
            # de 0,9 sur un client à 2 000 DT ne vaut pas 0,6 sur un client à
            # 2 M DT. Le score seul ne suffit pas à décider.
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


# ── Explicabilité ───────────────────────────────────────────────────────────
#
# Traduction de chaque variable en langage de commercial. Sans elle, le modèle
# reste une boîte qui produit un nombre — et un commercial ne décroche pas son
# téléphone sur un nombre. Le sens est donné pour une contribution POSITIVE au
# risque ; l'inverse n'est pas affiché, un client rassurant n'appelant pas d'action.
_SENS_VARIABLES: Dict[str, str] = {
    "recence_j": "n'a pas commandé depuis {v:.0f} jours",
    "ratio_recence_intervalle": "son silence dure {v:.1f} fois son rythme habituel",
    "freq_3m": "seulement {v:.0f} commande(s) sur les 3 derniers mois",
    "freq_6m": "activité faible sur 6 mois ({v:.0f} commandes)",
    "freq_12m": "seulement {v:.0f} commande(s) sur 12 mois",
    "tendance_ca": "son chiffre d'affaires récent a reculé",
    "tendance_freq": "il commande moins souvent qu'avant",
    "ca_3m": "chiffre d'affaires quasi nul sur le trimestre",
    "ca_6m": "chiffre d'affaires en retrait sur 6 mois",
    "ca_12m": "volume annuel faible au regard de son historique",
    "log_ca_12m": "volume annuel faible au regard de son historique",
    "intervalle_moyen_j": "il espace naturellement ses commandes",
    "intervalle_ecart_type_j": "son rythme de commande est irrégulier",
    "panier_moyen": "ses commandes sont de faible montant",
    "anciennete_j": "relation encore récente",
    "mois": "effet de saison",
}


def expliquer(modele_lineaire, scaler_stats, panel: pd.DataFrame,
              lignes: pd.DataFrame, n_raisons: int = 3) -> List[List[Dict[str, Any]]]:
    """Raisons individuelles derrière chaque score, en langage métier.

    Sur une régression logistique, la contribution d'une variable au score vaut
    `coefficient × valeur normalisée`. C'est une décomposition EXACTE, pas une
    approximation : la somme des contributions et de l'ordonnée à l'origine donne
    exactement le logit. Un modèle d'ensemble aurait exigé une méthode
    d'attribution approchée — c'est l'une des raisons pour lesquelles le modèle
    linéaire a été retenu à performance équivalente.

    Seules les contributions POSITIVES sont remontées : un commercial veut savoir
    ce qui inquiète, pas ce qui rassure.
    """
    coefs, moyennes, echelles = scaler_stats
    X = lignes[FEATURES].to_numpy(dtype=float)
    Xn = (X - moyennes) / np.where(echelles == 0, 1.0, echelles)
    contributions = Xn * coefs      # (n_clients, n_variables)

    out: List[List[Dict[str, Any]]] = []
    for i in range(len(lignes)):
        ordre = np.argsort(-contributions[i])
        raisons: List[Dict[str, Any]] = []
        for j in ordre:
            if contributions[i, j] <= 0.05:     # contribution négligeable
                continue
            nom = FEATURES[j]
            gabarit = _SENS_VARIABLES.get(nom)
            if not gabarit:
                continue
            raisons.append({
                "variable": nom,
                "valeur": round(float(X[i, j]), 2),
                "poids": round(float(contributions[i, j]), 3),
                "explication": gabarit.format(v=float(X[i, j])),
            })
            if len(raisons) >= n_raisons:
                break
        out.append(raisons)
    return out


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
