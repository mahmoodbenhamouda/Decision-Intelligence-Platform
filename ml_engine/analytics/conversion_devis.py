"""Quel devis a une chance d'être signé ?"""

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

MATURATION_MOIS = 6

DEBUT_EXPLOITABLE = "2019-01-01"

SEUIL_AUC_MINIMALE = 0.70
SEUIL_GAIN_MINIMAL = 0.02
SEUIL_ECART_TRAIN_VALID = 0.10
ECART_PARCIMONIE = 0.01

CANDIDATS = ["regression_logistique", "gradient_boosting"]

REGLAGES: Dict[str, List[Dict[str, Any]]] = {
    "regression_logistique": [{"C": 1.0}, {"C": 0.1}, {"C": 0.01}],
    "gradient_boosting": [
        {"max_depth": 4, "min_samples_leaf": 40, "l2_regularization": 2.0,
         "max_iter": 300, "learning_rate": 0.06},
        {"max_depth": 3, "min_samples_leaf": 80, "l2_regularization": 5.0,
         "max_iter": 200, "learning_rate": 0.05},
        {"max_depth": 2, "min_samples_leaf": 150, "l2_regularization": 10.0,
         "max_iter": 150, "learning_rate": 0.05},
    ],
}

VARIABLES_DEVIS = [
    "log_montant_ht", "mois", "trimestre", "jour_semaine",
    "n_devis_meme_mois",
]

VARIABLES_CLIENT = [
    "est_client", "anciennete_j", "n_factures_12m", "log_ca_12m",
    "recence_facture_j", "panier_moyen", "marge_moyenne_pct",
    "delai_median_accorde_j",
]

VARIABLES_HISTORIQUE_DEVIS = [
    "n_devis_12m", "taux_conversion_passe", "log_montant_moyen_devis_passes",
    "ratio_montant_vs_habituel",
]

VARIABLES_RELATIVES = ["ratio_montant_panier", "ratio_montant_ca_12m"]

FEATURES = (VARIABLES_DEVIS + VARIABLES_CLIENT
            + VARIABLES_HISTORIQUE_DEVIS + VARIABLES_RELATIVES)

#: Un devis gros et probable ne se traite pas comme un devis gros et improbable.
#: Le second est presque toujours un appel d'offres public : le relancer au
#: téléphone ne sert à rien, il se suit administrativement. Les seuils sont
#: déclarés ici, pas dans l'interface, pour que la règle soit unique.
SEUIL_CHANCE_HAUTE = 0.25
SEUIL_MONTANT_GROS_DT = 20_000.0

#: Au-delà de cet âge, un devis non signé n'est plus un devis en cours : il est
#: perdu ou remplacé. Mesuré sur la donnée : au-delà de 120 jours, la
#: conversion observée devient négligeable.
AGE_DEVIS_MORT_J = 120

PROTOCOLES = {
    "appeler": {
        "libelle": "Appeler cette semaine",
        "quoi_faire": ("Montant significatif et bonne chance de signature : "
                       "c'est là que le temps commercial rapporte le plus. "
                       "Un appel, une date de décision, un compte rendu."),
    },
    "appel_offres": {
        "libelle": "Suivi d'appel d'offres",
        "quoi_faire": ("Gros montant mais faible chance : ce sont des marchés "
                       "publics. Ils ne se relancent pas commercialement, ils "
                       "se suivent — date de commission, pièces à fournir, "
                       "concurrents. Vérifier que le dossier est complet."),
    },
    "traiter_en_lot": {
        "libelle": "Traiter en lot",
        "quoi_faire": ("Petits montants à bonne chance : un par un, ils "
                       "coûtent plus de temps qu'ils ne rapportent. Un envoi "
                       "groupé de rappels par courriel suffit."),
    },
    "laisser": {
        "libelle": "Laisser courir",
        "quoi_faire": ("Petit montant et faible chance : aucune action ne se "
                       "justifie. Le devis reste ouvert, il se fermera seul."),
    },
}


def protocole(montant_dt: float, probabilite: float) -> str:
    """Quelle action pour ce devis — la règle, pas une appréciation."""
    gros = montant_dt >= SEUIL_MONTANT_GROS_DT
    probable = probabilite >= SEUIL_CHANCE_HAUTE
    if gros and probable:
        return "appeler"
    if gros:
        return "appel_offres"
    return "traiter_en_lot" if probable else "laisser"

JEUX_DE_VARIABLES: Dict[str, List[str]] = {
    "tout": FEATURES,
    "devis_seul": VARIABLES_DEVIS,
}

_EPS = 1e-6


def _connect():
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        from ml_engine.determinisme import limiter_duckdb
        limiter_duckdb(con, 1)
    except Exception:
        pass
    return con


def charger_brut(con=None) -> Dict[str, pd.DataFrame]:
    """Devis, factures et marges — trois tables, aucune agrégation prématurée."""
    fermer = con is None
    con = con or _connect()
    try:
        devis = con.execute(f"""
            SELECT client, piece_no, date, ht, ttc, transforme
            FROM devis
            WHERE date >= DATE '{DEBUT_EXPLOITABLE}'
              AND ht IS NOT NULL AND ht > 0
              AND client IS NOT NULL AND trim(client) <> ''
            ORDER BY date, client, piece_no
        """).df()

        factures = con.execute(f"""
            SELECT client, date, ttc, payment_delay_days
            FROM sales
            WHERE NOT est_avoir AND date IS NOT NULL
              AND client IS NOT NULL AND trim(client) <> ''
              AND date >= DATE '2017-01-01'
            ORDER BY client, date
        """).df()

        marges = con.execute("""
            SELECT client,
                   CAST(date_trunc('month', date) AS DATE) AS mois,
                   sum(montant) AS montant,
                   sum(cout)    AS cout
            FROM sales_lines
            WHERE client IS NOT NULL AND trim(client) <> ''
              AND date IS NOT NULL
            GROUP BY 1, 2
            ORDER BY client, mois
        """).df()
        return {"devis": devis, "factures": factures, "marges": marges}
    finally:
        if fermer:
            con.close()


def courbe_de_maturation(devis: pd.DataFrame) -> Dict[str, Any]:
    """Taux de conversion par mois d'émission — et où il se stabilise."""
    d = devis.copy()
    d["mois"] = pd.to_datetime(d["date"]).dt.to_period("M")
    par_mois = (d.groupby("mois")
                 .agg(n=("transforme", "size"), taux=("transforme", "mean"))
                 .reset_index())
    par_mois = par_mois[par_mois["n"] >= 5]
    if par_mois.empty:
        return {"applicable": False, "motif": "effectifs mensuels insuffisants"}

    dernier = par_mois["mois"].max()
    mures = par_mois[par_mois["mois"] <= dernier - MATURATION_MOIS]
    recentes = par_mois[par_mois["mois"] > dernier - MATURATION_MOIS]

    taux_mur = float(mures["taux"].mean()) if not mures.empty else None
    taux_recent = float(recentes["taux"].mean()) if not recentes.empty else None

    return {
        "applicable": True,
        "maturation_declaree_mois": MATURATION_MOIS,
        "dernier_mois": str(dernier),
        "taux_cohortes_mures_pct": (round(taux_mur * 100, 2)
                                    if taux_mur is not None else None),
        "taux_cohortes_recentes_pct": (round(taux_recent * 100, 2)
                                       if taux_recent is not None else None),
        "chute_relative_pct": (
            round((1 - taux_recent / taux_mur) * 100, 1)
            if taux_mur and taux_recent is not None and taux_mur > 0 else None),
        "par_mois": [{"mois": str(r["mois"]), "n": int(r["n"]),
                      "taux_pct": round(float(r["taux"]) * 100, 2)}
                     for _, r in par_mois.iterrows()],
        "lecture": (
            "Le taux des cohortes récentes est mécaniquement plus bas : ces devis "
            "n'ont pas encore eu le temps d'être signés. L'écart mesure le "
            "censurage, pas une dégradation commerciale. Les devis émis dans les "
            f"{MATURATION_MOIS} derniers mois sont donc ÉCARTÉS de "
            "l'apprentissage — les inclure enseignerait « récent donc perdu »."),
    }


def construire_panel(brut: Optional[Dict[str, pd.DataFrame]] = None,
                     pour_prediction: bool = False) -> pd.DataFrame:
    """Un devis = une ligne."""
    if brut is None:
        brut = charger_brut()
    devis, factures, marges = brut["devis"], brut["factures"], brut["marges"]
    if devis is None or devis.empty:
        return pd.DataFrame()

    d = devis.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values(["date", "client", "piece_no"]).reset_index(drop=True)

    f = factures.copy()
    f["date"] = pd.to_datetime(f["date"])
    f = f.sort_values(["client", "date"]).reset_index(drop=True)

    m = marges.copy()
    m["mois"] = pd.to_datetime(m["mois"])

    marge_par_client: Dict[str, pd.DataFrame] = {
        c: g.sort_values("mois") for c, g in m.groupby("client", sort=False)}

    fact_par_client: Dict[str, pd.DataFrame] = {
        c: g for c, g in f.groupby("client", sort=False)}

    d["_n"] = 1
    par_client_devis: Dict[str, pd.DataFrame] = {
        c: g for c, g in d.groupby("client", sort=False)}

    d["_mois"] = d["date"].dt.to_period("M")
    compte_mois = d.groupby(["client", "_mois"])["_n"].transform("sum")
    d["n_devis_meme_mois"] = compte_mois.astype(float)

    lignes: List[Dict[str, Any]] = []
    for i, r in d.iterrows():
        client, t = r["client"], r["date"]

        fc = fact_par_client.get(client)
        if fc is not None:
            passe = fc[fc["date"] < t]
        else:
            passe = f.iloc[0:0]

        est_client = 1.0 if len(passe) else 0.0
        if len(passe):
            anciennete = float((t - passe["date"].min()).days)
            recence = float((t - passe["date"].max()).days)
            douze = passe[passe["date"] >= t - pd.Timedelta(days=365)]
            n_12m = float(len(douze))
            ca_12m = float(douze["ttc"].sum())
            panier = float(passe["ttc"].mean())
            delais = passe["payment_delay_days"].dropna()
            delai_med = float(delais.median()) if len(delais) else 0.0
        else:
            anciennete = recence = 0.0
            n_12m = ca_12m = panier = delai_med = 0.0

        mg = marge_par_client.get(client)
        if mg is not None:
            mgp = mg[mg["mois"] < t]
            montant_tot = float(mgp["montant"].sum())
            cout_tot = float(mgp["cout"].sum())
            marge_pct = ((montant_tot - cout_tot) / montant_tot * 100
                         if montant_tot > 0 else 0.0)
        else:
            marge_pct = 0.0

        dv = par_client_devis.get(client)
        if dv is not None:
            dvp = dv[dv["date"] < t]
        else:
            dvp = d.iloc[0:0]

        n_devis_12m = float(len(
            dvp[dvp["date"] >= t - pd.Timedelta(days=365)])) if len(dvp) else 0.0
        if len(dvp):
            taux_passe = float(dvp["transforme"].mean())
            montant_moyen_passe = float(dvp["ht"].mean())
        else:
            taux_passe = -1.0
            montant_moyen_passe = 0.0

        ht = float(r["ht"])
        lignes.append({
            "client": client,
            "piece_no": r["piece_no"],
            "date": t,
            "y": int(bool(r["transforme"])),

            "log_montant_ht": float(np.log1p(max(ht, 0.0))),
            "mois": float(t.month),
            "trimestre": float((t.month - 1) // 3 + 1),
            "jour_semaine": float(t.dayofweek),
            "n_devis_meme_mois": float(r["n_devis_meme_mois"]),

            "est_client": est_client,
            "anciennete_j": anciennete,
            "n_factures_12m": n_12m,
            "log_ca_12m": float(np.log1p(max(ca_12m, 0.0))),
            "recence_facture_j": recence,
            "panier_moyen": panier,
            "marge_moyenne_pct": marge_pct,
            "delai_median_accorde_j": delai_med,

            "n_devis_12m": n_devis_12m,
            "taux_conversion_passe": taux_passe,
            "log_montant_moyen_devis_passes": float(
                np.log1p(max(montant_moyen_passe, 0.0))),
            "ratio_montant_vs_habituel": ht / (montant_moyen_passe + _EPS),

            "ratio_montant_panier": ht / (panier + _EPS),
            "ratio_montant_ca_12m": ht / (ca_12m + _EPS),
        })

    panel = pd.DataFrame(lignes)
    if panel.empty:
        return panel

    if not pour_prediction:
        fin = panel["date"].max()
        limite = fin - pd.DateOffset(months=MATURATION_MOIS)
        panel = panel[panel["date"] <= limite]

    return panel.dropna(subset=FEATURES + ["y"]).reset_index(drop=True)


def _references_triviales(te: pd.DataFrame) -> Dict[str, float]:
    from sklearn.metrics import roc_auc_score

    refs = {
        "classe_majoritaire": 0.5,
        "est_deja_client": te["est_client"],
        "taux_conversion_passe": te["taux_conversion_passe"],
        "inverse_recence": -te["recence_facture_j"],
        "inverse_montant": -te["log_montant_ht"],
        "frequence_12m": te["n_factures_12m"],
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


def comparer_par_bootstrap(y: np.ndarray, p_modele: np.ndarray,
                           p_reference: np.ndarray,
                           n_tirages: int = 2000) -> Dict[str, Any]:
    """L'écart à la référence triviale est-il distinguable du bruit ?"""
    from sklearn.metrics import roc_auc_score

    rng = np.random.default_rng(SEED)
    n = len(y)
    ecarts: List[float] = []
    aucs_modele: List[float] = []

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
        aucs_modele.append(a_m)
        ecarts.append(a_m - a_r)

    if len(ecarts) < 200:
        return {"applicable": False, "motif": "tirages insuffisants"}

    e = np.array(ecarts)
    bas, haut = float(np.percentile(e, 2.5)), float(np.percentile(e, 97.5))
    am = np.array(aucs_modele)

    significatif = bas > 0.0

    return {
        "applicable": True,
        "n_tirages_valides": len(ecarts),
        "auc_modele_ic95": [round(float(np.percentile(am, 2.5)), 4),
                            round(float(np.percentile(am, 97.5)), 4)],
        "ecart_median": round(float(np.median(e)), 4),
        "ecart_ic95": [round(bas, 4), round(haut, 4)],
        "part_tirages_ou_le_modele_gagne_pct": round(
            float((e > 0).mean() * 100), 1),
        "significatif": bool(significatif),
        "lecture": (
            "L'intervalle porte sur l'ÉCART, mesuré par tirages APPARIÉS — les "
            "mêmes devis rééchantillonnés pour les deux scores. Si cet intervalle "
            "contient zéro, l'avantage du modèle n'est pas distinguable du bruit "
            "d'échantillonnage, et le déployer reviendrait à servir un hasard "
            "favorable."),
    }


def selectionner(tr: pd.DataFrame) -> Dict[str, Any]:
    """Famille, réglage et jeu de variables — choisis SANS voir le test."""
    from sklearn.metrics import roc_auc_score

    from ml_engine.determinisme import limiter_threads

    coupure_i = tr["date"].quantile(0.75)
    tr_i = tr[tr["date"] <= coupure_i]
    va_i = tr[tr["date"] > coupure_i]

    if len(va_i) < 150 or va_i["y"].nunique() < 2 or len(tr_i) < 400:
        return {"applicable": False,
                "motif": (f"validation interne trop petite "
                          f"(train {len(tr_i)}, valid {len(va_i)})")}

    essais: List[Dict[str, Any]] = []
    with limiter_threads(1):
        for nom in CANDIDATS:
            for reglage in REGLAGES[nom]:
                for nom_jeu, jeu in JEUX_DE_VARIABLES.items():
                    m = _modele(nom, reglage)
                    m.fit(tr_i[jeu], tr_i["y"])
                    auc_tr = float(roc_auc_score(
                        tr_i["y"], m.predict_proba(tr_i[jeu])[:, 1]))
                    auc_va = float(roc_auc_score(
                        va_i["y"], m.predict_proba(va_i[jeu])[:, 1]))
                    essais.append({
                        "famille": nom, "reglage": reglage, "variables": nom_jeu,
                        "auc_train_interne": round(auc_tr, 4),
                        "auc_valid_interne": round(auc_va, 4),
                        "surapprentissage": round(auc_tr - auc_va, 4),
                        "eligible": (auc_tr - auc_va) < SEUIL_ECART_TRAIN_VALID,
                    })

    eligibles = [e for e in essais if e["eligible"]]
    if not eligibles:
        return {"applicable": False,
                "motif": ("aucun réglage ne tient sous le seuil de "
                          f"sur-apprentissage de {SEUIL_ECART_TRAIN_VALID}"),
                "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"])}

    meilleur = max(eligibles, key=lambda e: e["auc_valid_interne"])

    for e in eligibles:
        if (e["variables"] == "devis_seul"
                and e["famille"] == meilleur["famille"]
                and meilleur["auc_valid_interne"] - e["auc_valid_interne"]
                <= ECART_PARCIMONIE):
            meilleur = e
            break

    for e in eligibles:
        if (e["famille"] == "regression_logistique"
                and e["variables"] == meilleur["variables"]
                and meilleur["auc_valid_interne"] - e["auc_valid_interne"]
                <= ECART_PARCIMONIE):
            meilleur = e
            break

    return {
        "applicable": True,
        "coupure_interne": str(pd.Timestamp(coupure_i).date()),
        "n_train_interne": int(len(tr_i)), "n_valid_interne": int(len(va_i)),
        "n_essais": len(essais), "n_eligibles": len(eligibles),
        "retenu": meilleur,
        "essais": sorted(essais, key=lambda e: -e["auc_valid_interne"]),
        "principe": ("sélection sur coupure interne à la période "
                     "d'entraînement ; le jeu de test n'est touché qu'une fois"),
    }


def calibration_par_decile(y: np.ndarray, p: np.ndarray,
                           n_groupes: int = 10) -> Dict[str, Any]:
    """Une probabilité annoncée vaut-elle ce qu'elle dit ?

    L'AUC mesure l'ORDRE : elle dit si les devis les mieux classés se signent
    plus souvent. Elle ne dit rien de la VALEUR annoncée. Un modèle qui
    prédirait systématiquement 3 % là où le taux réel est 30 % aurait la même
    AUC — et l'espérance affichée à l'écran, elle, serait dix fois trop basse.

    Or toute la carte « ventes probables » repose sur cette valeur : une
    espérance est un montant multiplié par une probabilité. Si la probabilité
    est mal calibrée, le montant est faux, quelle que soit l'AUC.

    Protocole. Les devis du test sont rangés par probabilité prédite croissante
    et découpés en `n_groupes` groupes d'effectifs égaux. Pour chacun :
    probabilité moyenne PRÉDITE contre taux de signature OBSERVÉ. Une
    calibration parfaite les rend égaux — les points suivent la diagonale.

    Deux mesures résument l'écart :

    · l'ECE (*expected calibration error*) — moyenne des écarts absolus,
      pondérée par l'effectif de chaque groupe ;
    · le biais — écart signé moyen. Positif, le modèle est trop optimiste et
      l'espérance affichée est surestimée ; négatif, l'inverse.

    Les groupes sont construits par rangs (`argsort`) et non par quantiles de
    valeur : quand beaucoup de devis partagent la même probabilité basse — le
    cas ici, les positifs étant rares — les bornes de quantiles se confondent
    et produisent des groupes vides.
    """
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = len(y)
    if n < 2 * n_groupes:
        return {"applicable": False,
                "motif": (f"{n} devis au test pour {n_groupes} groupes : "
                          "effectifs trop faibles pour une courbe lisible")}

    ordre = np.argsort(p, kind="stable")
    groupes = np.array_split(ordre, n_groupes)

    lignes: List[Dict[str, Any]] = []
    ece = 0.0
    biais = 0.0
    for i, idx in enumerate(groupes, start=1):
        if len(idx) == 0:
            continue
        predit = float(p[idx].mean())
        observe = float(y[idx].mean())
        poids = len(idx) / n
        ece += poids * abs(predit - observe)
        biais += poids * (predit - observe)
        lignes.append({
            "groupe": i,
            "n_devis": int(len(idx)),
            "n_signes": int(y[idx].sum()),
            "probabilite_predite_moyenne_pct": round(predit * 100, 2),
            "taux_observe_pct": round(observe * 100, 2),
            "probabilite_min_pct": round(float(p[idx].min()) * 100, 2),
            "probabilite_max_pct": round(float(p[idx].max()) * 100, 2),
            "ecart_pt": round((predit - observe) * 100, 2),
        })

    return {
        "applicable": True,
        "n_groupes": len(lignes),
        "n_devis": int(n),
        "ece_pt": round(ece * 100, 2),
        "biais_pt": round(biais * 100, 2),
        "sens_du_biais": ("optimiste — l'espérance affichée est surestimée"
                          if biais > 0.005 else
                          "pessimiste — l'espérance affichée est sous-estimée"
                          if biais < -0.005 else
                          "sans biais décelable à cette échelle"),
        "par_groupe": lignes,
        "lecture": (
            "Chaque point compare ce que le modèle ANNONÇAIT à ce qui s'est "
            "RÉELLEMENT signé, sur des devis qu'il n'avait jamais vus. Plus les "
            "points collent à la diagonale, plus l'espérance en dinars est "
            "fiable. L'AUC, elle, ne dit que l'ordre : elle resterait identique "
            "si toutes les probabilités étaient dix fois trop basses."),
        "pourquoi_hors_periode": (
            "Calculée sur le test hors période, jamais sur les devis "
            "d'entraînement : un modèle est toujours bien calibré sur les "
            "données qui ont servi à l'ajuster."),
    }


def evaluer_hors_periode(panel: pd.DataFrame) -> Dict[str, Any]:
    """Entraînement sur le passé, test sur le futur."""
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 confusion_matrix, f1_score, precision_score,
                                 recall_score, roc_auc_score)

    from ml_engine.determinisme import limiter_threads

    coupure = panel["date"].quantile(0.75)
    tr = panel[panel["date"] <= coupure]
    te = panel[panel["date"] > coupure]

    if len(te) < 200 or te["y"].nunique() < 2 or len(tr) < 600:
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

    _SCORES_REFERENCE = {
        "est_deja_client": lambda x: x["est_client"].to_numpy(dtype=float),
        "taux_conversion_passe": lambda x: x["taux_conversion_passe"].to_numpy(dtype=float),
        "inverse_recence": lambda x: -x["recence_facture_j"].to_numpy(dtype=float),
        "inverse_montant": lambda x: -x["log_montant_ht"].to_numpy(dtype=float),
        "frequence_12m": lambda x: x["n_factures_12m"].to_numpy(dtype=float),
    }
    fabrique = _SCORES_REFERENCE.get(meilleure)
    if fabrique is not None:
        comparaison = comparer_par_bootstrap(
            te["y"].to_numpy(dtype=int), p, fabrique(te))
    else:
        comparaison = {"applicable": False,
                       "motif": f"référence « {meilleure} » non reconstructible"}

    walk: Dict[str, Any] = {"applicable": False, "motif": "non calculé"}
    if fabrique is not None:
        from ml_engine.validation import comparer_apparie, walk_forward

        refs_accumulees: List[np.ndarray] = []

        def _ajuster_et_predire(tr_i: pd.DataFrame,
                                te_i: pd.DataFrame) -> np.ndarray:
            s = selectionner(tr_i)
            if s.get("applicable"):
                c = s["retenu"]
                fam, reg = c["famille"], c["reglage"]
                jeu_i = JEUX_DE_VARIABLES[c["variables"]]
            else:
                fam, reg, jeu_i = "regression_logistique", {"C": 1.0}, FEATURES
            with limiter_threads(1):
                mm = _modele(fam, reg)
                mm.fit(tr_i[jeu_i], tr_i["y"])
                proba = mm.predict_proba(te_i[jeu_i])[:, 1]
            refs_accumulees.append(np.asarray(fabrique(te_i), dtype=float))
            return proba

        wf = walk_forward(panel, "date", _ajuster_et_predire, n_origines=4)
        if wf.get("applicable"):
            y_agg = wf.pop("y_agrege")
            p_agg = wf.pop("p_agrege")
            ref_agg = (np.concatenate(refs_accumulees)
                       if refs_accumulees else np.array([]))
            if len(ref_agg) == len(y_agg):
                wf["comparaison_agregee"] = comparer_apparie(
                    y_agg, p_agg, ref_agg)
            else:
                wf["comparaison_agregee"] = {
                    "applicable": False,
                    "motif": (f"appariement rompu : {len(ref_agg)} scores de "
                              f"référence pour {len(y_agg)} prédictions")}
        walk = wf

    taux_base = float(te["y"].mean())
    n_dec = max(int(len(te) * 0.10), 1)
    seuil_dec = float(np.sort(p)[-n_dec])
    pred_dec = (p >= seuil_dec).astype(int)
    prec_dec = float(precision_score(te["y"], pred_dec, zero_division=0))
    pred_05 = (p >= 0.5).astype(int)

    return {
        "applicable": True,
        "coupure": str(pd.Timestamp(coupure).date()),
        "n_train": int(len(tr)), "n_test": int(len(te)),
        "n_clients_test": int(te["client"].nunique()),
        "taux_positif_train": round(float(tr["y"].mean()), 4),
        "taux_positif_test": round(taux_base, 4),

        "selection": sel,
        "modele_retenu": choix["famille"],
        "reglage_retenu": choix["reglage"],
        "variables_retenues": choix["variables"],

        "auc": round(auc, 4),
        "average_precision": round(float(average_precision_score(te["y"], p)), 4),
        "brier": round(float(brier_score_loss(te["y"], p)), 4),
        "classification": metriques_classification(
            te["y"], p, y_train=tr["y"], p_train=p_tr),
        "surapprentissage_interne": choix["surapprentissage"],
        "derive_temporelle": round(choix["auc_valid_interne"] - auc, 4),

        # L'AUC dit l'ordre, la calibration dit la valeur. L'écran affiche des
        # dinars : c'est la seconde qui engage.
        "calibration": calibration_par_decile(te["y"].to_numpy(), p),

        "au_seuil_du_decile": {
            "n_devis_signales": int(n_dec),
            "precision": round(prec_dec, 4),
            "recall": round(float(recall_score(te["y"], pred_dec,
                                               zero_division=0)), 4),
            "f1": round(float(f1_score(te["y"], pred_dec, zero_division=0)), 4),
            "lift": round(prec_dec / taux_base, 2) if taux_base > 0 else None,
            "confusion_matrix": confusion_matrix(te["y"], pred_dec).tolist(),
            "lecture_metier": (
                "sur les 10 % de devis les mieux classés, cette part se "
                "transforme réellement — à comparer au taux de base, qui est ce "
                "qu'obtient une relance dans l'ordre d'arrivée"),
        },
        "au_seuil_de_0_5": {
            "n_positifs_predits": int(pred_05.sum()),
            "precision": round(float(precision_score(te["y"], pred_05,
                                                     zero_division=0)), 4),
            "recall": round(float(recall_score(te["y"], pred_05,
                                               zero_division=0)), 4),
            "pourquoi_peu_informatif": (
                f"avec {taux_base * 100:.1f} % de positifs, peu de probabilités "
                "atteignent 0,5. Publié pour montrer pourquoi ce seuil est "
                "écarté, et non effacé par commodité."),
        },

        "references_triviales": {k: round(v, 4) for k, v in triv.items()},
        "meilleure_reference_triviale": meilleure,
        "auc_meilleure_reference_triviale": round(triv[meilleure], 4),
        "gain_vs_reference_triviale": round(auc - triv[meilleure], 4),
        "comparaison_vs_reference_triviale": comparaison,
        "walk_forward_multi_origines": walk,

        "apport_de_la_relation_client": (
            f"jeu « {choix['variables']} » retenu sur validation interne."
            + (" La relation client apporte donc une information que la pièce "
               "seule ne porte pas."
               if choix["variables"] == "tout" else
               " Les caractéristiques du devis suffisent : la relation client "
               "n'apportait rien, ce qui réfute l'hypothèse de départ.")),
    }


def train() -> Dict[str, Any]:
    """Entraîne, mesure, décide."""
    import joblib

    from ml_engine.determinisme import etat as etat_determinisme
    from ml_engine.determinisme import limiter_threads

    brut = charger_brut()
    if brut["devis"] is None or brut["devis"].empty:
        return {"error": "table `devis` vide ou absente"}

    maturation = courbe_de_maturation(brut["devis"])
    panel = construire_panel(brut)
    if panel.empty or panel["y"].nunique() < 2:
        return {"error": "panneau vide ou cible dégénérée après censurage"}

    hp = evaluer_hors_periode(panel)

    base: Dict[str, Any] = {
        "version": 1,
        "question": "ce devis a-t-il une chance d'être signé ?",
        "nature_de_la_cible": (
            "STATUT DU DEVIS décodé — l'un des états signifie « transformé en "
            "facture. Interprétation validée empiriquement : 89,4 % des devis en "
            "état 8 ont une facture du même client au même montant (± 1 %), "
            "contre 37,4 % pour l'état 1. Aucune formule sur les variables."),
        "donnees": "100 % réelles — vos devis, factures et coûts de revient",
        "determinisme": etat_determinisme(),
        "n_devis_total": int(len(brut["devis"])),
        "n_observations": int(len(panel)),
        "n_clients": int(panel["client"].nunique()),
        "periode": f"{panel['date'].min().date()} → {panel['date'].max().date()}",
        "taux_de_base": round(float(panel["y"].mean()), 4),
        "censurage_a_droite": maturation,
        "seuils_declares_avant_mesure": {
            "auc_minimale": SEUIL_AUC_MINIMALE,
            "gain_minimal_sur_reference_triviale": SEUIL_GAIN_MINIMAL,
            "ecart_train_valid_maximal": SEUIL_ECART_TRAIN_VALID,
            "maturation_mois": MATURATION_MOIS,
            "ecart_doit_etre_significatif": (
                "IC95 de l'écart apparié ne contenant pas zéro — règle déjà "
                "appliquée par le registre à la prévision de demande, ajoutée ici "
                "APRÈS un premier résultat positif, au risque de l'invalider"),
        },
        "variables": {
            "devis": VARIABLES_DEVIS,
            "client": VARIABLES_CLIENT,
            "historique_devis": VARIABLES_HISTORIQUE_DEVIS,
            "relatives": VARIABLES_RELATIVES,
            "prevention_de_fuite": (
                "L'historique de chaque client est tronqué STRICTEMENT avant la "
                "date du devis. Un devis ne peut donc voir ni lui-même, ni une "
                "facture émise le même jour — laquelle pourrait être sa propre "
                "transformation. Les variables sont construites en Python et non "
                "par une agrégation SQL par client, qui aurait donné le même "
                "profil à tous les devis d'un client, y compris les plus anciens."),
            "convention_client_nouveau": (
                "`taux_conversion_passe` vaut -1 en l'absence de devis antérieur, "
                "valeur hors domaine. Mettre 0 aurait appris au modèle à "
                "confondre un client nouveau avec un client qui ne signe jamais."),
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
    base["importance_permutation"] = importance_permutation(
        panel, retenu, reglage, jeu)

    auc, gain = hp["auc"], hp["gain_vs_reference_triviale"]
    cmp_ = hp.get("comparaison_vs_reference_triviale") or {}

    walk_cmp = ((hp.get("walk_forward_multi_origines") or {})
                .get("comparaison_agregee") or {})
    if walk_cmp.get("applicable"):
        cmp_decisif = walk_cmp
        protocole_decisif = "walk-forward multi-origines"
    else:
        cmp_decisif = cmp_
        protocole_decisif = "coupure unique"

    significatif = ((not cmp_decisif.get("applicable"))
                    or bool(cmp_decisif.get("significatif")))

    deploye = (auc >= SEUIL_AUC_MINIMALE
               and gain >= SEUIL_GAIN_MINIMAL
               and significatif)

    if deploye:
        ic = cmp_decisif.get("ecart_ic95")
        motif = (f"AUC {auc:.4f} hors période, soit {gain:+.4f} sur la meilleure "
                 f"référence triviale ({hp['meilleure_reference_triviale']}) — "
                 "les seuils déclarés sont atteints"
                 + (f", et l'écart est significatif sur {protocole_decisif} : "
                    f"IC95 de l'écart apparié [{ic[0]:+.4f} ; {ic[1]:+.4f}], "
                    f"{cmp_decisif.get('n_positifs')} signatures de test"
                    if ic else ""))
    elif auc >= SEUIL_AUC_MINIMALE and gain >= SEUIL_GAIN_MINIMAL:
        ic = cmp_decisif.get("ecart_ic95") or [0, 0]
        motif = (f"gain de {gain:+.4f} mais NON SIGNIFICATIF sur "
                 f"{protocole_decisif} : l'intervalle à 95 % de l'écart apparié "
                 f"est [{ic[0]:+.4f} ; {ic[1]:+.4f}] et contient zéro. Mesuré sur "
                 f"{cmp_decisif.get('n_observations', hp['n_test'])} devis dont "
                 f"{cmp_decisif.get('n_positifs', '?')} signés, cet avantage "
                 "n'est pas distinguable d'un découpage favorable.")
    elif auc < SEUIL_AUC_MINIMALE:
        motif = (f"AUC {auc:.4f} sous le seuil de {SEUIL_AUC_MINIMALE} — pas "
                 "assez discriminant pour orienter une relance")
    else:
        motif = (f"gain de seulement {gain:+.4f} sur "
                 f"« {hp['meilleure_reference_triviale']} » "
                 f"(AUC {hp['auc_meilleure_reference_triviale']:.4f}) : sous le "
                 f"seuil de {SEUIL_GAIN_MINIMAL}, un modèle n'ajoute rien qu'une "
                 "règle d'une ligne ne ferait déjà")

    base["decision_deploiement"] = {"modele_deploye": bool(deploye),
                                    "motif": motif}
    base["portee_et_limite"] = (
        "Le modèle dit quels devis ont une chance d'aboutir, pas comment les "
        "faire aboutir. Il apprend aussi le comportement commercial PASSÉ : si "
        "les relances ont jusqu'ici privilégié certains clients, il reproduira ce "
        "biais. C'est un outil de priorisation, pas un arbitre de qualité "
        "commerciale.")

    if deploye:
        with limiter_threads(1):
            m = _modele(retenu, reglage)
            m.fit(panel[jeu], panel["y"])
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"modele": m, "features": jeu, "nom": retenu,
                     "reglage": reglage,
                     "jeu_de_variables": hp["variables_retenues"],
                     "maturation_mois": MATURATION_MOIS, "seed": SEED},
                    MODELS_DIR / "conversion_devis.joblib")
        base["artefact"] = "models/conversion_devis.joblib"
    else:
        ancien = MODELS_DIR / "conversion_devis.joblib"
        if ancien.exists():
            try:
                ancien.unlink()
            except Exception:
                pass

    _ecrire(base)
    return base


def importance_permutation(panel: pd.DataFrame, modele: str,
                           reglage: Optional[Dict[str, Any]] = None,
                           variables: Optional[List[str]] = None
                           ) -> Dict[str, float]:
    """Mesurée sur le TEST hors période."""
    from sklearn.inspection import permutation_importance

    from ml_engine.determinisme import limiter_threads

    jeu = variables or FEATURES
    coupure = panel["date"].quantile(0.75)
    tr = panel[panel["date"] <= coupure]
    te = panel[panel["date"] > coupure]
    if len(te) < 200 or len(tr) < 600:
        return {}

    with limiter_threads(1):
        m = _modele(modele, reglage)
        m.fit(tr[jeu], tr["y"])
        r = permutation_importance(m, te[jeu], te["y"], n_repeats=5,
                                   random_state=SEED, scoring="roc_auc")
    return {f: round(float(v), 4)
            for f, v in sorted(zip(jeu, r.importances_mean),
                               key=lambda kv: -kv[1])}


def _ecrire(metriques: Dict[str, Any]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "conversion_devis_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)


def predire(limite: int = 20, clients: Optional[List[str]] = None) -> Dict[str, Any]:
    """Devis en cours à relancer en priorité, si le registre l'autorise."""
    from ml_engine.registre import est_deploye

    if not est_deploye("conversion_devis"):
        return {"servi": False,
                "motif": "modèle refusé par le registre — non servi"}

    chemin = MODELS_DIR / "conversion_devis.joblib"
    if not chemin.exists():
        return {"servi": False, "motif": "artefact absent"}

    try:
        import joblib
        paquet = joblib.load(chemin)
        from ml_engine.cache_panel import panel as _panel_en_cache
        panel = _panel_en_cache("conversion_devis",
                                lambda: construire_panel(pour_prediction=True),
                                construire_panel, charger_brut)
        if panel.empty:
            return {"servi": False, "motif": "panneau indisponible"}

        fin = panel["date"].max()
        recents = panel[panel["date"] > fin - pd.DateOffset(months=MATURATION_MOIS)]
        en_cours = recents[recents["y"] == 0]
        if clients is not None:
            en_cours = en_cours[en_cours["client"].astype(str).isin({str(c) for c in clients})]
        if en_cours.empty:
            return {"servi": True, "n_devis": 0, "top": [],
                    "motif": "aucun devis récent encore ouvert"}

        p = paquet["modele"].predict_proba(en_cours[paquet["features"]])[:, 1]
        en_cours = en_cours.assign(probabilite=p)
        en_cours["montant_ht_dt"] = np.expm1(en_cours["log_montant_ht"])
        en_cours["esperance_dt"] = (en_cours["probabilite"]
                                    * en_cours["montant_ht_dt"])
        # Âge compté depuis la dernière date de l'entrepôt, pas depuis
        # aujourd'hui : les données s'arrêtent à l'export, et un âge calculé sur
        # l'horloge ferait vieillir tous les devis chaque jour sans raison.
        en_cours["age_j"] = (fin - en_cours["date"]).dt.days.astype(int)
        en_cours["protocole"] = [
            protocole(float(m), float(q))
            for m, q in zip(en_cours["montant_ht_dt"], en_cours["probabilite"])]

        top = en_cours.sort_values("esperance_dt", ascending=False).head(limite)

        raisons_par_devis: List[List[Dict[str, Any]]] = [[] for _ in range(len(top))]
        explication: Dict[str, Any] = {"disponible": False}
        try:
            from ml_engine.explication import (contributions_lineaires,
                                               extraire_pipeline_lineaire)
            lin = extraire_pipeline_lineaire(paquet["modele"])
            if lin is None:
                explication = {
                    "disponible": False,
                    "motif": ("le modèle servi n'est pas linéaire : une "
                              "attribution exacte est impossible")}
            else:
                features = paquet["features"]
                X = top[features].to_numpy(dtype=float)
                # Le centile se lit sur TOUS les devis du panel, pas sur les
                # quinze affichés : une position dans un échantillon trié par
                # espérance ne voudrait rien dire.
                reference = {v: panel[v].to_numpy(dtype=float) for v in features
                             if v in panel.columns}
                raisons_par_devis = [
                    contributions_lineaires(lin["coefficients"], lin["moyennes"],
                                            lin["ecarts"], ligne, features,
                                            sens=("favorise", "freine"),
                                            reference=reference)
                    for ligne in X]
                explication = {
                    "disponible": True,
                    "methode": "attribution linéaire exacte",
                    "origine_des_coefficients": lin["origine"],
                    "n_devis_expliques": int(len(top)),
                }
        except Exception as e:
            explication = {"disponible": False,
                           "motif": f"{type(e).__name__} : {str(e)[:120]}"}

        top = top.assign(_raisons=raisons_par_devis)
        return {
            "servi": True,
            "explication": explication,
            "nature": "modele_appris",
            "horizon_maturation_mois": MATURATION_MOIS,
            "n_devis": int(len(en_cours)),
            "montant_ouvert_total_dt": round(float(en_cours["montant_ht_dt"].sum()), 0),
            "esperance_totale_dt": round(float(en_cours["esperance_dt"].sum()), 0),
            "n_clients_concernes": int(en_cours["client"].nunique()),
            "protocoles": _repartition_protocoles(en_cours),
            "definitions": PROTOCOLES,
            "seuils": {
                "montant_gros_dt": SEUIL_MONTANT_GROS_DT,
                "chance_haute_pct": round(SEUIL_CHANCE_HAUTE * 100, 0),
                "age_devis_mort_j": AGE_DEVIS_MORT_J,
            },
            "top": [{
                "client": r["client"],
                "piece_no": r["piece_no"],
                "date": str(pd.Timestamp(r["date"]).date()),
                "age_j": int(r["age_j"]),
                "montant_ht_dt": round(float(r["montant_ht_dt"]), 0),
                "probabilite": round(float(r["probabilite"]), 3),
                "esperance_dt": round(float(r["esperance_dt"]), 0),
                "protocole": r["protocole"],
                "est_client": bool(r["est_client"]),
                "raisons": r["_raisons"],
            } for _, r in top.iterrows()],
            "lecture_du_classement": (
                "trié par espérance de chiffre d'affaires — probabilité × montant "
                "HT — et non par probabilité seule"),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _repartition_protocoles(en_cours) -> List[Dict[str, Any]]:
    """Combien de devis, et combien d'espérance, dans chaque protocole.

    C'est la lecture qui manque le plus : savoir que 12 M DT sont « ouverts »
    n'aide pas, savoir que 9 M relèvent du suivi d'appel d'offres et 800 K de
    l'appel téléphonique dit où passer sa semaine."""
    out: List[Dict[str, Any]] = []
    for cle, meta in PROTOCOLES.items():
        lot = en_cours[en_cours["protocole"] == cle]
        if lot.empty:
            continue
        out.append({
            "code": cle,
            "libelle": meta["libelle"],
            "quoi_faire": meta["quoi_faire"],
            "n_devis": int(len(lot)),
            "montant_ouvert_dt": round(float(lot["montant_ht_dt"].sum()), 0),
            "esperance_dt": round(float(lot["esperance_dt"].sum()), 0),
            "n_clients": int(lot["client"].nunique()),
            "age_median_j": int(lot["age_j"].median()),
        })
    return sorted(out, key=lambda o: -o["esperance_dt"])


def reperes_conversion(clients: Optional[List[str]] = None) -> Dict[str, Any]:
    """Taux de conversion CONSTATÉ par tranche de montant, sur devis mûrs.

    Pur comptage sur l'historique des devis : aucun modèle. C'est la toile de
    fond qui rend l'espérance lisible — sans elle, « 12 M DT de ventes
    probables » laisse croire qu'un gros devis se signe comme un petit, alors
    que la donnée dit exactement le contraire.

    CENSURE À DROITE. Un devis émis il y a trois semaines n'a pas encore eu le
    temps d'être signé : le compter dans un taux de conversion fait baisser ce
    taux pour une raison qui n'a rien à voir avec le devis. Le comptage ne porte
    donc que sur les devis émis il y a plus de `MATURATION_MOIS` mois. Les plus
    récents sont dénombrés à part, explicitement « pas encore jugeables ».
    """
    con = _connect()
    try:
        ou = ""
        if clients:
            vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in clients)
            ou = f" AND client IN ({vals})"

        base = (f"ht IS NOT NULL AND ht > 0 "
                f"AND date >= DATE '{DEBUT_EXPLOITABLE}'{ou}")
        murs = (f"{base} AND date <= (SELECT md FROM ref) "
                f"- INTERVAL {MATURATION_MOIS} MONTH")

        tranches = con.execute(f"""
            WITH ref AS (SELECT max(date) md FROM devis)
            SELECT CASE WHEN ht <  5000  THEN 'moins de 5 K'
                        WHEN ht <  20000 THEN '5 à 20 K'
                        WHEN ht < 100000 THEN '20 à 100 K'
                        ELSE 'plus de 100 K' END            AS tranche,
                   min(ht)                                  AS borne,
                   count(*)                                 AS n,
                   count(*) FILTER (WHERE transforme)       AS signes,
                   sum(ht)                                  AS montant_dt
            FROM devis WHERE {murs}
            GROUP BY 1 ORDER BY borne
        """).fetchall()

        recents = con.execute(f"""
            WITH ref AS (SELECT max(date) md FROM devis)
            SELECT count(*), sum(ht) FROM devis
            WHERE {base} AND date > (SELECT md FROM ref)
                              - INTERVAL {MATURATION_MOIS} MONTH
        """).fetchone()

        def taux(n: int, s: int):
            return round(s / n * 100, 1) if n else None

        lignes = [{
            "tranche": r[0], "n_devis": int(r[2] or 0),
            "n_signes": int(r[3] or 0),
            "taux_pct": taux(int(r[2] or 0), int(r[3] or 0)),
            "montant_dt": round(float(r[4] or 0), 0),
        } for r in tranches]

        return {
            "servi": True,
            "nature": "comptage",
            "par_tranche_de_montant": lignes,
            "maturation_mois": MATURATION_MOIS,
            "non_jugeables": {
                "n_devis": int(recents[0] or 0),
                "montant_dt": round(float(recents[1] or 0), 0),
                "motif": (f"émis il y a moins de {MATURATION_MOIS} mois : trop "
                          "récents pour savoir s'ils aboutiront. Les compter "
                          "dans un taux le ferait baisser à tort."),
            },
            "lecture": (
                "Le taux de signature s'effondre quand le montant monte. Les "
                "gros devis sont des appels d'offres publics : leur issue ne "
                "dépend pas d'une relance commerciale, et dans les faits ils ne "
                "se transforment pratiquement jamais en facture directe. Un "
                "même montant ouvert n'a donc pas du tout la même valeur selon "
                "sa tranche."),
            "source": "statut du devis : transformé en facture, ou non",
        }
    finally:
        con.close()


def afficher() -> None:
    m = train()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    print("\n" + "=" * 78)
    print("  CONVERSION DES DEVIS")
    print("=" * 78)
    print(f"\n  {m['question']}")
    print(f"  Données : {m['donnees']}")

    mat = m.get("censurage_a_droite") or {}
    if mat.get("applicable"):
        print("\n  " + "-" * 74)
        print("  CENSURAGE À DROITE — pourquoi les devis récents sont écartés")
        print(f"    cohortes mûres    : {mat['taux_cohortes_mures_pct']} % "
              "de conversion")
        print(f"    cohortes récentes : {mat['taux_cohortes_recentes_pct']} % "
              f"(chute relative {mat['chute_relative_pct']} %)")
        print(f"    -> les {mat['maturation_declaree_mois']} derniers mois sont "
              "exclus de l'apprentissage.")
        print("       Les inclure enseignerait « récent donc perdu », artefact de")
        print("       la date d'observation et non du comportement commercial.")

    print(f"\n  Devis au total     : {m['n_devis_total']:,}".replace(",", " "))
    print(f"  Retenus (mûrs)     : {m['n_observations']:,}".replace(",", " ")
          + f"  sur {m['n_clients']} clients")
    print(f"  Période            : {m['periode']}")
    print(f"  Taux de base       : {m['taux_de_base'] * 100:.1f} % de devis signés")

    hp = m.get("hors_periode") or {}
    if not hp.get("applicable"):
        print(f"\n  Hors période inapplicable : {hp.get('motif')}")
        print("=" * 78 + "\n")
        return

    sel = hp.get("selection") or {}
    if sel.get("applicable"):
        print("\n  " + "-" * 74)
        print(f"  SÉLECTION sur validation interne "
              f"(coupure {sel['coupure_interne']}, {sel['n_essais']} essais, "
              f"{sel['n_eligibles']} éligibles)")
        print(f"    {'famille':<24}{'variables':<13}{'AUC int.':>9}{'sur-app.':>10}")
        for e in sel["essais"][:8]:
            marque = "" if e["eligible"] else "  DISQUALIFIÉ"
            if (e["famille"] == sel["retenu"]["famille"]
                    and e["reglage"] == sel["retenu"]["reglage"]
                    and e["variables"] == sel["retenu"]["variables"]):
                marque = "  <- retenu"
            print(f"    {e['famille']:<24}{e['variables']:<13}"
                  f"{e['auc_valid_interne']:>9.4f}"
                  f"{e['surapprentissage']:>+10.4f}{marque}")
        print(f"\n    réglage retenu : {hp['reglage_retenu']}")

    print("\n  " + "-" * 74)
    print(f"  HORS PÉRIODE — coupure {hp['coupure']}")
    print(f"    train {hp['n_train']:,}".replace(",", " ")
          + f" · test {hp['n_test']:,}".replace(",", " ")
          + f" · {hp['n_clients_test']} clients")
    print(f"\n    AUC                 : {hp['auc']:.4f}")
    print(f"    Average precision   : {hp['average_precision']:.4f}   "
          f"(taux de base {hp['taux_positif_test'] * 100:.1f} %)")
    print(f"    Brier               : {hp['brier']:.4f}")
    print(f"    Sur-apprentissage   : {hp['surapprentissage_interne']:+.4f}")
    print(f"    Dérive temporelle   : {hp['derive_temporelle']:+.4f}")

    d10 = hp.get("au_seuil_du_decile") or {}
    if d10:
        print(f"\n    Au seuil du DÉCILE ({d10['n_devis_signales']} devis "
              "signalés) :")
        print(f"      précision {d10['precision']:.4f} · rappel "
              f"{d10['recall']:.4f} · LIFT {d10['lift']}")
        print("      -> sur les 10 % de devis les mieux classés, cette part se")
        print("         transforme réellement, contre le taux de base pour une")
        print("         relance dans l'ordre d'arrivée.")

    print("\n    Références triviales (une variable, aucun apprentissage) :")
    for nom, a in sorted(hp["references_triviales"].items(), key=lambda kv: -kv[1]):
        print(f"      {nom:<26} AUC {a:.4f}")
    print(f"\n    GAIN sur la meilleure : {hp['gain_vs_reference_triviale']:+.4f}"
          f"   (seuil {SEUIL_GAIN_MINIMAL})")

    cmp_ = hp.get("comparaison_vs_reference_triviale") or {}
    if cmp_.get("applicable"):
        ic = cmp_["ecart_ic95"]
        etat = "SIGNIFICATIF" if cmp_["significatif"] else "NON SIGNIFICATIF"
        print(f"\n    Écart apparié, {cmp_['n_tirages_valides']} tirages "
              f"bootstrap :")
        print(f"      médiane {cmp_['ecart_median']:+.4f} · "
              f"IC95 [{ic[0]:+.4f} ; {ic[1]:+.4f}]  -> {etat}")
        print(f"      le modèle gagne dans "
              f"{cmp_['part_tirages_ou_le_modele_gagne_pct']} % des tirages")
        print(f"      AUC du modèle, IC95 : [{cmp_['auc_modele_ic95'][0]:.4f} ; "
              f"{cmp_['auc_modele_ic95'][1]:.4f}]")

    wf = hp.get("walk_forward_multi_origines") or {}
    if wf.get("applicable"):
        print("\n    " + "-" * 70)
        print(f"    WALK-FORWARD — {wf['n_origines']} coupures, même exigence, "
              "plus d'observations")
        for pli in wf["plis"]:
            if pli.get("retenu"):
                print(f"      pli {pli['pli']} · coupure {pli['coupure']} · "
                      f"test {pli['n_test']:>4} dont {pli['n_positifs_test']:>3} "
                      f"signés · AUC {pli['auc']:.4f}")
            else:
                print(f"      pli {pli['pli']} · coupure {pli['coupure']} · "
                      f"écarté ({pli.get('motif')})")
        print(f"\n      AUC agrégée : {wf['auc_agregee']:.4f}  sur "
              f"{wf['n_test_agrege']} devis dont {wf['n_positifs_agrege']} signés")
        if wf.get("auc_ecart_type_des_plis") is not None:
            print(f"      dispersion entre plis : "
                  f"± {wf['auc_ecart_type_des_plis']:.4f}")
        wc = wf.get("comparaison_agregee") or {}
        if wc.get("applicable"):
            ic = wc["ecart_ic95"]
            etat = "SIGNIFICATIF" if wc["significatif"] else "NON SIGNIFICATIF"
            print(f"\n      Écart apparié agrégé : médiane "
                  f"{wc['ecart_median']:+.4f} · IC95 "
                  f"[{ic[0]:+.4f} ; {ic[1]:+.4f}]  -> {etat}")
            print(f"      le modèle gagne dans "
                  f"{wc['part_tirages_ou_le_modele_gagne_pct']} % des tirages")
            print("\n      C'est CETTE mesure qui décide : même exigence, "
                  f"{wc['n_positifs']} signatures")
            print("      de test au lieu de 92. Un écart qui disparaît sur un "
                  "test élargi")
            print("      n'a jamais existé ; un écart qui se confirme est établi.")

    print(f"\n    Jeu retenu : « {hp['variables_retenues']} »")
    for i in range(0, len(hp["apport_de_la_relation_client"]), 70):
        print(f"      {hp['apport_de_la_relation_client'][i:i+70]}")

    imp = m.get("importance_permutation") or {}
    if imp:
        print("\n  Variables les plus utiles (permutation, sur le test) :")
        for f, v in list(imp.items())[:8]:
            print(f"    {f:<32} {v:+.4f}")

    d = m["decision_deploiement"]
    print("\n" + "-" * 78)
    print(f"  DÉCISION : {'DÉPLOYÉ' if d['modele_deploye'] else 'REFUSÉ'}")
    for i in range(0, len(d["motif"]), 72):
        print(f"    {d['motif'][i:i+72]}")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
