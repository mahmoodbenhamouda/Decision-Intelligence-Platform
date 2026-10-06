"""Analyse de la DEMANDE & de l'APPROVISIONNEMENT (sans données de stock ERP)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

#: Erreur moyenne au-delà de laquelle une prévision cesse d'être un chiffre
#: d'action. Seuil DÉCLARÉ avant mesure, pas ajusté après coup.
#:
#: Sur l'entreprise entière, l'erreur tourne autour de 16 % : la demande agrégée
#: est régulière. Restreinte à un établissement, elle grimpe au-delà de 200 % —
#: un hôpital commande par à-coups, et une moyenne n'a plus de sens. Publier ce
#: chiffre comme les autres laisserait croire qu'il se décide pareil.
MAPE_MAXIMALE_EXPLOITABLE = 40.0


def _connect(data_dir: Optional[Path] = None):
    import duckdb
    try:
        from ml_engine.analytics.kpi_engine import STORE_PATH
        db = str(STORE_PATH)
    except Exception:
        db = str(Path(__file__).resolve().parents[2] / "output" / "analytics_store.duckdb")
    return duckdb.connect(db, read_only=True)


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    a, p = np.asarray(actual, float), np.asarray(pred, float)
    mask = a != 0
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((a[mask] - p[mask]) / a[mask])) * 100)


def _predict(hist: np.ndarray, method: str) -> float:
    if method == "saisonnier" and len(hist) >= 12:
        return float(hist[-12])
    if method == "saisonnier_croissance" and len(hist) >= 15:
        base = hist[-12]
        recent = hist[-3:].mean()
        ref = hist[-15:-12].mean()
        factor = (recent / ref) if ref else 1.0
        return float(base * min(2.0, max(0.5, factor)))
    if method == "moyenne_mobile":
        return float(hist[-3:].mean())
    w = hist[-12:] if len(hist) >= 12 else hist
    x = np.arange(len(w))
    return float(np.polyval(np.polyfit(x, w, 1), len(w)))


_METHODS = ["saisonnier", "saisonnier_croissance", "moyenne_mobile", "tendance"]


def _backtest(q: np.ndarray, horizon: int = 12) -> Dict[str, float]:
    """MAPE de chaque méthode sur les `horizon` derniers mois (walk-forward)."""
    out: Dict[str, float] = {}
    if len(q) <= horizon + 12:
        horizon = max(3, len(q) // 4)
    for m in _METHODS:
        errs = []
        for i in range(len(q) - horizon, len(q)):
            pred = _predict(q[:i], m)
            if q[i]:
                errs.append(abs((q[i] - pred) / q[i]) * 100)
        if errs:
            out[m] = round(float(np.mean(errs)), 1)
    return out


def _forecast(q: np.ndarray, method: str, h: int = 3) -> List[float]:
    hist = list(q)
    preds = []
    for _ in range(h):
        p = _predict(np.array(hist), method)
        p = max(0.0, p)
        preds.append(round(p, 0))
        hist.append(p)
    return preds


def compute_supply_demand(filters: Optional[Dict[str, Any]] = None,
                          data_dir: Optional[Path] = None) -> Dict[str, Any]:
    con = _connect(data_dir)
    out: Dict[str, Any] = {}

    # PÉRIMÈTRE. Un filtre client restreint la demande : celle d'un
    # établissement se prévoit comme celle de l'entreprise entière, tant qu'il
    # reste assez d'historique mensuel. En dessous, le modèle refuse plutôt que
    # d'extrapoler sur trois points — et le dit.
    clients = list((filters or {}).get("selected_clients") or [])
    ou = ""
    if clients:
        vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in clients)
        ou = f" AND client IN ({vals})"
    out["perimetre"] = {
        "n_clients": len(clients),
        "libelle": (f"{len(clients)} client(s) filtré(s)" if clients
                    else "entreprise entière"),
    }

    rows = con.execute(
        "SELECT strftime(date,'%Y-%m') m, sum(nbr_article) q "
        f"FROM sales WHERE date IS NOT NULL{ou} GROUP BY m ORDER BY m"
    ).fetchall()
    months = [r[0] for r in rows]
    q = np.array([float(r[1] or 0) for r in rows])
    out["demande_mensuelle"] = [{"period": m, "qte": float(v)} for m, v in zip(months, q)]

    fait = False
    try:
        from ml_engine.forecasting import demande_hybride as dh

        mois_h, serie = dh.charger_serie(clients=clients or None)
        if len(serie) < dh.MIN_TRAIN and clients:
            out["demande_motif"] = (
                f"Historique trop court pour prévoir sur ce périmètre : "
                f"{len(serie)} mois de commandes, {dh.MIN_TRAIN} nécessaires. "
                "La prévision reste disponible sans filtre client.")
        if len(serie) >= dh.MIN_TRAIN:
            ev = dh.evaluer(mois_h, serie)
            if ev.get("applicable"):
                methode = ev["socle_fixe_retenu"]
                debut_test = max(dh.MIN_TRAIN, len(serie) - dh.N_TEST)
                quantiles = dh._quantiles_erreur(serie, mois_h, methode, debut_test)
                prev = dh.prevoir(mois_h, serie, h_max=3,
                                  socle_fixe=methode, quantiles=quantiles)
                out["demande_prevision"] = [
                    {"period": p["period"], "qte": p["qte"],
                     "bas": (p.get("intervalle_80") or {}).get("bas"),
                     "haut": (p.get("intervalle_80") or {}).get("haut"),
                     "fiabilite": p.get("fiabilite")}
                    for p in prev
                ]
                out["demande_mape"] = ev["mape_socle_seul_pct"]
                out["demande_methode"] = methode
                out["demande_ic95"] = ev.get("ic95_hybride")
                out["demande_source"] = "hybride"
                fait = True
    except Exception:
        fait = False

    if not fait and len(q) >= 6:
        bt = _backtest(q)
        best = min(bt, key=bt.get) if bt else "saisonnier"
        fc = _forecast(q, best, h=3)
        from datetime import datetime
        last = datetime.strptime(months[-1], "%Y-%m")
        fut = []
        yy, mm = last.year, last.month
        for i in range(3):
            mm += 1
            if mm > 12:
                mm = 1; yy += 1
            fut.append(f"{yy:04d}-{mm:02d}")
        out["demande_backtest_mape"] = bt
        out["demande_methode"] = best
        out["demande_mape"] = bt.get(best)
        out["demande_prevision"] = [{"period": p, "qte": v} for p, v in zip(fut, fc)]
        out["demande_source"] = "backtest_local"
    elif not fait:
        out["demande_prevision"] = []
        out["demande_mape"] = None

    # FIABILITÉ. Une prévision dont l'erreur dépasse le seuil déclaré reste
    # affichée — la cacher laisserait croire à une panne — mais elle est
    # étiquetée comme non exploitable, avec son chiffre. Un directeur doit
    # pouvoir distinguer « 8 200 articles ± 16 % » de « 266 ± 228 % ».
    mape = out.get("demande_mape")
    out["demande_seuil_mape"] = MAPE_MAXIMALE_EXPLOITABLE
    out["demande_exploitable"] = bool(
        mape is not None and mape <= MAPE_MAXIMALE_EXPLOITABLE)
    if mape is not None and not out["demande_exploitable"]:
        out["demande_reserve"] = (
            f"Erreur moyenne de {mape:.0f} % sur les mois de contrôle, pour un "
            f"maximum exploitable fixé à {MAPE_MAXIMALE_EXPLOITABLE:.0f} %. "
            + ("La demande d'un seul établissement arrive par à-coups : une "
               "moyenne mensuelle n'y a pas de sens. Cette prévision situe un "
               "ordre de grandeur, elle ne se budgète pas."
               if clients else
               "Cette prévision situe un ordre de grandeur, elle ne se "
               "budgète pas."))

    sup = con.execute(
        "SELECT fournisseur, sum(ttc) t, count(*) n FROM purchases "
        "WHERE fournisseur IS NOT NULL GROUP BY fournisseur ORDER BY t DESC NULLS LAST"
    ).fetchall()
    con.close()
    tot = sum(float(s[1] or 0) for s in sup) or 1.0
    top = [{"fournisseur": s[0], "part_pct": round(float(s[1] or 0) / tot * 100, 1),
            "achats_dt": float(s[1] or 0), "n_factures": int(s[2] or 0)} for s in sup[:5]]
    hhi = float(sum((float(s[1] or 0) / tot * 100) ** 2 for s in sup))
    top1 = top[0]["part_pct"] if top else 0.0
    top3 = round(sum(t["part_pct"] for t in top[:3]), 1)
    out["fournisseurs_nb"] = len(sup)
    out["fournisseurs_hhi"] = round(hhi, 0)
    out["fournisseur_top1_pct"] = top1
    out["fournisseurs_top3_pct"] = top3
    out["fournisseurs_top"] = top
    out["dependance_fournisseur"] = (
        "critique" if top1 >= 50 else "élevée" if top1 >= 30 else "modérée" if top1 >= 15 else "faible"
    )
    return out


def save_metrics_report(d: Optional[Dict[str, Any]] = None) -> Path:
    """Écrit reports/demand_forecast_metrics.json (méthodologie + backtest MAPE)."""
    import json
    d = d or compute_supply_demand()
    reports = Path(__file__).resolve().parents[2] / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    metrics = {
        "cible": "volume mensuel d'articles vendus, faute de relevé de stock",
        "validation": "backtest walk-forward sur les 12 derniers mois (MAPE par méthode)",
        "methodes_testees": _METHODS,
        "backtest_mape_par_methode": d.get("demande_backtest_mape"),
        "methode_retenue": d.get("demande_methode"),
        "mape_retenue_pct": d.get("demande_mape"),
        "n_mois_historique": len(d.get("demande_mensuelle") or []),
        "prevision_3_mois": d.get("demande_prevision"),
        "dependance_fournisseur": {
            "hhi": d.get("fournisseurs_hhi"),
            "top1_pct": d.get("fournisseur_top1_pct"),
            "top3_pct": d.get("fournisseurs_top3_pct"),
            "niveau": d.get("dependance_fournisseur"),
        },
        "limites": (
            "La demande est mesurée en volume d'articles facturés , "
            "faute de relevé de stock ou de mouvements par produit. "
            "Ce proxy capte la demande servie, pas la demande latente (ruptures invisibles)."
        ),
    }
    p = reports / "demand_forecast_metrics.json"
    p.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    d = compute_supply_demand()
    print("=== Demande & Approvisionnement ===")
    print(f"Historique : {len(d['demande_mensuelle'])} mois")
    print(f"Backtest MAPE par méthode : {d.get('demande_backtest_mape')}")
    print(f"Méthode retenue : {d.get('demande_methode')} (MAPE {d.get('demande_mape')}%)")
    print(f"Prévision 3 mois : {[(p['period'], int(p['qte'])) for p in d.get('demande_prevision', [])]}")
    print(f"\nFournisseurs : {d['fournisseurs_nb']} | HHI {d['fournisseurs_hhi']} | "
          f"dépendance {d['dependance_fournisseur']}")
    print(f"Top 1 : {d['fournisseurs_top'][0]['fournisseur']} = {d['fournisseur_top1_pct']}% des achats")
    print(f"Top 3 = {d['fournisseurs_top3_pct']}% des achats")
    print(f"Métriques écrites : {save_metrics_report(d)}")
