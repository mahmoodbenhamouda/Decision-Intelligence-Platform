"""
etl/qualite.py
==============
Contrôles exécutés à la fin de chaque construction, avant validation.

Trois familles :

* **erreur** — l'entrepôt serait faux : clé de dimension en double (une vente
  compterait deux fois), fait orphelin de sa dimension, fait vide. Une seule
  erreur annule toute la construction : l'entrepôt précédent reste en place.
* **alerte** — la donnée source est imparfaite mais l'entrepôt reste juste :
  date hors calendrier, ligne sans référence produit, lignes rejetées.
* **info** — ce que les règles ont fait : doublons écartés, avoirs, montants.

Le résultat est écrit dans la table `etl_controles` et dans
`reports/etl_construction.json`.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: (dimension, clé)
CLES = [
    ("dim_client", "client_code"), ("dim_produit", "reference"),
    ("dim_fournisseur", "fournisseur_code"), ("dim_depot", "depot_code"),
    ("dim_mode_reglement", "mode_cle"), ("dim_date", "date"),
]

#: (fait, colonne, dimension, clé) — une valeur vide ou NULL n'est pas
#: une référence : elle est comptée à part (« sans … »).
REFERENCES = [
    ("fait_vente", "client_code", "dim_client", "client_code"),
    ("fait_vente", "mode_cle", "dim_mode_reglement", "mode_cle"),
    ("fait_vente", "depot_code", "dim_depot", "depot_code"),
    ("fait_ligne_vente", "client_code", "dim_client", "client_code"),
    ("fait_ligne_vente", "reference", "dim_produit", "reference"),
    ("fait_achat", "fournisseur_code", "dim_fournisseur", "fournisseur_code"),
    ("fait_ligne_achat", "reference", "dim_produit", "reference"),
    ("fait_ligne_achat", "fournisseur_code", "dim_fournisseur", "fournisseur_code"),
    ("fait_devis", "client_code", "dim_client", "client_code"),
    ("fait_livraison", "client_code", "dim_client", "client_code"),
]

#: Faits dont les dates doivent tomber dans le calendrier.
DATES = [("fait_vente", "date"), ("fait_ligne_vente", "date"), ("fait_achat", "date"),
         ("fait_ligne_achat", "date"), ("fait_devis", "date"), ("fait_livraison", "date")]

FAITS = ["fait_vente", "fait_ligne_vente", "fait_achat", "fait_ligne_achat",
         "fait_devis", "fait_livraison"]


def _n(con, sql: str) -> float:
    v = con.execute(sql).fetchone()[0]
    return float(v or 0)


def controler(con) -> List[Dict[str, Any]]:
    res: List[Dict[str, Any]] = []

    def ajouter(nom: str, niveau: str, valeur: float, description: str) -> None:
        # Un contrôle d'erreur ou d'alerte passe quand sa valeur est nulle.
        statut = "ok" if (niveau == "info" or valeur == 0) else niveau
        res.append({"controle": nom, "niveau": niveau, "valeur": valeur,
                    "statut": statut, "description": description})

    for fait in FAITS:
        n = _n(con, f"SELECT count(*) FROM {fait}")
        ajouter(f"volume:{fait}", "erreur", float(n == 0),
                f"{fait} contient {int(n)} ligne(s) — un fait vide est une erreur")

    for dim, cle in CLES:
        n = _n(con, f"SELECT count(*) FROM (SELECT {cle} FROM {dim} "
                    f"GROUP BY {cle} HAVING count(*) > 1)")
        ajouter(f"unicite:{dim}.{cle}", "erreur", n,
                f"valeurs de {dim}.{cle} présentes plusieurs fois")

    for fait, col, dim, cle in REFERENCES:
        n = _n(con, f"""SELECT count(*) FROM {fait} f
                        WHERE f.{col} IS NOT NULL AND f.{col} <> ''
                          AND NOT EXISTS (SELECT 1 FROM {dim} d WHERE d.{cle} = f.{col})""")
        ajouter(f"integrite:{fait}.{col}", "erreur", n,
                f"lignes de {fait} dont {col} est absent de {dim}")

    for fait, col in DATES:
        n = _n(con, f"""SELECT count(*) FROM {fait} f WHERE f.{col} IS NOT NULL
                        AND NOT EXISTS (SELECT 1 FROM dim_date d WHERE d.date = f.{col})""")
        ajouter(f"calendrier:{fait}.{col}", "alerte", n,
                f"lignes de {fait} datées hors du calendrier (date de remplissage de l'export)")

    ajouter("lignes_vente_sans_reference", "alerte",
            _n(con, "SELECT count(*) FROM fait_ligne_vente WHERE reference IS NULL OR reference = ''"),
            "lignes de vente sans référence produit (rattachées à aucun produit)")
    ajouter("lignes_vente_rejetees", "alerte", _n(con, "SELECT count(*) FROM rejet_ligne_vente"),
            "lignes de vente écartées pour décalage de colonnes (rejet_ligne_vente)")

    # Ce que les règles ont fait, pour que les écarts avec la source se lisent.
    ajouter("ventes:entetes_lus", "info", _n(con, "SELECT count(*) FROM stg_ventes_entetes"),
            "en-têtes de vente lus dans la source")
    ajouter("ventes:sans_date_ou_montant", "info",
            _n(con, "SELECT count(*) FROM stg_ventes_entetes WHERE date IS NULL OR ttc_abs IS NULL"),
            "en-têtes écartés : date ou montant illisible")
    ajouter("ventes:doublons_ecartes", "info",
            _n(con, """SELECT count(*) FROM stg_ventes_entetes
                       WHERE date IS NOT NULL AND ttc_abs IS NOT NULL""")
            - _n(con, "SELECT count(*) FROM fait_vente"),
            "pièces de vente présentes plusieurs fois dans l'export, gardées une fois")
    ajouter("ventes:avoirs", "info", _n(con, "SELECT count(*) FROM fait_vente WHERE est_avoir"),
            "avoirs, comptés en déduction du chiffre d'affaires")
    ajouter("ventes:ttc_total", "info", _n(con, "SELECT round(sum(ttc), 2) FROM fait_vente"),
            "chiffre d'affaires TTC net des avoirs (DT)")
    ajouter("clients:deduits", "info",
            _n(con, "SELECT count(*) FROM dim_client WHERE origine = 'deduit'"),
            "clients présents dans les faits mais absents du référentiel")
    return res


def enregistrer(con, controles: List[Dict[str, Any]]) -> None:
    con.execute("""CREATE OR REPLACE TABLE etl_controles (
                       controle VARCHAR, niveau VARCHAR, valeur DOUBLE,
                       statut VARCHAR, description VARCHAR)""")
    con.executemany("INSERT INTO etl_controles VALUES (?, ?, ?, ?, ?)",
                    [(c["controle"], c["niveau"], c["valeur"], c["statut"], c["description"])
                     for c in controles])


def erreurs(controles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [c for c in controles if c["statut"] == "erreur"]
