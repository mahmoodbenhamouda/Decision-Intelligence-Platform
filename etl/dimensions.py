"""
etl/dimensions.py
=================
Dimensions conformes, partagées par tous les faits.

| Dimension           | Clé (naturelle, ERP)  | Source de référence                   |
|---------------------|-----------------------|---------------------------------------|
| dim_date            | date                  | calendrier continu couvrant les faits |
| dim_client          | client_code           | référentiel commercial GSL            |
| dim_produit         | reference             | lignes de vente et d'achat            |
| dim_fournisseur     | fournisseur_code      | référentiel fournisseurs              |
| dim_depot           | depot_code            | référentiel commercial GSL            |
| dim_mode_reglement  | mode_cle              | libellés des factures de vente        |

Construites APRÈS les faits : un code présent dans un fait mais absent du
référentiel devient un membre DÉDUIT (`origine = 'deduit'`), libellé par son
code — c'est déjà ainsi que l'application l'affichait. Sans cela, 158 clients
représentant 3,9 M DT de ventes n'avaient pas de ligne dans `dim_client`.

Historisation : type 1 (écrasement). Les libellés sont ceux du dernier export ;
aucun indicateur du projet ne dépend de l'historique d'un nom ou d'une ville.
"""

from __future__ import annotations

def construire(con) -> None:
    _dim_mode_reglement(con)
    _dim_client(con)
    _dim_produit(con)
    _dim_fournisseur(con)
    _dim_depot(con)
    _dim_date(con)


def _dim_mode_reglement(con) -> None:
    # Libellé affiché = la variante réelle la plus fréquente de chaque groupe.
    con.execute("""
        CREATE OR REPLACE TABLE dim_mode_reglement AS
        WITH base AS (
            SELECT mode_cle, mode_libelle, count(*) AS n
            FROM stg_ventes_entetes GROUP BY 1, 2
        )
        SELECT mode_cle, max_by(mode_libelle, n) AS libelle
        FROM base GROUP BY mode_cle
    """)


def _table_existe(con, nom: str) -> bool:
    return bool(con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name = ?", [nom]).fetchone()[0])


def _colonnes(con, table: str) -> set:
    return {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name = ?", [table]).fetchall()}


def _dim_client(con) -> None:
    # `origine` : 'erp' (référentiel), 'ocr' (client créé à l'import d'une
    # facture scannée), 'deduit' (code présent dans les faits seulement).
    # Valeur par défaut 'application' : un client créé par l'application entre
    # deux constructions est ajouté ici directement (ml_engine/ocr/importer.py).
    con.execute("""
        CREATE OR REPLACE TABLE dim_client (
            client_code VARCHAR, client_name VARCHAR, ville VARCHAR,
            origine VARCHAR DEFAULT 'application')
    """)
    con.execute("""
        INSERT INTO dim_client
        WITH b AS (
            SELECT client_code, client_name, ville, count(*) AS n
            FROM stg_gsl_factures
            WHERE client_code_brut IS NOT NULL AND client_code <> ''
            GROUP BY 1, 2, 3
        )
        SELECT client_code, max_by(client_name, n), max_by(ville, n), 'erp'
        FROM b GROUP BY client_code
    """)
    # Clients créés à l'import OCR : sans cette étape, la reconstruction les
    # effaçait, et le client suivant recevait à nouveau le code OCR-0001, déjà
    # porté par des factures importées.
    if _table_existe(con, "factures_importees"):
        sens = ("coalesce(sens, 'vente') = 'vente'"
                if "sens" in _colonnes(con, "factures_importees") else "TRUE")
        con.execute(f"""
            INSERT INTO dim_client
            SELECT client_code, max(client_name), NULL, 'ocr'
            FROM factures_importees
            WHERE {sens} AND client_code IS NOT NULL AND client_code <> ''
              AND client_code NOT IN (SELECT client_code FROM dim_client)
            GROUP BY client_code
        """)
    con.execute("""
        INSERT INTO dim_client
        SELECT DISTINCT c, c, NULL, 'deduit' FROM (
            SELECT client_code AS c FROM fait_vente
            UNION SELECT client_code FROM fait_ligne_vente
            UNION SELECT client_code FROM fait_devis
            UNION SELECT client_code FROM fait_livraison
        )
        WHERE c IS NOT NULL AND c <> ''
          AND c NOT IN (SELECT client_code FROM dim_client)
    """)


def _dim_produit(con) -> None:
    # Libellé de référence : la désignation la plus facturée de la référence
    # (208 références en portent plusieurs dans les factures).
    con.execute("""
        CREATE OR REPLACE TABLE dim_produit AS
        WITH ventes AS (
            SELECT reference, designation, famille, count(*) AS n
            FROM fait_ligne_vente
            WHERE reference IS NOT NULL AND reference <> ''
            GROUP BY 1, 2, 3
        ),
        vendus AS (
            SELECT reference,
                   max_by(designation, n) AS designation,
                   max_by(famille, n)     AS famille
            FROM ventes GROUP BY reference
        ),
        achetes AS (
            SELECT reference, max_by(designation, n) AS designation
            FROM (SELECT reference, designation, count(*) AS n
                  FROM fait_ligne_achat
                  WHERE reference IS NOT NULL AND reference <> ''
                  GROUP BY 1, 2)
            GROUP BY reference
        )
        SELECT coalesce(v.reference, a.reference)     AS reference,
               coalesce(v.designation, a.designation) AS designation,
               v.famille,
               (v.reference IS NOT NULL)              AS vendu,
               (a.reference IS NOT NULL)              AS achete
        FROM vendus v FULL OUTER JOIN achetes a ON a.reference = v.reference
    """)


def _dim_fournisseur(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_fournisseur AS
        SELECT fournisseur_code, any_value(tiers_code) AS tiers_code,
               any_value(nom) AS nom, any_value(ville) AS ville,
               any_value(pays) AS pays, 'erp' AS origine
        FROM stg_fournisseurs
        WHERE fournisseur_code IS NOT NULL AND fournisseur_code <> ''
        GROUP BY fournisseur_code
    """)
    con.execute("""
        INSERT INTO dim_fournisseur
        SELECT fournisseur_code, NULL, max(fournisseur), NULL, NULL, 'deduit'
        FROM (SELECT fournisseur_code, fournisseur FROM fait_achat
              UNION ALL
              SELECT fournisseur_code, NULL FROM fait_ligne_achat)
        WHERE fournisseur_code IS NOT NULL AND fournisseur_code <> ''
          AND fournisseur_code NOT IN (SELECT fournisseur_code FROM dim_fournisseur)
        GROUP BY fournisseur_code
    """)


def _dim_depot(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE dim_depot AS
        WITH b AS (
            SELECT depot_code, depot_label, count(*) AS n
            FROM stg_gsl_factures
            WHERE depot_code_brut IS NOT NULL AND depot_code <> ''
            GROUP BY 1, 2
        )
        SELECT depot_code, max_by(depot_label, n) AS depot_label, 'erp' AS origine
        FROM b GROUP BY depot_code
    """)
    con.execute("""
        INSERT INTO dim_depot
        SELECT DISTINCT depot_code, depot_code, 'deduit' FROM fait_vente
        WHERE depot_code IS NOT NULL
          AND depot_code NOT IN (SELECT depot_code FROM dim_depot)
    """)


def _dim_date(con) -> None:
    # Calendrier CONTINU, du premier au dernier jour porté par un fait (dates
    # de pièce et d'échéance). Une date aberrante — l'export contient un
    # « 1900-01-01 » de remplissage — n'étire pas le calendrier : elle est
    # signalée par les contrôles de qualité.
    con.execute("""
        CREATE OR REPLACE TABLE dim_date AS
        WITH dates AS (
            SELECT date AS d FROM fait_vente
            UNION ALL SELECT echeance FROM fait_vente
            UNION ALL SELECT date FROM fait_ligne_vente
            UNION ALL SELECT date FROM fait_achat
            UNION ALL SELECT echeance FROM fait_achat
            UNION ALL SELECT date FROM fait_ligne_achat
            UNION ALL SELECT date FROM fait_devis
            UNION ALL SELECT date FROM fait_livraison
        ),
        jours AS (
            SELECT CAST(unnest(generate_series(min(d), max(d), INTERVAL 1 DAY)) AS DATE) AS d
            FROM dates WHERE year(d) BETWEEN 2000 AND 2035
        )
        SELECT d                            AS date,
               year(d)                      AS year,
               month(d)                     AS month,
               quarter(d)                   AS quarter,
               dayofweek(d)                 AS dow,          -- 0 = dimanche
               strftime(d, '%Y-%m')         AS mois,
               weekofyear(d)                AS semaine_iso,
               dayofweek(d) IN (0, 6)       AS fin_de_semaine
        FROM jours
        ORDER BY d
    """)

