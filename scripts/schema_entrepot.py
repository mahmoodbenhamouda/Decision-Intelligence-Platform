"""Dessine le schéma en étoile de l'entrepôt À PARTIR DE L'ENTREPÔT LUI-MÊME : tables, colonnes,…"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

_GV_WINDOWS = r"C:\Program Files\Graphviz\bin"
if os.path.isdir(_GV_WINDOWS) and _GV_WINDOWS not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _GV_WINDOWS + os.pathsep + os.environ.get("PATH", "")

import duckdb  # noqa: E402
from graphviz import Digraph  # noqa: E402

from etl.qualite import REFERENCES  # noqa: E402
from etl.sources import ENTREPOT  # noqa: E402

GRAINS = {
    "fait_vente": "une pièce de vente (facture ou avoir)",
    "fait_ligne_vente": "une ligne de facture de vente",
    "fait_achat": "une pièce d'achat",
    "fait_ligne_achat": "une ligne de facture d'achat",
    "fait_devis": "un devis",
    "fait_livraison": "un bon de livraison",
}
CLES_DIM = {"dim_client": "client_code", "dim_produit": "reference",
            "dim_fournisseur": "fournisseur_code", "dim_depot": "depot_code",
            "dim_mode_reglement": "mode_cle", "dim_date": "date"}
VENTES = ["fait_vente", "fait_ligne_vente", "fait_devis", "fait_livraison"]
ACHATS = ["fait_achat", "fait_ligne_achat"]
DATES = ["fait_vente", "fait_ligne_vente", "fait_achat", "fait_ligne_achat",
         "fait_devis", "fait_livraison"]

COULEUR_FAIT = "#1F4E79"
COULEUR_DIM = "#2E7D5B"


def _colonnes(con, table):
    return con.execute("SELECT column_name, data_type FROM information_schema.columns "
                       "WHERE table_name = ? ORDER BY ordinal_position", [table]).fetchall()


def _table_html(nom, colonnes, volume, entete, sous_titre, cles, fks):
    lignes = [f'<TR><TD BGCOLOR="{entete}" ALIGN="LEFT"><FONT COLOR="white"><B>{nom}</B>'
              f'</FONT><FONT COLOR="white" POINT-SIZE="9">   {volume:,} lignes</FONT></TD></TR>'
              .replace(",", " ")]
    if sous_titre:
        lignes.append(f'<TR><TD ALIGN="LEFT" BGCOLOR="#F3F3F3"><I><FONT POINT-SIZE="9">'
                      f'grain : {sous_titre}</FONT></I></TD></TR>')
    for col, typ in colonnes:
        marque = "PK  " if col in cles else ("FK  " if col in fks else "")
        gras = ("<B>", "</B>") if col in cles else ("", "")
        lignes.append(f'<TR><TD ALIGN="LEFT" PORT="{col}"><FONT POINT-SIZE="10">{marque}'
                      f'{gras[0]}{col}{gras[1]}</FONT> <FONT POINT-SIZE="8" COLOR="#777777">'
                      f'{typ.lower()}</FONT></TD></TR>')
    return ('<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" COLOR="#BBBBBB">'
            + "".join(lignes) + "</TABLE>>")


def dessiner(entrepot: Path, sortie: Path) -> list[Path]:
    con = duckdb.connect(str(entrepot), read_only=True)
    dot = Digraph("entrepot", graph_attr={"rankdir": "LR", "splines": "spline",
                                          "nodesep": "0.35", "ranksep": "1.2",
                                          "fontname": "Helvetica", "bgcolor": "white",
                                          "label": "Entrepôt de données — schémas en étoile partageant des dimensions conformes "
                                                   "(constellation de faits, clés naturelles ERP)",
                                          "labelloc": "t", "fontsize": "18"},
                  node_attr={"shape": "plaintext", "fontname": "Helvetica"},
                  edge_attr={"color": "#8A8A8A", "arrowsize": "0.6"})
    fks = {}
    for fait, col, _dim, _cle in REFERENCES:
        fks.setdefault(fait, set()).add(col)
    for fait in DATES:
        fks.setdefault(fait, set()).add("date")

    for cluster, titre, faits in (("cluster_ventes", "Faits — cycle de vente", VENTES),
                                  ("cluster_achats", "Faits — cycle d'achat", ACHATS)):
        with dot.subgraph(name=cluster) as g:
            g.attr(label=titre, style="dashed", color="#CCCCCC", fontcolor="#555555")
            for fait in faits:
                n = con.execute(f"SELECT count(*) FROM {fait}").fetchone()[0]
                g.node(fait, _table_html(fait, _colonnes(con, fait), n, COULEUR_FAIT,
                                         GRAINS[fait], set(), fks.get(fait, set())))
    with dot.subgraph(name="cluster_dims") as g:
        g.attr(label="Dimensions", style="dashed", color="#CCCCCC", fontcolor="#555555")
        for dim, cle in CLES_DIM.items():
            n = con.execute(f"SELECT count(*) FROM {dim}").fetchone()[0]
            g.node(dim, _table_html(dim, _colonnes(con, dim), n, COULEUR_DIM, None,
                                    {cle}, set()))
    con.close()

    def lien(fait, col, dim, cle, **style):
        if fait in ACHATS:
            dot.edge(f"{dim}:{cle}", f"{fait}:{col}", dir="back", **style)
        else:
            dot.edge(f"{fait}:{col}", f"{dim}:{cle}", **style)

    for fait, col, dim, cle in REFERENCES:
        lien(fait, col, dim, cle)
    for fait in DATES:
        lien(fait, "date", "dim_date", "date", style="dashed")

    sortie.parent.mkdir(parents=True, exist_ok=True)
    produits = []
    for fmt in ("svg", "png"):
        dot.format = fmt
        if fmt == "png":
            dot.graph_attr["dpi"] = "160"
        produits.append(Path(dot.render(str(sortie), cleanup=True)))
    return produits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--entrepot", type=Path, default=ENTREPOT)
    ap.add_argument("--sortie", type=Path,
                    default=RACINE / "docs" / "data_warehouse" / "schema_etoile")
    a = ap.parse_args()
    for p in dessiner(a.entrepot, a.sortie):
        print(f"→ {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
