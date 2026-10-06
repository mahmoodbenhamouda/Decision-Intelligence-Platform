"""Métriques de classification COMPLÈTES, identiques pour tous les modèles."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np


def _bloc(y: np.ndarray, pred: np.ndarray) -> Dict[str, Any]:
    from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                                 cohen_kappa_score, f1_score,
                                 matthews_corrcoef, precision_score,
                                 recall_score)

    tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tp = int(((pred == 1) & (y == 1)).sum())
    specificite = tn / (tn + fp) if (tn + fp) else 0.0
    une_seule_classe_predite = len(np.unique(pred)) < 2

    return {
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "specificite": round(float(specificite), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "mcc": round(0.0 if une_seule_classe_predite
                     else float(matthews_corrcoef(y, pred)), 4),
        "kappa_cohen": round(0.0 if une_seule_classe_predite
                             else float(cohen_kappa_score(y, pred)), 4),
        "matrice_confusion": {"vrais_negatifs": tn, "faux_positifs": fp,
                              "faux_negatifs": fn, "vrais_positifs": tp},
        "n_predits_positifs": int(tp + fp),
    }


def seuil_optimal_f1(y_train: np.ndarray, p_train: np.ndarray) -> float:
    """Seuil maximisant le F1 sur l'ENTRAÎNEMENT — jamais sur le test."""
    from sklearn.metrics import f1_score

    y_train = np.asarray(y_train).astype(int)
    p_train = np.asarray(p_train, dtype=float)
    if len(np.unique(y_train)) < 2:
        return 0.5
    candidats = np.unique(np.quantile(p_train, np.linspace(0.01, 0.99, 99)))
    meilleur, meilleur_f1 = 0.5, -1.0
    for s in candidats:
        f1 = f1_score(y_train, (p_train >= s).astype(int), zero_division=0)
        if f1 > meilleur_f1 + 1e-12:
            meilleur, meilleur_f1 = float(s), float(f1)
    return meilleur


def metriques_classification(y_test, p_test,
                             y_train=None, p_train=None,
                             score_est_une_probabilite: bool = True
                             ) -> Dict[str, Any]:
    """Toutes les métriques d'un classifieur binaire, sur le jeu de TEST."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 roc_auc_score)

    y = np.asarray(y_test).astype(int)
    p = np.asarray(p_test, dtype=float)
    if len(y) == 0 or len(np.unique(y)) < 2:
        return {"applicable": False,
                "motif": "le jeu de test ne contient qu'une seule classe"}

    taux = float(y.mean())
    majoritaire = max(taux, 1 - taux)

    out: Dict[str, Any] = {
        "applicable": True,
        "n_test": int(len(y)),
        "taux_de_base_test": round(taux, 4),
        "accuracy_classe_majoritaire": round(majoritaire, 4),
        "auc": round(float(roc_auc_score(y, p)), 4),
        "average_precision": round(float(average_precision_score(y, p)), 4),
    }

    if score_est_une_probabilite:
        out["brier"] = round(float(brier_score_loss(y, np.clip(p, 0, 1))), 4)
        b05 = _bloc(y, (p >= 0.5).astype(int))
        b05["gain_accuracy_vs_majoritaire"] = round(b05["accuracy"] - majoritaire, 4)
        out["au_seuil_0_5"] = b05

    if y_train is not None and p_train is not None:
        seuil = seuil_optimal_f1(np.asarray(y_train), np.asarray(p_train))
        bopt = _bloc(y, (p >= seuil).astype(int))
        bopt["seuil"] = round(seuil, 4)
        bopt["seuil_choisi_sur"] = "entraînement seul (maximisation du F1)"
        bopt["gain_accuracy_vs_majoritaire"] = round(bopt["accuracy"] - majoritaire, 4)
        out["au_seuil_optimise_train"] = bopt

    ref = out.get("au_seuil_optimise_train") or out.get("au_seuil_0_5")
    if ref:
        out["accuracy"] = ref["accuracy"]
        out["balanced_accuracy"] = ref["balanced_accuracy"]
        out["f1"] = ref["f1"]
        out["mcc"] = ref["mcc"]
        out["lecture"] = (
            f"Accuracy {ref['accuracy']:.1%} contre {majoritaire:.1%} pour un "
            f"classifieur qui répondrait toujours la classe majoritaire "
            f"(taux de base {taux:.1%}). "
            + ("Sur une cible aussi déséquilibrée, l'accuracy est dominée par "
               "la classe majoritaire : balanced accuracy "
               f"{ref['balanced_accuracy']:.1%} et MCC {ref['mcc']:.2f} "
               "mesurent la capacité réelle à détecter les positifs."
               if majoritaire >= 0.75 else
               f"Balanced accuracy {ref['balanced_accuracy']:.1%}, MCC "
               f"{ref['mcc']:.2f}."))
    return out


def metriques_decision(y_test, pred_test, score_test=None) -> Dict[str, Any]:
    """Métriques d'une RÈGLE dont la décision binaire est déjà fixée."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    y = np.asarray(y_test).astype(int)
    pred = np.asarray(pred_test).astype(int)
    if len(y) == 0 or len(np.unique(y)) < 2:
        return {"applicable": False,
                "motif": "le jeu de test ne contient qu'une seule classe"}
    taux = float(y.mean())
    majoritaire = max(taux, 1 - taux)
    b = _bloc(y, pred)
    out: Dict[str, Any] = {
        "applicable": True,
        "n_test": int(len(y)),
        "taux_de_base_test": round(taux, 4),
        "accuracy_classe_majoritaire": round(majoritaire, 4),
        "decision_de_la_regle": {**b, "gain_accuracy_vs_majoritaire":
                                 round(b["accuracy"] - majoritaire, 4)},
        "accuracy": b["accuracy"], "balanced_accuracy": b["balanced_accuracy"],
        "f1": b["f1"], "mcc": b["mcc"],
    }
    if score_test is not None:
        s = np.asarray(score_test, dtype=float)
        out["auc"] = round(float(roc_auc_score(y, s)), 4)
        out["average_precision"] = round(float(average_precision_score(y, s)), 4)
    out["lecture"] = (
        f"Accuracy {b['accuracy']:.1%} contre {majoritaire:.1%} pour la classe "
        f"majoritaire ; balanced accuracy {b['balanced_accuracy']:.1%}, "
        f"MCC {b['mcc']:.2f}.")
    return out


def metriques_depuis_matrice(matrice) -> Dict[str, Any]:
    """Accuracy et compagnie reconstruites d'une matrice de confusion publiée."""
    (tn, fp), (fn, tp) = matrice
    n = tn + fp + fn + tp
    if n == 0 or (tp + fn) == 0 or (tn + fp) == 0:
        return {"applicable": False, "motif": "matrice dégénérée"}
    rappel = tp / (tp + fn)
    specificite = tn / (tn + fp)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * rappel / (precision + rappel) if (precision + rappel) else 0.0
    denom = ((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) ** 0.5
    mcc = ((tp * tn - fp * fn) / denom) if denom else 0.0
    taux = (tp + fn) / n
    return {
        "applicable": True, "source": "matrice de confusion publiée (seuil 0,5)",
        "n_test": int(n), "taux_de_base_test": round(taux, 4),
        "accuracy_classe_majoritaire": round(max(taux, 1 - taux), 4),
        "accuracy": round((tp + tn) / n, 4),
        "balanced_accuracy": round((rappel + specificite) / 2, 4),
        "precision": round(precision, 4), "recall": round(rappel, 4),
        "specificite": round(specificite, 4), "f1": round(f1, 4), "mcc": round(mcc, 4),
    }
