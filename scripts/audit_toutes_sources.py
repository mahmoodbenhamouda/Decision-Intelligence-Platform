"""Etend aux ACHATS et aux LIGNES DE FACTURE l'audit mene sur les ventes."""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

import duckdb  # noqa: E402

from etl.sources import lecture  # noqa: E402


def lu(role: str) -> str:
    """Lecture d'une source par son rôle dans le catalogue de l'ETL (etl/sources.py)."""
    return lecture(role)


def titre(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def dt(v) -> str:
    return "n/d" if v is None else f"{float(v):,.0f} DT".replace(",", " ")


def main() -> int:
    con = duckdb.connect()
    num = "TRY_CAST({} AS DOUBLE)"

    titre("ACHATS -- Facture_achat_ent_v.csv")
    a = lu("achats_entetes")
    ttc, ht, sig = num.format("TTC_DEV"), num.format("HT_DEV"), num.format("MONTANTSIGNE_DEV")
    ou = f"FROM {a} WHERE {ttc} IS NOT NULL"

    n, s_ttc, s_sig = con.execute(f"SELECT count(*), sum({ttc}), sum({sig}) {ou}").fetchone()
    print(f"  Lignes                        : {n:,}".replace(",", " "))
    print(f"  sum(TTC_DEV)   -- utilise auj.: {dt(s_ttc)}")
    print(f"  sum(MONTANTSIGNE_DEV)         : {dt(s_sig)}")

    n_av, ttc_av = con.execute(
        f"SELECT count(*), sum({ttc}) {ou} AND {sig} < 0").fetchone()
    n_av, ttc_av = n_av or 0, ttc_av or 0
    print(f"\n  AVOIRS FOURNISSEUR            : {n_av:,}".replace(",", " "))
    print(f"  Leur TTC                      : {dt(ttc_av)}")
    if n_av:
        print(f"  Surevaluation des achats      : {dt(2 * float(ttc_av))}")
    else:
        print("  -> Aucun avoir fournisseur : les achats sont sains de ce cote.")

    r = con.execute(f"""
        WITH d AS (
            SELECT count(*) AS k, {ttc} AS m
            {ou} AND trim(PIECENOFULL) <> ''
            GROUP BY trim(PIECENOFULL), trim(TIERS), DATEPIECE, {ttc}
            HAVING count(*) > 1
        ) SELECT count(*), coalesce(sum(k - 1), 0), coalesce(sum((k - 1) * m), 0) FROM d
    """).fetchone()
    g, surnum, ca_dup = r
    print(f"\n  DOUBLONS (meme PIECENOFULL)   : {g:,} groupe(s)".replace(",", " "))
    print(f"  Lignes surnumeraires          : {surnum:,}".replace(",", " "))
    print(f"  Montant en trop               : {dt(ca_dup)}")

    achats_corrige = float(s_ttc or 0) - 2 * float(ttc_av) - float(ca_dup)
    print(f"\n  Achats affiches aujourd'hui   : {dt(s_ttc)}")
    print(f"  Achats corriges               : {dt(achats_corrige)}")
    if s_ttc:
        ecart = float(s_ttc) - achats_corrige
        print(f"  Ecart                         : {dt(ecart)}  "
              f"({ecart / float(s_ttc) * 100:.2f} %)")
        print("  -> Impacte le DPO, le BFR et le cycle de tresorerie.")

    titre("LIGNES DE FACTURE -- ZZ_Facture_vente_mouv.csv")
    L = lu("ventes_lignes")
    mt, mts = num.format("MONTANT_DEV"), num.format("MONTANTSIGNE_DEV")
    cr = num.format("MTCRSIGNE")

    n, s_mt, s_mts = con.execute(
        f"SELECT count(*), sum({mt}), sum({mts}) FROM {L}").fetchone()
    print(f"  Lignes                        : {n:,}".replace(",", " "))
    print(f"  sum(MONTANT_DEV)  -- utilise  : {dt(s_mt)}")
    print(f"  sum(MONTANTSIGNE_DEV)         : {dt(s_mts)}")
    if s_mt and s_mts:
        e = float(s_mt) - float(s_mts)
        print(f"  ECART                         : {dt(e)}  "
              f"({e / float(s_mt) * 100:.2f} %)")
        print("  -> C'est l'erreur portee par le CA par PRODUIT et par FAMILLE,")
        print("     qui utilisent aujourd'hui la colonne NON signee.")

    neg, mt_neg = con.execute(
        f"SELECT count(*), sum({mts}) FROM {L} WHERE {mts} < 0").fetchone()
    print(f"\n  Lignes de retour (montant < 0): {neg or 0:,}".replace(",", " "))
    print(f"  Leur montant                  : {dt(mt_neg)}")

    rows = con.execute(f"SELECT trim(SENS) AS s, count(*) FROM {L} GROUP BY 1 ORDER BY 2 DESC"
                       ).fetchall()
    print("\n  Repartition de la colonne SENS :")
    for s, k in rows:
        print(f"    SENS = {s or '(vide)':<6} : {k:,}".replace(",", " "))

    titre("MARGE -- effet du filtre `ca > 0`")
    r = con.execute(f"""
        SELECT
          count(*) FILTER (WHERE {mts} > 0)                       AS n_pos,
          sum({mts}) FILTER (WHERE {mts} > 0)                     AS ca_pos,
          sum({cr})  FILTER (WHERE {mts} > 0)                     AS cout_pos,
          count(*) FILTER (WHERE {mts} < 0)                       AS n_neg,
          sum({mts}) FILTER (WHERE {mts} < 0)                     AS ca_neg,
          sum({cr})  FILTER (WHERE {mts} < 0)                     AS cout_neg
        FROM {L}
    """).fetchone()
    n_pos, ca_pos, cout_pos, n_neg, ca_neg, cout_neg = [x or 0 for x in r]
    marge_actuelle = float(ca_pos) - float(cout_pos)
    marge_nette = (float(ca_pos) + float(ca_neg)) - (float(cout_pos) + float(cout_neg))
    print(f"  Lignes de vente (>0)          : {n_pos:,}".replace(",", " "))
    print(f"  Lignes de retour (<0)         : {n_neg:,}  -- AUJOURD'HUI IGNOREES"
          .replace(",", " "))
    print(f"\n  Marge calculee aujourd'hui    : {dt(marge_actuelle)}")
    print(f"  Marge nette (retours inclus)  : {dt(marge_nette)}")
    if marge_actuelle:
        e = marge_actuelle - marge_nette
        print(f"  Surevaluation de la marge     : {dt(e)}  "
              f"({e / marge_actuelle * 100:.2f} %)")
        print("  -> Le filtre `ca > 0` garde la vente et oublie le retour.")

    titre("LIGNES : y a-t-il des doublons, en echo aux 1 324 factures ?")
    r = con.execute(f"""
        WITH d AS (
            SELECT count(*) AS k, {mts} AS m
            FROM {L} WHERE trim(NUMEROFULL) <> ''
            GROUP BY trim(NUMEROFULL), trim(TIERS), DATEFACTURE,
                     trim(REFERENCE), {mts}, TRY_CAST(QTEFACTURE AS DOUBLE)
            HAVING count(*) > 1
        ) SELECT count(*), coalesce(sum(k - 1), 0), coalesce(sum((k - 1) * m), 0) FROM d
    """).fetchone()
    g, surnum, mt_dup = r
    print(f"  Groupes identiques            : {g:,}".replace(",", " "))
    print(f"  Lignes surnumeraires          : {surnum:,}".replace(",", " "))
    print(f"  Montant en trop               : {dt(mt_dup)}")
    print("\n  ATTENTION : une facture peut legitimement porter deux fois la meme")
    print("  reference (deux lots, deux dates de peremption). Ce chiffre est un")
    print("  MAJORANT ; il ne faut dedupliquer que s'il correspond aux factures")
    print("  deja identifiees comme dupliquees dans l'entete.")
    croise = con.execute(f"""
        WITH entetes_dupliquees AS (
            SELECT trim(PIECENOFULL) AS p
            FROM {lu('ventes_entetes')}
            WHERE TRY_CAST(TTC_DEV AS DOUBLE) IS NOT NULL AND trim(PIECENOFULL) <> ''
            GROUP BY 1, trim(TIERS), DATEPIECE, TRY_CAST(TTC_DEV AS DOUBLE)
            HAVING count(*) > 1
        )
        SELECT count(*) FROM {L} l
        WHERE trim(l.NUMEROFULL) IN (SELECT p FROM entetes_dupliquees)
    """).fetchone()[0]
    print(f"\n  Lignes appartenant aux factures dupliquees de l'entete : {croise:,}"
          .replace(",", " "))

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
