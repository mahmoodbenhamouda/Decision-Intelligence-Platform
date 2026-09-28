"""
scripts/verif_carnet_h3.py
===========================
Tranche une contradiction interne du module carnet d'echeances.

Le soupcon
----------
A h=3, le taux de maturite mesure est de 0,1 % : le carnet ne contient
pratiquement rien. La prevision se reduit donc a `acquis + reste`, ou `reste` est
la mediane des totaux des mois T-5 a T.

Or la reference `mediane_mobile_6m` calcule la mediane des totaux des mois
T-5 a T. **La meme fenetre.** Les deux devraient donc donner presque la meme
valeur, et pourtant le rapport annonce 9,3 % contre 16,7 %.

L'une des deux est mal calculee. Ce script affiche les deux, origine par
origine, avec leurs composantes, pour identifier laquelle.

    .venv\\Scripts\\python.exe scripts\\verif_carnet_h3.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import median

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting.carnet_echeances import (  # noqa: E402
    _acquis, _baselines, _libelle, _reste_recent, _serie_observable,
    _taux_maturite, _total, charger_factures, prevoir)

H = 3
N_TEST = 12


def dt(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def main() -> int:
    factures = charger_factures()
    echeances = sorted({e for _, e, _ in factures})
    emissions = sorted({em for em, _, _ in factures})
    debut, fin_cible = echeances[0], max(emissions) - 1
    origines = [t for t in range(debut, fin_cible - H + 1)][-N_TEST:]

    print(f"\nfactures={len(factures):,}".replace(",", " "))
    print(f"debut={_libelle(debut)}  fin_cible={_libelle(fin_cible)}")
    print(f"origines h={H} : {_libelle(origines[0])} -> {_libelle(origines[-1])}\n")

    print(f"{'origine':<9}{'cible':<9}{'reel':>13}{'carnet':>13}"
          f"{'acquis':>11}{'reste':>13}{'med6':>13}{'taux':>8}{'regime':>15}")
    ec_carnet, ec_med6 = [], []
    for t in origines:
        cible = t + H
        reel = _total(factures, cible)
        if reel <= 0:
            continue
        sortie = prevoir(factures, t, H, debut)
        if sortie is None:
            print(f"{_libelle(t):<9}{_libelle(cible):<9}  prevoir() -> None")
            continue
        pred, regime, taux = sortie
        acq = _acquis(factures, t, cible)
        reste = _reste_recent(factures, t, H, debut)
        z = _serie_observable(factures, t, debut)
        med6 = _baselines(z, t, H).get("mediane_mobile_6m", float("nan"))

        ec_carnet.append(abs(pred - reel) / reel)
        ec_med6.append(abs(med6 - reel) / reel)
        print(f"{_libelle(t):<9}{_libelle(cible):<9}{dt(reel):>13}{dt(pred):>13}"
              f"{dt(acq):>11}{dt(reste or 0):>13}{dt(med6):>13}"
              f"{taux:>7.1%}{regime:>15}")

    print(f"\nMAPE carnet          : {sum(ec_carnet) / len(ec_carnet) * 100:.2f} %")
    print(f"MAPE mediane_mobile_6m: {sum(ec_med6) / len(ec_med6) * 100:.2f} %")

    # ── Les deux fenetres sont-elles reellement identiques ? ────────────────
    print("\n--- FENETRES COMPAREES (derniere origine) ---")
    t = origines[-1]
    fen_reste = [t_p + H for t_p in range(max(debut, t - H - 6 + 1), t - H + 1)]
    z = _serie_observable(factures, t, debut)
    dispo = sorted(k for k in z if z[k] > 0)
    fen_med6 = dispo[-6:]
    print(f"  reste_recent  utilise les cibles : "
          f"{', '.join(_libelle(k) for k in fen_reste)}")
    print(f"  mediane_mobile_6m utilise les mois: "
          f"{', '.join(_libelle(k) for k in fen_med6)}")
    print(f"  identiques ? {fen_reste == fen_med6}")
    print(f"\n  mediane(reste)  = {dt(median([_total(factures, k) - _acquis(factures, k - H, k) for k in fen_reste]))}")
    print(f"  mediane(totaux) = {dt(median([z[k] for k in fen_med6]))}")

    # ── Le taux de maturite est-il fausse par la periode morte ? ────────────
    print("\n--- TAUX DE MATURITE : effet de la periode 2017-2020 ---")
    taux_tout = _taux_maturite(factures, origines[-1], H, debut)
    debut_2021 = 2021 * 12
    taux_2021 = _taux_maturite(factures, origines[-1], H, debut_2021)
    print(f"  estime depuis {_libelle(debut)} : {taux_tout:.2%}")
    print(f"  estime depuis 2021-01           : "
          f"{taux_2021:.2%}" if taux_2021 is not None else "  n/d")
    print("\n  Si l'ecart est fort, le taux est ecrase par les mois vides de")
    print("  2017-2020 : la mediane inclut des origines ou le carnet etait nul")
    print("  faute de donnees, pas faute de maturite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
