"""
evaluation_demande/propagation.py
=================================
Comment un pic se propage-t-il dans la prévision de LightGBM ?

Questions traitées (toutes au moment de la prévision, sans lire le futur) :

  1. Le pic de décembre 2025 est-il repris par les retards (lag_*), les moyennes
     glissantes (moy_*, med_*), la croissance (croissance_12, moy_12_precedente)
     ou le marché (marche_*) ? → contributions TreeSHAP exactes, converties en
     unités de demande.
  2. Le modèle lit-il un pic ponctuel comme une hausse durable ? → part de la
     prévision de janvier qui vient de l'ÉCHELLE (moy_12, contaminée par le pic)
     et part qui vient de la FORME apprise (prévision / échelle).
  3. Ce pic était-il prévisible à l'origine ? → contrefactuel : décembre remplacé,
     dans les VARIABLES seulement, par la médiane 12 mois de chaque référence.
  4. Le même comportement existe-t-il sur les pics historiques (déc. 2021,
     oct. 2022, déc. 2022, déc. 2023) ? → même modèle, mêmes réglages, entraîné à
     chacune de ces origines sur le seul passé.
  5. Un détecteur de pic robuste, disponible à l'origine, isole-t-il les mois
     où LightGBM décroche ? → règle « marché du dernier mois > 1,3 × médiane 12
     mois du marché », appliquée à toutes les origines AVANT le test.

Le test n'est lu qu'aux points (1)-(3), qui décrivent une prévision déjà
publiée ; rien ici ne sert à choisir un modèle.

    python evaluation_demande/propagation.py --extrait output/demande_reference
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting import demande_reference as dr  # noqa: E402

RES = RACINE / "evaluation_demande" / "resultats"

FAMILLES_VARIABLES = {
    "retards (lag_0..lag_11)": lambda c: c.startswith("lag_"),
    "saisonnalité (saison_1, saison_2, mois_cible)": lambda c: c in ("saison_1", "saison_2", "mois_cible"),
    "moyennes glissantes (moy_*, med_*, max, écart-type)": lambda c: c.startswith(("moy_", "med_", "max_", "ecart_type"))
    and c != "moy_12_precedente",
    "croissance (croissance_12, moy_12_precedente)": lambda c: c in ("croissance_12", "moy_12_precedente"),
    "marché (marche_*)": lambda c: c.startswith("marche_"),
    "intermittence (zéros, ADI, CV², ancienneté)": lambda c: c in (
        "part_zeros_12", "adi", "cv2", "mois_depuis_derniere_vente", "anciennete", "mois_actifs_24"),
    "clientèle et prix": lambda c: c.startswith(("part_", "hhi", "n_clients", "prix")),
    "approvisionnement": lambda c: c in ("achats_3", "achats_12", "position_fin"),
}


def _famille(col: str) -> str:
    for nom, test in FAMILLES_VARIABLES.items():
        if test(col):
            return nom
    return "autres (gamme, horizon)"


def idx(p, mois: str) -> int:
    return int(np.flatnonzero(p.mois == pd.Timestamp(mois))[0])


def expliquer(p, o: int, modele=None) -> Dict[str, Any]:
    """Prévision à 1 mois depuis l'origine `o`, décomposée."""
    modele = modele or dr.entrainer_lgbm(p, o, 1)
    m = dr.eligibles(p, o)
    X = dr.variables(p, o, 1, m)
    X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
    Xn, e = dr._normaliser(X, True)
    contrib = modele.predict(Xn, pred_contrib=True)          # espace normalisé
    g = contrib.sum(axis=1)
    pred = np.maximum(g * e, 0.0)
    y = p.Y[m, o + 1] if o + 1 < p.Y.shape[1] else None
    med12 = X["med_12"].values
    cols = list(Xn.columns)
    # Contributions en UNITÉS : contribution normalisée × échelle de la référence.
    unites = contrib[:, :-1] * e[:, None]
    base = float((contrib[:, -1] * e).sum())
    par_fam: Dict[str, float] = {}
    for j, c in enumerate(cols):
        par_fam[_famille(c)] = par_fam.get(_famille(c), 0.0) + float(unites[:, j].sum())
    top = sorted(((c, float(unites[:, j].sum())) for j, c in enumerate(cols)), key=lambda t: -abs(t[1]))[:8]
    out = {
        "origine": str(p.mois[o].date())[:7], "cible": str(p.mois[o + 1].date())[:7] if o + 1 < len(p.mois) else None,
        "references": int(m.sum()),
        "prevision_lightgbm": round(float(pred.sum())),
        "prevision_mediane_12": round(float(med12.sum())),
        "echelle_moy_12": round(float(e.sum())),
        "forme_moyenne_ponderee": round(float(pred.sum() / e.sum()), 3),
        "valeur_de_base_en_unites": round(base),
        "contributions_par_famille_unites": {k: round(v) for k, v in sorted(par_fam.items(), key=lambda t: -abs(t[1]))},
        "huit_variables_les_plus_influentes_unites": {c: round(v) for c, v in top},
    }
    if y is not None:
        out["reel"] = float(y.sum())
        out["wape_lightgbm"] = round(dr.wape(y, pred), 2)
        out["wape_mediane_12"] = round(dr.wape(y, med12), 2)
        out["biais_lightgbm_pct"] = round(dr.biais(y, pred), 1)
        out["biais_mediane_pct"] = round(dr.biais(y, med12), 1)
    return out, modele, pred


def contrefactuel(p, o: int, modele) -> Dict[str, Any]:
    """Même modèle, mêmes réglages ; seul le mois de l'origine est remplacé, dans
    les variables, par la médiane des 12 mois qui le précèdent. La cible n'est
    jamais touchée : on mesure ce que le pic a AJOUTÉ à la prévision."""
    import copy
    q = copy.deepcopy(p)
    m = dr.eligibles(p, o)
    normal = np.median(p.Y[:, o - 12:o], axis=1)
    q.Y[:, o] = normal
    X0 = dr.variables(p, o, 1, m)
    X1 = dr.variables(q, o, 1, m)
    res = {}
    for nom, X in (("observe", X0), ("pic_neutralise", X1)):
        X = X.copy()
        X["gamme"] = pd.Categorical(X["gamme"].astype(str), categories=sorted(set(p.gamme)))
        Xn, e = dr._normaliser(X, True)
        res[nom] = (np.maximum(modele.predict(Xn) * e, 0), X["med_12"].values, e)
    y = p.Y[m, o + 1]
    return {
        "prevision_lightgbm_observee": round(float(res["observe"][0].sum())),
        "prevision_lightgbm_pic_neutralise": round(float(res["pic_neutralise"][0].sum())),
        "prevision_mediane_12_observee": round(float(res["observe"][1].sum())),
        "prevision_mediane_12_pic_neutralise": round(float(res["pic_neutralise"][1].sum())),
        "echelle_observee": round(float(res["observe"][2].sum())),
        "echelle_pic_neutralise": round(float(res["pic_neutralise"][2].sum())),
        "reel": float(y.sum()),
        "wape_lightgbm_pic_neutralise": round(dr.wape(y, res["pic_neutralise"][0]), 2),
        "part_du_surcroit_venant_de_l_echelle_pct": None,
    }


def pics_historiques(p) -> List[Dict[str, Any]]:
    """Mêmes réglages, entraînés à chaque origine sur le seul passé."""
    out = []
    for mois in ("2021-12-01", "2022-10-01", "2022-12-01", "2023-06-01", "2023-12-01",
                 "2024-06-01", "2024-12-01", "2025-11-01", "2025-12-01"):
        o = idx(p, mois)
        if o < 18:
            continue
        r, _, _ = expliquer(p, o)
        tot = p.Y.sum(axis=0)
        r["marche_origine_sur_mediane_12"] = round(float(tot[o] / np.median(tot[o - 12:o])), 2)
        r.pop("huit_variables_les_plus_influentes_unites", None)
        out.append(r)
    return out


def detecteur(p, jusqu_a: str = "2024-09-01", seuil: float = 1.3) -> Dict[str, Any]:
    """Toutes les origines de 2022-06 à la fin de la validation : LightGBM
    (réentraîné tous les 3 mois) contre médiane, séparées par le détecteur.
    AUCUNE origine de test."""
    tot = p.Y.sum(axis=0)
    o0, o1 = idx(p, "2022-06-01"), idx(p, jusqu_a) - 1
    orig = list(range(o0, o1 + 1))
    yh, y, r, oo = dr.walk_forward_appris(
        p, orig, 1, lambda o: dr.entrainer_lgbm(p, o, 1),
        lambda mod, o, m: dr.predire_lgbm(mod, p, o, 1, m))
    med = np.concatenate([np.median(p.Y[dr.eligibles(p, o), o - 11:o + 1], axis=1) for o in orig if o + 1 < p.Y.shape[1]])
    flag = np.array([tot[o] > seuil * np.median(tot[o - 12:o]) for o in oo])
    lignes = []
    for o in orig:
        s = oo == o
        lignes.append({"origine": str(p.mois[o].date())[:7], "pic_detecte": bool(tot[o] > seuil * np.median(tot[o - 12:o])),
                       "wape_lightgbm": round(dr.wape(y[s], yh[s]), 1), "wape_mediane": round(dr.wape(y[s], med[s]), 1),
                       "biais_lightgbm": round(dr.biais(y[s], yh[s]), 1), "biais_mediane": round(dr.biais(y[s], med[s]), 1)})
    bloc = {}
    for nom, s in (("apres_pic_detecte", flag), ("autres_origines", ~flag)):
        bloc[nom] = {"origines": int(len(set(oo[s]))),
                     "wape_lightgbm": round(dr.wape(y[s], yh[s]), 2), "wape_mediane": round(dr.wape(y[s], med[s]), 2),
                     "biais_lightgbm": round(dr.biais(y[s], yh[s]), 1), "biais_mediane": round(dr.biais(y[s], med[s]), 1)}
    return {"seuil": seuil, "periode": f"origines {p.mois[o0].date()} → {p.mois[o1].date()} (avant le test)",
            "blocs": bloc, "par_origine": lignes}


def main(extrait=None) -> Dict[str, Any]:
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    o = idx(p, "2025-12-01")
    jan, modele, pred = expliquer(p, o)
    # Contrôle de reproduction : la prévision publiée pour janvier 2026.
    t = pd.read_parquet(RES / "predictions_test.parquet")
    pub = t[(t.modele == "lightgbm") & (t.h == 1) & (t.origine == o)].sort_values("ref")
    ecart_repro = float(np.abs(np.sort(pub.yhat.values) - np.sort(pred)).max())
    normal, _, _ = expliquer(p, idx(p, "2025-09-01"))
    cf = contrefactuel(p, o, modele)
    surcroit = cf["prevision_lightgbm_observee"] - cf["prevision_lightgbm_pic_neutralise"]
    d_ech = cf["echelle_observee"] - cf["echelle_pic_neutralise"]
    cf["surcroit_du_au_pic_unites"] = surcroit
    cf["hausse_d_echelle_unites"] = d_ech
    cf["forme_moyenne_observee"] = jan["forme_moyenne_ponderee"]
    # Si la forme était restée celle du contrefactuel, le surcroît dû à l'échelle
    # seule vaut forme_cf × Δéchelle.
    forme_cf = cf["prevision_lightgbm_pic_neutralise"] / max(cf["echelle_pic_neutralise"], 1)
    cf["part_du_surcroit_venant_de_l_echelle_pct"] = round(100 * forme_cf * d_ech / max(surcroit, 1), 1)
    res = {
        "reproduction_prevision_publiee_ecart_max_unites": round(ecart_repro, 4),
        "janvier_2026_depuis_decembre_2025": jan,
        "origine_normale_septembre_2025": normal,
        "contrefactuel_decembre_neutralise": cf,
        "pics_historiques": pics_historiques(p),
        "detecteur_de_pic_avant_test": detecteur(p),
    }
    (RES / "propagation.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--extrait")
    print(json.dumps(main(a.parse_args().extrait), indent=1, ensure_ascii=False))
