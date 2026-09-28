"""
scripts/verif_pic_echeances.py
===============================
Explique le pic d'echeances de 2026-01 a 2026-03.

Le fait a expliquer
-------------------
Les totaux mensuels par date d'echeance sont stables autour de 4,0-4,8 M DT sur
tout 2025, puis montent brutalement :

    2026-01 : 5,68 M     2026-02 : 6,70 M     2026-03 : 9,09 M

Le dernier mois vaut le DOUBLE de la norme. Et c'est exactement sur ces trois
mois que la methode du carnet semble gagner, parce que la part deja acquise y
passe de 0,1 % a 49 %. Tout le resultat a h=3 repose donc sur ce pic.

Deux explications possibles, aux consequences opposees :

  * REALITE METIER -- forte facturation de fin 2025 a delais longs, ou
    saisonnalite des marches publics. Le resultat tient.

  * ARTEFACT DE FENETRE -- les mois d'echeance proches de la fin des donnees
    accumulent anormalement, ou des dates d'echeance aberrantes s'y empilent.
    Le resultat ne tient pas, et la cible doit etre tronquee plus tot.

Ce script mesure la composition de ces mois : distribution des delais, mois
d'emission d'origine, et presence de delais anormalement longs.

    .venv\\Scripts\\python.exe scripts\\verif_pic_echeances.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ml_engine.forecasting.carnet_echeances import (  # noqa: E402
    _libelle, _total, charger_factures)


def dt(v) -> str:
    return f"{float(v):,.0f}".replace(",", " ")


def main() -> int:
    factures = charger_factures()          # (mois emission, mois echeance, ttc)
    echeances = sorted({e for _, e, _ in factures})
    emissions = sorted({em for em, _, _ in factures})
    print(f"\nfactures = {len(factures):,}".replace(",", " "))
    print(f"emissions : {_libelle(emissions[0])} -> {_libelle(emissions[-1])}")
    print(f"echeances : {_libelle(echeances[0])} -> {_libelle(echeances[-1])}")

    # ── 1. La serie complete des echeances, sans troncature ────────────────
    print("\n=== 1. TOTAL PAR MOIS D'ECHEANCE (2025-01 et au-dela) ===")
    print(f"  {'mois':<10}{'total':>14}{'n factures':>12}{'delai median':>14}")
    seuil = 2025 * 12
    for k in [x for x in echeances if x >= seuil]:
        lot = [(em, t) for em, ech, t in factures if ech == k]
        if not lot:
            continue
        delais = sorted(k - em for em, _ in lot)
        med = delais[len(delais) // 2]
        print(f"  {_libelle(k):<10}{dt(sum(t for _, t in lot)):>14}"
              f"{len(lot):>12}{med:>11} mois")

    # ── 2. Distribution des delais, en mois ────────────────────────────────
    print("\n=== 2. DISTRIBUTION DES DELAIS (echeance - emission, en mois) ===")
    c = Counter(ech - em for em, ech, _ in factures)
    total_n = sum(c.values())
    cumul = 0
    for d in sorted(c):
        part = c[d] / total_n * 100
        cumul += part
        if d <= 8 or part > 0.5:
            print(f"  {d:>3} mois : {c[d]:>8,} ({part:>5.2f} %)  cumul {cumul:>6.2f} %"
                  .replace(",", " "))
    longs = sum(n for d, n in c.items() if d >= 6)
    print(f"\n  delais >= 6 mois : {longs:,} factures "
          f"({longs / total_n * 100:.2f} %)".replace(",", " "))
    print("  -> Si ce taux est faible, un `acquis` de 49 % a h=3 est IMPOSSIBLE")
    print("     par la seule structure des delais : il faut une autre cause.")

    # ── 3. D'ou viennent les echeances des trois mois du pic ? ─────────────
    print("\n=== 3. COMPOSITION DES TROIS MOIS DU PIC ===")
    for cible_lbl in ("2026-01", "2026-02", "2026-03"):
        a, m = cible_lbl.split("-")
        k = int(a) * 12 + (int(m) - 1)
        lot = [(em, t) for em, ech, t in factures if ech == k]
        if not lot:
            continue
        print(f"\n  --- {cible_lbl} : {dt(sum(t for _, t in lot))} DT, "
              f"{len(lot)} factures ---")
        par_em = Counter()
        mt_em = {}
        for em, t in lot:
            par_em[em] += 1
            mt_em[em] = mt_em.get(em, 0.0) + t
        for em in sorted(par_em, reverse=True)[:8]:
            d = k - em
            print(f"    emises {_libelle(em)} (delai {d:>2} mois) : "
                  f"{par_em[em]:>6} factures  {dt(mt_em[em]):>13} DT")

    # ── 4. Comparaison avec un mois normal ─────────────────────────────────
    print("\n=== 4. MOIS DE REFERENCE (2025-06) POUR COMPARAISON ===")
    k = 2025 * 12 + 5
    lot = [(em, t) for em, ech, t in factures if ech == k]
    par_em = Counter()
    mt_em = {}
    for em, t in lot:
        par_em[em] += 1
        mt_em[em] = mt_em.get(em, 0.0) + t
    print(f"  2025-06 : {dt(sum(t for _, t in lot))} DT, {len(lot)} factures")
    for em in sorted(par_em, reverse=True)[:8]:
        print(f"    emises {_libelle(em)} (delai {k - em:>2} mois) : "
              f"{par_em[em]:>6} factures  {dt(mt_em[em]):>13} DT")

    print("\n=== LECTURE ===")
    print("  Si les mois du pic recoivent des echeances de factures emises")
    print("  BEAUCOUP plus tot que les mois normaux, alors leur maturite elevee")
    print("  est reelle -- mais leur TOTAL est gonfle par des delais longs")
    print("  inhabituels, et il faut comprendre pourquoi avant de conclure.")
    print("\n  Si au contraire leur composition ressemble a celle d'un mois")
    print("  normal, le pic vient d'un VOLUME de facturation exceptionnel en")
    print("  fin 2025, et la maturite elevee est un artefact de la fenetre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
