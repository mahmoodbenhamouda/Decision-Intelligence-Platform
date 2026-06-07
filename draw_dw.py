import os, sys

# Ensure Graphviz bin is on PATH regardless of system configuration
_GV_BIN = r"C:\Program Files\Graphviz\bin"
if os.path.isdir(_GV_BIN) and _GV_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _GV_BIN + os.pathsep + os.environ.get("PATH", "")

from graphviz import Digraph
import pandas as pd

# -----------------------------
# 1. Heuristiques de détection
# -----------------------------

DIMENSIONS = {
    "Dim_Client": ["cle_client", "client"],
    "Dim_Fournisseur": ["cle_fournisseur", "supplier"],
    "Dim_Date": ["date"],
    "Dim_Payment": ["payment", "mode_reglement"]
}

FACTS = {
    "Fact_Ventes": ["ventes", "facture_vente"],
    "Fact_Achats": ["achat", "facture_achat"],
    "Fact_Devis": ["devis"],
    "Fact_BL": ["bl", "livraison"],
    "Fact_Paiements": ["paiement", "reglement"]
}

# -----------------------------
# 2. Détection automatique
# -----------------------------

def detect_table_type(table_name: str):
    name = table_name.lower()

    for dim, keywords in DIMENSIONS.items():
        if any(k in name for k in keywords):
            return "dimension", dim

    for fact, keywords in FACTS.items():
        if any(k in name for k in keywords):
            return "fact", fact

    return "unknown", table_name


# -----------------------------
# 3. Détection relations (clé étrangère simple)
# -----------------------------

def detect_relations(tables: dict):
    relations = []

    for fact_name, fact_df in tables.items():
        for dim_name, dim_df in tables.items():

            if fact_name == dim_name:
                continue

            for col in fact_df.columns:
                if col in dim_df.columns:
                    relations.append((dim_name, fact_name, col))

    return relations


# -----------------------------
# 4. Génération du schéma
# -----------------------------

def draw_warehouse_pretty(tables: dict, output_name="dw_beautiful"):

    dot = Digraph("DataWarehouse")

    # ⭐ STYLE GLOBAL
    dot.attr(
        rankdir="LR",
        splines="ortho",
        nodesep="0.8",
        ranksep="1.2",
        fontsize="12"
    )

    dot.attr("node", shape="box", style="rounded,filled", fontsize="10")

    # -------------------
    # DIMENSIONS (BLEU)
    # -------------------
    dims = ["Dim_Client", "Dim_Fournisseur", "Dim_Date", "Dim_Payment"]

    for d in dims:
        if d in tables:
            dot.node(d, d, fillcolor="#cfe2f3", color="#2b5797", penwidth="2")

    # -------------------
    # FACTS (ORANGE)
    # -------------------
    facts = [
        "Fact_Ventes",
        "Fact_Achats",
        "Fact_Devis",
        "Fact_BL",
        "Fact_Paiements"
    ]

    for f in facts:
        if f in tables:
            dot.node(f, f, fillcolor="#f9cb9c", color="#e69138", penwidth="2")

    # -------------------
    # RELATIONS PROPRES
    # -------------------

    def link(a, b, label=""):
        dot.edge(a, b, label=label, color="#666666", penwidth="1.2")

    # Client relations
    if "Dim_Client" in tables:
        for f in ["Fact_Ventes", "Fact_Devis", "Fact_Paiements"]:
            if f in tables:
                link("Dim_Client", f, "client_key")

    # Fournisseur
    if "Dim_Fournisseur" in tables:
        for f in ["Fact_Achats", "Fact_Devis", "Fact_BL"]:
            if f in tables:
                link("Dim_Fournisseur", f, "supplier_key")

    # Date (hub central)
    if "Dim_Date" in tables:
        for f in facts:
            if f in tables:
                link("Dim_Date", f, "date_key")

    # Payment
    if "Dim_Payment" in tables:
        for f in facts:
            if f in tables:
                link("Dim_Payment", f, "payment_code")

    # -------------------
    # EXPORT HD
    # -------------------
    dot.render(output_name, format="png", view=True, cleanup=True)

    print(f"✔ Beautiful DW generated: {output_name}.png")


# -----------------------------
# 5. TEST avec ton warehouse
# -----------------------------

if __name__ == "__main__":

    warehouse = {
        "Dim_Client": pd.DataFrame(columns=["cle_client"]),
        "Dim_Fournisseur": pd.DataFrame(columns=["cle_fournisseur"]),
        "Dim_Date": pd.DataFrame(columns=["date"]),
        "Dim_Payment": pd.DataFrame(columns=["payment_code"]),

        "Fact_Ventes": pd.DataFrame(columns=["cle_client", "date", "payment_code"]),
        "Fact_Achats": pd.DataFrame(columns=["cle_fournisseur", "date"]),
        "Fact_Paiements": pd.DataFrame(columns=["cle_client", "date", "payment_code"]),
    }

    draw_warehouse_pretty(warehouse)