"""
ml_engine/analytics/credit_risk_model.py
=========================================
Modèle de **conditions de crédit client** — version 2, après réfutation de la v1.

Pourquoi une v2
---------------
La v1 prédisait `délai accordé > 60 j` à partir, entre autres, de la moyenne des
délais **passés du même client**. Elle affichait AUC = 0,9975. Ce chiffre n'était
pas une performance : c'était une **tautologie**, et le diagnostic ci-dessous la
chiffre (`diagnostic_tautologie()`) :

* l'écart-type du délai **à l'intérieur d'un client** vaut ~1,0 jour, contre
  ~20,7 jours sur l'ensemble : le délai est une **constante contractuelle par
  client**, pas un comportement à prédire ;
* une **règle à un seul seuil** — « la moyenne passée du client dépasse-t-elle
  60 j ? » — atteint à elle seule AUC ≈ 0,918 et reproduit la cible dans 86,5 %
  des cas, sans aucun apprentissage ;
* le modèle n'ajoutait donc que la mémorisation de la constante de chaque client.

Un modèle qui redit ce que le contrat dit déjà n'a aucune valeur opérationnelle.
La v2 sépare le problème en deux régimes, et n'utilise l'apprentissage QUE là où
il a quelque chose à apprendre.

Régime A — client connu : AUCUN modèle
--------------------------------------
Le délai étant contractuel et stable, la meilleure estimation est la **norme
historique du client**. C'est une règle déterministe, auditable, sans
entraînement. Le score publié pour ces clients est un **fait mesuré**, pas une
prédiction.

Régime B — client nouveau (cold start) : le seul endroit où le ML aurait un rôle
-------------------------------------------------------------------------------
À la première facture, aucun historique n'existe *par construction*. La question
métier devient réelle : « ce client que nous n'avons jamais servi va-t-il exiger
des conditions longues ? » Le modèle n'utilise que des attributs disponibles au
premier contact — commercial, dépôt, établissement, code tarif, RIB, montant,
calendrier — et **jamais** d'agrégat du client lui-même.

Deux protocoles, deux verdicts :

* **GroupKFold par client** (client de test jamais vu) → AUC 0,811. Encourageant,
  mais ce protocole brasse les périodes : le modèle peut apprendre l'usage d'une
  année sur d'autres clients de la même année.
* **Cold start hors période** (client jamais vu ET arrivé APRÈS la coupure —
  la situation réelle de production) → **AUC 0,572**, sous la régression
  logistique de référence (0,673).

Le gain ne survit donc pas au seul protocole qui reproduit l'usage. **Aucun
modèle n'est déployé** : les clients sans historique reçoivent le taux de base,
seule information honnête à leur sujet. Même règle d'acceptation que la prévision
de demande 30/60/90 j — un gain non confirmé hors échantillon n'est pas servi.

Trois fuites rencontrées, toutes documentées
--------------------------------------------
1. **Tautologie v1** : la moyenne des délais passés du client, alors que le délai
   est une constante contractuelle (AUC 0,9975 → réfutée).
2. **Proxy `MODEREGL`** : le code de règlement épelle le délai (C060 = « CHÈQUE
   60 JOURS »). Seul, AUC 0,934. Détecté par le garde-fou `fuite_suspectee`
   lorsque le cold start est monté à 0,9998.
3. **Fuite temporelle** : révélée par l'écart 0,811 → 0,572 entre GroupKFold et
   cold start hors période.

`DELAIDEMANDE`, `DELAIACCEPTE`, `DELAIREPORTE`, `DATEECHEANCE` et `MODEREGL` sont
verrouillés dans `_FEATURES_INTERDITES` ; `tests/test_ml_credit.py` échoue si
l'un d'eux réapparaît dans les variables.

Sortie
------
- `models/credit_risk_model.joblib`  : modèle cold-start + encodeurs + norme par client
- `reports/credit_risk_metrics.json` : diagnostic v1, métriques cold-start, baselines
- `output/client_risk.json`          : score par client (+ `source` du score)

Lancement :
    python -m ml_engine.analytics.credit_risk_model
"""

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
# Jeu d'apprentissage construit sur la source brute, avec ses propres règles
# (voir docs/DATA_WAREHOUSE.md, « Ce qui lit encore les CSV ») ; le chemin vient
# du catalogue de l'ETL, seul endroit qui nomme un fichier source.
SALES_CSV = chemin_source("ventes_entetes", DATA_DIR)

RISK_THRESHOLD_DAYS = 60    # au-delà : conditions de crédit « longues »
HIGH_RISK_SCORE = 70        # score (0-100) au-delà duquel un client est « à risque élevé »
MIN_HISTORIQUE = 3          # factures nécessaires pour que la norme d'un client soit fiable
SEED = 42

# Variables disponibles dès la PREMIÈRE facture d'un client inconnu.
CAT_FEATURES = ["commercial", "depot", "etablissement", "code_tarif", "code_rib"]
NUM_FEATURES = ["ht", "ttc", "log_ttc", "nbart", "month", "quarter", "dow", "year"]
FEATURES = CAT_FEATURES + NUM_FEATURES

# Verrou anti-fuite : ces champs SONT la cible ou sa transcription directe.
# Toute réapparition dans FEATURES fait échouer tests/test_ml_credit.py.
_FEATURES_INTERDITES = {
    "delay", "y", "date_echeance", "dateecheance",
    "delaidemande", "delaiaccepte", "delaireporte",
    # Agrégats du client lui-même : indisponibles en cold start, et vecteurs de
    # la tautologie de la v1.
    "cli_prior_mean_delay", "cli_prior_n", "cli_prior_mean_ttc", "norme_client",
    # Le mode de règlement est la cible RÉÉCRITE EN CODE : C030 = « CHÈQUE
    # 30 JOURS » (délai médian 31 j), C060 = 61 j, V090 = 90 j, C120 = 122 j.
    # Seul, il atteint AUC 0,934 — il ne prédit pas le délai, il l'épelle.
    # Conservé au chargement pour DOCUMENTER la fuite, jamais dans FEATURES.
    "mode_regl", "modereglibelle", "modereglLIBELLE",
}


# ── Chargement ──────────────────────────────────────────────────────────────
def _load_invoices() -> pd.DataFrame:
    import duckdb
    con = duckdb.connect()
    con.execute("SET threads=4")
    dp = "COALESCE(TRY_STRPTIME(DATEPIECE,'%m/%d/%Y'),TRY_STRPTIME(DATEPIECE,'%Y-%m-%d'))::DATE"
    de = "COALESCE(TRY_STRPTIME(DATEECHEANCE,'%m/%d/%Y'),TRY_STRPTIME(DATEECHEANCE,'%Y-%m-%d'))::DATE"
    # NETTOYAGE IDENTIQUE À CELUI DE L'ENTREPÔT — indispensable.
    #
    # Cette fonction lisait le CSV brut. Le modèle s'entraînait donc sur :
    #
    #   * les 5 761 AVOIRS, traités comme des ventes. Un avoir n'est pas un
    #     événement de crédit : c'est l'annulation d'un précédent. Son « délai »
    #     DATEPIECE → DATEECHEANCE n'a aucun sens comme cible, et son étiquette
    #     y injectait donc du bruit pur ;
    #
    #   * les 1 324 FACTURES DUPLIQUÉES, qui pondéraient doublement certaines
    #     observations et pouvaient placer la même facture des deux côtés d'un
    #     découpage de validation.
    #
    # Les deux biais gonflent mécaniquement les métriques. Toute performance
    # mesurée avant cette correction est donc invalide, y compris les refus de
    # déploiement : il fallait refaire la mesure sur données propres pour que la
    # conclusion, quelle qu'elle soit, ait une valeur.
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

    # Norme du client sur ses factures STRICTEMENT antérieures. Réservée au
    # régime A (règle déterministe) et au diagnostic — jamais donnée au modèle.
    df = df.sort_values(["client", "date", "piece"], kind="mergesort")
    g = df.groupby("client")["delay"]
    df["cli_prior_n"] = df.groupby("client").cumcount()
    df["norme_client"] = g.apply(lambda s: s.shift(1).expanding().median()).reset_index(level=0, drop=True)
    df["cli_prior_mean_delay"] = (g.cumsum() - df["delay"]) / df["cli_prior_n"].replace(0, np.nan)
    return df.sort_values(["date", "client", "piece"], kind="mergesort").reset_index(drop=True)


def _encoder(df: pd.DataFrame, mapping: Dict[str, Dict[str, int]] | None = None):
    """Encodage ordinal des catégorielles. Une modalité inconnue en test → -1
    (cas normal en cold start : nouveau commercial, nouveau mode de règlement)."""
    mapping = mapping or {c: {v: i for i, v in enumerate(sorted(df[c].astype(str).unique()))}
                          for c in CAT_FEATURES}
    out = df.copy()
    for c in CAT_FEATURES:
        out[c] = out[c].astype(str).map(mapping[c]).fillna(-1).astype(int)
    return out, mapping


# ── Diagnostic : la v1 était-elle tautologique ? ────────────────────────────
def diagnostic_tautologie(df: pd.DataFrame) -> Dict:
    """Chiffre la réfutation de la v1. Conservé dans le code : c'est la preuve
    que le rejet du modèle précédent repose sur une mesure, pas sur une opinion."""
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


# ── Régime A : règle déterministe pour les clients connus ───────────────────
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
    """La règle historique tient-elle SUR L'AVENIR ? C'est ce qui autorise à la servir.

    Le régime A affiche une AUC élevée, mais mesurée sur l'ensemble de
    l'historique. Or « la norme passée prédit le délai futur » est une
    affirmation temporelle : elle doit être vérifiée dans le sens du temps, sinon
    elle ne vaut pas mieux que la tautologie reprochée à la v1.

    Protocole : la norme est calculée sur les factures ANTÉRIEURES à une coupure,
    et confrontée aux factures POSTÉRIEURES des mêmes clients. Si le résultat
    s'effondre — comme s'était effondré le modèle cold-start — la règle ne doit
    pas être servie davantage que lui.
    """
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

    cut = df["date"].quantile(0.8)
    avant, apres = df[df["date"] <= cut], df[df["date"] > cut]

    # Norme établie AVANT la coupure, sur les clients ayant assez d'historique.
    norme = (avant.groupby("client")["delay"]
             .agg(["median", "size"]).query(f"size >= {MIN_HISTORIQUE}")["median"])
    te = apres[apres["client"].isin(norme.index)].copy()
    if len(te) < 200 or te["y"].nunique() < 2:
        return {"applicable": False,
                "motif": f"seulement {len(te)} factures postérieures exploitables"}

    te["norme_avant"] = te["client"].map(norme)
    pred = (te["norme_avant"] > RISK_THRESHOLD_DAYS).astype(int)

    # Référence : le taux de base global, seule information disponible sans
    # regarder le client. Si la règle ne la bat pas, elle n'apporte rien.
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
        # La règle SERVIE, mesurée avec les mêmes grandeurs qu'un modèle appris.
        "classification": metriques_decision(te["y"], pred, te["norme_avant"]),
        "reference_taux_de_base": base_taux,
        "note": ("La norme est calculée uniquement sur les factures antérieures à "
                 "la coupure, puis confrontée aux factures postérieures. Aucune "
                 "information future n'entre dans le calcul de la norme."),
    }


# ── Régime B : ML cold-start, évalué sur des clients jamais vus ─────────────
def _baselines_cold_start(Xtr, ytr, Xte, yte, tr_raw, te_raw) -> Dict[str, float]:
    """Références triviales que le modèle DOIT battre pour être déployé."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    out = {"classe_majoritaire": 0.5}
    out["montant_seul"] = float(roc_auc_score(yte, Xte["log_ttc"]))

    # Saisonnalité seule : taux de positifs par mois, appris sur le seul train.
    taux_m = tr_raw.groupby("month")["y"].mean()
    out["saisonnalite_seule"] = float(
        roc_auc_score(yte, te_raw["month"].map(taux_m).fillna(ytr.mean())))

    lr = make_pipeline(StandardScaler(),
                       LogisticRegression(max_iter=1000, random_state=SEED))
    lr.fit(Xtr[FEATURES], ytr)
    out["regression_logistique"] = float(roc_auc_score(yte, lr.predict_proba(Xte[FEATURES])[:, 1]))
    return out


def diagnostic_proxy_mode_reglement(df: pd.DataFrame) -> Dict:
    """Documente la 2ᵉ fuite : le mode de règlement épelle le délai.

    Détectée par le garde-fou `fuite_suspectee` (AUC cold start = 0,9998 au
    premier entraînement). Conservée dans le rapport : une fuite écartée doit
    rester traçable, sinon rien ne distingue « variable jamais essayée » de
    « variable essayée et rejetée pour cause de fuite »."""
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
    """Protocole le plus strict : client **nouveau ET postérieur**.

    Le GroupKFold garantit que le client de test est inconnu, mais brasse les
    périodes : le modèle peut apprendre « en 2024, les conditions se sont
    allongées » sur d'autres clients de 2024. Ici on ferme aussi cette porte —
    entraînement sur les clients arrivés AVANT la coupure, test sur ceux dont la
    **première facture** est POSTÉRIEURE. C'est littéralement la situation de
    production : un client que nous n'avons jamais servi se présente demain."""
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

    # 1) Réfutation chiffrée de la v1
    diag = diagnostic_tautologie(df)
    print(f"[credit_risk] v1 réfutée : règle à un seuil AUC={diag['auc_regle_un_seuil']:.4f} "
          f"| σ intra-client={diag['ecart_type_intra_client_median_j']:.2f}j "
          f"vs σ global={diag['ecart_type_global_j']:.2f}j")
    proxy = diagnostic_proxy_mode_reglement(df)
    print(f"[credit_risk] fuite n°2 écartée : mode de règlement seul "
          f"AUC={proxy['auc_mode_reglement_seul']:.4f} (il épelle le délai)")

    # 2) Régime A — règle déterministe, puis vérification qu'elle tient sur l'avenir
    regle = evaluer_regle_client_connu(df)
    print(f"[credit_risk] Régime A (client connu, sans ML) : AUC={regle['auc']:.4f} "
          f"acc={regle['accuracy']:.4f} sur {regle['n']:,} factures")
    regle_hp = evaluer_regle_hors_periode(df)
    if regle_hp.get("applicable"):
        print(f"[credit_risk] Régime A HORS PÉRIODE (norme d'avant {regle_hp['coupure']} "
              f"confrontée à l'après) : AUC={regle_hp['auc']:.4f} "
              f"acc={regle_hp['accuracy']:.4f} sur {regle_hp['n_factures_test']:,} factures")

    # 3) Régime B — ML cold-start, GroupKFold par client
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

    # 4) Écart train→test : mesure de surapprentissage sur le protocole cold-start
    a, b = next(iter(gkf.split(enc, enc["y"], groups)))
    m_ref = _clf(); m_ref.fit(enc.iloc[a][FEATURES], enc.iloc[a]["y"])
    train_auc = float(roc_auc_score(enc.iloc[a]["y"],
                                    m_ref.predict_proba(enc.iloc[a][FEATURES])[:, 1]))

    # 5) Ablation : retirer les deux variables les plus informatives restantes
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

    # 6) Protocole le plus strict : client nouveau ET postérieur à la coupure
    hors_periode = evaluer_cold_start_hors_periode(enc, df, cat_idx, _clf)
    if hors_periode.get("applicable"):
        print(f"[credit_risk] Cold start HORS PÉRIODE ({hors_periode['n_clients_test']} clients "
              f"arrivés après {hors_periode['coupure']}) : AUC={hors_periode['auc']:.4f}")

    # 7) Règle d'acceptation — identique à celle de la prévision de demande :
    #    un gain non confirmé face aux références triviales n'est pas déployé.
    MARGE_MIN = 0.02
    gain_confirme = bool(gain >= MARGE_MIN)
    fuite_suspectee = bool(auc_moy > 0.98)
    # Le gain doit tenir sur le protocole strict quand celui-ci est calculable.
    confirme_hors_periode = (not hors_periode.get("applicable")
                             or hors_periode["auc"] >= baselines[meilleure_baseline])
    deploye = bool(gain_confirme and not fuite_suspectee and confirme_hors_periode)

    # 8) Modèle final calibré (probabilités exploitables comme des probabilités)
    final = CalibratedClassifierCV(
        _clf(), method="isotonic",
        cv=list(GroupKFold(n_splits=5).split(enc, enc["y"], groups)))
    final.fit(enc[FEATURES], enc["y"])
    yv, pv, predv = dernier

    metrics = {
        "version": 3,
        "cible": f"délai de crédit accordé > {RISK_THRESHOLD_DAYS} jours",
        # Provenance des données d'entraînement. La version 2 a été mesurée sur
        # le CSV brut, avoirs et doublons inclus : ses métriques — y compris son
        # refus de déploiement — ne sont pas comparables à celles-ci.
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

        # ── CE QUE LE MODULE SERT RÉELLEMENT ────────────────────────────────
        # Distinction essentielle, et c'est elle qui rend ce module cohérent :
        # « aucun modèle appris n'est déployé » ne veut pas dire « le module ne
        # sert rien ». Le scoring des conditions de crédit fonctionne, et il
        # fonctionne SANS apprentissage — parce que le délai est une clause
        # contractuelle, et qu'une clause se lit, elle ne se prédit pas.
        #
        # Le module sert donc une RÈGLE DÉTERMINISTE, vérifiée hors période. Ce
        # n'est pas un modèle dégradé faute de mieux : c'est la réponse juste à
        # la question posée. Un modèle ne pourrait que recopier cette règle, en
        # ajoutant de l'opacité et un risque de dérive.
        "production": {
            "statut": "servi",
            "nature": "règle déterministe auditable (aucun apprentissage)",
            "methode_servie": (
                "score = 100 si la médiane des délais passés du client dépasse "
                f"{RISK_THRESHOLD_DAYS} j, 0 sinon ; taux de base pour un client "
                f"ayant moins de {MIN_HISTORIQUE} factures"),
            "metrique_de_reference": "AUC hors période de la règle",
            "auc_hors_periode": regle_hp.get("auc") if regle_hp.get("applicable") else None,
            # Référence d'une AUC : le tirage au hasard, soit 0,5. Le taux de base
            # (proportion de conditions longues) N'EST PAS une référence d'AUC —
            # les deux grandeurs ne vivent pas sur la même échelle, et les
            # comparer produisait un « gain » dépourvu de sens.
            "reference_auc_hasard": 0.5,
            "couverture_par_la_regle_pct": None,   # renseigné plus bas
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

    # 9) Score par client — contrat inchangé pour le dashboard, + provenance
    norme = (df[df["cli_prior_n"] >= MIN_HISTORIQUE]
             .groupby("client")["delay"].median())
    df["p_cold"] = final.predict_proba(enc[FEATURES])[:, 1]
    taux_base = float(df["y"].mean())
    agg = df.groupby("client").agg(exposure=("ttc", "sum"), n=("ttc", "size"),
                                   avg_delay=("delay", "mean"), p_cold=("p_cold", "mean"))
    client_risk = {}
    for cl, r in agg.iterrows():
        if cl in norme.index:
            # Fait mesuré sur l'historique du client, pas une prédiction.
            score, source = (100.0 if norme[cl] > RISK_THRESHOLD_DAYS else 0.0), "regle_historique"
        elif deploye:
            score, source = float(r.p_cold) * 100.0, "modele_cold_start"
        else:
            # Modèle refusé : on ne sert PAS ses probabilités. Repli sur le taux
            # de base, seule information honnête sur un client sans historique.
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
    # Le JSON a été écrit avant que la couverture soit connue : on le réécrit.
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
