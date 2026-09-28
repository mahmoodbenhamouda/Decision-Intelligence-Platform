"""
evaluation_demande/diagnostic.py
================================
Diagnostic de l'écart validation (≈ 32 %) → test (≈ 38 %), décomposition de
l'erreur du test, et comparaison LightGBM / médiane observation par observation.

Ce script DÉCRIT ; il ne choisit rien. Il lit les prévisions déjà produites par
`comparer_modeles.py` (aucun réentraînement, aucun réglage) et les données.
Rien dans ce qui suit ne modifie ni ne filtre les 18 mois de test : les
exclusions qui apparaissent (« hors janvier 2026 ») sont des lectures de
sensibilité, jamais des métriques de décision.

    python evaluation_demande/diagnostic.py [--extrait output/demande_reference]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting import demande_reference as dr  # noqa: E402

RES = RACINE / "evaluation_demande" / "resultats"


def _charger(extrait):
    d = dr.charger(extrait=Path(extrait) if extrait else None)
    p = dr.construire_panel(d)
    val = pd.read_parquet(RES / "predictions_validation.parquet")
    tst = pd.read_parquet(RES / "predictions_test.parquet")
    return d, p, val, tst


def _paires(df: pd.DataFrame, a: str, b: str, h: int = 1) -> pd.DataFrame:
    """Les deux méthodes sur EXACTEMENT les mêmes observations."""
    x = df[(df.modele == a) & (df.h == h)][["origine", "ref", "y", "yhat"]].rename(columns={"yhat": a})
    y = df[(df.modele == b) & (df.h == h)][["origine", "ref", "yhat"]].rename(columns={"yhat": b})
    m = x.merge(y, on=["origine", "ref"], how="inner")
    assert len(m) == len(x) == len(y), "les deux méthodes ne couvrent pas les mêmes observations"
    return m


def _contexte(p, m: pd.DataFrame, clients_publics: np.ndarray) -> pd.DataFrame:
    """Ce qu'on savait à l'origine de chaque observation."""
    med12 = np.array([np.median(p.Y[r, max(0, o - 11):o + 1]) for r, o in zip(m.ref, m.origine)])
    moy12 = np.array([p.Y[r, max(0, o - 11):o + 1].mean() for r, o in zip(m.ref, m.origine)])
    m = m.copy()
    m["med12"], m["moy12"] = med12, moy12
    m["mois"] = [p.mois[o + 1] for o in m.origine]
    m["classe"] = [dr.classe_demande(p.Y[r, max(0, o - 23):o + 1]) for r, o in zip(m.ref, m.origine)]
    ref_niv = np.maximum(med12, moy12)
    m["type_obs"] = np.select(
        [m.y == 0, m.y < 0.5 * ref_niv, (m.y > 2 * ref_niv) & (m.y > ref_niv + 3)],
        ["zero", "creux", "pic"], "normal")
    m["public"] = clients_publics[m.ref.values]
    return m


def _part_publique(d, p) -> np.ndarray:
    """Référence dont > 50 % du volume 2021-2023 va aux hôpitaux publics.
    Calculé AVANT la validation : aucune information de test."""
    noms = dict(zip(d.clients.client_code.astype(str), d.clients.client_name))
    L = d.lignes[(d.lignes.famille == dr.FAMILLE) & (d.lignes.mois < "2023-10-01")].copy()
    L["pub"] = L.client.astype(str).map(lambda c: dr.classer_etablissement(noms.get(c)) == "HOPITAL_PUBLIC")
    g = L.groupby("reference").apply(lambda s: s.qte.clip(lower=0)[s.pub].sum() / max(s.qte.clip(lower=0).sum(), 1e-9))
    return np.array([bool(g.get(r, 0) > 0.5) for r in p.refs])


def _wape(y, yh) -> float:
    return round(dr.wape(np.asarray(y, float), np.asarray(yh, float)), 2)


def ecart_validation_test(p, val, tst, pub) -> Dict[str, Any]:
    """Pourquoi toutes les méthodes perdent 6 à 8 points entre les deux périodes."""
    out: Dict[str, Any] = {}
    for nom, df in (("validation", val), ("test", tst)):
        m = _contexte(p, _paires(df, "mediane_12", "lightgbm"), pub)
        # Plafond « oracle » : chaque mois prévu par la médiane des 3 mois qui
        # l'entourent (AVANT et APRÈS, lui exclu). Irréalisable — il lit le futur
        # — il mesure le bruit mensuel qu'aucune méthode ne peut expliquer.
        orac = np.array([np.median(np.r_[p.Y[r, max(0, o + 1 - 3):o + 1], p.Y[r, o + 2:o + 5]])
                         for r, o in zip(m.ref, m.origine)])
        # Oracle de niveau : médiane réelle des 12 mois centrés, le mois cible
        # exclu (lit le futur) — le meilleur « niveau local » qu'on puisse espérer.
        orac_niv = np.array([np.median(np.r_[p.Y[r, max(0, o + 1 - 6):o + 1], p.Y[r, o + 2:o + 8]])
                             for r, o in zip(m.ref, m.origine)])
        # Oracle constant : pour chaque référence, LA constante qui minimise l'erreur
        # absolue sur la période elle-même (sa médiane réelle sur la période). Aucune
        # prévision « de niveau », même clairvoyante, ne fait mieux en moyenne.
        med_periode = m.groupby("ref").y.transform("median")
        vol = m.y.sum()
        out[nom] = {
            "wape_mediane_12": _wape(m.y, m.mediane_12),
            "wape_lightgbm": _wape(m.y, m.lightgbm),
            "plafond_oracle_voisinage_pct": _wape(m.y, orac),
            "plafond_oracle_niveau_annuel_pct": _wape(m.y, orac_niv),
            "plafond_oracle_constante_par_reference_pct": _wape(m.y, med_periode),
            "biais_mediane_pct": round(dr.biais(m.y.values, m.mediane_12.values), 2),
            "volatilite_ponderee": round(float((np.abs(m.y - m.med12)).sum() / max(m.med12.sum(), 1e-9)), 3),
            "part_volume_en_pics_pct": round(100 * m.y[m.type_obs == "pic"].sum() / vol, 1),
            "part_volume_refs_hopitaux_publics_pct": round(100 * m.y[m.public].sum() / vol, 1),
            "wape_mediane_refs_publiques": _wape(m.y[m.public], m.mediane_12[m.public]),
            "wape_mediane_refs_non_publiques": _wape(m.y[~m.public], m.mediane_12[~m.public]),
            "croissance_volume_vs_niveau_12m_pct": round(100 * (vol / m.moy12.sum() - 1), 1),
            "observations": int(len(m)),
        }
    v, t = out["validation"], out["test"]
    out["lecture"] = {
        "degradation_mediane_pts": round(t["wape_mediane_12"] - v["wape_mediane_12"], 2),
        "degradation_lightgbm_pts": round(t["wape_lightgbm"] - v["wape_lightgbm"], 2),
        "degradation_plafond_oracle_pts": round(t["plafond_oracle_voisinage_pct"] - v["plafond_oracle_voisinage_pct"], 2),
        "optimisme_de_selection_estime_pts": round(
            (t["wape_lightgbm"] - v["wape_lightgbm"]) - (t["wape_mediane_12"] - v["wape_mediane_12"]), 2),
    }
    return out


def decomposition_test(p, tst, pub) -> Dict[str, Any]:
    m = _contexte(p, _paires(tst, "mediane_12", "lightgbm"), pub)
    m["e_med"] = (m.y - m.mediane_12).abs()
    m["e_lgb"] = (m.y - m.lightgbm).abs()
    tot_med, tot_lgb, vol = m.e_med.sum(), m.e_lgb.sum(), m.y.sum()
    out: Dict[str, Any] = {"wape": {"mediane_12": _wape(m.y, m.mediane_12), "lightgbm": _wape(m.y, m.lightgbm)},
                           "mae": {"mediane_12": round(float(m.e_med.mean()), 3), "lightgbm": round(float(m.e_lgb.mean()), 3)},
                           "biais_pct": {"mediane_12": round(dr.biais(m.y.values, m.mediane_12.values), 2),
                                         "lightgbm": round(dr.biais(m.y.values, m.lightgbm.values), 2)}}
    pm = m.groupby("mois").agg(y=("y", "sum"), e_med=("e_med", "sum"), e_lgb=("e_lgb", "sum"),
                               p_med=("mediane_12", "sum"), p_lgb=("lightgbm", "sum"))
    pm["part_erreur_mediane_pct"] = (100 * pm.e_med / tot_med).round(1)
    pm["part_erreur_lightgbm_pct"] = (100 * pm.e_lgb / tot_lgb).round(1)
    pm["biais_lightgbm_pct"] = (100 * (pm.p_lgb - pm.y) / pm.y).round(1)
    pm["biais_mediane_pct"] = (100 * (pm.p_med - pm.y) / pm.y).round(1)
    pm["wape_mediane"] = (100 * pm.e_med / pm.y).round(1)
    pm["wape_lightgbm"] = (100 * pm.e_lgb / pm.y).round(1)
    out["par_mois"] = {str(k.date()): v for k, v in pm[[
        "y", "wape_mediane", "wape_lightgbm", "part_erreur_mediane_pct", "part_erreur_lightgbm_pct",
        "biais_mediane_pct", "biais_lightgbm_pct"]].round(1).to_dict("index").items()}
    out["dix_mois_les_plus_couteux_lightgbm"] = [str(k.date()) for k in pm.e_lgb.sort_values(ascending=False).index[:10]]
    out["dix_mois_les_plus_couteux_mediane"] = [str(k.date()) for k in pm.e_med.sort_values(ascending=False).index[:10]]
    out["part_erreur_10_mois_lightgbm_pct"] = round(float(100 * pm.e_lgb.sort_values(ascending=False).head(10).sum() / tot_lgb), 1)
    out["mois_surestimes_lightgbm"] = [str(k.date()) for k in pm.index[pm.biais_lightgbm_pct > 5]]
    out["mois_sousestimes_lightgbm"] = [str(k.date()) for k in pm.index[pm.biais_lightgbm_pct < -5]]

    pr = m.groupby("ref").agg(y=("y", "sum"), e_med=("e_med", "sum"), e_lgb=("e_lgb", "sum"))
    pr = pr.sort_values("e_lgb", ascending=False)
    out["references_les_plus_couteuses"] = [
        {"reference": p.refs[i], "designation": p.designation[i][:40], "volume": float(r.y),
         "part_erreur_lightgbm_pct": round(float(100 * r.e_lgb / tot_lgb), 1),
         "part_erreur_mediane_pct": round(float(100 * r.e_med / tot_med), 1),
         "hopital_public": bool(pub[i])} for i, r in pr.head(10).iterrows()]
    out["part_erreur_10_references_lightgbm_pct"] = round(float(100 * pr.e_lgb.head(10).sum() / tot_lgb), 1)
    out["part_erreur_50_references_lightgbm_pct"] = round(float(100 * pr.e_lgb.head(50).sum() / tot_lgb), 1)

    def bloc(col):
        g = m.groupby(col).agg(obs=("y", "size"), y=("y", "sum"), e_med=("e_med", "sum"), e_lgb=("e_lgb", "sum"),
                               p_med=("mediane_12", "sum"), p_lgb=("lightgbm", "sum"))
        return {str(k): {"observations": int(r.obs), "part_volume_pct": round(100 * r.y / vol, 1),
                         "part_erreur_mediane_pct": round(100 * r.e_med / tot_med, 1),
                         "part_erreur_lightgbm_pct": round(100 * r.e_lgb / tot_lgb, 1),
                         "surprevision_mediane_unites": round(float(r.p_med - r.y), 0),
                         "surprevision_lightgbm_unites": round(float(r.p_lgb - r.y), 0)}
                for k, r in g.iterrows()}
    out["par_type_d_observation"] = bloc("type_obs")
    out["par_classe_de_demande"] = bloc("classe")
    out["par_clientele"] = bloc(m.public.map({True: "hopitaux_publics", False: "autres"}))

    # LightGBM vs médiane, observation par observation
    diff = m.e_med - m.e_lgb
    tol = np.maximum(1.0, 0.05 * m.y)
    etat = np.select([diff > tol, diff < -tol], ["lightgbm_meilleur", "mediane_meilleure"], "similaires")
    g = pd.DataFrame({"etat": etat, "gain": diff, "y": m.y, "type": m.type_obs, "classe": m.classe})
    out["duel_par_observation"] = {
        k: {"observations": int((etat == k).sum()), "part_obs_pct": round(100 * (etat == k).mean(), 1),
            "unites_d_erreur_evitees_par_lightgbm": round(float(g.gain[etat == k].sum()), 0),
            "type_dominant": g.type[etat == k].value_counts().head(3).to_dict()}
        for k in ("lightgbm_meilleur", "mediane_meilleure", "similaires")}
    out["duel_par_type"] = {t: {"lightgbm_meilleur": int(((etat == "lightgbm_meilleur") & (m.type_obs == t)).sum()),
                                "mediane_meilleure": int(((etat == "mediane_meilleure") & (m.type_obs == t)).sum()),
                                "erreur_nette_evitee_par_lightgbm": round(float(diff[m.type_obs == t].sum()), 0)}
                            for t in ("pic", "creux", "zero", "normal")}
    k = m.mois != pd.Timestamp("2026-01-01")
    out["sensibilite_hors_janvier_2026"] = {"mediane_12": _wape(m.y[k], m.mediane_12[k]),
                                            "lightgbm": _wape(m.y[k], m.lightgbm[k]),
                                            "avertissement": "lecture de sensibilité, jamais une métrique de décision"}
    return out


def main(extrait=None) -> Dict[str, Any]:
    d, p, val, tst = _charger(extrait)
    pub = _part_publique(d, p)
    res = {"ecart_validation_test": ecart_validation_test(p, val, tst, pub),
           "decomposition_test": decomposition_test(p, tst, pub),
           "references_majoritairement_hopitaux_publics": int(pub.sum())}
    (RES / "diagnostic.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


if __name__ == "__main__":  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument("--extrait", default=None)
    r = main(ap.parse_args().extrait)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str)[:6000])
