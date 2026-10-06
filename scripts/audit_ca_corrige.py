"""Chiffrage exact des deux anomalies confirmees, et CA corrige."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import duckdb  # noqa: E402

from ml_engine.analytics.kpi_engine import STORE_PATH, SOURCES  # noqa: E402

SRC = (RACINE / "data_pfe" / SOURCES["sales"]).as_posix()
LU = f"read_csv_auto('{SRC}', sample_size=8000, ignore_errors=true, all_varchar=true)"
TTC = "TRY_CAST(TTC_DEV AS DOUBLE)"
HT = "TRY_CAST(HT_DEV AS DOUBLE)"
SIG = "TRY_CAST(MONTANTSIGNE_DEV AS DOUBLE)"
OU = f"FROM {LU} WHERE {TTC} IS NOT NULL"


def titre(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def dt(v) -> str:
    return "n/d" if v is None else f"{float(v):,.0f} DT".replace(",", " ")


def main() -> int:
    con = duckdb.connect(str(STORE_PATH), read_only=True)
    ca_actuel = con.execute("SELECT sum(ttc) FROM sales").fetchone()[0]
    n_actuel = con.execute("SELECT count(*) FROM sales").fetchone()[0]

    titre("1. AVOIRS -- pieces que l'ERP compte en negatif")
    n_av, ttc_av, ht_av = con.execute(
        f"SELECT count(*), sum({TTC}), sum({HT}) {OU} AND {SIG} < 0").fetchone()
    print(f"  Nombre d'avoirs           : {n_av:,}".replace(",", " "))
    print(f"  Leur HT cumule            : {dt(ht_av)}")
    print(f"  Leur TTC cumule           : {dt(ttc_av)}")
    print(f"\n  Ils sont aujourd'hui AJOUTES au CA : +{dt(ttc_av)}")
    print(f"  Ils devraient en etre RETRANCHES   : -{dt(ttc_av)}")
    print(f"  Correction a appliquer             : -{dt(2 * float(ttc_av or 0))}")
    rows = con.execute(f"""
        SELECT year(COALESCE(TRY_STRPTIME(DATEPIECE, '%m/%d/%Y'),
                             TRY_STRPTIME(DATEPIECE, '%Y-%m-%d'))) AS an,
               count(*), sum({TTC})
        {OU} AND {SIG} < 0 GROUP BY 1 ORDER BY 1
    """).fetchall()
    print("\n  Repartition par annee :")
    for an, n, ca in rows:
        print(f"    {an}  {n:>6,} avoirs   {dt(ca):>18}".replace(",", " "))

    titre("2. DOUBLONS -- meme numero, meme client, meme date, meme montant")
    r = con.execute(f"""
        WITH d AS (
            SELECT trim(PIECENOFULL) AS p, trim(TIERS) AS c, DATEPIECE AS dd,
                   {TTC} AS m, count(*) AS n
            {OU} AND trim(PIECENOFULL) <> ''
            GROUP BY 1, 2, 3, 4 HAVING count(*) > 1
        )
        SELECT count(*), sum(n), sum(n - 1), sum((n - 1) * m) FROM d
    """).fetchone()
    g, li, surnum, ca_dup = [x or 0 for x in r]
    print(f"  Groupes concernes         : {g:,}".replace(",", " "))
    print(f"  Lignes impliquees         : {li:,}".replace(",", " "))
    print(f"  Lignes SURNUMERAIRES      : {surnum:,}".replace(",", " "))
    print(f"  CA en trop                : {dt(ca_dup)}")
    print(f"\n  Correction a appliquer    : -{dt(ca_dup)}")

    titre("3. CHIFFRE D'AFFAIRES CORRIGE")
    corr_av = 2 * float(ttc_av or 0)
    ca_corrige = float(ca_actuel) - corr_av - float(ca_dup)
    ecart = float(ca_actuel) - ca_corrige
    print(f"  CA affiche aujourd'hui              : {dt(ca_actuel)}")
    print(f"    - double comptage des avoirs      : -{dt(corr_av)}")
    print(f"    - factures dupliquees             : -{dt(ca_dup)}")
    print(f"  {'-' * 54}")
    print(f"  CA CORRIGE                          : {dt(ca_corrige)}")
    print(f"\n  Surevaluation : {dt(ecart)}  soit {ecart / float(ca_actuel) * 100:.2f} % du CA affiche")

    titre("4. INDICATEURS DERIVES")
    n_corrige = n_actuel - int(n_av or 0) - int(surnum or 0)
    zeros = con.execute("SELECT count(*) FROM sales WHERE ttc = 0").fetchone()[0]
    print(f"  Nombre de factures affiche          : {n_actuel:,}".replace(",", " "))
    print(f"    - avoirs comptes comme factures   : -{n_av:,}".replace(",", " "))
    print(f"    - lignes dupliquees               : -{surnum:,}".replace(",", " "))
    print(f"  Nombre de factures corrige          : {n_corrige:,}".replace(",", " "))
    print(f"\n  Panier moyen affiche                : "
          f"{dt(float(ca_actuel) / n_actuel)}")
    print(f"  Panier moyen corrige                : {dt(ca_corrige / n_corrige)}")
    print(f"\n  (dont {zeros} factures a 0 DT, qui abaissent le panier moyen "
          "sans toucher au CA)")

    titre("5. PALMARES CLIENT -- effet de la correction")
    avant = con.execute("""
        SELECT coalesce(d.client_name, s.client) AS nom, sum(s.ttc) AS ca
        FROM sales s LEFT JOIN dim_client d ON d.client_code = s.client
        GROUP BY 1 ORDER BY ca DESC LIMIT 8
    """).fetchall()
    apres = con.execute(f"""
        SELECT trim(TIERS) AS code, sum({SIG}) AS ca_net
        {OU} GROUP BY 1 ORDER BY ca_net DESC LIMIT 8
    """).fetchall()
    noms = dict(con.execute(
        "SELECT client_code, client_name FROM dim_client").fetchall())
    print("  Classement ACTUEL (TTC brut, avoirs comptes en plus) :")
    for i, (nom, ca) in enumerate(avant, 1):
        print(f"    {i}. {str(nom)[:40]:<40} {dt(ca)}")
    print("\n  Classement NET (montant signe de l'ERP, en HT) :")
    for i, (code, ca) in enumerate(apres, 1):
        nom = noms.get(code) or code
        print(f"    {i}. {str(nom)[:40]:<40} {dt(ca)}")
    set_av = {str(n)[:40] for n, _ in avant}
    set_ap = {str(noms.get(c) or c)[:40] for c, _ in apres}
    sortis = set_av - set_ap
    if sortis:
        print(f"\n  -> Sortent du top 8 une fois les avoirs deduits : "
              f"{', '.join(sorted(sortis))}")
    else:
        print("\n  -> Le top 8 ne change pas de composition.")

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
