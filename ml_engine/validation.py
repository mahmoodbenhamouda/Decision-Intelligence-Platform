"""
ml_engine/validation.py
========================
Protocoles de validation partagés — walk-forward multi-origines et test apparié.

Le problème que ce module résout
--------------------------------
Le modèle de conversion des devis a été mesuré à **AUC 0,7165**, soit **+0,0341**
sur la meilleure référence triviale. Les deux seuils déclarés étaient atteints.
Puis le test de significativité l'a refusé :

    écart médian +0,0350 · IC95 [-0,0290 ; +0,0948]  ->  NON SIGNIFICATIF
    le modèle gagne dans 86,4 % des tirages

Lecture exacte de ce résultat, et elle est importante : **le modèle n'est pas
mauvais, le jeu de test est trop petit pour conclure**. 988 devis dont 92 signés.
Avec si peu de positifs, l'intervalle sur l'écart mesure surtout notre ignorance.

Une coupure unique 75/25 gaspille des données
---------------------------------------------
Elle n'utilise qu'un seul quart de l'historique comme test, et toujours le même.
Le remède n'est pas de desserrer un seuil : c'est de **mesurer sur plus
d'observations, avec le même protocole**.

Le walk-forward multi-origines entraîne et teste plusieurs fois, en avançant la
coupure, puis **met en commun** les prédictions hors période. Chaque prédiction
reste faite par un modèle qui n'a vu que le passé — la garantie anti-fuite est
identique — mais le test agrégé porte sur trois à quatre fois plus de positifs, et
l'intervalle de confiance se resserre d'autant.

Ce n'est pas un assouplissement. C'est la même exigence, mieux mesurée. Et la
conclusion peut rester négative : un écart qui disparaît sur un test élargi n'a
jamais existé.

Ce que ce module ne fait pas
----------------------------
Il ne choisit aucun modèle et ne fixe aucun seuil. Il fournit deux outils — un
protocole de découpage et un test d'écart — que chaque module d'apprentissage
appelle avec ses propres règles, déclarées chez lui.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

SEED = 42


def walk_forward(panel: pd.DataFrame,
                 colonne_date: str,
                 ajuster_et_predire: Callable[[pd.DataFrame, pd.DataFrame],
                                              np.ndarray],
                 n_origines: int = 4,
                 part_test: float = 0.15,
                 marge: Optional[pd.DateOffset] = None,
                 min_train: int = 400,
                 min_test: int = 120) -> Dict[str, Any]:
    """Plusieurs coupures temporelles, prédictions hors période mises en commun.

    Paramètres
    ----------
    ajuster_et_predire
        Reçoit `(train, test)` et renvoie les probabilités sur `test`. C'est
        l'appelant qui décide du modèle, de ses variables et de son réglage — ce
        module ne connaît rien de tout cela.
    marge
        Décalage à imposer entre la fin du train et le début du test, pour les
        cibles observées sur une fenêtre future. `None` quand la cible est un état
        atteint plutôt qu'un événement à venir.

    Garantie
    --------
    Chaque prédiction est produite par un modèle entraîné **exclusivement** sur
    des observations antérieures à sa propre coupure. Mettre les prédictions en
    commun n'introduit donc aucune fuite : on agrège des mesures hors période, pas
    des modèles.
    """
    d = panel.sort_values(colonne_date).reset_index(drop=True)
    n = len(d)
    if n < min_train + min_test:
        return {"applicable": False,
                "motif": f"{n} observations — insuffisant pour un walk-forward"}

    # Les origines sont réparties sur la fin de l'historique : la première laisse
    # assez de passé pour entraîner, la dernière teste les données les plus
    # récentes exploitables.
    debut = max(min_train, int(n * (1.0 - n_origines * part_test)))
    if debut >= n - min_test:
        debut = max(min_train, n - int(n * part_test) - min_test)

    bornes: List[int] = []
    pas = max(int(n * part_test), 1)
    i = debut
    while i + min_test <= n and len(bornes) < n_origines:
        bornes.append(i)
        i += pas
    if not bornes:
        return {"applicable": False, "motif": "aucune origine exploitable"}

    y_tous: List[np.ndarray] = []
    p_tous: List[np.ndarray] = []
    plis: List[Dict[str, Any]] = []

    from sklearn.metrics import roc_auc_score

    for k, borne in enumerate(bornes, start=1):
        coupure = d[colonne_date].iloc[borne]
        fin_test = (d[colonne_date].iloc[min(borne + pas, n) - 1]
                    if borne + pas < n else d[colonne_date].iloc[-1])

        tr = d[d[colonne_date] <= coupure]
        if marge is not None:
            tr = tr[tr[colonne_date] + marge <= coupure]
        te = d[(d[colonne_date] > coupure) & (d[colonne_date] <= fin_test)]

        if len(tr) < min_train or len(te) < 40 or te["y"].nunique() < 2:
            plis.append({"pli": k, "coupure": str(pd.Timestamp(coupure).date()),
                         "retenu": False,
                         "motif": f"train={len(tr)} test={len(te)}"})
            continue

        p = np.asarray(ajuster_et_predire(tr, te), dtype=float)
        y = te["y"].to_numpy(dtype=int)
        try:
            auc_pli = float(roc_auc_score(y, p))
        except Exception:
            auc_pli = float("nan")

        y_tous.append(y)
        p_tous.append(p)
        plis.append({
            "pli": k,
            "coupure": str(pd.Timestamp(coupure).date()),
            "retenu": True,
            "n_train": int(len(tr)), "n_test": int(len(te)),
            "n_positifs_test": int(y.sum()),
            "auc": round(auc_pli, 4) if auc_pli == auc_pli else None,
        })

    if not y_tous:
        return {"applicable": False, "motif": "aucun pli exploitable"}

    y_agg = np.concatenate(y_tous)
    p_agg = np.concatenate(p_tous)
    aucs = [f["auc"] for f in plis if f.get("retenu") and f.get("auc") is not None]

    return {
        "applicable": True,
        "n_origines": len([f for f in plis if f.get("retenu")]),
        "plis": plis,
        "n_test_agrege": int(len(y_agg)),
        "n_positifs_agrege": int(y_agg.sum()),
        "auc_agregee": round(float(roc_auc_score(y_agg, p_agg)), 4),
        "auc_moyenne_des_plis": round(float(np.mean(aucs)), 4) if aucs else None,
        "auc_ecart_type_des_plis": (round(float(np.std(aucs)), 4)
                                    if len(aucs) > 1 else None),
        "y_agrege": y_agg,
        "p_agrege": p_agg,
        "principe": (
            "Chaque prédiction vient d'un modèle entraîné exclusivement sur le "
            "passé de sa propre coupure. Agréger les prédictions hors période "
            "n'introduit aucune fuite : on met en commun des mesures, pas des "
            "modèles. Le gain est statistique — plus de positifs, donc un "
            "intervalle de confiance plus étroit sur la même exigence."),
    }


def comparer_apparie(y: np.ndarray, p_modele: np.ndarray,
                     p_reference: np.ndarray,
                     n_tirages: int = 2000,
                     graine: int = SEED) -> Dict[str, Any]:
    """L'écart d'AUC entre un modèle et sa référence est-il distinguable du bruit ?

    Le test est **apparié** : chaque tirage rééchantillonne les mêmes observations
    pour les deux scores. Comparer deux intervalles calculés séparément serait plus
    faible — ils peuvent se chevaucher alors que la différence, elle, est stable.

    Le critère porte sur l'intervalle de l'ÉCART, jamais sur celui des AUC : c'est
    la seule formulation qui répond à la question « le modèle fait-il mieux, ou
    a-t-il eu de la chance sur ce découpage ? ».
    """
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(graine)
    n = len(y)
    ecarts: List[float] = []
    aucs_m: List[float] = []
    aucs_r: List[float] = []

    for _ in range(n_tirages):
        idx = rng.integers(0, n, size=n)
        yb = y[idx]
        if len(np.unique(yb)) < 2:
            continue
        try:
            a_m = roc_auc_score(yb, p_modele[idx])
            a_r = roc_auc_score(yb, p_reference[idx])
        except Exception:
            continue
        aucs_m.append(a_m)
        aucs_r.append(a_r)
        ecarts.append(a_m - a_r)

    if len(ecarts) < 200:
        return {"applicable": False, "motif": "tirages insuffisants"}

    e = np.array(ecarts)
    bas, haut = float(np.percentile(e, 2.5)), float(np.percentile(e, 97.5))

    return {
        "applicable": True,
        "n_tirages_valides": len(ecarts),
        "n_observations": int(n),
        "n_positifs": int(np.asarray(y).sum()),
        "auc_modele_ic95": [round(float(np.percentile(aucs_m, 2.5)), 4),
                            round(float(np.percentile(aucs_m, 97.5)), 4)],
        "auc_reference_ic95": [round(float(np.percentile(aucs_r, 2.5)), 4),
                               round(float(np.percentile(aucs_r, 97.5)), 4)],
        "ecart_median": round(float(np.median(e)), 4),
        "ecart_ic95": [round(bas, 4), round(haut, 4)],
        "part_tirages_ou_le_modele_gagne_pct": round(float((e > 0).mean() * 100), 1),
        "significatif": bool(bas > 0.0),
        "lecture": (
            "Intervalle sur l'ÉCART, par tirages APPARIÉS. S'il contient zéro, "
            "l'avantage n'est pas distinguable du bruit d'échantillonnage : le "
            "déployer reviendrait à servir un découpage favorable."),
    }
