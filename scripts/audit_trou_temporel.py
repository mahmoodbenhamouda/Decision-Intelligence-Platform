"""Explique les 27 mois sans facture et l'effondrement de 2020."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import duckdb  # noqa: E402

from etl.sources import lecture  # noqa: E402
from ml_engine.analytics.kpi_engine import STORE_PATH  # noqa: E402


def lu(role: str) -> str:
    """Lecture d'une source par son rôle dans le catalogue de l'ETL (etl/sources.py)."""
    return lecture(role)


def titre(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def dt(v) -> str:
    return "n/d" if v is None else f"{float(v):,.0f}".replace(",", " ")


DATE = ("COALESCE(TRY_STRPTIME({c},'%m/%d/%Y'),"
        "TRY_STRPTIME({c},'%Y-%m-%d'),TRY_STRPTIME({c},'%d/%m/%Y'))::DATE")


def main() -> int:
    con = duckdb.connect(str(STORE_PATH), read_only=True)

    titre("1. VENTES PAR ANNEE (entrepot corrige)")
    rows = con.execute("""
        SELECT year, count(*) AS n, sum(ttc) AS ca,
               count(DISTINCT strftime(date, '%Y-%m')) AS mois_actifs
        FROM sales WHERE NOT est_avoir AND year IS NOT NULL
        GROUP BY year ORDER BY year
    """).fetchall()
    derniere = max(r[0] for r in rows) if rows else 0
    total_factures = sum(r[1] for r in rows) or 1
    print(f"  {'Annee':<8}{'Factures':>10}{'CA (DT)':>18}{'Mois':>8}{'Part':>8}")
    for an, n, ca, mois in rows:
        part = n / total_factures * 100
        if an == derniere:
            drapeau = "  annee en cours (incomplete par nature)"
        elif part < 2:
            drapeau = "  <-- RESIDUEL : trop peu pour etre une annee d'activite"
        elif mois < 6:
            drapeau = "  <-- TROU"
        else:
            drapeau = ""
        print(f"  {an:<8}{n:>10,}{dt(ca):>18}{mois:>6}/12{part:>7.1f}%{drapeau}"
              .replace(",", " "))

    titre("2. MOIS MANQUANTS A L'INTERIEUR DE LA PERIODE")
    manquants = con.execute("""
        WITH mois AS (
            SELECT DISTINCT date_trunc('month', date) AS m
            FROM sales WHERE date IS NOT NULL AND NOT est_avoir
        ),
        bornes AS (SELECT min(m) AS d, max(m) AS f FROM mois),
        attendus AS (
            SELECT unnest(generate_series(
                (SELECT d FROM bornes), (SELECT f FROM bornes),
                INTERVAL 1 MONTH)) AS m
        )
        SELECT strftime(a.m, '%Y-%m') FROM attendus a
        WHERE NOT EXISTS (SELECT 1 FROM mois x WHERE x.m = a.m)
        ORDER BY a.m
    """).fetchall()
    liste = [r[0] for r in manquants]
    print(f"  {len(liste)} mois sans aucune facture :")
    for i in range(0, len(liste), 8):
        print("    " + "  ".join(liste[i:i + 8]))

    if liste:
        plages, debut, prec = [], liste[0], liste[0]
        for m in liste[1:]:
            a1, m1 = int(prec[:4]), int(prec[5:])
            suivant = f"{a1 + (m1 // 12):04d}-{(m1 % 12) + 1:02d}"
            if m != suivant:
                plages.append((debut, prec))
                debut = m
            prec = m
        plages.append((debut, prec))
        print("\n  Regroupes en plages continues :")
        for d, f in plages:
            print(f"    {d} -> {f}" + ("   (mois isole)" if d == f else ""))

    titre("3. LE MEME TROU EXISTE-T-IL DANS LES AUTRES FICHIERS ?")
    print("  Si oui -> realite de l'entreprise. Si non -> export des ventes incomplet.\n")

    sources = [("ventes", "ventes_entetes", "DATEPIECE"),
               ("lignes", "ventes_lignes", "DATEFACTURE"),
               ("achats", "achats_entetes", "DATEPIECE"),
               ("devis", "devis", "DATEPIECE")]
    par_annee: dict[str, dict[int, int]] = {}
    for libelle, cle, colonne in sources:
        try:
            d = DATE.format(c=colonne)
            r = con.execute(f"""
                SELECT year({d}) AS an, count(*) FROM {lu(cle)}
                WHERE {d} IS NOT NULL AND year({d}) BETWEEN 2015 AND 2030
                GROUP BY 1 ORDER BY 1
            """).fetchall()
            par_annee[libelle] = {int(a): int(n) for a, n in r}
        except Exception as exc:
            print(f"  [{libelle}] illisible : {exc}")

    annees = sorted({a for m in par_annee.values() for a in m})
    entetes = "".join(f"{lib:>12}" for lib in par_annee)
    print(f"  {'Annee':<8}{entetes}")
    for an in annees:
        ligne = "".join(f"{par_annee[lib].get(an, 0):>12,}".replace(",", " ")
                        for lib in par_annee)
        n_ventes = par_annee.get("ventes", {}).get(an, 0)
        autres = sum(n for lib, m in par_annee.items()
                     if lib != "ventes" for a2, n in m.items() if a2 == an)
        if n_ventes == 0 and autres > 0:
            drapeau = "  <-- SUSPECT : ventes vides, autres sources alimentees"
        elif n_ventes == 0 and autres == 0:
            drapeau = "  (absente partout)"
        else:
            drapeau = ""
        print(f"  {an:<8}{ligne}{drapeau}")

    titre("4. LECTURE")
    suspectes = [an for an, n, _, _ in rows
                 if an != derniere and n / total_factures * 100 < 2]
    toutes = sorted(set(annees) | {r[0] for r in rows})
    absentes = [an for an in toutes
                if all(par_annee[lib].get(an, 0) == 0 for lib in par_annee)]

    if absentes:
        print(f"  ANNEES ABSENTES DE TOUTES LES SOURCES : "
              f"{', '.join(str(a) for a in absentes)}")
        print("    -> Aucun fichier ne contient quoi que ce soit. Ce n'est donc")
        print("       pas un defaut d'export des ventes : l'ERP lui-meme ne")
        print("       couvre pas cette periode (bascule d'ERP, dossier repris).")

    for an in suspectes:
        cohorte = {lib: par_annee[lib].get(an, 0) for lib in par_annee}
        print(f"\n  {an} — {dict(((a, n) for a, n, _, _ in rows if a == an))[an]:,} "
              f"factures dans l'entrepot :".replace(",", " "))
        for lib, n in cohorte.items():
            print(f"    {lib:<10} {n:>10,} pieces (source brute)".replace(",", " "))
        if all(n == 0 for n in cohorte.values()):
            print("    -> Vide partout : periode non couverte par l'ERP.")
        elif cohorte.get("ventes", 0) == 0:
            print("    -> Les ventes sont vides alors que d'AUTRES sources ont")
            print("       des donnees : l'export des ventes est INCOMPLET ici.")
        else:
            print("    -> Presence residuelle dans toutes les sources : volumes")
            print("       trop faibles pour une annee d'exploitation. Trace de")
            print("       migration ou periode de demarrage, pas d'activite reelle.")

    pleines = [(an, n, ca) for an, n, ca, mois in rows
               if an != derniere and n / total_factures * 100 >= 2]
    print("\n" + "-" * 78)
    if pleines:
        d, f = min(a for a, _, _ in pleines), derniere
        ca_pleines = sum(c for _, _, c in pleines)
        ca_total = sum(r[2] for r in rows)
        print("  PROFONDEUR D'HISTORIQUE REELLEMENT EXPLOITABLE")
        print(f"    Annees pleines : {d} -> {max(a for a, _, _ in pleines)}"
              f"  (+ {f} en cours)")
        print(f"    Elles portent {ca_pleines / ca_total * 100:.1f} % du CA total.")
        print(f"\n    A ANNONCER EN SOUTENANCE : {d}-{f}, et non 2017-{f}.")
        print("    Les annees anterieures sont des residus, pas de l'historique.")
    print("-" * 78)
    print("\n  Note : les comptages de la section 3 portent sur les fichiers BRUTS")
    print("  (avoirs et doublons inclus) et depassent donc ceux de la section 1,")
    print("  qui lit l'entrepot corrige. L'ecart est attendu.")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
