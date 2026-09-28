"""
evaluation_demande/pipeline_robuste.py
======================================
Existe-t-il une information prédictive exploitable au-delà de la médiane 12 mois ?

Le diagnostic (`diagnostic.py`, `propagation.py`) a établi, AVANT toute nouvelle
lecture du test, trois défauts du LightGBM actuel :

  * deux variables NON STATIONNAIRES — `marche_dernier_mois` (total du marché en
    unités absolues) et `anciennete` (qui croît d'un mois chaque mois, donc joue le
    rôle d'une horloge) — font extrapoler le modèle hors de ce qu'il a vu : au
    1er janvier 2026, le marché de décembre valait 2,5 fois sa médiane, du jamais
    vu, et ces deux variables ont ajouté ~4 700 unités à la prévision ;
  * l'ÉCHELLE de normalisation est la moyenne 12 mois, qu'un seul mois de pic
    gonfle ; la prévision (forme × échelle) en hérite ;
  * sa sélection s'est faite sur 12 mois de validation seulement ; sur les
    12 mois d'avant (2022-09 → 2023-08), jamais utilisés, il ne battait pas la
    médiane.

Candidats — fixés AVANT la phase de test, réglages LightGBM inchangés (aucune
nouvelle recherche d'hyperparamètres) :

  mediane_12              la référence
  lightgbm_actuel         le challenger publié (contrôle de reproduction)
  lightgbm_stationnaire   marché en RATIOS (dernier mois / médiane 12, même mois
                          an passé / médiane 12, croissance 12 / 12 précédents),
                          ancienneté plafonnée à 24 mois
  lightgbm_robuste        stationnaire + échelle = moyenne 12 mois SANS son mois
                          maximal (un pic isolé ne gonfle plus l'échelle)
  combinaison_50_50       ½ médiane + ½ lightgbm_robuste (poids fixé a priori)
  quantile_12_q55/q60     quantile 55 % / 60 % des 12 derniers mois (corrige le
                          biais négatif de la médiane sur une demande qui croît)
  hybride_par_classe      médiane pour la demande régulière, lightgbm_robuste
                          pour les autres classes (Syntetos-Boylan à l'origine)

Aucun candidat ne touche la CIBLE : ni écrêtage, ni suppression de mois. Les
pics restent dans y ; seules les VARIABLES les voient autrement.

Deux phases :

  --phase dev    période de DÉVELOPPEMENT = 12 origines de pré-validation
                 (2022-09 → 2023-08, jamais utilisées jusqu'ici) + les 12 de
                 validation. Applique la règle de sélection et ÉCRIT un fichier
                 de pré-enregistrement (candidat retenu, règle, empreintes).
  --phase test   refuse de tourner sans pré-enregistrement ; évalue TOUS les
                 candidats sur les 18 mois de test (pour la transparence) mais
                 seule la décision pré-enregistrée compte.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting import demande_reference as dr  # noqa: E402

RES = RACINE / "evaluation_demande" / "resultats"
PREENREGISTREMENT = RES / "preenregistrement.json"
PRE_VALIDATION = ("2022-09-01", "2023-08-01")   # origines ; cibles 2022-10 → 2023-09

REGLE_DE_SELECTION = (
    "Un candidat remplace la médiane 12 mois si et seulement si, sur la période de "
    "développement (24 origines antérieures au test) : (a) sa WAPE à 1 mois est "
    "inférieure à celle de la médiane dans CHACUNE des deux sous-périodes "
    "(pré-validation et validation) ; (b) l'IC95 bootstrap par référence de son gain "
    "sur les 24 origines réunies est entièrement positif. Parmi les candidats qui "
    "passent, celui de plus faible WAPE sur les 24 origines. Sinon : la médiane reste.")


# ── Variables ────────────────────────────────────────────────────────────────
def variables_stationnaires(p: dr.Panel, o: int, h: int, m: np.ndarray) -> pd.DataFrame:
    X = dr.variables(p, o, h, m)
    tot = p.Y.sum(axis=0)
    med = max(float(np.median(tot[max(0, o - 11):o + 1])), 1e-9)
    X["marche_dernier_mois"] = tot[o] / med
    s = o + h - 12
    X["marche_meme_mois_an_passe"] = tot[s] / med if s >= 0 else np.nan
    prec = tot[max(0, o - 23):max(1, o - 11)].mean()
    X["marche_moy_12"] = tot[max(0, o - 11):o + 1].mean() / prec if prec > 0 else np.nan
    X["anciennete"] = np.minimum(X["anciennete"].values, 24.0)
    return X


def echelle_moyenne(X: pd.DataFrame, p: dr.Panel, o: int, m: np.ndarray) -> np.ndarray:
    return np.maximum(X["moy_12"].values, 0.5)


def echelle_robuste(X: pd.DataFrame, p: dr.Panel, o: int, m: np.ndarray) -> np.ndarray:
    """Moyenne des 12 derniers mois privée de son mois maximal."""
    w = p.Y[m, max(0, o - 11):o + 1]
    return np.maximum((w.sum(axis=1) - w.max(axis=1)) / max(w.shape[1] - 1, 1), 0.5)


VARIANTES: Dict[str, Tuple[Callable, Callable]] = {
    "lightgbm_actuel": (dr.variables, echelle_moyenne),
    "lightgbm_stationnaire": (variables_stationnaires, echelle_moyenne),
    "lightgbm_robuste": (variables_stationnaires, echelle_robuste),
}


def _jeu(p, origines_, h, fvar, fech, avec_cible=True):
    Xs, ys, es, rs, os_ = [], [], [], [], []
    T = p.Y.shape[1]
    for o in origines_:
        if avec_cible and o + h >= T:
            continue
        m = dr.eligibles(p, o)
        if not m.any():
            continue
        X = fvar(p, o, h, m)
        e = fech(X, p, o, m)
        for c in dr.COLONNES_QUANTITE:
            if c in X:
                X[c] = X[c] / e
        Xs.append(X); es.append(e)
        ys.append(p.Y[m, o + h] if avec_cible else np.full(m.sum(), np.nan))
        rs.append(np.flatnonzero(m)); os_.append(np.full(m.sum(), o))
    X = pd.concat(Xs, ignore_index=True)
    X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
    return X, np.concatenate(ys), np.concatenate(es), np.concatenate(rs), np.concatenate(os_)


def walk_forward(p, origines_, h, variante) -> pd.DataFrame:
    """Même protocole que le challenger publié : réentraîné tous les 3 mois sur
    les seules cibles connues à l'origine, mêmes réglages."""
    fvar, fech = VARIANTES[variante]
    T = p.Y.shape[1]
    modele, depuis, out = None, None, []
    for o in origines_:
        if o + h >= T:
            continue
        if modele is None or o - depuis >= dr.RAFRAICHISSEMENT:
            X, y, e, _, _ = _jeu(p, range(12, o - h + 1), h, fvar, fech)
            modele, depuis = dr._lgbm(dr.CHALLENGER["params"]), o
            modele.fit(X, y / e)
        X, y, e, r, oo = _jeu(p, [o], h, fvar, fech)
        out.append(pd.DataFrame({"origine": oo, "ref": r, "h": h, "y": y,
                                 "yhat": np.maximum(modele.predict(X) * e, 0.0)}))
    return pd.concat(out, ignore_index=True)


def regles(p, origines_, h) -> Dict[str, pd.DataFrame]:
    T = p.Y.shape[1]
    out: Dict[str, List[pd.DataFrame]] = {}
    for o in origines_:
        if o + h >= T:
            continue
        m = dr.eligibles(p, o)
        w = p.Y[m, max(0, o - 11):o + 1]
        y = p.Y[m, o + h]
        base = {"origine": o, "ref": np.flatnonzero(m), "h": h, "y": y}
        classes = np.array([dr.classe_demande(p.Y[r, max(0, o - 23):o + 1]) for r in np.flatnonzero(m)])
        for nom, v in (("mediane_12", np.median(w, axis=1)),
                       ("quantile_12_q55", np.quantile(w, 0.55, axis=1)),
                       ("quantile_12_q60", np.quantile(w, 0.60, axis=1))):
            out.setdefault(nom, []).append(pd.DataFrame({**base, "yhat": v, "classe": classes}))
    return {k: pd.concat(v, ignore_index=True) for k, v in out.items()}


def candidats(p, origines_, horizons=(1,)) -> Dict[str, pd.DataFrame]:
    res: Dict[str, List[pd.DataFrame]] = {}
    for h in horizons:
        rg = regles(p, origines_, h)
        for k, v in rg.items():
            res.setdefault(k, []).append(v)
        for var in VARIANTES:
            res.setdefault(var, []).append(walk_forward(p, origines_, h, var))
        med, rob = rg["mediane_12"], res["lightgbm_robuste"][-1]
        mm = med.merge(rob[["origine", "ref", "yhat"]], on=["origine", "ref"], suffixes=("", "_rob"))
        assert len(mm) == len(med) == len(rob)
        res.setdefault("combinaison_50_50", []).append(
            mm.assign(yhat=0.5 * mm.yhat + 0.5 * mm.yhat_rob)[["origine", "ref", "h", "y", "yhat"]])
        res.setdefault("hybride_par_classe", []).append(
            mm.assign(yhat=np.where(mm.classe == "reguliere", mm.yhat, mm.yhat_rob))[["origine", "ref", "h", "y", "yhat"]])
    return {k: pd.concat(v, ignore_index=True) for k, v in res.items()}


def _idx(p, mois):
    return int(np.flatnonzero(p.mois == pd.Timestamp(mois))[0])


def _mesures(df: pd.DataFrame, h: int = 1) -> Dict[str, float]:
    s = df[df.h == h]
    return {"wape": round(dr.wape(s.y.values, s.yhat.values), 2),
            "biais": round(dr.biais(s.y.values, s.yhat.values), 2),
            "mae": round(float(np.abs(s.y - s.yhat).mean()), 3), "n": int(len(s))}


def _cumul3(df: pd.DataFrame) -> float:
    c = df.groupby(["origine", "ref"]).agg(y=("y", "sum"), yhat=("yhat", "sum"), n=("h", "size"))
    c = c[c.n == 3]
    return round(dr.wape(c.y.values, c.yhat.values), 2)


def _duel(ref: pd.DataFrame, cand: pd.DataFrame) -> Dict[str, Any]:
    a = ref[ref.h == 1].sort_values(["origine", "ref"])
    b = cand[cand.h == 1].sort_values(["origine", "ref"])
    assert (a[["origine", "ref"]].values == b[["origine", "ref"]].values).all()
    return dr.ecart_bootstrap(a.y.values, a.yhat.values, b.yhat.values, a.ref.values)


def _empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


# ── Phase développement ─────────────────────────────────────────────────────
def phase_dev(extrait) -> Dict[str, Any]:
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    pre = list(range(_idx(p, PRE_VALIDATION[0]), _idx(p, PRE_VALIDATION[1]) + 1))
    val = dr.origines(p)["validation"]
    assert max(pre) < min(val) and len(pre) == 12
    per = {"pre_validation": candidats(p, pre), "validation": candidats(p, val)}
    noms = list(per["validation"])
    tableau, verdicts = {}, {}
    for n in noms:
        both = pd.concat([per["pre_validation"][n], per["validation"][n]], ignore_index=True)
        tableau[n] = {"pre_validation": _mesures(per["pre_validation"][n]),
                      "validation": _mesures(per["validation"][n]),
                      "developpement_24": _mesures(both)}
        if n == "mediane_12":
            continue
        ref_both = pd.concat([per["pre_validation"]["mediane_12"], per["validation"]["mediane_12"]], ignore_index=True)
        duel = _duel(ref_both, both)
        a = all(tableau[n][k]["wape"] < tableau["mediane_12"][k]["wape"] for k in ("pre_validation", "validation"))
        verdicts[n] = {"bat_la_mediane_dans_les_deux_sous_periodes": a, "duel_24_origines": duel,
                       "passe": bool(a and duel["ic95"][0] > 0)}
    passants = [n for n, v in verdicts.items() if v["passe"]]
    retenu = min(passants, key=lambda n: tableau[n]["developpement_24"]["wape"]) if passants else "mediane_12"
    res = {"regle_de_selection": REGLE_DE_SELECTION, "tableau": tableau, "verdicts": verdicts,
           "candidat_retenu": retenu,
           "controle_reproduction_lightgbm_actuel_validation": tableau["lightgbm_actuel"]["validation"]["wape"]}
    (RES / "pipeline_robuste_dev.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    PREENREGISTREMENT.write_text(json.dumps({
        "horodatage_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "candidat_retenu": retenu,
        "regle_de_selection": REGLE_DE_SELECTION,
        "regle_de_deploiement_plateforme": f"+{dr.SEUIL_GAIN_PTS} pts de WAPE à 1 mois sur le test et IC95 > 0",
        "sha256_script": _empreinte(Path(__file__)),
        "sha256_resultats_dev": _empreinte(RES / "pipeline_robuste_dev.json"),
        "reglages_lightgbm": dr.CHALLENGER["params"],
        "avertissement": ("Le test de 18 mois a déjà été lu une fois (comparaison publiée) et le "
                          "diagnostic l'a décomposé : ce qui suit est une CONFIRMATION, pas une "
                          "preuve indépendante. La preuve viendra des mois postérieurs à mars 2026."),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


# ── Phase test ──────────────────────────────────────────────────────────────
def phase_test(extrait) -> Dict[str, Any]:
    if not PREENREGISTREMENT.exists():
        raise SystemExit("Pas de pré-enregistrement : lancez d'abord --phase dev.")
    pre = json.loads(PREENREGISTREMENT.read_text(encoding="utf-8"))
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    test = dr.origines(p)["test"]
    res = candidats(p, test, horizons=dr.HORIZONS)
    tab = {}
    for n, df in res.items():
        tab[n] = {**_mesures(df), "wape_cumul_3_mois": _cumul3(df)}
        if n != "mediane_12":
            tab[n]["duel_contre_mediane_h1"] = _duel(res["mediane_12"], df)
    # Point prospectif : avril 2026, que personne n'a jamais utilisé (29 jours).
    q = dr.construire_panel(d, fin="2026-04")
    o = len(q.mois) - 2
    pros = {n: _mesures(df) for n, df in candidats(q, [o]).items()}
    out = {"preenregistrement": pre, "tableau_test": tab,
           "retenu": pre["candidat_retenu"],
           "point_prospectif_avril_2026": {"avertissement": "un seul mois, 29 jours sur 30 : indicatif",
                                            "mesures": pros}}
    (RES / "pipeline_robuste_test.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    pd.concat([df.assign(modele=n) for n, df in res.items()]).to_parquet(RES / "predictions_pipeline_robuste_test.parquet")
    return out


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--extrait")
    a.add_argument("--phase", choices=("dev", "test"), required=True)
    x = a.parse_args()
    r = phase_dev(x.extrait) if x.phase == "dev" else phase_test(x.extrait)
    print(json.dumps(r, indent=1, ensure_ascii=False)[:6000])
