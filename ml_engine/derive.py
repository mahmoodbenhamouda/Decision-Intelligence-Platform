"""
ml_engine/derive.py
====================
Surveillance de la dérive — un modèle qui vieillit doit se signaler lui-même.

Le problème
-----------
Un modèle est entraîné sur une période, puis servi sur les suivantes. Rien ne
garantit que le monde reste identique : les clients changent, la facturation
évolue, un produit remplace un autre. Le modèle continue pourtant de répondre
avec le même aplomb, et sa dégradation est **silencieuse** — c'est ce qui la rend
dangereuse.

Ce projet en a déjà fait l'expérience, et de la pire manière. La prévision de
demande gagnait 5 % en validation croisée et perdait jusqu'à 27,7 % sur les six
derniers mois : toutes les méthodes s'y dégradaient d'un facteur 1,7 et leur
hiérarchie s'inversait. C'était un changement de régime, découvert par un
hold-out. Sans lui, un modèle inutilisable aurait été déployé.

Un hold-out ne protège qu'une fois, au moment de l'entraînement. Ce module fait
la même chose **en continu**.

Ce qui est surveillé, et pourquoi ces trois choses
--------------------------------------------------
1. **L'âge du modèle.** Le plus simple et le plus négligé. Un modèle entraîné il
   y a dix-huit mois n'a jamais vu la conjoncture actuelle.

2. **Le déplacement des variables d'entrée.** Si la distribution des variables
   change, le modèle extrapole au lieu d'interpoler — et un modèle qui extrapole
   se trompe sans le savoir. Mesuré par l'indice de stabilité de population (PSI),
   standard du scoring bancaire.

3. **Le déplacement de la cible.** Si le taux de décrochage passe de 8 % à 20 %,
   les probabilités calibrées deviennent fausses même si le classement reste bon.

Ce que ce module ne fait PAS
----------------------------
Il ne mesure **pas** la performance réelle du modèle en production : cela
exigerait de connaître la vérité terrain, qui n'arrive qu'après le délai de la
cible — 90 jours pour le décrochage. La dérive est un signal d'ALERTE précoce,
pas une mesure de performance. Elle dit « les conditions ont changé, vérifiez »,
jamais « le modèle s'est trompé ».

Lancement :
    python -m ml_engine.derive
"""

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

# ── Seuils ──────────────────────────────────────────────────────────────────
#
# Le PSI est un standard du scoring de crédit, et ses seuils sont ceux de la
# pratique établie — ils ne sont pas ajustés pour ce projet.
PSI_STABLE = 0.10        # en dessous : distribution inchangée
PSI_MODERE = 0.25        # entre les deux : à surveiller ; au-delà : dérive nette

AGE_ALERTE_JOURS = 180   # deux trimestres sans réentraînement
AGE_CRITIQUE_JOURS = 365

# ── Variables qui dérivent PAR CONSTRUCTION ─────────────────────────────────
#
# Certaines variables se déplacent mécaniquement avec le temps, sans que rien ne
# change dans le métier. L'ancienneté d'un client en est l'exemple pur : elle
# augmente d'un jour par jour. Comparer les observations récentes aux anciennes
# donne donc un PSI énorme — mesuré à 2,62 ici — qui ne signale strictement rien.
#
# Une alerte qui se déclenche par construction est pire qu'une absence d'alerte :
# elle épuise l'attention et fait ignorer les vraies. Ces variables sont donc
# exclues du DÉCLENCHEMENT, tout en restant mesurées et affichées — masquer une
# mesure gênante serait une autre forme de malhonnêteté.
VARIABLES_DERIVE_ATTENDUE = {
    "anciennete_j": ("l'ancienneté d'un client croît d'un jour par jour : son "
                     "déplacement est arithmétique, pas comportemental"),
}

# Variation relative du taux de positifs au-delà de laquelle la calibration
# n'est plus fiable, même si le pouvoir de classement subsiste.
DERIVE_CIBLE_MAX = 0.50


def psi(attendu: np.ndarray, observe: np.ndarray, n_bacs: int = 10) -> float:
    """Indice de stabilité de population entre deux échantillons.

    Compare la répartition d'une variable entre la période d'entraînement et la
    période courante. Les bornes de bacs viennent des quantiles de la période
    d'ENTRAÎNEMENT : c'est elle la référence, et les recalculer sur la période
    courante masquerait précisément le déplacement qu'on cherche.
    """
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
    # Plancher : un bac vide rendrait le logarithme infini alors qu'il traduit
    # seulement un échantillon fini.
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


# ── Surveillance du modèle de décrochage ────────────────────────────────────
def surveiller_churn() -> Dict[str, Any]:
    """Compare la période récente à la période d'entraînement.

    Le panel est reconstruit à l'identique, puis coupé en deux : ce sur quoi le
    modèle a appris, et ce qu'il rencontre aujourd'hui.
    """
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

    # Seules les variables dont le déplacement serait ANORMAL entrent dans le
    # déclenchement. Les autres restent mesurées et visibles.
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


# ── Surveillance des délais de paiement ─────────────────────────────────────
def surveiller_delais() -> Dict[str, Any]:
    """La structure des délais accordés est-elle stable ?

    Elle conditionne deux modules à la fois : la règle de crédit suppose que le
    délai d'un client reste constant, et l'échéancier suppose que 99 % des
    factures se règlent sous deux mois. Si cette structure bouge, les deux
    deviennent faux **sans qu'aucune métrique de modèle ne bronche** — ils ne
    contiennent pas de modèle.
    """
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

    seuil = mois[-4]        # les trois derniers mois forment la période courante
    ref = np.array([r[1] for r in rows if r[0] < seuil], float)
    cur = np.array([r[1] for r in rows if r[0] >= seuil], float)
    if len(cur) < 100:
        return {"applicable": False, "motif": "période récente trop courte"}

    v = psi(ref, cur)
    part_ref = float(np.mean(ref <= 62))     # « sous deux mois », avec marge
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


# ── Rapport consolidé ───────────────────────────────────────────────────────
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
