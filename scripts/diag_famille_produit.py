"""
scripts/diag_famille_produit.py
================================
La famille produit est-elle renseignée ? Mesurer au lieu d'affirmer.

Pourquoi ce script existe
-------------------------
J'ai affirmé que la colonne `ARTICLE_LIBELLE_FAM_STAT1` portait une nomenclature
produit exploitable, en me fondant sur le fait qu'elle est **lue** dans
`kpi_engine` et sur un commentaire annonçant « ~99 % du CA réel ».

La mesure a donné **0 désignation** avec une famille. L'affirmation était fausse,
et elle l'était pour la raison exacte que ce projet reproche ailleurs : j'ai lu du
code et un commentaire au lieu d'interroger la donnée.

Ce script existe pour que la question soit tranchée par une mesure, dans un sens
ou dans l'autre, et qu'elle le reste si l'export change un jour. Il regarde à
trois endroits, du plus brut au plus transformé — un vide peut apparaître à
n'importe lequel des trois.

    python scripts/diag_famille_produit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

COLONNE = "ARTICLE_LIBELLE_FAM_STAT1"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH

    try:
        from config.settings import settings
        data_dir = Path(settings.data_dir)
    except Exception:
        data_dir = BASE / "data_pfe"

    print("=" * 74)
    print(f"  FAMILLE PRODUIT — la colonne {COLONNE} est-elle remplie ?")
    print("=" * 74)

    # ── 1. Le CSV brut : la colonne existe-t-elle, et que contient-elle ? ────
    csv = None
    for nom in ("Facture_vente_mouv_v.csv", "Facture_vente_lig_v.csv",
                "Facture_vente_ent_v.csv"):
        p = data_dir / nom
        if p.exists():
            csv = p
            break

    if csv is None:
        print(f"\n  [!] aucun fichier de lignes de vente trouvé dans {data_dir}")
    else:
        print(f"\n  Fichier : {csv.name}")
        con = duckdb.connect()
        try:
            colonnes = [r[0] for r in con.execute(
                f"DESCRIBE SELECT * FROM read_csv_auto("
                f"'{csv.as_posix()}', sample_size=2000, all_varchar=true)"
            ).fetchall()]
            present = COLONNE in colonnes
            print(f"  Colonne présente dans le schéma : "
                  f"{'OUI' if present else 'NON'}")
            if not present:
                proches = [c for c in colonnes if "FAM" in c.upper()]
                print(f"  Colonnes contenant « FAM » : {proches or 'aucune'}")
            else:
                n, remplies = con.execute(f"""
                    SELECT count(*),
                           count(*) FILTER (WHERE trim({COLONNE}) <> ''
                                            AND {COLONNE} IS NOT NULL)
                    FROM read_csv_auto('{csv.as_posix()}', sample_size=20000,
                                       ignore_errors=true, all_varchar=true)
                """).fetchone()
                part = (remplies or 0) / max(n or 1, 1) * 100
                print(f"  Lignes : {n:,}".replace(",", " ")
                      + f" · renseignées : {remplies:,}".replace(",", " ")
                      + f" ({part:.1f} %)")
                if remplies:
                    print("\n  Valeurs les plus fréquentes :")
                    for v, c in con.execute(f"""
                        SELECT trim({COLONNE}) AS f, count(*) AS n
                        FROM read_csv_auto('{csv.as_posix()}', sample_size=20000,
                                           ignore_errors=true, all_varchar=true)
                        WHERE trim({COLONNE}) <> '' AND {COLONNE} IS NOT NULL
                        GROUP BY 1 ORDER BY n DESC LIMIT 12
                    """).fetchall():
                        print(f"    {str(v)[:44]:<46} {c:>8}")
        except Exception as e:
            print(f"  [erreur] {type(e).__name__} : {e}")
        finally:
            con.close()

    # ── 2 et 3. L'entrepôt : sales_lines, puis product_family ───────────────
    if not STORE_PATH.exists():
        print(f"\n  [!] entrepôt absent : {STORE_PATH}")
        print("=" * 74)
        return 1

    con = duckdb.connect(str(STORE_PATH), read_only=True)
    try:
        n, remplies = con.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE famille IS NOT NULL
                                    AND trim(famille) <> '')
            FROM sales_lines
        """).fetchone()
        part = (remplies or 0) / max(n or 1, 1) * 100
        print(f"\n  sales_lines.famille : {remplies:,} / {n:,}".replace(",", " ")
              + f" lignes ({part:.1f} %)")

        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "product_family" in tables:
            nf = con.execute("SELECT count(*) FROM product_family").fetchone()[0]
            print(f"  product_family      : {nf} ligne(s)")
            if nf == 0:
                print("    -> la table alimentant « top_familles » du tableau de")
                print("       bord est VIDE : ce panneau n'affiche donc rien.")
        else:
            print("  product_family      : table absente")
    except Exception as e:
        print(f"  [erreur] {type(e).__name__} : {e}")
    finally:
        con.close()

    print("\n" + "-" * 74)
    print("  Lecture. Si la part est nulle partout, la famille produit est bien")
    print("  ABSENTE de l'export, et le classement par mots-clés de libellé reste")
    print("  la seule source — avec la valeur exposée que cela implique. Si elle")
    print("  est renseignée, `ml_engine/stock/nomenclature.py` la prend")
    print("  automatiquement comme source primaire, sans modification.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
