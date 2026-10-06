"""
etl/presentation.py
===================
Couche de présentation : les objets que l'application lit, sous des noms
stables.

Le moteur d'indicateurs, les modèles, les agents et l'API interrogent `sales`,
`sales_lines`, `purchases`… depuis le début du projet. Ces noms sont désormais
des VUES sur le schéma en étoile : chaque vue recompose, à partir d'un fait et
de ses dimensions, exactement les colonnes attendues (nom du client, libellé du
mode de règlement, année, délai de paiement). Le modèle en étoile peut évoluer
sans qu'aucun lecteur ne change, tant que ces vues gardent leur contrat.

Les dimensions `dim_client`, `dim_date` et `dim_depot` gardent leur nom : ce
sont les tables de l'étoile elles-mêmes.
"""

from __future__ import annotations

from typing import Dict

#: nom lu par l'application → définition de la vue.
VUES: Dict[str, str] = {
    # Une pièce de vente, avec le nom du client et le libellé du mode de
    # règlement. Le nom retombe sur le code quand le référentiel n'en a pas.
    "sales": """
        SELECT f.ent_id, f.piece_no, f.client_code AS client, f.date, f.echeance,
               f.ht, f.ttc, f.est_avoir,
               coalesce(m.libelle, 'Non renseigné') AS mode_regl,
               f.nbr_article,
               CAST(year(f.date) AS INTEGER) AS year,
               CAST(CASE WHEN f.echeance IS NOT NULL
                         THEN datediff('day', f.date, f.echeance) END AS INTEGER)
                   AS payment_delay_days,
               CASE WHEN c.client_name IS NULL OR c.client_name = ''
                    THEN f.client_code ELSE c.client_name END AS client_name
        FROM fait_vente f
        LEFT JOIN dim_mode_reglement m ON m.mode_cle = f.mode_cle
        -- Jointure sur UNE ligne par code, même si une insertion applicative
        -- venait à dupliquer un client : une vente ne doit jamais compter deux fois.
        LEFT JOIN (SELECT client_code, max(client_name) AS client_name
                   FROM dim_client GROUP BY client_code) c
               ON c.client_code = f.client_code
    """,
    "sales_lines": """
        SELECT mouv_id, piece_no, client_code AS client, reference, designation,
               famille, date, montant, qte, cout, format_valide
        FROM fait_ligne_vente
    """,
    "sales_lines_rejetees": """
        SELECT mouv_id, piece_no, client_code AS client, reference, designation,
               famille, date, montant, qte, cout, format_valide
        FROM rejet_ligne_vente
    """,
    "purchases": """
        SELECT ent_id, piece_no, fournisseur, fournisseur_code, date, echeance,
               ht, ttc, est_avoir, mode_regl, tva, piece_externe,
               CAST(year(date) AS INTEGER) AS year,
               CAST(CASE WHEN echeance IS NOT NULL
                         THEN datediff('day', date, echeance) END AS INTEGER)
                   AS payment_delay_days
        FROM fait_achat
    """,
    "devis": """
        SELECT client_code AS client, piece_no, date, ht, ttc, status,
               etat_piece, transforme
        FROM fait_devis
    """,
    "bl": "SELECT client_code AS client, date, nbr_article FROM fait_livraison",
    "product_sales": "SELECT * FROM mart_ventes_produit",
    "product_family": "SELECT * FROM mart_ventes_famille",
    "client_product_demand": "SELECT * FROM mart_demande_client_produit",
    "client_margin": "SELECT * FROM mart_marge_client_mois",
    "margin_quality": "SELECT * FROM mart_qualite_marge",
    "margin_category": "SELECT * FROM mart_marge_categorie_mois",
    "margin_product": "SELECT * FROM mart_marge_produit",
}

#: Tables de l'ancien entrepôt remplacées par une vue ou devenues sans objet.
OBSOLETES = ("mode_map", "_build_info")


def _type_objet(con, nom: str) -> str | None:
    r = con.execute("SELECT table_type FROM information_schema.tables "
                    "WHERE table_schema = 'main' AND table_name = ?", [nom]).fetchone()
    return r[0] if r else None


def supprimer(con, nom: str) -> None:
    """Supprime une table ou une vue, quelle que soit sa nature actuelle."""
    t = _type_objet(con, nom)
    if t == "VIEW":
        con.execute(f"DROP VIEW {nom}")
    elif t is not None:
        con.execute(f"DROP TABLE {nom}")


def construire(con) -> None:
    for nom in OBSOLETES:
        supprimer(con, nom)
    for nom, definition in VUES.items():
        # Un entrepôt construit avant la refonte porte ces noms en TABLES :
        # elles sont remplacées par les vues.
        if _type_objet(con, nom) not in (None, "VIEW"):
            supprimer(con, nom)
        con.execute(f"CREATE OR REPLACE VIEW {nom} AS {definition}")
