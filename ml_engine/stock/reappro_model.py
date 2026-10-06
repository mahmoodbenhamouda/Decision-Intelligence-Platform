"""Besoin de réapprovisionnement à 3 mois — un modèle appris sur des données **réelles**."""

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
MIN_MOIS_HISTORIQUE = 12

SEUIL_AUC_MINIMALE = 0.70
SEUIL_GAIN_MINIMAL = 0.02

ECART_PARCIMONIE = 0.01
CANDIDATS = ["regression_logistique", "gradient_boosting"]

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
    """Variables au mois m, cible sur ]m, m+3]."""
    if brut is None:
        from ml_engine.stock.positions_historiques import charger_panel
        brut = charger_panel()

    if brut is None or brut.empty:
        return pd.DataFrame()

    df = brut.copy()
    df["mois"] = pd.to_datetime(df["mois"])
    df = df.sort_values(["cle", "mois"]).reset_index(drop=True)

    def par_ref(colonne: str):
        return df.groupby("cle", sort=False)[colonne]

    df["rang_ref"] = df.groupby("cle", sort=False).cumcount() + 1

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

    df["_achat"] = (df["entrees"] > 0).astype(int)
    df["n_achats_12m"] = par_ref("_achat").transform(
        lambda s: s.rolling(12, min_periods=1).sum())

    df["_rang_achat"] = np.where(df["_achat"] == 1, df["rang_ref"], np.nan)
    df["mois_depuis_dernier_achat"] = (
        df["rang_ref"] - par_ref("_rang_achat").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    df["_rang_vente"] = np.where(df["sorties"] > 0, df["rang_ref"], np.nan)
    df["mois_depuis_derniere_vente"] = (
        df["rang_ref"] - par_ref("_rang_vente").transform(lambda s: s.ffill())
    ).fillna(df["rang_ref"]).astype(float)

    achats_cumul = par_ref("_achat").transform("cumsum")
    df["intervalle_moyen_achat"] = df["rang_ref"] / achats_cumul.clip(lower=1)
    df["ratio_attente"] = (df["mois_depuis_dernier_achat"]
                           / (df["intervalle_moyen_achat"] + _EPS))

    df["_entree_si_achat"] = np.where(df["_achat"] == 1, df["entrees"], np.nan)
    df["taille_lot_moyen"] = par_ref("_entree_si_achat").transform(
        lambda s: s.expanding().mean()).ffill().fillna(0.0)

    df["position_fin"] = df["position_fin"].astype(float)
    df["couverture_mois"] = df["position_fin"] / (df["conso_3m"] + _EPS)
    df["variation_position_3m"] = par_ref("position_fin").transform(
        lambda s: s - s.shift(3)).fillna(0.0)
    df["ratio_position_lot"] = df["position_fin"] / (df["taille_lot_moyen"] + _EPS)

    df["log_cout_unitaire"] = np.log1p(df["cout_unitaire"].fillna(0.0).clip(lower=0))
    df["mois_calendaire"] = df["mois"].dt.month.astype(float)

    futurs = [df.groupby("cle", sort=False)["_achat"].shift(-k)
              for k in range(1, HORIZON_MOIS + 1)]
    fut = pd.concat(futurs, axis=1)
    df["y"] = (fut.sum(axis=1) > 0).astype(float)
    df["_horizon_observe"] = fut.notna().all(axis=1)

    df = df[df["rang_ref"] >= MIN_MOIS_HISTORIQUE]
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
        "achat_recent": -te["mois_depuis_dernier_achat"],
        "frequence_achat_12m": te["n_achats_12m"],
        "ratio_attente": te["ratio_attente"],
        "couverture_faible": -te["couverture_mois"],
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
    """Entraînement sur le passé, test sur le futur — avec marge anti-fuite."""
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
    """Par référence — INDICATIF seulement : ce protocole brasse les périodes."""
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
    """Mesurée sur le TEST hors période : une variable très utilisée à l'entraînement peut n'apporter…"""
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
    """Entraîne, mesure, décide — et n'enregistre l'artefact que si la décision est positive."""
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
    """Références à préparer pour le trimestre, si le registre l'autorise."""
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
