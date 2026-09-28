"""
ml_engine/stock/reappro_model.py
=================================
Besoin de réapprovisionnement à 3 mois — un modèle appris sur des données **réelles**.

Pourquoi ce modèle, et pas un autre
-----------------------------------
Les deux modèles de risque produit existants (`ml_engine/models/`) apprennent sur
des variables de position **simulées**, faute d'inventaire dans l'ERP. Leur usage
est donc borné : ils hiérarchisent, ils ne chiffrent pas. La reconstruction des
positions mensuelles (`positions_historiques.py`) lève cette limite, et rend
possible une question entièrement mesurable sur les factures :

    à la fin du mois m, cette référence sera-t-elle réapprovisionnée
    au cours des trois mois suivants ?

Trois propriétés rendent cette formulation défendable là où d'autres échouaient :

1. **La cible est observée, jamais construite.** Un achat a eu lieu, ou non. Il
   n'y a rien à estimer, rien à simuler, aucun seuil à déclarer. C'est l'exact
   opposé du premier modèle de risque de stock, dont la cible « rupture » était
   définie par une formule mêlant trois variables explicatives — et qui affichait
   pour cette raison une AUC de 1,0000.

2. **Aucune variable ne peut contenir la cible.** Toutes se calculent sur les
   mois ≤ m ; la cible se lit sur ]m, m+3]. La séparation est temporelle, donc
   vérifiable mécaniquement plutôt que par relecture.

3. **La question a un usage.** Savoir quelles références seront à commander au
   prochain trimestre, c'est préparer les négociations fournisseur et lisser la
   trésorerie. C'est la décision que le service achat prend réellement.

Ce que ce modèle apprend, et qu'il faut dire
--------------------------------------------
Il apprend le **comportement d'achat historique**, pas le besoin optimal. Si
l'entreprise a jusqu'ici surcommandé certaines références, le modèle reproduira
cette habitude. Il prévoit ce que le service achat VA faire, non ce qu'il DEVRAIT
faire — et c'est pour cela qu'il est présenté à côté du constat d'obsolescence,
qui dit l'inverse : là où les deux se contredisent, il y a une décision à revoir.

Ne pas énoncer cette limite serait la faute la plus grave du module, parce qu'elle
est invisible dans les métriques : un modèle qui reproduit fidèlement une mauvaise
habitude affiche une excellente AUC.

Seuils de déploiement — déclarés AVANT la mesure
------------------------------------------------
    AUC hors période ≥ 0,70   ET   gain ≥ 0,02 sur la meilleure référence triviale

Le registre applique ces seuils. Si le modèle ne les atteint pas, il est refusé
et le tableau de bord continue de servir la détection de rupture arithmétique de
`flux_reels.py`, qui ne dépend d'aucun apprentissage.

Sorties : `models/reappro_model.joblib` + `reports/reappro_metrics.json`

Lancement :
    python -m ml_engine.stock.reappro_model
"""

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
HORIZON_MOIS = 3            # fenêtre d'observation de la cible
MIN_MOIS_HISTORIQUE = 12    # avant cela, aucune moyenne sur 12 mois n'existe

# Seuils de déploiement, fixés avant toute mesure. Les écrire ici plutôt que de
# les choisir après coup est ce qui distingue une règle d'un arrangement.
SEUIL_AUC_MINIMALE = 0.70
SEUIL_GAIN_MINIMAL = 0.02

ECART_PARCIMONIE = 0.01
CANDIDATS = ["regression_logistique", "gradient_boosting"]

# ── Les variables, et pourquoi chacune est légitime ─────────────────────────
#
# Le classement en deux familles n'est pas décoratif. La position reconstruite
# porte un décalage inconnu mais CONSTANT par référence (le stock antérieur à
# l'historique). Ce décalage :
#   * s'annule dans toute variable de VARIATION — une différence de positions ;
#   * subsiste dans toute variable de NIVEAU — la position elle-même.
#
# Les variables de niveau sont conservées parce que l'information reste utile,
# mais leur biais est documenté et l'ablation ci-dessous mesure ce qu'elles
# apportent réellement.
VARIABLES_VARIATION = [
    "conso_1m", "conso_3m", "conso_6m", "conso_12m",
    "tendance_conso", "volatilite_conso", "part_mois_actifs_12m",
    "variation_position_3m", "mois_depuis_dernier_achat",
    "mois_depuis_derniere_vente", "n_achats_12m",
    "intervalle_moyen_achat", "ratio_attente", "taille_lot_moyen",
]
VARIABLES_NIVEAU = ["position_fin", "couverture_mois", "ratio_position_lot"]
VARIABLES_CONTEXTE = ["log_cout_unitaire", "mois_calendaire", "rang_ref"]

FEATURES = VARIABLES_VARIATION + VARIABLES_NIVEAU + VARIABLES_CONTEXTE

_EPS = 1e-6


def construire_panel(brut: Optional[pd.DataFrame] = None,
                     pour_prediction: bool = False) -> pd.DataFrame:
    """Variables au mois m, cible sur ]m, m+3].

    Toute la prévention de fuite tient dans une règle appliquée sans exception :
    chaque variable se calcule par `rolling`/`cumsum` sur les lignes passées ou
    courantes, la cible par un `shift` NÉGATIF. Aucune variable n'utilise
    `shift(-k)`, aucune cible n'utilise `shift(+k)`.
    """
    if brut is None:
        from ml_engine.stock.positions_historiques import charger_panel
        brut = charger_panel()

    if brut is None or brut.empty:
        return pd.DataFrame()

    df = brut.copy()
    df["mois"] = pd.to_datetime(df["mois"])
    df = df.sort_values(["cle", "mois"]).reset_index(drop=True)

    # Le groupement est reconstruit à chaque usage plutôt que conservé dans une
    # variable : un objet `groupby` fige les colonnes existantes au moment de sa
    # création, et lever une colonne ajoutée ensuite échoue. Le coût est
    # négligeable, l'erreur qu'il évite est silencieuse.
    def par_ref(colonne: str):
        return df.groupby("cle", sort=False)[colonne]

    # Rang du mois dans l'historique PROPRE à la référence.
    #
    # Distinction qui a son importance : `rang_mois`, calculé en SQL, compte les
    # mois depuis le début du calendrier commun. Une référence dont le premier
    # achat date de 2024 y porte donc un rang élevé sans avoir pour autant un
    # long historique. Exiger « rang_mois >= 12 » ne garantirait rien ; exiger
    # douze mois de série propre, si.
    df["rang_ref"] = df.groupby("cle", sort=False).cumcount() + 1

    # ── Consommation : moyennes glissantes, mois courant inclus ─────────────
    df["conso_1m"] = df["sorties"].astype(float)
    for f in (3, 6, 12):
        df[f"conso_{f}m"] = par_ref("sorties").transform(
            lambda s, f=f: s.rolling(f, min_periods=1).mean())

    df["tendance_conso"] = df["conso_3m"] / (df["conso_12m"] + _EPS)
    ecart = par_ref("sorties").transform(
        lambda s: s.rolling(12, min_periods=3).std())
    df["volatilite_conso"] = (ecart / (df["conso_12m"] + _EPS)).fillna(0.0)
    df["part_mois_actifs_12m"] = par_ref("sorties").transform(
        lambda s: (s > 0).rolling(12, min_periods=1).mean())

    # ── Achats : rythme, attente, taille de lot ─────────────────────────────
    df["_achat"] = (df["entrees"] > 0).astype(int)
    df["n_achats_12m"] = par_ref("_achat").transform(
        lambda s: s.rolling(12, min_periods=1).sum())

    # Mois écoulés depuis le dernier achat. Calculé par différence de rangs et
    # non par une date : la grille étant mensuelle et complète, le rang EST le
    # temps, et cela évite tout décalage de calendrier.
    df["_rang_achat"] = np.where(df["_achat"] == 1, df["rang_ref"], np.nan)
    df["mois_depuis_dernier_achat"] = (
        df["rang_ref"] - par_ref("_rang_achat").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    df["_rang_vente"] = np.where(df["sorties"] > 0, df["rang_ref"], np.nan)
    df["mois_depuis_derniere_vente"] = (
        df["rang_ref"] - par_ref("_rang_vente").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    # Intervalle moyen entre deux achats DEPUIS LE DÉBUT — une moyenne
    # expansive, jamais calculée sur toute la série : utiliser la fréquence
    # d'achat totale de la référence ferait entrer le futur dans le passé.
    achats_cumul = par_ref("_achat").transform("cumsum")
    df["intervalle_moyen_achat"] = df["rang_ref"] / achats_cumul.clip(lower=1)
    df["ratio_attente"] = (df["mois_depuis_dernier_achat"]
                           / (df["intervalle_moyen_achat"] + _EPS))

    # Taille de lot habituelle : moyenne des entrées des mois où il y a eu achat.
    df["_entree_si_achat"] = np.where(df["_achat"] == 1, df["entrees"], np.nan)
    df["taille_lot_moyen"] = par_ref("_entree_si_achat").transform(
        lambda s: s.expanding().mean()).ffill().fillna(0.0)

    # ── Niveau (biaisé par le stock initial inconnu, conservé et mesuré) ────
    df["position_fin"] = df["position_fin"].astype(float)
    df["couverture_mois"] = df["position_fin"] / (df["conso_3m"] + _EPS)
    df["variation_position_3m"] = par_ref("position_fin").transform(
        lambda s: s - s.shift(3)).fillna(0.0)
    df["ratio_position_lot"] = df["position_fin"] / (df["taille_lot_moyen"] + _EPS)

    # ── Contexte ────────────────────────────────────────────────────────────
    df["log_cout_unitaire"] = np.log1p(df["cout_unitaire"].fillna(0.0).clip(lower=0))
    df["mois_calendaire"] = df["mois"].dt.month.astype(float)

    # ── Cible : un achat survient-il dans les 3 mois suivants ? ─────────────
    #
    # `shift(-k)` est le SEUL endroit du fichier où le futur est regardé, et il
    # ne sert qu'à la cible. Les lignes dont l'horizon dépasse la fin des données
    # sont supprimées : garder un « pas d'achat » qu'on n'a pas pu observer
    # apprendrait au modèle une absence fictive.
    futurs = [df.groupby("cle", sort=False)["_achat"].shift(-k)
              for k in range(1, HORIZON_MOIS + 1)]
    fut = pd.concat(futurs, axis=1)
    df["y"] = (fut.sum(axis=1) > 0).astype(float)
    df["_horizon_observe"] = fut.notna().all(axis=1)

    # Deux usages, deux filtres — et la distinction n'est pas cosmétique.
    #
    # Pour APPRENDRE et MESURER, les trois derniers mois doivent disparaître :
    # leur cible n'est pas observable, et conserver un « pas d'achat » qu'on n'a
    # pas pu constater apprendrait une absence fictive.
    #
    # Pour PRÉDIRE, c'est l'inverse : la seule ligne utile est justement la plus
    # récente. Les écarter rendrait le modèle systématiquement en retard de trois
    # mois sur la réalité — un défaut invisible dans les métriques, puisque
    # celles-ci se calculent sur le passé.
    df = df[df["rang_ref"] >= MIN_MOIS_HISTORIQUE]
    if not pour_prediction:
        df = df[df["_horizon_observe"]]
        df = df.dropna(subset=FEATURES + ["y"])
        df["y"] = df["y"].astype(int)
    else:
        df = df.dropna(subset=FEATURES)

    return df.reset_index(drop=True)


# ── Références triviales : une variable, aucun apprentissage ────────────────
#
# Elles jugent le DÉPLOIEMENT : un modèle qui ne les bat pas n'apporte rien
# qu'un tableur ne ferait. Chacune a une direction fixée a priori, jamais
# choisie après avoir vu le résultat — inverser un signe au vu de l'AUC
# reviendrait à entraîner la référence elle-même.
def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    from sklearn.metrics import roc_auc_score

    refs = {
        "classe_majoritaire": 0.5,
        # Une référence achetée récemment est une référence activement réapprovisionnée.
        "achat_recent": -te["mois_depuis_dernier_achat"],
        # Un acheteur régulier rachète.
        "frequence_achat_12m": te["n_achats_12m"],
        # Retard par rapport au rythme habituel.
        "ratio_attente": te["ratio_attente"],
        # Une couverture faible appelle une commande.
        "couverture_faible": -te["couverture_mois"],
        # Un fort volume consommé se recommande.
        "consommation_3m": te["conso_3m"],
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


def _modele(nom: str = "gradient_boosting"):
    """Les deux candidats voient exactement les mêmes variables."""
    if nom == "regression_logistique":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(max_iter=3000, C=1.0, random_state=SEED))

    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_iter=350, learning_rate=0.06, max_depth=5,
        l2_regularization=1.0, min_samples_leaf=40,
        early_stopping=True, validation_fraction=0.15,
        random_state=SEED)


def evaluer_hors_periode(panel: pd.DataFrame) -> Dict[str, Any]:
    """Entraînement sur le passé, test sur le futur — avec marge anti-fuite.

    La marge est le point délicat. La cible d'une observation d'entraînement se
    lit sur ]m, m+3] : sans exiger `m + 3 mois <= coupure`, les derniers mois du
    train verraient le début de la période de test. C'est exactement l'écart qui
    avait révélé la fuite du modèle de crédit (0,8116 en validation croisée
    contre 0,5973 hors période).
    """
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)

    coupure = panel["mois"].quantile(0.75)
    marge = pd.DateOffset(months=HORIZON_MOIS)

    tr = panel[panel["mois"] + marge <= coupure]
    te = panel[panel["mois"] > coupure]

    if len(te) < 300 or te["y"].nunique() < 2 or len(tr) < 1000:
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
    meilleure = max(triv, key=triv.get)

    # ── Ablation : que valent les variables de NIVEAU ? ─────────────────────
    #
    # Ce sont les seules affectées par le stock initial inconnu. Si le modèle
    # tient sans elles, sa performance ne repose pas sur la partie biaisée de la
    # reconstruction — et c'est une réponse directe à l'objection la plus
    # légitime qu'on puisse opposer à ce module.
    sans_niveau = [f for f in FEATURES if f not in VARIABLES_NIVEAU]
    m2 = _modele(retenu)
    m2.fit(tr[sans_niveau], tr["y"])
    auc_sans_niveau = float(roc_auc_score(
        te["y"], m2.predict_proba(te[sans_niveau])[:, 1]))

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(coupure).date()),
        "marge_anti_fuite_mois": HORIZON_MOIS,
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_references_test": int(te["cle"].nunique()),
        "taux_positif_train": round(float(tr["y"].mean()), 4),
        "taux_positif_test": round(float(te["y"].mean()), 4),

        "modeles_candidats": {k: round(v, 4) for k, v in aucs.items()},
        "modele_retenu": retenu,
        "regle_selection": (
            f"parcimonie — le modèle le plus simple est conservé sauf si un "
            f"modèle plus complexe gagne plus de {ECART_PARCIMONIE} d'AUC"),

        "auc": round(auc, 4),
        "average_precision": round(float(average_precision_score(te["y"], p)), 4),
        "precision": round(float(precision_score(te["y"], pred, zero_division=0)), 4),
        "recall": round(float(recall_score(te["y"], pred, zero_division=0)), 4),
        "f1": round(float(f1_score(te["y"], pred, zero_division=0)), 4),
        "brier": round(float(brier_score_loss(te["y"], p)), 4),
        "confusion_matrix": confusion_matrix(te["y"], pred).tolist(),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"],
            p_train=ajustes[retenu].predict_proba(tr[FEATURES])[:, 1]),

        "references_triviales": {k: round(v, 4) for k, v in triv.items()},
        "meilleure_reference_triviale": meilleure,
        "auc_meilleure_reference_triviale": round(triv[meilleure], 4),
        "gain_vs_reference_triviale": round(auc - triv[meilleure], 4),

        "ablation_variables_de_niveau": {
            "variables_retirees": VARIABLES_NIVEAU,
            "auc_sans": round(auc_sans_niveau, 4),
            "perte": round(auc - auc_sans_niveau, 4),
            "lecture": (
                "Les variables de niveau sont les seules affectées par le stock "
                "antérieur à l'historique, inconnu. Une perte faible signifie "
                "que la performance ne repose pas sur la partie biaisée de la "
                "reconstruction."),
        },
    }


def evaluer_groupkfold(panel: pd.DataFrame, modele: str) -> Dict[str, Any]:
    """Par référence — INDICATIF seulement : ce protocole brasse les périodes.

    Conservé pour que l'écart avec le protocole hors période reste visible. C'est
    cet écart, et non sa valeur absolue, qui informe : un GroupKFold très
    supérieur signale que le modèle exploite la conjoncture d'une période.
    """
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold

    aucs: List[float] = []
    for a, b in GroupKFold(n_splits=5).split(panel, panel["y"],
                                             panel["cle"].values):
        tr, te = panel.iloc[a], panel.iloc[b]
        if te["y"].nunique() < 2:
            continue
        m = _modele(modele)
        m.fit(tr[FEATURES], tr["y"])
        aucs.append(float(roc_auc_score(
            te["y"], m.predict_proba(te[FEATURES])[:, 1])))

    return {
        "auc_moyen": round(float(np.mean(aucs)), 4) if aucs else None,
        "auc_par_pli": [round(a, 4) for a in aucs],
        "avertissement": ("protocole indicatif : il brasse les périodes et flatte "
                          "le résultat. La décision de déploiement repose sur le "
                          "protocole hors période."),
    }


def importance_permutation(panel: pd.DataFrame, modele: str) -> Dict[str, float]:
    """Mesurée sur le TEST hors période : une variable très utilisée à
    l'entraînement peut n'apporter aucune généralisation."""
    from sklearn.inspection import permutation_importance

    coupure = panel["mois"].quantile(0.75)
    tr = panel[panel["mois"] + pd.DateOffset(months=HORIZON_MOIS) <= coupure]
    te = panel[panel["mois"] > coupure]
    if len(te) < 300 or len(tr) < 1000:
        return {}

    m = _modele(modele)
    m.fit(tr[FEATURES], tr["y"])
    r = permutation_importance(m, te[FEATURES], te["y"], n_repeats=5,
                              random_state=SEED, scoring="roc_auc")
    return {f: round(float(v), 4)
            for f, v in sorted(zip(FEATURES, r.importances_mean),
                               key=lambda kv: -kv[1])}


def train() -> Dict[str, Any]:
    """Entraîne, mesure, décide — et n'enregistre l'artefact que si la décision
    est positive.

    Écrire le modèle sur le disque quoi qu'il arrive serait le piège que le
    registre existe pour fermer : un artefact présent finit par être chargé.
    """
    import joblib

    panel = construire_panel()
    if panel.empty:
        return {"error": ("panneau vide — lancer d'abord "
                          "python -m ml_engine.stock.positions_historiques")}

    hp = evaluer_hors_periode(panel)
    if not hp.get("applicable"):
        metriques = {
            "version": 1,
            "horizon_mois": HORIZON_MOIS,
            "n_observations": int(len(panel)),
            "hors_periode": hp,
            "decision_deploiement": {
                "modele_deploye": False,
                "motif": f"protocole hors période inapplicable — {hp.get('motif')}",
            },
        }
        _ecrire(metriques)
        return metriques

    retenu = hp["modele_retenu"]
    gk = evaluer_groupkfold(panel, retenu)
    imp = importance_permutation(panel, retenu)

    auc = hp["auc"]
    gain = hp["gain_vs_reference_triviale"]
    deploye = (auc >= SEUIL_AUC_MINIMALE and gain >= SEUIL_GAIN_MINIMAL)

    if deploye:
        motif = (f"AUC {auc:.4f} hors période, soit {gain:+.4f} sur la meilleure "
                 f"référence triviale ({hp['meilleure_reference_triviale']}) — "
                 "les deux seuils déclarés sont atteints")
    elif auc < SEUIL_AUC_MINIMALE:
        motif = (f"AUC {auc:.4f} sous le seuil de {SEUIL_AUC_MINIMALE} — "
                 "le modèle n'est pas assez discriminant pour décider")
    else:
        motif = (f"gain de seulement {gain:+.4f} sur "
                 f"« {hp['meilleure_reference_triviale']} » "
                 f"(AUC {hp['auc_meilleure_reference_triviale']:.4f}) : sous le "
                 f"seuil de {SEUIL_GAIN_MINIMAL}, un modèle n'ajoute rien qu'une "
                 "règle d'une ligne ne ferait déjà")

    metriques = {
        "version": 1,
        "question": ("à la fin d'un mois, cette référence sera-t-elle "
                     f"réapprovisionnée dans les {HORIZON_MOIS} mois suivants ?"),
        "nature_de_la_cible": (
            "OBSERVÉE — un achat a eu lieu, ou non. Aucun seuil déclaré, aucune "
            "simulation, aucune formule mêlant des variables explicatives."),
        "horizon_mois": HORIZON_MOIS,
        "n_observations": int(len(panel)),
        "n_references": int(panel["cle"].nunique()),
        "periode": f"{panel['mois'].min().date()} → {panel['mois'].max().date()}",
        "taux_de_base": round(float(panel["y"].mean()), 4),
        "variables": {
            "de_variation": VARIABLES_VARIATION,
            "de_niveau": VARIABLES_NIVEAU,
            "de_contexte": VARIABLES_CONTEXTE,
            "pourquoi_cette_distinction": (
                "La position reconstruite porte un décalage inconnu mais CONSTANT "
                "par référence. Il s'annule dans les variables de variation et "
                "subsiste dans celles de niveau — d'où l'ablation mesurée."),
        },
        "seuils_declares_avant_mesure": {
            "auc_minimale": SEUIL_AUC_MINIMALE,
            "gain_minimal_sur_reference_triviale": SEUIL_GAIN_MINIMAL,
        },
        "hors_periode": hp,
        "groupkfold_indicatif": gk,
        "ecart_groupkfold_hors_periode": (
            round(gk["auc_moyen"] - auc, 4) if gk.get("auc_moyen") else None),
        "importance_permutation": imp,
        "decision_deploiement": {"modele_deploye": bool(deploye), "motif": motif},
        "ce_que_le_modele_apprend": (
            "Le COMPORTEMENT D'ACHAT historique, pas le besoin optimal. Si "
            "l'entreprise a surcommandé une référence, le modèle reproduira "
            "cette habitude. Il prévoit ce que le service achat VA faire, non ce "
            "qu'il DEVRAIT faire — raison pour laquelle il est lu à côté du "
            "constat d'obsolescence, qui dit l'inverse. Là où les deux se "
            "contredisent, il y a une décision à revoir."),
    }

    if deploye:
        m = _modele(retenu)
        m.fit(panel[FEATURES], panel["y"])
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"modele": m, "features": FEATURES, "nom": retenu,
                     "horizon_mois": HORIZON_MOIS, "seed": SEED},
                    MODELS_DIR / "reappro_model.joblib")
        metriques["artefact"] = "models/reappro_model.joblib"
        metriques["entraine_sur"] = ("panneau complet, après validation hors "
                                     "période — le modèle servi voit donc plus "
                                     "de données que celui mesuré")
    else:
        # Aucun artefact écrit, et l'ancien est retiré : un fichier présent finit
        # toujours par être chargé par quelqu'un.
        ancien = MODELS_DIR / "reappro_model.joblib"
        if ancien.exists():
            try:
                ancien.unlink()
            except Exception:
                pass

    _ecrire(metriques)
    return metriques


def _ecrire(metriques: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "reappro_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)


def predire(limite: int = 15) -> Dict[str, Any]:
    """Références à préparer pour le trimestre, si le registre l'autorise.

    Le classement suit le **budget à prévoir** — probabilité × trois mois de
    consommation × coût unitaire — et non la probabilité seule. Une référence
    quasi certaine à 40 DT n'appelle aucune décision ; une référence probable à
    80 000 DT en appelle une.
    """
    from ml_engine.registre import est_deploye

    if not est_deploye("reappro"):
        return {"servi": False,
                "motif": "modèle refusé par le registre — non servi"}

    chemin = MODELS_DIR / "reappro_model.joblib"
    if not chemin.exists():
        return {"servi": False, "motif": "artefact absent"}

    try:
        import joblib
        paquet = joblib.load(chemin)
        panel = construire_panel(pour_prediction=True)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        # Dernier mois connu pour chaque référence : c'est la seule ligne dont
        # la prédiction porte sur l'avenir plutôt que sur le passé.
        dernier = panel.sort_values("mois").groupby("cle", as_index=False).tail(1)
        p = paquet["modele"].predict_proba(dernier[paquet["features"]])[:, 1]
        dernier = dernier.assign(probabilite=p)
        dernier["budget_dt"] = (dernier["probabilite"]
                                * dernier["conso_3m"]
                                * dernier["cout_unitaire"].fillna(0.0))

        top = dernier.sort_values("budget_dt", ascending=False).head(limite)
        return {
            "servi": True,
            "mois_de_reference": str(dernier["mois"].max().date()),
            "horizon_mois": HORIZON_MOIS,
            "n_references": int(len(dernier)),
            "budget_total_dt": round(float(dernier["budget_dt"].sum()), 0),
            "top": [{
                "produit": r["produit"],
                "probabilite": round(float(r["probabilite"]), 3),
                "conso_mensuelle": round(float(r["conso_3m"]), 1),
                "couverture_mois": round(float(r["couverture_mois"]), 1),
                "mois_sans_achat": int(r["mois_depuis_dernier_achat"]),
                "budget_dt": round(float(r["budget_dt"]), 0),
            } for _, r in top.iterrows()],
            "lecture_du_classement": (
                "trié par budget à prévoir — probabilité × trois mois de "
                "consommation × coût d'achat réel — et non par probabilité"),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def afficher() -> None:
    m = train()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    print("\n" + "=" * 78)
    print("  BESOIN DE RÉAPPROVISIONNEMENT À 3 MOIS")
    print("=" * 78)
    print(f"\n  {m['question']}")
    print(f"\n  Observations   : {m['n_observations']:,}".replace(",", " ")
          + f"  sur {m['n_references']} références")
    print(f"  Période        : {m['periode']}")
    print(f"  Taux de base   : {m['taux_de_base'] * 100:.1f} % des mois "
          "comportent un achat dans les 3 suivants")

    hp = m.get("hors_periode") or {}
    if hp.get("applicable"):
        print("\n  " + "-" * 74)
        print("  HORS PÉRIODE — entraînement sur le passé, test sur le futur")
        print(f"    coupure {hp['coupure']} · marge anti-fuite "
              f"{hp['marge_anti_fuite_mois']} mois")
        print(f"    train {hp['n_train']:,}".replace(",", " ")
              + f" · test {hp['n_test']:,}".replace(",", " "))
        print("\n    Candidats :")
        for nom, a in hp["modeles_candidats"].items():
            marque = "  <- retenu" if nom == hp["modele_retenu"] else ""
            print(f"      {nom:<26} AUC {a:.4f}{marque}")
        print(f"\n    AUC retenue         : {hp['auc']:.4f}")
        print(f"    Précision / Rappel  : {hp['precision']:.4f} / {hp['recall']:.4f}")
        print(f"    Brier               : {hp['brier']:.4f}")

        print("\n    Références triviales (une variable, aucun apprentissage) :")
        for nom, a in sorted(hp["references_triviales"].items(),
                             key=lambda kv: -kv[1]):
            print(f"      {nom:<26} AUC {a:.4f}")
        print(f"\n    GAIN sur la meilleure : {hp['gain_vs_reference_triviale']:+.4f}")

        abl = hp.get("ablation_variables_de_niveau") or {}
        if abl:
            print(f"\n    Sans les variables de niveau : AUC {abl['auc_sans']:.4f} "
                  f"(perte {abl['perte']:+.4f})")
            print("    — les seules affectées par le stock initial inconnu")

    gk = m.get("groupkfold_indicatif") or {}
    if gk.get("auc_moyen"):
        print(f"\n  GroupKFold (indicatif) : AUC {gk['auc_moyen']:.4f} — "
              f"écart {m.get('ecart_groupkfold_hors_periode'):+.4f}")

    imp = m.get("importance_permutation") or {}
    if imp:
        print("\n  Variables les plus utiles (importance par permutation, sur le test) :")
        for f, v in list(imp.items())[:6]:
            print(f"    {f:<28} {v:+.4f}")

    d = m["decision_deploiement"]
    print("\n" + "-" * 78)
    print(f"  DÉCISION : {'DÉPLOYÉ' if d['modele_deploye'] else 'REFUSÉ'}")
    for i in range(0, len(d["motif"]), 72):
        print(f"    {d['motif'][i:i+72]}")
    if not d["modele_deploye"]:
        print("\n  Le tableau de bord continue de servir la détection de rupture")
        print("  arithmétique de flux_reels.py, qui ne dépend d'aucun modèle.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
