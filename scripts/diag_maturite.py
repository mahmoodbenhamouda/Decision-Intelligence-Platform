"""Y a-t-il quelque chose à apprendre dans le taux de maturité du carnet ?"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import median

import numpy as np

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting.carnet_echeances import (  # noqa: E402
    _acquis, _libelle, _total, charger_factures)

H = 2
DEBUT = 2021 * 12


def main() -> int:
    factures = charger_factures()
    echeances = sorted({e for _, e, _ in factures})
    emissions = sorted({em for em, _, _ in factures})
    fin = max(emissions) - 1

    lignes = []
    for t in range(DEBUT, fin - H + 1):
        cible = t + H
        tot = _total(factures, cible)
        if tot <= 0:
            continue
        acq = _acquis(factures, t, cible)
        recents = [_total(factures, k) for k in range(t - 2, t + 1)]
        recents = [v for v in recents if v > 0]
        if not recents:
            continue
        niveau = float(np.mean(recents))
        precedents = [_total(factures, k) for k in range(t - 5, t - 2)]
        precedents = [v for v in precedents if v > 0]
        tendance = (niveau / float(np.mean(precedents))) if precedents else 1.0
        lignes.append({
            "origine": t, "cible": cible,
            "taux": acq / tot,
            "mois_cible": (cible % 12) + 1,
            "niveau": niveau,
            "tendance": tendance,
            "acquis_relatif": acq / niveau if niveau else 0.0,
            "total": tot,
        })

    if len(lignes) < 20:
        print(f"panel trop court ({len(lignes)} origines) — diagnostic impossible")
        return 1

    taux = np.array([l["taux"] for l in lignes])
    print(f"\n{len(lignes)} origines exploitables : "
          f"{_libelle(lignes[0]['origine'])} → {_libelle(lignes[-1]['origine'])}")
    print(f"\n=== 1. DISPERSION DU TAUX DE MATURITE (h={H}) ===")
    print(f"  médiane   {np.median(taux):.4f}")
    print(f"  moyenne   {taux.mean():.4f}")
    print(f"  écart-type {taux.std():.4f}")
    print(f"  min / max  {taux.min():.4f} / {taux.max():.4f}")
    print(f"  écart interquartile {np.percentile(taux, 75) - np.percentile(taux, 25):.4f}")
    print("\n  Si l'écart-type est faible devant la médiane, le taux est une "
          "constante\n  et il n'y a rien à apprendre.")

    print(f"\n=== 2. LE TAUX DEPEND-IL DU MOIS ? ===")
    par_mois = {}
    for l in lignes:
        par_mois.setdefault(l["mois_cible"], []).append(l["taux"])
    for m in sorted(par_mois):
        v = par_mois[m]
        print(f"  mois {m:>2} : médiane {median(v):.4f}  (n={len(v)})")
    med_mois = [median(v) for v in par_mois.values() if len(v) >= 2]
    if med_mois:
        etendue = max(med_mois) - min(med_mois)
        print(f"\n  étendue des médianes mensuelles : {etendue:.4f}")
        print(f"  écart-type global du taux        : {taux.std():.4f}")
        print("  -> Si l'étendue dépasse nettement l'écart-type, le mois porte "
              "un signal.")

    print(f"\n=== 3. CORRELATIONS (Spearman, robuste aux valeurs extremes) ===")
    try:
        from scipy.stats import spearmanr
        for nom in ("niveau", "tendance", "acquis_relatif"):
            x = np.array([l[nom] for l in lignes])
            r, p = spearmanr(x, taux)
            marque = "  <- significatif" if p < 0.05 else ""
            print(f"  {nom:<18} rho={r:+.3f}  p={p:.4f}{marque}")
    except Exception:
        for nom in ("niveau", "tendance", "acquis_relatif"):
            x = np.array([l[nom] for l in lignes])
            print(f"  {nom:<18} corr={np.corrcoef(x, taux)[0, 1]:+.3f}")

    print(f"\n=== 4. ERREUR D'ESTIMATION DU TAUX (walk-forward) ===")
    err_med, err_mois, err_recent = [], [], []
    for i in range(12, len(lignes)):
        passe = lignes[:i]
        vrai = lignes[i]["taux"]
        m = lignes[i]["mois_cible"]

        err_med.append(abs(median([l["taux"] for l in passe]) - vrai))

        meme_mois = [l["taux"] for l in passe if l["mois_cible"] == m]
        est = median(meme_mois) if len(meme_mois) >= 2 else median([l["taux"] for l in passe])
        err_mois.append(abs(est - vrai))

        err_recent.append(abs(median([l["taux"] for l in passe[-6:]]) - vrai))

    print(f"  médiane globale      : {np.mean(err_med):.4f}")
    print(f"  médiane du même mois : {np.mean(err_mois):.4f}")
    print(f"  médiane des 6 dernières : {np.mean(err_recent):.4f}")

    meilleur = min([("globale", np.mean(err_med)),
                    ("mois", np.mean(err_mois)),
                    ("récente", np.mean(err_recent))], key=lambda kv: kv[1])
    gain = (np.mean(err_med) - meilleur[1]) / np.mean(err_med) * 100

    print(f"\n=== VERDICT ===")
    print(f"  Meilleur estimateur : {meilleur[0]} ({meilleur[1]:.4f})")
    print(f"  Gain sur la médiane globale : {gain:+.1f} %")
    if gain < 5:
        print("\n  -> Aucun estimateur contextuel simple ne bat nettement la")
        print("     constante. Un modèle appris n'a pas de signal à exploiter :")
        print("     inutile d'en construire un.")
    else:
        print("\n  -> Le contexte porte un signal exploitable. Un modèle appris")
        print("     mérite d'être tenté sur ces variables.")
    return 0


if __name__ == "__main__":
    import sys as _s
    try:
        _s.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
