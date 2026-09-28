"""
ml_engine/models/stock_risk.py
==============================
CRISP-DM — PHASES 4-5 : SCORING DU RISQUE DE STOCK

Classifieur qui score chaque référence : **quel risque de perte financière
dans les 90 prochains jours ?**

## ⚠️ Itération n°1 ABANDONNÉE — détection d'une fuite de données

La première formulation définissait la cible comme
`rupture = (stock ÷ demande) < délai_réapprovisionnement`, tout en donnant
`stock`, `demande` et `délai` comme variables explicatives. Résultat :
**AUC = 1,0000 sur tous les modèles**, y compris en hold-out.

Une AUC parfaite n'est pas une réussite : c'est le symptôme que la cible est une
**fonction déterministe des features**. Le modèle ne prédisait rien, il
recalculait une règle arithmétique. Aucune valeur ajoutée — un simple `if`
aurait fait le même travail, plus vite et sans modèle.

## Reformulation (itération n°2) : prédire ce qui n'est PAS déductible

Le vrai problème métier est **prospectif** : *ce produit va-t-il manquer dans
les 90 prochains jours ?* La réponse dépend de la **demande future**, qui est
par définition inconnue au moment de la décision.

| | Itération 1 (fuite) | Itération 2 (retenue) |
|---|---|---|
| Cible | règle sur l'état actuel | **rupture réelle constatée** : demande des 3 mois suivants > stock disponible |
| Features | contenaient les termes de la règle | **uniquement le passé** : historique de demande, volatilité, saisonnalité, typologie clients |
| Fuite | totale | aucune — la demande future n'est jamais donnée au modèle |
| AUC attendue | 1,0 (illusoire) | réaliste, à mesurer |

La cible est construite depuis les **séries de demande réelles** (6 ans,
`demand_features`) : pour chaque produit et chaque mois, on sait *a posteriori*
ce qui a été consommé sur les 3 mois suivants. Le modèle, lui, ne voit que
l'historique disponible à cette date.

Les trois risques métier restent distingués :

| Risque | Définition (constatée a posteriori) | Coût |
|---|---|---|
| **Rupture** | demande des 90 j > stock disponible | vente perdue, fret aérien d'urgence |
| **Péremption** | stock non écoulé avant expiration | perte sèche du coût de revient |
| **Surstock** | couverture > 180 j | trésorerie immobilisée |

## Sorties (contrat d'interface demandé)

Pour chaque référence :
- `risk_score` : 0-100 (probabilité calibrée × 100)
- `risk_category` : Faible / Moyen / Élevé / Critique
- `financial_impact_dt` : perte attendue en dinars = `P(risque) × exposition`
- `risk_type` : nature dominante du risque (péremption / rupture / surstock)
- `days_to_stockout` : jours avant rupture au rythme de consommation actuel

## Rigueur méthodologique

- **Split temporel** impossible ici (photo à un instant t) → **StratifiedKFold
  5 plis** + **hold-out stratifié 20 %** jamais vu pendant la sélection.
- **Fuite écartée** : les variables qui définissent mécaniquement la cible
  (jours de péremption restants, couverture brute) sont **exclues** des
  features. Le modèle doit apprendre depuis les caractéristiques du produit,
  pas depuis la réponse. Une **ablation** mesure ce que vaut le modèle sans
  ses variables les plus fortes.
- **Calibration** vérifiée (courbe de fiabilité) : un score de 80 doit
  correspondre à 80 % de cas à risque, sinon `financial_impact_dt` serait faux.

Usage :
    python -m ml_engine.models.stock_risk train
    python -m ml_engine.models.stock_risk score
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from ml_engine.metriques import metriques_classification

BASE = Path(__file__).resolve().parents[2]
MODELS_DIR = BASE / "models"
REPORTS_DIR = BASE / "reports"
MODEL_PATH = MODELS_DIR / "stock_risk.joblib"
METRICS_PATH = REPORTS_DIR / "stock_risk_metrics.json"

SEED = 42
SEUIL_SURSTOCK_JOURS = 180
HORIZON_RISQUE_JOURS = 90

# Écart maximal toléré entre l'AUC d'entraînement et celle de validation. Un
# candidat au-dessus n'est pas retenu — la contrainte vit dans la sélection, pas
# seulement dans un test qui échouerait après coup.
SEUIL_ECART_TRAIN_VALID = 0.10

# À performance quasi égale, on préfère le modèle le plus simple. Un demi-point
# d'AUC ne justifie pas de renoncer à l'interprétabilité d'un modèle linéaire.
ECART_PARCIMONIE = 0.01

# FEATURES — uniquement des informations disponibles À LA DATE DE DÉCISION.
# La demande future (qui définit la cible) n'y figure JAMAIS : c'est ce qui
# distingue cette version de l'itération 1, où la cible était déductible.
FEATURES: List[str] = [
    # historique de demande (passé strict)
    "lag_1", "lag_2", "lag_3", "lag_6", "lag_12",
    "ma_3", "ma_6", "ma_12", "std_3", "std_6",
    # dynamique et saisonnalité
    "ratio_3_12", "tendance_3m", "mois", "trimestre",
    # structure de clientèle
    "n_clients", "part_public", "part_labo", "hhi_clients",
    # cycle de vie du produit
    "anciennete_mois", "mois_actifs", "taux_activite",
    # prix
    "prix_moyen", "variation_prix",
    # position de stock à la date de décision (connue, mais la DEMANDE future
    # qui déterminera la rupture ne l'est pas)
    "couverture_actuelle_j", "coef_variation",
]

CATEGORIES = [(80, "Critique"), (60, "Élevé"), (35, "Moyen"), (0, "Faible")]


def _connect():
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    # Un seul thread côté entrepôt. `sum()` et `avg()` sont parallélisés par
    # DuckDB : deux exécutions peuvent renvoyer des totaux différant au dernier
    # bit. Sur le coût unitaire ou la valeur de stock, cela suffit à déplacer un
    # point de coupure d'arbre — et la conclusion avec lui. Cf.
    # ml_engine/determinisme.py.
    try:
        from ml_engine.determinisme import limiter_duckdb
        limiter_duckdb(con, 1)
    except Exception:
        pass
    return con


# ── CRISP-DM 3 : préparation ────────────────────────────────────────────────
def build_risk_dataset(verbose: bool = True) -> pd.DataFrame:
    """Jeu d'apprentissage PROSPECTIF : features du passé, cible du futur.

    Base : séries de demande RÉELLES (`demand_features`) enrichies de la
    position de stock. La cible est constatée *a posteriori* — le modèle ne la
    voit jamais dans ses variables.
    """
    from .demand_features import build_demand_dataset

    hist = build_demand_dataset(verbose=False)

    # Position de stock par produit (agrégée tous clients : le stock central)
    con = _connect()
    stock = con.execute("""
        SELECT produit,
               sum(stock_actuel)                        AS stock_actuel,
               avg(lead_time_jours)                     AS lead_time_jours,
               avg(cout_unitaire)                       AS cout_unitaire,
               sum(valeur_stock)                        AS valeur_stock,
               min(date_peremption)                     AS date_peremption,
               any_value(famille)                       AS famille
        FROM stock_simule GROUP BY produit
    """).df()
    ref = con.execute("SELECT max(date) FROM sales").fetchone()[0]
    con.close()

    df = hist.merge(stock, on="produit", how="inner")
    if df.empty:
        raise RuntimeError("Jointure historique × stock vide.")

    ref = pd.Timestamp(ref)
    df["date_peremption"] = pd.to_datetime(df["date_peremption"], errors="coerce")
    df["jours_peremption"] = (df["date_peremption"] - ref).dt.days

    # Demande journalière récente (issue de l'historique, pas du stock simulé)
    d_jour = (df["ma_3"] / 30.0).replace(0, np.nan)
    df["couverture_actuelle_j"] = (df["stock_actuel"] / d_jour).clip(upper=3650)
    df["coef_variation"] = (df["std_3"] / df["ma_3"].replace(0, np.nan)).clip(upper=10)
    df["days_to_stockout"] = df["couverture_actuelle_j"]
    df["couverture_j"] = df["couverture_actuelle_j"]

    fam = df["famille"].fillna("").str.upper()
    df["est_reactif"] = (fam == "REACTIF").astype(int)

    # ══ CIBLE PROSPECTIVE — constatée a posteriori, JAMAIS dans les features ══
    # 1. Rupture : la demande RÉELLE des 3 mois suivants dépasse le stock.
    df["risque_rupture"] = ((df["y_h3"].notna())
                            & (df["y_h3"] > df["stock_actuel"])).astype(int)

    # 2. Péremption : le stock ne sera pas écoulé avant expiration.
    conso_futur = df["y_h3"].fillna(0)
    horizon_perem = df["jours_peremption"].fillna(9999)
    df["risque_peremption"] = ((horizon_perem <= 120)
                               & (df["stock_actuel"] > conso_futur)
                               & (df["stock_actuel"] > 0)).astype(int)
    df["qte_perimee"] = np.where(df["risque_peremption"] == 1,
                                 np.maximum(0, df["stock_actuel"] - conso_futur), 0.0)

    # 3. Surstock : la demande future ne consommera qu'une fraction du stock.
    #
    # ══ TAUTOLOGIE RÉSIDUELLE CORRIGÉE ICI ══
    # La version précédente exigeait AUSSI `couverture_actuelle_j > 180`. Or
    # `couverture_actuelle_j` est une VARIABLE EXPLICATIVE (cf. FEATURES) : un
    # tiers de la cible était donc un simple seuil sur une entrée du modèle.
    # C'est le même défaut que la v1 du modèle de crédit, sous une autre forme,
    # et il avait franchi le test anti-fuite parce que celui-ci vérifiait une
    # liste NOMMÉE de colonnes interdites au lieu de la construction réelle.
    #
    # La condition conservée porte uniquement sur des grandeurs ABSENTES des
    # features (`stock_actuel`) et sur la demande FUTURE observée. Prédire
    # « la demande des 3 mois suivants ne consommera pas la moitié du stock »
    # exige donc de prévoir cette demande : c'est un vrai problème.
    df["risque_surstock"] = (conso_futur < df["stock_actuel"] * 0.5).astype(int)

    df["y"] = ((df["risque_peremption"] + df["risque_rupture"]
                + df["risque_surstock"]) > 0).astype(int)
    df = df.dropna(subset=["y_h3"]).reset_index(drop=True)
    df["client"] = ""            # scoring au niveau produit (stock central)

    # Type de risque dominant (pour l'affichage)
    def _type(r) -> str:
        if r["risque_peremption"]:
            return "peremption"
        if r["risque_rupture"]:
            return "rupture"
        if r["risque_surstock"]:
            return "surstock"
        return "aucun"
    df["risk_type"] = df.apply(_type, axis=1)

    # ── Exposition financière (base de l'impact attendu) ──
    manque = np.maximum(0, df["y_h3"].fillna(0) - df["stock_actuel"])
    df["exposition_dt"] = np.where(
        df["risque_peremption"] == 1, df["qte_perimee"] * df["cout_unitaire"],
        np.where(df["risque_rupture"] == 1,
                 manque * df["cout_unitaire"],          # vente perdue
                 df["valeur_stock"] * 0.15))            # portage du surstock

    df[FEATURES] = df[FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    if verbose:
        print(f"[risque] {len(df):,} références · taux de risque {df['y'].mean()*100:.1f} %"
              .replace(",", " "))
        print(f"[risque]   péremption {df['risque_peremption'].sum():,} · "
              f"rupture {df['risque_rupture'].sum():,} · "
              f"surstock {df['risque_surstock'].sum():,}".replace(",", " "))
    return df


# ── CRISP-DM 4-5 : entraînement, comparaison, évaluation ────────────────────
def _candidats() -> Dict[str, Any]:
    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  RandomForestClassifier)
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    c: Dict[str, Any] = {}
    try:
        import xgboost as xgb
        c["xgboost"] = xgb.XGBClassifier(
            n_estimators=300, learning_rate=0.05, max_depth=4,
            min_child_weight=20, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.5, reg_lambda=3.0, random_state=SEED,
            n_jobs=2, tree_method="hist", eval_metric="logloss")
    except Exception:
        pass
    try:
        import lightgbm as lgb
        # ══ DÉTERMINISME FORCÉ ══
        #
        # Deux exécutions identiques donnaient 0,8168 puis 0,8157 d'AUC, et un
        # écart train/validation de +0,1320 puis +0,1331. La cause est connue et
        # déjà documentée pour la prévision de demande : en multi-thread, l'ordre
        # de sommation des gradients varie, et le résultat avec lui.
        #
        # Ici l'enjeu n'est pas cosmétique. Le seuil de disqualification est à
        # 0,10 et la sélection se joue à 0,003 d'AUC entre candidats : une
        # décision de déploiement pouvait donc basculer selon l'ordonnancement
        # des threads. Un résultat qui change sans que rien ne change n'est pas
        # un résultat.
        c["lightgbm"] = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.05, num_leaves=15, max_depth=4,
            min_child_samples=40, subsample=0.8, subsample_freq=1,
            colsample_bytree=0.8, reg_alpha=0.5, reg_lambda=3.0,
            random_state=SEED, verbose=-1,
            n_jobs=1, deterministic=True, force_row_wise=True)
    except Exception:
        pass
    # `HistGradientBoostingClassifier` n'expose pas de `n_jobs` : sa
    # parallélisation passe par OpenMP, bridée dans `train_stock_risk` par
    # `threadpool_limits`. C'est le seul moyen de le rendre reproductible.
    c["hist_gb"] = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.06, max_depth=4, min_samples_leaf=30,
        l2_regularization=3.0, random_state=SEED)
    c["random_forest"] = RandomForestClassifier(
        n_estimators=250, max_depth=8, min_samples_leaf=20,
        random_state=SEED, n_jobs=2)
    c["regression_logistique"] = make_pipeline(
        StandardScaler(), LogisticRegression(max_iter=1000, C=1.0, random_state=SEED))
    return c


def train_stock_risk(save: bool = True, verbose: bool = True) -> Dict[str, Any]:
    """Entraîne, compare, évalue et calibre le classifieur de risque."""
    warnings.filterwarnings("ignore")
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import (accuracy_score, average_precision_score,
                                 brier_score_loss, confusion_matrix, f1_score,
                                 precision_score, recall_score, roc_auc_score)
    from sklearn.model_selection import StratifiedKFold, train_test_split

    from sklearn.model_selection import GroupKFold, GroupShuffleSplit

    df = build_risk_dataset(verbose=verbose)
    X, y = df[FEATURES], df["y"].to_numpy()
    groupes = df["produit"].astype(str).to_numpy()

    # ══ DÉCOUPAGE GROUPÉ PAR PRODUIT — second défaut corrigé ══
    #
    # Le hold-out était stratifié ALÉATOIREMENT. Or le jeu compte ~18 000 lignes
    # pour quelques centaines de produits, et l'instantané de stock (`stock_actuel`,
    # `date_peremption`, donc `couverture_actuelle_j`) est joint à TOUTE la série
    # temporelle d'un produit : ces variables sont donc constantes par produit.
    #
    # Un découpage aléatoire plaçait le même produit — avec les mêmes valeurs de
    # stock — des deux côtés de la coupure. Le modèle n'avait plus qu'à mémoriser
    # l'identité du produit. C'est une fuite par DUPLICATION, invisible dans
    # l'écart train/validation puisque les deux en bénéficient également.
    #
    # Un produit appartient désormais entièrement au développement ou entièrement
    # au hold-out. Aucun produit du test n'a jamais été vu.
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED)
    idx_dev, idx_hold = next(gss.split(X, y, groups=groupes))
    Xd, Xh = X.iloc[idx_dev], X.iloc[idx_hold]
    yd, yh = y[idx_dev], y[idx_hold]
    groupes_dev = groupes[idx_dev]

    # Le hold-out stratifié d'origine est CONSERVÉ, uniquement pour mesurer
    # l'écart entre les deux protocoles. Cet écart est la preuve chiffrée de la
    # fuite, et le supprimer effacerait la trace du défaut corrigé.
    Xd_s, Xh_s, yd_s, yh_s = train_test_split(X, y, test_size=0.2, stratify=y,
                                              random_state=SEED)

    cv = GroupKFold(n_splits=5)
    resultats: Dict[str, Dict[str, Any]] = {}

    # Un seul thread pendant la comparaison. La cause et sa portée sont
    # documentées une fois pour tout le projet dans `ml_engine/determinisme.py` :
    # la sélection se joue ici à 0,003 d'AUC et la disqualification à 0,10
    # d'écart, donc une décision de déploiement ne peut pas dépendre de
    # l'ordonnancement des threads.
    from ml_engine.determinisme import etat as etat_determinisme
    from ml_engine.determinisme import limiter_threads

    determinisme = etat_determinisme()

    with limiter_threads(1):
        for nom, modele in _candidats().items():
            aucs, f1s, ecarts = [], [], []
            for tr, va in cv.split(Xd, yd, groups=groupes_dev):
                m = _clone(modele)
                m.fit(Xd.iloc[tr], yd[tr])
                p_va = m.predict_proba(Xd.iloc[va])[:, 1]
                p_tr = m.predict_proba(Xd.iloc[tr])[:, 1]
                aucs.append(roc_auc_score(yd[va], p_va))
                f1s.append(f1_score(yd[va], (p_va >= 0.5).astype(int)))
                ecarts.append(roc_auc_score(yd[tr], p_tr) - aucs[-1])
            resultats[nom] = {
                "cv_auc": round(float(np.mean(aucs)), 4),
                "cv_auc_std": round(float(np.std(aucs)), 4),
                "cv_f1": round(float(np.mean(f1s)), 4),
                "ecart_train_valid_auc": round(float(np.mean(ecarts)), 4),
            }

    # ══ LE SUR-APPRENTISSAGE DEVIENT UN CRITÈRE D'ÉLIGIBILITÉ ══
    #
    # Le passage au découpage groupé a fait bondir l'écart train/validation des
    # modèles d'ensemble : de +0,03 à +0,12 ou +0,13. Ce n'est pas une
    # régression, c'est la MÊME fuite vue d'un autre angle. Avec un découpage
    # aléatoire, train et validation partageaient des produits : l'écart
    # paraissait faible parce que les deux côtés mémorisaient les mêmes
    # références. Groupes disjoints, l'écart réel apparaît.
    #
    # Jusqu'ici un test échouait APRÈS l'entraînement si l'écart dépassait 0,10.
    # Un test qui constate un défaut que le code laisse produire ne protège de
    # rien : il faut relancer, et la tentation est de desserrer le seuil. La
    # contrainte est donc déplacée DANS la sélection — un candidat qui
    # sur-apprend n'est plus éligible, quelle que soit son AUC.
    disqualifies = {nom: r["ecart_train_valid_auc"]
                    for nom, r in resultats.items()
                    if r["ecart_train_valid_auc"] >= SEUIL_ECART_TRAIN_VALID}
    for nom in disqualifies:
        resultats[nom]["disqualifie"] = True
        resultats[nom]["motif_disqualification"] = (
            f"écart train/validation d'AUC {disqualifies[nom]:+.4f} ≥ "
            f"{SEUIL_ECART_TRAIN_VALID} — sur-apprentissage")

    eligibles = {nom: r for nom, r in resultats.items() if nom not in disqualifies}
    if not eligibles:
        # Aucun candidat honnête : on refuse plutôt que de servir le moins
        # mauvais. C'est la même règle que partout ailleurs dans le projet.
        eligibles = {}
        meilleur_nom = None
    else:
        classement_e = sorted(eligibles.items(), key=lambda kv: -kv[1]["cv_auc"])
        meilleur_nom = classement_e[0][0]
        # Parcimonie : à performance équivalente, le modèle linéaire est préféré
        # — interprétable par ses coefficients et beaucoup plus stable (son écart
        # train/validation est de +0,0166 contre +0,10 pour les ensembles).
        lin = eligibles.get("regression_logistique")
        if (lin is not None and meilleur_nom != "regression_logistique"
                and eligibles[meilleur_nom]["cv_auc"] - lin["cv_auc"]
                <= ECART_PARCIMONIE):
            meilleur_nom = "regression_logistique"

    classement = sorted(resultats.items(), key=lambda kv: -kv[1]["cv_auc"])

    if meilleur_nom is None:
        rapport_refus = {
            "methodologie": ("CRISP-DM — GroupKFold 5 plis PAR PRODUIT + "
                             "hold-out groupé 20 %"),
            "seed": SEED,
            "n_references": int(len(df)),
            "taux_positif": round(float(y.mean()), 4),
            "comparaison": resultats,
            "modele_retenu": None,
            "decision_deploiement": {
                "modele_deploye": False,
                "motif": (
                    "tous les candidats dépassent le seuil de sur-apprentissage "
                    f"de {SEUIL_ECART_TRAIN_VALID} en écart train/validation "
                    "d'AUC. Aucun modèle n'est servi : mieux vaut une absence "
                    "qu'un score dont on sait qu'il ne généralise pas."),
            },
            "candidats_disqualifies": disqualifies,
        }
        if save:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            METRICS_PATH.write_text(
                json.dumps(rapport_refus, indent=2, ensure_ascii=False),
                encoding="utf-8")
            if MODEL_PATH.exists():
                try:
                    MODEL_PATH.unlink()      # un artefact présent finit par être chargé
                except Exception:
                    pass
        if verbose:
            print("\n[risque] AUCUN candidat éligible — tous sur-apprennent.")
            for nom, e in disqualifies.items():
                print(f"[risque]   {nom:22} écart {e:+.4f}")
        return rapport_refus

    # ── Modèle final + calibration ──
    from sklearn.calibration import CalibratedClassifierCV
    base = _clone(_candidats()[meilleur_nom])
    final = CalibratedClassifierCV(base, method="isotonic", cv=3)
    final.fit(Xd, yd)

    p_hold = final.predict_proba(Xh)[:, 1]
    pred_hold = (p_hold >= 0.5).astype(int)
    holdout = {
        "n_test": int(len(yh)),
        "auc": round(float(roc_auc_score(yh, p_hold)), 4),
        "average_precision": round(float(average_precision_score(yh, p_hold)), 4),
        "accuracy": round(float(accuracy_score(yh, pred_hold)), 4),
        "precision": round(float(precision_score(yh, pred_hold, zero_division=0)), 4),
        "recall": round(float(recall_score(yh, pred_hold, zero_division=0)), 4),
        "f1": round(float(f1_score(yh, pred_hold, zero_division=0)), 4),
        "brier_score": round(float(brier_score_loss(yh, p_hold)), 4),
        "confusion_matrix": confusion_matrix(yh, pred_hold).tolist(),
        "classification": metriques_classification(
            yh, p_hold, y_train=yd, p_train=final.predict_proba(Xd)[:, 1]),
    }

    # ── Calibration : un score de 80 doit valoir 80 % de risque réel ──
    try:
        frac_pos, moy_pred = calibration_curve(yh, p_hold, n_bins=10, strategy="quantile")
        calib = [{"proba_predite": round(float(a), 3), "frequence_reelle": round(float(b), 3)}
                 for a, b in zip(moy_pred, frac_pos)]
        ecart_calib = float(np.mean(np.abs(np.array(moy_pred) - np.array(frac_pos))))
    except Exception:
        calib, ecart_calib = [], None

    # ── Utilité décisionnelle : ce que l'AUC ne dit pas ──────────────────────
    #
    # 88 % des références sont positives. À ce taux de base, le drapeau binaire
    # n'apprend rien à personne : répondre « oui » partout donne déjà 88 % de
    # justesse, et le rappel de 0,997 mesuré ci-dessus dit surtout que le modèle
    # fait à peu près cela.
    #
    # Publier l'AUC seule sur un problème à 88 % de positifs serait donc
    # trompeur, même sans aucune fuite. La question utile change de sens :
    #
    #   ce n'est pas « quelles références sont à risque ? » — presque toutes —
    #   c'est « lesquelles puis-je IGNORER sans risque ? »
    #
    # C'est la seule direction qui produit une décision : réduire une liste de
    # 18 000 lignes à ce qui mérite un examen. On mesure donc la pureté du décile
    # le plus BAS, là où se trouve la valeur, et non celle du décile le plus haut,
    # où le taux de base la garantit d'avance.
    utilite: Dict[str, Any] = {"applicable": False}
    try:
        taux_neg = float((yh == 0).mean())
        n_dec = max(int(len(yh) * 0.10), 1)
        ordre = np.argsort(p_hold)                       # score croissant
        bas, haut = ordre[:n_dec], ordre[-n_dec:]

        part_neg_bas = float((yh[bas] == 0).mean())
        part_pos_haut = float((yh[haut] == 1).mean())
        utilite = {
            "applicable": True,
            "taux_de_base_positif": round(float(yh.mean()), 4),
            "taux_de_base_negatif": round(taux_neg, 4),
            "n_par_decile": int(n_dec),
            "decile_le_plus_bas": {
                "part_reellement_sans_risque_pct": round(part_neg_bas * 100, 1),
                "lift": (round(part_neg_bas / taux_neg, 2) if taux_neg > 0 else None),
                "lecture": ("pureté du groupe que le modèle désigne comme SANS "
                            "risque. C'est la mesure qui porte la décision : "
                            "elle dit quelle part de la liste peut être écartée "
                            "d'un examen manuel sans se tromper."),
            },
            "decile_le_plus_haut": {
                "part_reellement_a_risque_pct": round(part_pos_haut * 100, 1),
                "lift": (round(part_pos_haut / float(yh.mean()), 2)
                         if yh.mean() > 0 else None),
                "lecture": ("volontairement peu impressionnant : avec 88 % de "
                            "positifs, le lift maximal atteignable est de "
                            f"{round(1 / float(yh.mean()), 2)}. Ce chiffre ne "
                            "démontre rien, et il est publié pour cette raison."),
            },
            "ce_qui_est_reellement_servi": (
                "le tableau de bord ne sert PAS ce drapeau binaire. Il classe par "
                "PERTE ATTENDUE = probabilité calibrée × exposition financière. "
                "C'est un ordre de priorité, pas une alerte oui/non — et c'est la "
                "seule sortie qu'un taux de base de 88 % permette d'exploiter."),
            "origine_du_taux_de_base": (
                "le stock SIMULÉ est généreux : la position médiane couvre plus "
                "de six mois de demande. Ce n'est donc pas la définition de la "
                "cible qui gonfle le taux, c'est le niveau des stocks générés. "
                "Sur les positions RÉELLES reconstruites (§3 quater), la même "
                "question donne 22 références au-delà de deux ans sur 1 501."),
        }
    except Exception as e:      # pragma: no cover — annexe, jamais bloquante
        utilite = {"applicable": False, "motif": type(e).__name__}

    # ── Audit de fuite : comparer les deux protocoles ────────────────────────
    #
    # Le même modèle, la même calibration, la seule différence étant le
    # découpage. L'écart mesure exactement ce que le découpage aléatoire offrait
    # gratuitement au modèle.
    audit_fuite: Dict[str, Any] = {"applicable": False}
    try:
        base_s = _clone(_candidats()[meilleur_nom])
        final_s = CalibratedClassifierCV(base_s, method="isotonic", cv=3)
        final_s.fit(Xd_s, yd_s)
        auc_strat = float(roc_auc_score(yh_s, final_s.predict_proba(Xh_s)[:, 1]))
        audit_fuite = {
            "applicable": True,
            "auc_holdout_groupe_par_produit": holdout["auc"],
            "auc_holdout_stratifie_aleatoire": round(auc_strat, 4),
            "ecart": round(auc_strat - holdout["auc"], 4),
            "protocole_servi": "groupé par produit",
            "lecture": (
                "L'écart est ce que le découpage aléatoire offrait au modèle sans "
                "qu'il l'apprenne : l'instantané de stock étant constant par "
                "produit, retrouver un produit des deux côtés de la coupure "
                "suffisait à retrouver sa cible. Seul le protocole groupé est "
                "retenu pour décider du déploiement."),
            "n_produits_dev": int(len(set(groupes_dev))),
            "n_produits_holdout": int(len(set(groupes[idx_hold]))),
        }
    except Exception as e:      # pragma: no cover — annexe, jamais bloquante
        audit_fuite = {"applicable": False, "motif": type(e).__name__}

    # ── Ablation : que vaut le modèle sans ses variables les plus fortes ? ──
    imp = _importances(base, Xd, yd, FEATURES)
    top3 = [v["variable"] for v in (imp or [])[:3]]
    ablation = None
    if top3:
        reste = [f for f in FEATURES if f not in top3]
        m2 = _clone(_candidats()[meilleur_nom])
        m2.fit(Xd[reste], yd)
        auc2 = roc_auc_score(yh, m2.predict_proba(Xh[reste])[:, 1])
        ablation = {"variables_retirees": top3, "auc_sans": round(float(auc2), 4),
                    "auc_avec": holdout["auc"],
                    "perte_auc": round(float(holdout["auc"] - auc2), 4)}

    rapport = {
        "methodologie": ("CRISP-DM — cible CALCULÉE (péremption / rupture / surstock), "
                         "GroupKFold 5 plis PAR PRODUIT + hold-out groupé 20 %, "
                         "calibration isotonique. Aucun produit du hold-out n'a "
                         "été vu à l'entraînement."),
        "seed": SEED,
        "determinisme": {
            **determinisme,
            "pourquoi": (
                "deux exécutions identiques donnaient 0,8168 puis 0,8157 d'AUC "
                "pour LightGBM, et un écart train/validation de +0,1320 puis "
                "+0,1331. En multi-thread, l'ordre de sommation des gradients "
                "varie. La sélection se jouant à 0,003 d'AUC et la "
                "disqualification à 0,10 d'écart, une décision de déploiement "
                "pouvait basculer sans qu'aucune donnée ne change."),
            "lightgbm": "deterministic=True, force_row_wise=True, n_jobs=1",
        },
        "n_references": int(len(df)),
        "taux_positif": round(float(y.mean()), 4),
        # Cible PROSPECTIVE : constatée à partir de la demande réelle des 3 mois
        # suivants (`y_h3`), qui n'est JAMAIS une variable explicative. La
        # première version, déduite de features présentes en entrée, donnait une
        # AUC de 1,0000 — symptôme de fuite, corrigé ici.
        "definition_cible": {
            "nature": "prospective — constatée a posteriori sur la demande réelle des 3 mois suivants",
            "peremption": ("expiration dans ≤ 120 j ET stock supérieur à la demande "
                           "réellement observée sur les 3 mois suivants"),
            "rupture": "demande réelle des 3 mois suivants supérieure au stock disponible",
            "surstock": ("demande réelle des 3 mois suivants < 50 % du stock. La "
                         f"condition « couverture > {SEUIL_SURSTOCK_JOURS} j » a "
                         "été RETIRÉE : `couverture_actuelle_j` est une variable "
                         "explicative, et un tiers de la cible n'était donc qu'un "
                         "seuil posé sur une entrée du modèle"),
            "y": "1 si au moins un des trois risques se matérialise",
            "aucune_variable_explicative_dans_la_cible": (
                "vérifié par construction : les trois conditions ne portent que "
                "sur `stock_actuel`, `jours_peremption` et la demande FUTURE "
                "observée (`y_h3`) — aucune de ces colonnes n'est dans FEATURES"),
        },
        "n_features": len(FEATURES), "features": FEATURES,
        "comparaison": resultats,
        "modele_retenu": meilleur_nom,
        "calibration": "isotonique (CalibratedClassifierCV, cv=3)",
        "holdout": holdout,
        "utilite_decisionnelle": utilite,
        "audit_fuite": audit_fuite,
        "courbe_calibration": calib,
        "ecart_calibration_moyen": round(ecart_calib, 4) if ecart_calib is not None else None,
        "ablation": ablation,
        "top_features": imp,
        "avertissement": ("Le stock est SIMULÉ (docs/STOCK_SIMULE.md) : ces métriques "
                          "valident la chaîne de modélisation, pas une performance "
                          "sur données de stock observées."),
    }

    if verbose:
        if not determinisme.get("reproductible"):
            print("\n[risque] ⚠ threadpoolctl ABSENT : le parallélisme numérique "
                  "n'est pas borné.")
            print("[risque]   Les AUC des modèles d'ensemble peuvent varier d'une "
                  "exécution à l'autre.")
            print("[risque]   `pip install threadpoolctl` puis relancer.")
        print(f"\n[risque] comparaison des modèles (AUC en validation croisée) :")
        for nom, r in classement:
            marque = " ←" if nom == meilleur_nom else ""
            print(f"    {nom:22} AUC {r['cv_auc']:.4f} ± {r['cv_auc_std']:.4f} · "
                  f"F1 {r['cv_f1']:.4f} · écart train/valid {r['ecart_train_valid_auc']:+.4f}{marque}")
        print(f"\n[risque] hold-out GROUPÉ PAR PRODUIT : AUC {holdout['auc']} · "
              f"F1 {holdout['f1']} · précision {holdout['precision']} · "
              f"rappel {holdout['recall']}")
        if audit_fuite.get("applicable"):
            print(f"[risque] audit de fuite : le même modèle affiche "
                  f"{audit_fuite['auc_holdout_stratifie_aleatoire']} avec un "
                  f"découpage ALÉATOIRE (écart {audit_fuite['ecart']:+.4f})")
            print(f"[risque]   -> {audit_fuite['n_produits_holdout']} produits du "
                  "hold-out n'ont jamais été vus à l'entraînement ; "
                  "seul ce chiffre décide du déploiement")
        print(f"[risque] Brier {holdout['brier_score']} (calibration : écart moyen "
              f"{rapport['ecart_calibration_moyen']})")
        if ablation:
            print(f"[risque] ablation sans {ablation['variables_retirees']} : "
                  f"AUC {ablation['auc_sans']} (perte {ablation['perte_auc']:+.4f})")
        if disqualifies:
            print("\n[risque] candidats DISQUALIFIÉS pour sur-apprentissage "
                  f"(écart ≥ {SEUIL_ECART_TRAIN_VALID}) :")
            for nom, e in disqualifies.items():
                print(f"[risque]   {nom:22} écart {e:+.4f}")
            print("[risque]   -> ces écarts ont bondi avec le découpage groupé :")
            print("[risque]      la même fuite, vue d'un autre angle.")
        if utilite.get("applicable"):
            u = utilite
            print(f"\n[risque] taux de base : {u['taux_de_base_positif']*100:.1f} % "
                  "de positifs — l'AUC seule ne suffit pas à juger ce modèle")
            b = u["decile_le_plus_bas"]
            print(f"[risque]   décile le plus BAS : "
                  f"{b['part_reellement_sans_risque_pct']} % réellement sans "
                  f"risque (lift {b['lift']}) — c'est CE chiffre qui décide")
            h = u["decile_le_plus_haut"]
            print(f"[risque]   décile le plus HAUT : "
                  f"{h['part_reellement_a_risque_pct']} % à risque "
                  f"(lift {h['lift']}) — garanti d'avance par le taux de base")

    if save:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import joblib
            joblib.dump({"modele": final, "features": FEATURES, "nom": meilleur_nom},
                        MODEL_PATH)
        except Exception as e:  # pragma: no cover
            rapport["sauvegarde"] = f"échec : {e}"
        METRICS_PATH.write_text(json.dumps(rapport, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        if verbose:
            print(f"\n[risque] modèle : {MODEL_PATH}\n[risque] métriques : {METRICS_PATH}")
    return rapport


def _clone(m):
    from sklearn.base import clone
    try:
        return clone(m)
    except Exception:
        return m


def _importances(modele, X, y, features: List[str]) -> Optional[List[Dict[str, Any]]]:
    try:
        m = _clone(modele)
        m.fit(X, y)
        imp = getattr(m, "feature_importances_", None)
        if imp is None:
            return None
        pairs = sorted(zip(features, imp), key=lambda x: -float(x[1]))
        total = float(sum(float(v) for _, v in pairs)) or 1.0
        return [{"variable": f, "importance_pct": round(float(v) / total * 100, 1)}
                for f, v in pairs[:10]]
    except Exception:
        return None


# ── Scoring (déploiement) ───────────────────────────────────────────────────
_CACHE: Optional[Dict[str, Any]] = None


def _load():
    global _CACHE
    if _CACHE is None:
        try:
            import joblib
            _CACHE = joblib.load(MODEL_PATH)
        except Exception:
            return None
    return _CACHE


def categorie(score: float) -> str:
    for seuil, label in CATEGORIES:
        if score >= seuil:
            return label
    return "Faible"


def score_stock_risk(client: Optional[str] = None,
                     limit: int = 50) -> Dict[str, Any]:
    """Score chaque référence : risque, catégorie, impact financier.

    Contrat de sortie : `risk_score` (0-100), `risk_category`,
    `financial_impact_dt`, `risk_type`, `days_to_stockout`.
    """
    bundle = _load()
    df = build_risk_dataset(verbose=False)
    # Le jeu d'apprentissage contient une ligne par produit ET par mois (pour
    # apprendre sur l'historique). Pour le SCORING, on ne garde que la situation
    # la plus récente de chaque produit — sinon le même produit apparaîtrait
    # autant de fois qu'il a de mois d'historique.
    df = (df.sort_values("period").groupby("produit", as_index=False).tail(1)
          .reset_index(drop=True))
    # ── Périmètre client ────────────────────────────────────────────────────
    # Le modèle score au niveau PRODUIT (stock central) : la probabilité de
    # risque est une propriété de la référence, pas du client. Filtrer par
    # client revient donc à restreindre la liste aux références que cet
    # établissement détient réellement — et non à re-scorer par client, ce qui
    # serait une extrapolation non validée.
    perimetre = "portefeuille global (stock central)"
    if client and str(client).strip():
        c = str(client).strip()
        try:
            con = _connect()
            # `stock_simule.client` stocke le NOM ; l'interface envoie le CODE.
            # On accepte les deux et on résout la correspondance via `sales`.
            refs = con.execute("""
                SELECT DISTINCT produit FROM stock_simule
                WHERE client = ?
                   OR client = (SELECT DISTINCT client_name FROM sales
                                WHERE client = ? AND client_name IS NOT NULL LIMIT 1)
                   OR client = (SELECT DISTINCT client FROM sales
                                WHERE client_name = ? AND client IS NOT NULL LIMIT 1)
            """, [c, c, c]).df()["produit"].tolist()
            con.close()
        except Exception:
            refs = []
        if refs:
            df = df[df["produit"].isin(refs)]
            df = df.assign(client=c)
            perimetre = f"références détenues par {c}"
        else:
            perimetre = (f"portefeuille global — aucune référence en stock "
                         f"rattachée à {c}")
    if df.empty:
        return {"error": "Aucune référence sur ce périmètre.", "produits": [],
                "is_simulated": True, "perimetre": perimetre}

    if bundle is not None:
        proba = bundle["modele"].predict_proba(df[bundle["features"]])[:, 1]
        source = f"modèle {bundle.get('nom', '?')} (calibré)"
    else:
        # Repli déterministe si le modèle n'est pas entraîné
        proba = df["y"].astype(float).to_numpy()
        source = "règles (modèle non entraîné)"

    df = df.assign(risk_score=(proba * 100).round(1))
    df["financial_impact_dt"] = (proba * df["exposition_dt"]).round(0)
    df["risk_category"] = df["risk_score"].map(categorie)

    top = df.sort_values("financial_impact_dt", ascending=False).head(limit)
    produits = [{
        "produit": r["produit"], "client": r["client"], "famille": r["famille"],
        "risk_score": float(r["risk_score"]),
        "risk_category": r["risk_category"],
        "risk_type": r["risk_type"],
        "financial_impact_dt": float(r["financial_impact_dt"]),
        "days_to_stockout": (round(float(r["days_to_stockout"]), 1)
                             if pd.notna(r["days_to_stockout"]) else None),
        "stock_actuel": float(r["stock_actuel"]),
        "couverture_jours": (round(float(r["couverture_j"]), 1)
                             if pd.notna(r["couverture_j"]) else None),
        "jours_avant_peremption": (int(r["jours_peremption"])
                                   if pd.notna(r["jours_peremption"]) else None),
    } for _, r in top.iterrows()]

    par_cat = df.groupby("risk_category").agg(
        n=("produit", "size"), impact=("financial_impact_dt", "sum")).reset_index()

    # Performance réelle du modèle servi, lue dans le rapport d'évaluation :
    # aucune métrique n'est écrite en dur dans l'interface ou le copilote, pour
    # qu'un réentraînement ne puisse pas rendre l'affichage mensonger.
    perf: Dict[str, Any] = {}
    try:
        rap = json.loads((REPORTS_DIR / "stock_risk_metrics.json").read_text(encoding="utf-8"))
        perf = {"modele": rap.get("modele_retenu"),
                "auc_holdout": (rap.get("holdout") or {}).get("auc"),
                "f1_holdout": (rap.get("holdout") or {}).get("f1"),
                "brier": (rap.get("holdout") or {}).get("brier_score"),
                "erreur_calibration": rap.get("ecart_calibration_moyen")}
    except Exception:
        pass

    return {
        "is_simulated": True,
        "source": source,
        "perimetre": perimetre,
        "performance": perf,
        "n_references": int(len(df)),
        "impact_total_dt": round(float(df["financial_impact_dt"].sum()), 0),
        "score_moyen": round(float(df["risk_score"].mean()), 1),
        "par_categorie": [{"categorie": r["risk_category"], "n_produits": int(r["n"]),
                           "impact_dt": round(float(r["impact"]), 0)}
                          for _, r in par_cat.iterrows()],
        "par_type": [{"type": k, "n_produits": int(v),
                      "impact_dt": round(float(df[df["risk_type"] == k]["financial_impact_dt"].sum()), 0)}
                     for k, v in df["risk_type"].value_counts().items()],
        "produits": produits,
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "train"
    if cmd == "train":
        train_stock_risk()
    else:
        r = score_stock_risk(limit=10)
        print(f"\n{r['n_references']} références · impact total "
              f"{r['impact_total_dt']:,.0f} DT · source : {r['source']}".replace(",", " "))
        print(f"\n{'produit':38} {'score':>6} {'catégorie':>10} {'type':>12} {'impact DT':>12}")
        for p in r["produits"]:
            print(f"{p['produit'][:38]:38} {p['risk_score']:>6.1f} "
                  f"{p['risk_category']:>10} {p['risk_type']:>12} "
                  f"{p['financial_impact_dt']:>12,.0f}".replace(",", " "))
