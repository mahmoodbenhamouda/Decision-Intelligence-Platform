"""Surveillance de la dérive — un modèle qui vieillit doit se signaler lui-même."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[1]

REPORTS_DIR = BASE / "reports"
MODELS_DIR = BASE / "models"

PSI_STABLE = 0.10
PSI_MODERE = 0.25

AGE_ALERTE_JOURS = 180
AGE_CRITIQUE_JOURS = 365

VARIABLES_DERIVE_ATTENDUE = {
    "anciennete_j": ("l'ancienneté d'un client croît d'un jour par jour : son "
                     "déplacement est arithmétique, pas comportemental"),
}

DERIVE_CIBLE_MAX = 0.50


def psi(attendu: np.ndarray, observe: np.ndarray, n_bacs: int = 10) -> float:
    """Indice de stabilité de population entre deux échantillons."""
    attendu = np.asarray(attendu, float)
    observe = np.asarray(observe, float)
    attendu = attendu[np.isfinite(attendu)]
    observe = observe[np.isfinite(observe)]
    if len(attendu) < 20 or len(observe) < 20:
        return float("nan")

    bornes = np.unique(np.quantile(attendu, np.linspace(0, 1, n_bacs + 1)))
    if len(bornes) < 3:
        return 0.0
    bornes[0], bornes[-1] = -np.inf, np.inf

    a, _ = np.histogram(attendu, bins=bornes)
    o, _ = np.histogram(observe, bins=bornes)
    pa = np.clip(a / max(a.sum(), 1), 1e-4, None)
    po = np.clip(o / max(o.sum(), 1), 1e-4, None)
    return float(np.sum((po - pa) * np.log(po / pa)))


def _niveau_psi(v: float) -> str:
    if not np.isfinite(v):
        return "indeterminé"
    if v < PSI_STABLE:
        return "stable"
    return "modere" if v < PSI_MODERE else "eleve"


def _age_modele(nom_artefact: str) -> Optional[int]:
    """Jours écoulés depuis la dernière écriture de l'artefact."""
    p = MODELS_DIR / nom_artefact
    if not p.exists():
        return None
    return (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).days


def surveiller_churn() -> Dict[str, Any]:
    """Compare la période récente à la période d'entraînement."""
    try:
        from ml_engine.analytics import churn_model as cm
    except Exception as e:
        return {"applicable": False, "motif": f"module indisponible ({type(e).__name__})"}

    try:
        panel = cm.construire_panel(cm.charger_factures())
    except Exception as e:
        return {"applicable": False, "motif": f"panel non reconstructible ({type(e).__name__})"}

    if panel.empty or len(panel) < 500:
        return {"applicable": False, "motif": "panel trop court"}

    coupure = panel["date_obs"].quantile(0.75)
    ref = panel[panel["date_obs"] <= coupure]
    cur = panel[panel["date_obs"] > coupure]
    if len(cur) < 100:
        return {"applicable": False, "motif": "période récente trop courte"}

    variables: Dict[str, Any] = {}
    for f in cm.FEATURES:
        v = psi(ref[f].to_numpy(), cur[f].to_numpy())
        attendue = f in VARIABLES_DERIVE_ATTENDUE
        variables[f] = {
            "psi": round(v, 4) if np.isfinite(v) else None,
            "niveau": "attendue" if attendue else _niveau_psi(v),
            "derive_attendue": attendue,
            "motif": VARIABLES_DERIVE_ATTENDUE.get(f),
        }

    surveillees = {f: d for f, d in variables.items()
                   if not d["derive_attendue"] and d["psi"] is not None}
    valeurs = [d["psi"] for d in surveillees.values()]
    pires = sorted(((f, d["psi"]) for f, d in surveillees.items()),
                   key=lambda kv: -kv[1])[:5]

    taux_ref = float(ref["y"].mean())
    taux_cur = float(cur["y"].mean())
    derive_cible = abs(taux_cur - taux_ref) / taux_ref if taux_ref else 0.0

    age = _age_modele("churn_model.joblib")

    alertes: List[str] = []
    if valeurs and max(valeurs) >= PSI_MODERE:
        alertes.append(
            f"déplacement net sur « {pires[0][0]} » (PSI {pires[0][1]:.3f}) : "
            "le modèle rencontre des valeurs qu'il n'a pas apprises")
    if derive_cible > DERIVE_CIBLE_MAX:
        alertes.append(
            f"le taux de décrochage passe de {taux_ref:.1%} à {taux_cur:.1%} "
            f"({derive_cible:+.0%}) : les probabilités ne sont plus calibrées")
    if age is not None and age > AGE_CRITIQUE_JOURS:
        alertes.append(f"modèle vieux de {age} jours — réentraînement requis")
    elif age is not None and age > AGE_ALERTE_JOURS:
        alertes.append(f"modèle vieux de {age} jours — réentraînement conseillé")

    return {
        "applicable": True,
        "coupure": str(coupure.date()),
        "n_reference": int(len(ref)), "n_recent": int(len(cur)),
        "age_modele_jours": age,
        "psi_max": round(max(valeurs), 4) if valeurs else None,
        "psi_median": round(float(np.median(valeurs)), 4) if valeurs else None,
        "n_variables_surveillees": len(surveillees),
        "variables_les_plus_deplacees": [
            {"variable": f, "psi": round(v, 4), "niveau": _niveau_psi(v)}
            for f, v in pires],
        "variables_exclues_du_declenchement": [
            {"variable": f, "psi": d["psi"], "motif": d["motif"]}
            for f, d in variables.items() if d["derive_attendue"]],
        "taux_positif_reference": round(taux_ref, 4),
        "taux_positif_recent": round(taux_cur, 4),
        "derive_cible_relative": round(derive_cible, 4),
        "alertes": alertes,
        "reentrainement_conseille": bool(alertes),
        "commande": "python -m ml_engine.analytics.churn_model",
    }


def surveiller_delais() -> Dict[str, Any]:
    """La structure des délais accordés est-elle stable ?"""
    try:
        from ml_engine.analytics.kpi_engine import _connect
    except Exception:
        return {"applicable": False, "motif": "entrepôt indisponible"}

    try:
        con = _connect()
        try:
            rows = con.execute("""
                SELECT strftime(date, '%Y-%m') AS mois,
                       datediff('day', date, echeance) AS delai
                FROM sales
                WHERE date IS NOT NULL AND echeance IS NOT NULL
                  AND NOT est_avoir AND echeance >= date
                  AND datediff('day', date, echeance) BETWEEN 0 AND 400
            """).fetchall()
        finally:
            con.close()
    except Exception as e:
        return {"applicable": False, "motif": f"requête impossible ({type(e).__name__})"}

    if len(rows) < 1000:
        return {"applicable": False, "motif": "trop peu de factures"}

    mois = sorted({r[0] for r in rows})
    if len(mois) < 12:
        return {"applicable": False, "motif": "historique trop court"}

    seuil = mois[-4]
    ref = np.array([r[1] for r in rows if r[0] < seuil], float)
    cur = np.array([r[1] for r in rows if r[0] >= seuil], float)
    if len(cur) < 100:
        return {"applicable": False, "motif": "période récente trop courte"}

    v = psi(ref, cur)
    part_ref = float(np.mean(ref <= 62))
    part_cur = float(np.mean(cur <= 62))

    alertes: List[str] = []
    if np.isfinite(v) and v >= PSI_MODERE:
        alertes.append(
            f"la structure des délais s'est déplacée (PSI {v:.3f}) : la règle de "
            "crédit et l'échéancier reposent tous deux sur sa stabilité")
    if part_cur < 0.95:
        alertes.append(
            f"seules {part_cur:.1%} des factures récentes ont un délai ≤ 2 mois "
            f"(contre {part_ref:.1%}) : l'horizon de l'échéancier n'est plus acquis")

    return {
        "applicable": True,
        "periode_recente_depuis": seuil,
        "n_reference": int(len(ref)), "n_recent": int(len(cur)),
        "psi_delais": round(v, 4) if np.isfinite(v) else None,
        "niveau": _niveau_psi(v),
        "delai_median_reference_j": float(np.median(ref)),
        "delai_median_recent_j": float(np.median(cur)),
        "part_sous_2_mois_reference": round(part_ref, 4),
        "part_sous_2_mois_recent": round(part_cur, 4),
        "alertes": alertes,
        "pourquoi_cela_compte": (
            "Ces deux modules ne contiennent aucun modèle appris : aucune "
            "métrique d'apprentissage ne signalerait leur obsolescence. C'est "
            "cette surveillance qui joue ce rôle à leur place."),
    }


def rapport() -> Dict[str, Any]:
    ch = surveiller_churn()
    de = surveiller_delais()

    alertes: List[Dict[str, str]] = []
    for src, bloc in (("decrochage_client", ch), ("delais_de_paiement", de)):
        for a in (bloc.get("alertes") or []):
            alertes.append({"source": src, "alerte": a})

    r = {
        "version": 1,
        "date": date.today().isoformat(),
        "seuils": {
            "psi_stable": PSI_STABLE, "psi_modere": PSI_MODERE,
            "age_alerte_jours": AGE_ALERTE_JOURS,
            "age_critique_jours": AGE_CRITIQUE_JOURS,
            "derive_cible_max": DERIVE_CIBLE_MAX,
            "origine": ("seuils PSI standards du scoring de crédit, non ajustés "
                        "pour ce projet"),
        },
        "decrochage_client": ch,
        "delais_de_paiement": de,
        "n_alertes": len(alertes),
        "alertes": alertes,
        "etat": "alerte" if alertes else "stable",
        "portee": (
            "La dérive mesure un déplacement des DONNÉES, jamais la performance "
            "du modèle. Cette dernière exigerait la vérité terrain, qui n'arrive "
            "qu'après le délai de la cible — 90 jours pour le décrochage. Le "
            "signal dit « les conditions ont changé, vérifiez », pas « le modèle "
            "s'est trompé »."),
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(r, open(REPORTS_DIR / "derive_metrics.json", "w",
                      encoding="utf-8"), indent=2, ensure_ascii=False)
    return r


def afficher() -> None:
    r = rapport()
    print("\n" + "=" * 78)
    print(f"  SURVEILLANCE DE DÉRIVE — {r['date']}")
    print("=" * 78)

    ch = r["decrochage_client"]
    print("\n  Décrochage client")
    if not ch.get("applicable"):
        print(f"     non évaluable — {ch.get('motif')}")
    else:
        print(f"     âge du modèle        {ch['age_modele_jours']} jours")
        print(f"     PSI médian / max     {ch['psi_median']} / {ch['psi_max']}"
              f"   ({ch['n_variables_surveillees']} variables surveillées)")
        print(f"     taux de décrochage   {ch['taux_positif_reference']:.1%} → "
              f"{ch['taux_positif_recent']:.1%}")
        print("     variables les plus déplacées :")
        for v in ch["variables_les_plus_deplacees"][:3]:
            print(f"       {v['variable']:<26} {v['psi']:>7.4f}  {v['niveau']}")
        for v in ch.get("variables_exclues_du_declenchement") or []:
            print(f"       {v['variable']:<26} {v['psi']:>7.4f}  "
                  "dérive attendue, hors déclenchement")

    de = r["delais_de_paiement"]
    print("\n  Délais de paiement (règle de crédit + échéancier)")
    if not de.get("applicable"):
        print(f"     non évaluable — {de.get('motif')}")
    else:
        print(f"     PSI                  {de['psi_delais']}  ({de['niveau']})")
        print(f"     délai médian         {de['delai_median_reference_j']:.0f} j → "
              f"{de['delai_median_recent_j']:.0f} j")
        print(f"     part ≤ 2 mois        {de['part_sous_2_mois_reference']:.1%} → "
              f"{de['part_sous_2_mois_recent']:.1%}")

    print("\n" + "-" * 78)
    if r["alertes"]:
        print(f"  {r['n_alertes']} ALERTE(S) :")
        for a in r["alertes"]:
            print(f"    [{a['source']}] {a['alerte']}")
    else:
        print("  Aucune alerte : distributions stables depuis l'entraînement.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
