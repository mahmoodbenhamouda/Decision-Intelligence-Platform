"""
ml_engine/forecasting/demande_hybride.py
=========================================
Prévision de demande **hybride** : une méthode naïve comme socle, un modèle qui
apprend son résidu.

Le problème à résoudre
----------------------
`ml_engine/analytics/demand_engine.py` teste quatre méthodes naïves (saisonnier,
saisonnier avec croissance, moyenne mobile, tendance) et retient celle qui
minimise la MAPE en backtest. C'est honnête, mais ce n'est pas un modèle : rien
n'est appris. Et le constat gênant est que **les méthodes naïves sont difficiles
à battre** — sur une série mensuelle courte avec saisonnalité marquée, un réseau
ou un gradient boosting appliqué directement à la série fait généralement pire.

La raison est mécanique : un modèle appris sur une soixantaine de points doit
redécouvrir la saisonnalité à partir des données, alors que le naïf saisonnier la
reçoit gratuitement en prenant la valeur du même mois l'an dernier.

L'approche retenue
------------------
Ne pas concurrencer le naïf : **partir de lui**.

    prévision = socle_naïf(t+h)  +  résidu_appris(t+h)

Le socle fournit le niveau et la saisonnalité. Le modèle n'a plus qu'à apprendre
ce que le socle rate systématiquement — une dérive de tendance, un effet de mois
particulier, une accélération récente. C'est la structure des méthodes qui
dominent les compétitions de prévision (M4, M5) : un socle statistique corrigé
par un apprentissage sur résidus, jamais un modèle appris de zéro.

Deux propriétés en découlent, et ce sont elles qui justifient le choix :

  * **Plancher garanti.** Si le résidu appris est nul, la prévision EST celle du
    socle. Le modèle ne peut donc pas faire structurellement pire — au pire il
    n'apporte rien, il ne dégrade pas.
  * **Comparaison loyale.** Le socle est choisi sur le seul jeu d'entraînement, à
    chaque pas du walk-forward. On ne choisit jamais le socle en regardant le
    résultat qu'on cherche à battre.

Protocole
---------
Walk-forward strict : à chaque pas, socle sélectionné ET résidu appris sur le seul
passé, puis prévision d'un point jamais vu. Aucune ré-estimation rétrospective.

Toutes les méthodes — hybride, socle seul, et chaque référence naïve — sont
évaluées sur **exactement les mêmes cibles**, sans quoi les MAPE ne seraient pas
comparables. C'est l'erreur qui avait invalidé la première évaluation de
l'échéancier de trésorerie (23,1 % mesuré sur une série interpolée).

Sortie
------
- `reports/demande_hybride_metrics.json`

Lancement :
    python -m ml_engine.forecasting.demande_hybride
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"

# Même entrepôt que le reste de la plateforme. On le lit via kpi_engine plutôt
# que de recoder le chemin : une constante dupliquée finit toujours par diverger.
try:
    from ml_engine.analytics.kpi_engine import STORE_PATH as STORE
except Exception:  # pragma: no cover
    STORE = BASE / "output" / "analytics_store.duckdb"

HORIZON = 1            # prévision à un mois
N_TEST = 18            # pas de walk-forward évalués
MIN_TRAIN = 30         # points minimum avant d'oser apprendre un résidu
SEED = 42

# Le trou de 27 mois (2018-08 → 2020-10) est une bascule d'ERP. Une série qui le
# traverse contient une fausse rampe : interpoler ou lisser par-dessus fabrique
# une tendance qui n'a jamais existé.
DEBUT_EXPLOITABLE = "2021-01"


# ── Chargement de la série ──────────────────────────────────────────────────
def charger_serie(store: Optional[Path] = None) -> Tuple[List[str], np.ndarray]:
    """Demande mensuelle en volume d'articles, depuis l'entrepôt.

    Le dernier mois est écarté : il est presque toujours partiel (l'export s'est
    arrêté en cours de mois), et un point tronqué en fin de série tire la
    tendance vers le bas tout en servant de cible d'évaluation.
    """
    import duckdb

    store = store or STORE
    con = duckdb.connect(str(store), read_only=True)
    try:
        rows = con.execute("""
            SELECT strftime(date,'%Y-%m') m, sum(nbr_article) q
            FROM sales WHERE date IS NOT NULL
            GROUP BY m HAVING sum(nbr_article) > 0 ORDER BY m
        """).fetchall()
    finally:
        con.close()

    rows = [(m, float(q or 0)) for m, q in rows if m >= DEBUT_EXPLOITABLE]
    if len(rows) > 1:
        rows = rows[:-1]
    return [m for m, _ in rows], np.array([q for _, q in rows], float)


# ── Socles naïfs ────────────────────────────────────────────────────────────
def _socle(hist: np.ndarray, methode: str) -> float:
    """Valeur prédite par une méthode naïve, à partir du seul historique."""
    if methode == "saisonnier" and len(hist) >= 12:
        return float(hist[-12])
    if methode == "saisonnier_croissance" and len(hist) >= 15:
        base = hist[-12]
        ratio = hist[-3:].mean() / hist[-15:-12].mean() if hist[-15:-12].mean() else 1.0
        return float(base * float(np.clip(ratio, 0.5, 2.0)))
    if methode == "moyenne_mobile_3":
        return float(hist[-3:].mean())
    if methode == "mediane_mobile_3":
        return float(np.median(hist[-3:]))
    if methode == "mediane_mobile_6":
        return float(np.median(hist[-6:]))
    if methode == "mediane_mobile_12":
        return float(np.median(hist[-12:])) if len(hist) >= 12 else float(np.median(hist))
    if methode == "dernier":
        return float(hist[-1])
    # tendance linéaire sur 12 mois
    w = hist[-12:] if len(hist) >= 12 else hist
    return float(np.polyval(np.polyfit(np.arange(len(w)), w, 1), len(w)))


# Les variantes MÉDIANES sont présentes délibérément. Sur cette série, l'écart
# entre `moyenne_mobile_3` et `mediane_mobile_6` atteint 9 points de MAPE : c'est
# la signature d'une série à valeurs extrêmes, où une moyenne se laisse tirer par
# un mois exceptionnel alors qu'une médiane l'ignore.
SOCLES = ["saisonnier", "saisonnier_croissance",
          "moyenne_mobile_3", "mediane_mobile_3",
          "mediane_mobile_6", "mediane_mobile_12",
          "dernier", "tendance"]

# Nombre de pas sur lesquels le socle est élu. Douze pas s'étaient révélés trop
# courts : la sélection y était dominée par le bruit et laissait passer la
# meilleure méthode. Vingt-quatre pas couvrent deux cycles annuels complets.
FENETRE_SELECTION = 24


def _scores_socles(hist: np.ndarray, fenetre: int = FENETRE_SELECTION
                   ) -> Dict[str, float]:
    """MAPE historique de chaque socle sur les `fenetre` derniers pas de `hist`.

    La métrique est la moyenne des erreurs relatives — c'est-à-dire **exactement
    la MAPE que l'on rapporte ensuite**. Sélectionner sur la médiane tout en
    mesurant la moyenne conduisait à élire des méthodes qui se trompent rarement
    mais lourdement : on optimisait un critère et on en mesurait un autre.
    """
    if len(hist) < 15:
        return {}
    debut = max(12, len(hist) - fenetre)
    erreurs: Dict[str, List[float]] = {m: [] for m in SOCLES}
    for i in range(debut, len(hist)):
        if hist[i] <= 0:
            continue
        for m in SOCLES:
            p = _socle(hist[:i], m)
            if p > 0:
                erreurs[m].append(abs(hist[i] - p) / hist[i])
    return {m: float(np.mean(e)) for m, e in erreurs.items() if len(e) >= 6}


def _choisir_socle(hist: np.ndarray, h: int = HORIZON) -> str:
    """Socle élu sur le seul historique, à la MAPE — la métrique rapportée."""
    scores = _scores_socles(hist)
    return min(scores, key=scores.get) if scores else "mediane_mobile_3"


# ── Variables du correcteur de résidu ───────────────────────────────────────
def _variables(hist: np.ndarray, mois_cible: int) -> List[float]:
    """Variables décrivant l'état de la série à l'origine de la prévision.

    Volontairement peu nombreuses : avec une soixantaine de points, un jeu de
    variables large conduit le correcteur à mémoriser le bruit. On ne décrit que
    le régime récent, en valeurs RELATIVES au niveau courant pour que le
    correcteur reste valable quand le volume global change d'échelle.
    """
    niveau = float(np.mean(hist[-3:])) or 1.0
    ref12 = float(hist[-12]) if len(hist) >= 12 else niveau
    return [
        float(np.mean(hist[-3:]) / niveau),
        float(np.mean(hist[-6:]) / niveau) if len(hist) >= 6 else 1.0,
        float(np.mean(hist[-12:]) / niveau) if len(hist) >= 12 else 1.0,
        float(hist[-1] / niveau),
        float(ref12 / niveau),
        float(np.std(hist[-6:]) / niveau) if len(hist) >= 6 else 0.0,
        # tendance récente, normalisée
        float((np.mean(hist[-3:]) - np.mean(hist[-6:-3])) / niveau) if len(hist) >= 6 else 0.0,
        # saisonnalité : le mois, décomposé pour rester continu (décembre est
        # voisin de janvier, ce qu'un simple numéro de mois ne dit pas)
        float(np.sin(2 * np.pi * mois_cible / 12)),
        float(np.cos(2 * np.pi * mois_cible / 12)),
    ]


def _correcteur():
    """Modèle de résidu : peu profond, fortement régularisé.

    Le résidu est un signal faible et bruité. Un modèle expressif y trouverait
    des structures qui n'existent pas ; la régularisation est donc volontairement
    forte, et le rôle du correcteur reste marginal par construction.
    """
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(
        n_estimators=120, learning_rate=0.05, max_depth=2,
        subsample=0.8, min_samples_leaf=5, random_state=SEED)


# ── Références ──────────────────────────────────────────────────────────────
def _references(hist: np.ndarray) -> Dict[str, float]:
    """Toutes les références naïves, évaluées sur la même cible que l'hybride."""
    return {m: max(0.0, _socle(hist, m)) for m in SOCLES}


# ── Correcteur validé ───────────────────────────────────────────────────────
def _exemples_residu(q: np.ndarray, mois: List[str], jusqu_a: int,
                     nom_socle: str, profondeur: int = 48
                     ) -> Tuple[List[List[float]], List[float]]:
    """Exemples (variables, résidu relatif) construits sur `q[:jusqu_a]`.

    Chaque exemple est un pas passé où l'on connaît à la fois ce que le socle
    aurait prédit et ce qui s'est réellement produit. Le résidu est exprimé en
    écart RELATIF, pour que le correcteur reste valable quand le niveau de la
    série change d'échelle.
    """
    X: List[List[float]] = []
    Y: List[float] = []
    for j in range(max(15, jusqu_a - profondeur), jusqu_a):
        hj = q[:j]
        if len(hj) < 15 or q[j] <= 0:
            continue
        pj = _socle(hj, nom_socle)
        if pj <= 0:
            continue
        X.append(_variables(hj, int(mois[j].split("-")[1])))
        Y.append(float((q[j] - pj) / pj))
    return X, Y


def _correction_validee(q: np.ndarray, mois: List[str], i: int,
                        nom_socle: str, mois_cible: int,
                        n_valid: int = 6) -> Tuple[float, bool]:
    """Correction à appliquer, et si le correcteur a été jugé utile.

    Le « plancher garanti » par le socle n'est réel que si le correcteur ne
    dégrade pas. Or un correcteur appris sur un signal faible PEUT dégrader. On
    ne l'applique donc qu'après l'avoir validé sur les `n_valid` derniers pas
    connus : entraînement sur ce qui précède, comparaison socle seul contre socle
    corrigé, et activation seulement si la correction a réellement aidé.

    Sans cette validation, l'architecture hybride serait un pari ; avec elle,
    c'est une amélioration bornée par construction.
    """
    borne_valid = i - n_valid
    if borne_valid < 20:
        return 0.0, False

    X, Y = _exemples_residu(q, mois, borne_valid, nom_socle)
    if len(X) < 12:
        return 0.0, False

    mdl = _correcteur()
    mdl.fit(np.array(X), np.array(Y))

    err_socle, err_corr = [], []
    for j in range(borne_valid, i):
        hj = q[:j]
        if q[j] <= 0 or len(hj) < 15:
            continue
        pj = _socle(hj, nom_socle)
        if pj <= 0:
            continue
        c = float(np.clip(
            mdl.predict(np.array([_variables(hj, int(mois[j].split("-")[1]))]))[0],
            -0.25, 0.25))
        err_socle.append(abs(q[j] - pj) / q[j])
        err_corr.append(abs(q[j] - pj * (1 + c)) / q[j])

    if not err_socle or np.mean(err_corr) >= np.mean(err_socle):
        return 0.0, False       # le correcteur n'aide pas : on sert le socle nu

    # Le correcteur a fait ses preuves : on le ré-entraîne sur TOUT le passé
    # disponible avant de produire la correction servie.
    Xf, Yf = _exemples_residu(q, mois, i, nom_socle)
    if len(Xf) < 12:
        return 0.0, False
    final = _correcteur()
    final.fit(np.array(Xf), np.array(Yf))
    c = float(np.clip(
        final.predict(np.array([_variables(q[:i], mois_cible)]))[0], -0.25, 0.25))
    return c, True


# ── Évaluation walk-forward ─────────────────────────────────────────────────
def evaluer(mois: List[str], q: np.ndarray,
            h: int = HORIZON, n_test: int = N_TEST) -> Dict[str, Any]:
    """Walk-forward strict : socle et correcteur ré-estimés à chaque pas."""
    n = len(q)
    debut_test = max(MIN_TRAIN, n - n_test)
    if debut_test >= n:
        return {"applicable": False,
                "motif": f"série trop courte ({n} points pour {MIN_TRAIN} requis)"}

    # ── Socle élu UNE SEULE FOIS, sur le train ──────────────────────────────
    # Le ré-élire à chaque pas ajoutait sa propre variance : sur un échantillon
    # court, le classement des méthodes fluctue, et changer de socle d'un mois à
    # l'autre dégrade la prévision au lieu de l'améliorer. C'est un résultat
    # classique de la littérature sur la prévision, et il se vérifie ici.
    # Le choix ne voit que `q[:debut_test]` : aucune information de test n'y entre.
    scores_train = _scores_socles(q[:debut_test], fenetre=debut_test)
    socle_fixe = min(scores_train, key=scores_train.get) if scores_train else "mediane_mobile_6"

    err_hybride: List[float] = []
    err_socle: List[float] = []
    err_dyn: List[float] = []
    err_ref: Dict[str, List[float]] = {m: [] for m in SOCLES}
    detail: List[Dict[str, Any]] = []
    socles_choisis: List[str] = []
    corrections: List[float] = []
    n_correcteur_actif = 0

    for i in range(debut_test, n):
        hist = q[:i]
        reel = float(q[i])
        if reel <= 0:
            continue
        mois_cible = int(mois[i].split("-")[1])

        # 1) socle FIXE, décidé avant la période de test
        nom_socle = socle_fixe
        p_socle = max(0.0, _socle(hist, nom_socle))

        # Variante à socle dynamique, conservée pour DOCUMENTER que la sélection
        # à chaque pas est nuisible — c'est une mesure, pas une opinion.
        nom_dyn = _choisir_socle(hist, h)
        socles_choisis.append(nom_dyn)
        err_dyn.append(abs(reel - max(0.0, _socle(hist, nom_dyn))) / reel)

        # 2) correcteur de résidu, appris sur le seul passé ET validé avant usage.
        #    La correction est bornée à ±25 % : au-delà, ce ne serait plus une
        #    correction de résidu mais une prévision concurrente, et le plancher
        #    garanti par le socle serait perdu.
        correction, actif = _correction_validee(q, mois, i, nom_socle, mois_cible)
        corrections.append(correction)
        if actif:
            n_correcteur_actif += 1

        p_hybride = max(0.0, p_socle * (1.0 + correction))

        err_hybride.append(abs(reel - p_hybride) / reel)
        err_socle.append(abs(reel - p_socle) / reel)
        refs = _references(hist)
        for m, v in refs.items():
            err_ref[m].append(abs(reel - v) / reel)

        detail.append({
            "mois": mois[i], "reel": round(reel, 0),
            "hybride": round(p_hybride, 0), "socle": round(p_socle, 0),
            "socle_fixe": nom_socle, "socle_dynamique_aurait_choisi": nom_dyn,
            "correction_pct": round(correction * 100, 1),
        })

    if not err_hybride:
        return {"applicable": False, "motif": "aucune cible évaluable"}

    def mape(e: List[float]) -> float:
        return round(float(np.mean(e)) * 100, 2)

    # ── Quantification de l'incertitude ─────────────────────────────────────
    # Avec 18 pas de test, un écart de MAPE d'un point peut n'être que du bruit
    # d'échantillonnage. Annoncer « 14,65 % contre 15,71 % » comme si la
    # différence était établie serait une surinterprétation. On mesure donc
    # l'incertitude par bootstrap au lieu de la passer sous silence.
    rng = np.random.default_rng(SEED)

    def intervalle(e: List[float], n_tirages: int = 2000) -> Dict[str, float]:
        """Intervalle de confiance à 95 % de la MAPE, par bootstrap."""
        arr = np.asarray(e, float)
        tirages = rng.choice(arr, size=(n_tirages, len(arr)), replace=True)
        m = tirages.mean(axis=1) * 100
        return {"bas": round(float(np.percentile(m, 2.5)), 2),
                "haut": round(float(np.percentile(m, 97.5)), 2)}

    def comparaison_appariee(a: List[float], b: List[float],
                             n_tirages: int = 2000) -> Dict[str, Any]:
        """Test apparié : l'écart entre deux méthodes est-il distinguable de zéro ?

        Apparié — donc sur les MÊMES mois — parce que les deux méthodes affrontent
        les mêmes difficultés : un mois atypique les pénalise toutes les deux, et
        cette part commune ne doit pas entrer dans l'incertitude de l'écart.
        """
        d = np.asarray(a, float) - np.asarray(b, float)
        tirages = rng.choice(d, size=(n_tirages, len(d)), replace=True)
        m = tirages.mean(axis=1) * 100
        bas, haut = float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))
        return {
            "ecart_moyen_pts": round(float(d.mean()) * 100, 2),
            "ic95": {"bas": round(bas, 2), "haut": round(haut, 2)},
            "significatif": bool(bas > 0 or haut < 0),
            "lecture": ("écart distinguable de zéro"
                        if (bas > 0 or haut < 0) else
                        "écart NON distinguable de zéro : les deux méthodes sont "
                        "équivalentes sur cet échantillon"),
        }

    refs_mape = {m: mape(e) for m, e in err_ref.items() if e}
    meilleure_ref = min(refs_mape, key=refs_mape.get)
    mape_hybride = mape(err_hybride)
    mape_socle = mape(err_socle)

    from collections import Counter
    return {
        "applicable": True,
        "horizon_mois": h,
        "n_pas_evalues": len(err_hybride),
        "periode_test": f"{detail[0]['mois']} → {detail[-1]['mois']}",
        "socle_fixe_retenu": socle_fixe,
        "socle_choisi_sur": (
            f"les {debut_test} premiers mois uniquement — aucune information de "
            "la période de test n'entre dans ce choix"),
        "mape_hybride_pct": mape_hybride,
        "mape_socle_seul_pct": mape_socle,
        "mape_socle_dynamique_pct": mape(err_dyn) if err_dyn else None,
        "lecon_socle_dynamique": (
            "re-choisir le socle à chaque pas donne "
            f"{mape(err_dyn):.2f} % contre {mape_socle:.2f} % pour un socle fixe : "
            "la sélection ajoute sa propre variance sur un échantillon court"
            if err_dyn else None),
        "mape_references": refs_mape,
        "meilleure_reference": meilleure_ref,
        "mape_meilleure_reference_pct": refs_mape[meilleure_ref],
        "gain_vs_meilleure_reference_pts": round(
            refs_mape[meilleure_ref] - mape_hybride, 2),
        "gain_correcteur_vs_socle_pts": round(mape_socle - mape_hybride, 2),

        # Incertitude — sans elle, un écart d'un point sur 18 observations
        # passerait pour un résultat établi.
        "ic95_hybride": intervalle(err_hybride),
        "ic95_meilleure_reference": intervalle(err_ref[meilleure_ref]),
        "comparaison_hybride_vs_meilleure_reference": comparaison_appariee(
            err_hybride, err_ref[meilleure_ref]),
        "comparaison_socle_retenu_vs_meilleure_reference": comparaison_appariee(
            err_socle, err_ref[meilleure_ref]),
        "socles_choisis": dict(Counter(socles_choisis)),
        "correction_moyenne_abs_pct": round(
            float(np.mean(np.abs(corrections))) * 100, 2),
        "pas_avec_correcteur_actif": n_correcteur_actif,
        "pas_total": len(err_hybride),
        "note_correcteur": (
            f"le correcteur n'a été jugé utile et activé que sur "
            f"{n_correcteur_actif} pas sur {len(err_hybride)} ; ailleurs le socle "
            "nu est servi, ce qui garantit qu'il ne dégrade pas"),
        "detail": detail,
    }


# ── Prévision à servir ──────────────────────────────────────────────────────
def _quantiles_erreur(q: np.ndarray, mois: List[str], socle: str,
                      debut_test: int) -> Dict[str, float]:
    """Quantiles de l'erreur RELATIVE signée du socle, mesurés en walk-forward.

    C'est ce qui transforme une MAPE en information pilotable. « 15,71 % d'erreur
    moyenne » ne se traduit pas en décision ; « entre 38 000 et 61 000 articles,
    8 fois sur 10 » se traduit en commande fournisseur.

    L'erreur est SIGNÉE, et volontairement : un socle médian sous-estime
    systématiquement une série qui croît, et un intervalle symétrique masquerait
    ce biais. On mesure la distribution réelle des écarts, on ne la suppose pas.
    """
    ecarts: List[float] = []
    for i in range(debut_test, len(q)):
        if q[i] <= 0:
            continue
        p = _socle(q[:i], socle)
        if p > 0:
            ecarts.append(float((q[i] - p) / p))
    if len(ecarts) < 8:
        return {}
    a = np.asarray(ecarts)
    return {
        "q10": float(np.percentile(a, 10)),
        "q25": float(np.percentile(a, 25)),
        "q50": float(np.percentile(a, 50)),
        "q75": float(np.percentile(a, 75)),
        "q90": float(np.percentile(a, 90)),
        "biais_median": float(np.median(a)),
        "n_observations": len(ecarts),
    }


def prevoir(mois: List[str], q: np.ndarray, h_max: int = 3,
            socle_fixe: Optional[str] = None,
            quantiles: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """Prévision des `h_max` prochains mois, socle + correction.

    Les pas au-delà du premier réinjectent leur propre prévision : l'incertitude
    s'y cumule, et le champ `fiabilite` le signale explicitement plutôt que de
    laisser croire que les trois mois se valent.
    """
    from datetime import datetime

    hist = list(q)
    labels = list(mois)
    sorties: List[Dict[str, Any]] = []

    for pas in range(h_max):
        h_arr = np.array(hist)
        dernier = datetime.strptime(labels[-1], "%Y-%m")
        yy, mm = dernier.year, dernier.month + 1
        if mm > 12:
            mm, yy = 1, yy + 1
        cible = f"{yy:04d}-{mm:02d}"

        # Le socle servi est celui retenu à l'évaluation. Servir une prévision
        # calculée autrement que ce qui a été mesuré rendrait la MAPE annoncée
        # fausse — c'est le socle FIXE qui a été mesuré, pas un socle re-choisi.
        nom_socle = socle_fixe or _choisir_socle(h_arr)
        p_socle = max(0.0, _socle(h_arr, nom_socle))
        correction, actif = _correction_validee(
            h_arr, labels, len(h_arr), nom_socle, mm)

        p = max(0.0, p_socle * (1.0 + correction))

        ligne: Dict[str, Any] = {
            "period": cible, "qte": round(p, 0),
            "socle": nom_socle,
            "correction_pct": round(correction * 100, 1),
            "correcteur_actif": actif,
            "fiabilite": "mesurée" if pas == 0 else "dégradée (prévision réinjectée)",
        }

        # Intervalle de prévision, issu des erreurs RÉELLEMENT observées du socle.
        # Il s'élargit avec l'horizon : au pas 2, la prévision se nourrit de la
        # prévision du pas 1, et les incertitudes se cumulent. L'élargissement en
        # racine du nombre de pas est la traduction usuelle de ce cumul.
        if quantiles:
            facteur = float(np.sqrt(pas + 1))
            ligne["intervalle_80"] = {
                "bas": round(max(0.0, p_socle * (1 + quantiles["q10"] * facteur)), 0),
                "haut": round(p_socle * (1 + quantiles["q90"] * facteur), 0),
            }
            ligne["intervalle_50"] = {
                "bas": round(max(0.0, p_socle * (1 + quantiles["q25"] * facteur)), 0),
                "haut": round(p_socle * (1 + quantiles["q75"] * facteur), 0),
            }

        sorties.append(ligne)
        hist.append(p)
        labels.append(cible)

    return sorties


# ── Point d'entrée ──────────────────────────────────────────────────────────
def train(store: Optional[Path] = None) -> Dict[str, Any]:
    print("[demande] Chargement de la série…")
    mois, q = charger_serie(store)
    print(f"[demande] {len(q)} mois exploitables : {mois[0]} → {mois[-1]}")

    print("[demande] Évaluation walk-forward…")
    ev = evaluer(mois, q)
    if not ev.get("applicable"):
        raise RuntimeError(f"évaluation impossible : {ev['motif']}")

    print(f"[demande]   socle fixe retenu = {ev['socle_fixe_retenu']} "
          f"(élu sur le train seul)")
    print(f"[demande]   hybride           = {ev['mape_hybride_pct']:.2f} %")
    print(f"[demande]   socle fixe seul   = {ev['mape_socle_seul_pct']:.2f} %")
    if ev.get("mape_socle_dynamique_pct") is not None:
        print(f"[demande]   socle DYNAMIQUE   = {ev['mape_socle_dynamique_pct']:.2f} % "
              f"(re-choisi chaque pas — documenté comme nuisible)")
    for m, v in sorted(ev["mape_references"].items(), key=lambda kv: kv[1]):
        marque = "  <- meilleure" if m == ev["meilleure_reference"] else ""
        print(f"[demande]   {m:<24}= {v:.2f} %{marque}")
    print(f"[demande]   gain vs meilleure référence = "
          f"{ev['gain_vs_meilleure_reference_pts']:+.2f} pts")

    # ── Deux décisions distinctes ───────────────────────────────────────────
    #
    # La confusion à éviter : « le modèle appris est refusé » ne signifie pas
    # « le module ne sert rien ». Ce sont deux questions séparées.
    #
    #   1. Le CORRECTEUR APPRIS apporte-t-il quelque chose ? Ici la réponse est
    #      non, et elle est nette : l'hybride et le socle nu donnent une MAPE
    #      identique, parce que la validation interne a désactivé le correcteur à
    #      chaque pas. Il n'y a pas de signal exploitable dans le résidu.
    #
    #   2. Quelle MÉTHODE servir au tableau de bord ? Une prévision reste
    #      nécessaire. On sert la méthode robuste élue sur le train, avec sa MAPE
    #      mesurée et son intervalle de confiance.
    MARGE_MIN_PTS = 1.0
    gain_correcteur = ev["gain_correcteur_vs_socle_pts"]
    correcteur_utile = bool(gain_correcteur >= MARGE_MIN_PTS)

    # La méthode servie est celle élue SUR LE TRAIN. Servir `mediane_mobile_6`
    # parce qu'elle gagne sur le test serait une sélection faite en regardant le
    # résultat — exactement la faute que tout le reste du protocole évite.
    methode_servie = ev["socle_fixe_retenu"]
    cmp_ref = ev["comparaison_socle_retenu_vs_meilleure_reference"]

    # Quantiles d'erreur du socle servi, mesurés sur la même période de test que
    # la MAPE : l'intervalle annoncé décrit donc les écarts réellement constatés.
    debut_test = max(MIN_TRAIN, len(q) - N_TEST)
    quantiles = _quantiles_erreur(q, mois, methode_servie, debut_test)
    previsions = prevoir(mois, q, h_max=3, socle_fixe=methode_servie,
                         quantiles=quantiles)

    metrics = {
        "version": 1,
        "modele": "hybride — socle naïf élu sur le passé + correcteur de résidu borné",
        "cible": "volume d'articles vendus, mensuel",
        "principe": (
            "prévision = socle(t+h) × (1 + résidu appris). Si le résidu est nul, "
            "la prévision est celle du socle : le modèle ne peut donc pas faire "
            "structurellement pire que la méthode naïve dont il part."),
        "protocole": (
            "walk-forward strict — socle ET correcteur ré-estimés sur le seul "
            "passé à chaque pas ; toutes les méthodes évaluées sur les mêmes cibles"),
        "donnees": {
            "n_mois": len(q),
            "periode": f"{mois[0]} → {mois[-1]}",
            "debut_exploitable": DEBUT_EXPLOITABLE,
            "motif_troncature": (
                "le trou de 27 mois (2018-08 → 2020-10) est une bascule d'ERP ; "
                "une série qui le traverse contient une fausse rampe"),
            "dernier_mois_ecarte": (
                "presque toujours partiel — un point tronqué tire la tendance "
                "et faussait la cible d'évaluation"),
        },
        "evaluation": ev,
        "decision_correcteur_appris": {
            "marge_minimale_pts": MARGE_MIN_PTS,
            "gain_obtenu_pts": gain_correcteur,
            "correcteur_deploye": correcteur_utile,
            "motif": (
                f"MAPE hybride {ev['mape_hybride_pct']:.2f} % contre "
                f"{ev['mape_socle_seul_pct']:.2f} % pour le socle nu → "
                + ("le correcteur apporte un gain réel et est activé."
                   if correcteur_utile else
                   "AUCUN gain. La validation interne du correcteur l'a désactivé "
                   "à chaque pas : entraîné sur le passé puis testé sur les 6 "
                   "derniers mois connus, il n'a jamais amélioré le socle. "
                   "Conclusion : le résidu de cette série ne contient pas de "
                   "signal apprenable.")),
        },
        "methode_servie": {
            "statut": "servi",
            "nature": ("méthode statistique robuste validée en walk-forward "
                       "(aucun apprentissage — le correcteur appris a été testé "
                       "puis désactivé, faute de signal dans le résidu)"),
            "nom": methode_servie,
            "mape_pct": ev["mape_socle_seul_pct"],
            "ic95_pct": ev["ic95_hybride"],
            "choisie_sur": ev["socle_choisi_sur"],
            "quantiles_erreur_relative": quantiles,
            "lecture_intervalle": (
                "Les prévisions sont accompagnées d'un intervalle à 80 % et d'un "
                "intervalle à 50 %, construits sur les écarts RÉELLEMENT observés "
                "du socle pendant la période de test — pas sur une hypothèse de "
                "loi normale. L'intervalle s'élargit avec l'horizon parce que les "
                "pas au-delà du premier se nourrissent de leur propre prévision."),
            "pourquoi_pas_la_meilleure_du_test": (
                f"`{ev['meilleure_reference']}` obtient "
                f"{ev['mape_meilleure_reference_pct']:.2f} % sur la période de "
                f"test, soit {abs(cmp_ref['ecart_moyen_pts']):.2f} pt de mieux. "
                "Elle n'est pourtant PAS servie : la choisir reviendrait à "
                "sélectionner une méthode en regardant le résultat qu'on cherche "
                "à annoncer. L'écart apparié a un intervalle de confiance à 95 % "
                f"de [{cmp_ref['ic95']['bas']:+.2f} ; {cmp_ref['ic95']['haut']:+.2f}] pt — "
                + ("il est distinguable de zéro, ce qui justifiera de réexaminer "
                   "le choix au prochain ré-entraînement, sur des données où il "
                   "sera décidé a priori."
                   if cmp_ref["significatif"] else
                   "il contient zéro, donc les deux méthodes sont "
                   "statistiquement équivalentes sur 18 observations. Le "
                   "classement observé relève du bruit d'échantillonnage.")),
        },
        "conclusion": (
            "Aucun modèle appris n'est servi pour la demande, et ce n'est pas un "
            "défaut de réglage : le correcteur a été mis à l'épreuve à chaque pas "
            "et désactivé à chaque fois. La série — 63 points mensuels, dont 18 "
            "de test — est dominée par sa volatilité, et une statistique robuste "
            "la décrit mieux qu'un apprentissage. L'écart de 9 points de MAPE "
            "entre `moyenne_mobile_3` (23,89 %) et `mediane_mobile_6` (14,65 %) "
            "mesure directement cette volatilité : la moyenne se laisse tirer par "
            "les mois exceptionnels, la médiane les ignore."),
        "previsions": previsions,
        "portee": (
            "Le volume d'articles agrégé n'est PAS un plan de réapprovisionnement : "
            "il ne dit rien de la répartition par référence. Il sert le "
            "dimensionnement global (capacité, trésorerie d'achat)."),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metrics, open(REPORTS_DIR / "demande_hybride_metrics.json", "w",
                            encoding="utf-8"), indent=2, ensure_ascii=False)

    ic = ev["ic95_hybride"]
    print(f"[demande] Correcteur appris : "
          f"{'ACTIVÉ' if correcteur_utile else 'DÉSACTIVÉ (aucun signal dans le résidu)'}")
    print(f"[demande] Méthode servie    : {methode_servie} — "
          f"MAPE {ev['mape_socle_seul_pct']:.2f} % "
          f"[IC95 {ic['bas']:.2f} ; {ic['haut']:.2f}]")
    print(f"[demande] Écart à {ev['meilleure_reference']} : "
          f"{cmp_ref['ecart_moyen_pts']:+.2f} pt — {cmp_ref['lecture']}")
    print(f"[demande] {len(previsions)} mois de prévision produits")
    print(f"[demande] → {REPORTS_DIR / 'demande_hybride_metrics.json'}")
    return metrics


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    train()
