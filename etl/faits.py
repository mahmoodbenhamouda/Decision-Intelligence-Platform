"""
etl/faits.py
============
Tables de faits : les mesures, au grain déclaré, après application des règles
métier. Chaque fait porte les CLÉS NATURELLES de ses dimensions (code client,
référence produit, code fournisseur, date, code dépôt, clé du mode de
règlement) : voir docs/DATA_WAREHOUSE.md, « Clés ».

| Fait               | Grain (une ligne =)                                  |
|--------------------|------------------------------------------------------|
| fait_vente         | une pièce de vente — facture ou avoir — dédoublonnée |
| fait_ligne_vente   | une ligne de facture de vente, au format valide      |
| fait_achat         | une pièce d'achat — facture ou avoir — dédoublonnée  |
| fait_ligne_achat   | une ligne de facture d'achat                         |
| fait_devis         | un devis de vente dédoublonné                        |
| fait_livraison     | un bon de livraison                                  |

Les lignes de vente écartées pour décalage de colonnes vont dans
`rejet_ligne_vente` : elles sont comptées et consultables, jamais perdues en
silence.
"""

from __future__ import annotations


def construire(con) -> None:
    _fait_vente(con)
    _fait_ligne_vente(con)
    _fait_achat(con)
    _fait_ligne_achat(con)
    _fait_devis(con)
    _fait_livraison(con)


def _fait_vente(con) -> None:
    # 1. SIGNE COMPTABLE. `TTC_DEV` et `HT_DEV` sont TOUJOURS positifs, y
    #    compris pour un avoir. Le sens est porté par `MONTANTSIGNE_DEV`.
    #    Sommer `TTC_DEV` ajoutait les avoirs au chiffre d'affaires au lieu de
    #    les en retrancher (5 761 avoirs, 14,8 M DT d'erreur sur ce jeu).
    #
    # 2. DÉDOUBLONNAGE. `ENT_ID` est un identifiant technique d'export, unique
    #    par construction : il ne détecte aucun doublon. La clé métier est
    #    `PIECENOFULL` ; 1 324 factures y figurent deux fois — même numéro,
    #    même client, même date, même montant — pour 1 053 938 DT. Une pièce
    #    sans numéro lisible est partitionnée sur son ENT_ID, donc toujours
    #    conservée : on ne fusionne jamais par défaut.
    con.execute("""
        CREATE OR REPLACE TABLE fait_vente AS
        WITH lues AS (
            SELECT * FROM stg_ventes_entetes
            WHERE date IS NOT NULL AND ttc_abs IS NOT NULL
        ),
        dedup AS (
            SELECT *, row_number() OVER (
                PARTITION BY CASE WHEN piece_no IS NULL OR piece_no = ''
                                  THEN CAST(ent_id AS VARCHAR) ELSE piece_no END,
                             client, date, ttc_abs
                ORDER BY ent_id
            ) AS rang
            FROM lues
        )
        SELECT ent_id, piece_no,
               client          AS client_code,
               date, echeance,
               ht_abs  * signe AS ht,
               ttc_abs * signe AS ttc,
               (signe < 0)     AS est_avoir,
               mode_cle,
               nbr_article,
               depot_code
        FROM dedup WHERE rang = 1
    """)


def _fait_ligne_vente(con) -> None:
    # DÉDOUBLONNAGE CIBLÉ. 11 412 lignes paraissent redondantes, mais seules
    # 8 518 appartiennent aux factures dont l'EN-TÊTE est en double. Les autres
    # sont légitimes : une facture peut porter deux fois la même référence
    # (deux lots, deux dates de péremption). On ne dédoublonne donc que les
    # lignes des en-têtes dupliqués, et on conserve n_exemplaires / n_copies
    # (arrondi au supérieur) : une facture présente 2 fois dont une ligne
    # apparaît 4 fois porte en réalité 2 exemplaires légitimes de cette ligne.
    #
    # FORMAT. SENS ne peut valoir que 1 (retour) ou 2 (vente). Toute autre
    # valeur — on trouve « CULTURE » et « GAFSA » — trahit une virgule non
    # échappée qui a décalé la ligne : ses montants appartiennent à d'autres
    # colonnes. Ces lignes sont écartées dans `rejet_ligne_vente`.
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _lignes_vente AS
        WITH groupes_entete AS (
            SELECT piece_no AS piece, count(*) AS n
            FROM stg_ventes_entetes
            WHERE ttc_abs IS NOT NULL AND piece_no <> ''
            GROUP BY piece_no, client, date_brute, ttc_abs
            HAVING count(*) > 1
        ),
        entetes_dupliquees AS (
            SELECT piece, max(n) AS n_copies FROM groupes_entete GROUP BY piece
        ),
        marque AS (
            SELECT l.*,
                   coalesce(e.n_copies, 1) AS n_copies_entete,
                   row_number() OVER (
                       PARTITION BY l.piece_no, l.client, l.date, l.reference, l.montant, l.qte
                       ORDER BY l.mouv_id)                     AS rang,
                   count(*) OVER (
                       PARTITION BY l.piece_no, l.client, l.date, l.reference, l.montant, l.qte)
                                                             AS n_exemplaires
            FROM stg_ventes_lignes l
            LEFT JOIN entetes_dupliquees e ON e.piece = l.piece_no
        )
        SELECT mouv_id, piece_no, client, reference, designation, famille,
               date, montant, qte, cout, format_valide
        FROM marque
        WHERE rang <= CAST(ceil(n_exemplaires * 1.0 / n_copies_entete) AS BIGINT)
    """)
    con.execute("""
        CREATE OR REPLACE TABLE rejet_ligne_vente AS
        SELECT mouv_id, piece_no, client AS client_code, reference, designation,
               famille, date, montant, qte, cout, format_valide
        FROM _lignes_vente WHERE NOT format_valide
    """)
    # `format_valide` peut être NULL (SENS absent) : ces lignes ne sont pas
    # prouvées décalées, elles sont conservées — comme avant la refonte.
    con.execute("""
        CREATE OR REPLACE TABLE fait_ligne_vente AS
        SELECT mouv_id, piece_no,
               client      AS client_code,
               reference,
               -- Libellé et famille TELS QUE FACTURÉS (attributs dégénérés) :
               -- une même référence porte parfois plusieurs désignations, et
               -- les analyses par désignation doivent voir celle de la facture.
               -- Le libellé de référence du produit est dans dim_produit.
               designation, famille,
               date, montant, qte, cout, format_valide
        FROM _lignes_vente
        WHERE format_valide IS DISTINCT FROM FALSE
    """)
    con.execute("DROP TABLE _lignes_vente")


def _fait_achat(con) -> None:
    # Mêmes règles que pour les ventes : signe comptable, dédoublonnage sur la
    # clé métier (numéro, fournisseur, date, montant).
    con.execute("""
        CREATE OR REPLACE TABLE fait_achat AS
        WITH lues AS (SELECT * FROM stg_achats_entetes WHERE date IS NOT NULL),
        dedup AS (
            SELECT *, row_number() OVER (
                PARTITION BY CASE WHEN piece_no IS NULL OR piece_no = ''
                                  THEN CAST(ent_id AS VARCHAR) ELSE piece_no END,
                             fournisseur_code, date, ttc_abs
                ORDER BY ent_id
            ) AS rang
            FROM lues
        )
        SELECT ent_id, piece_no,
               fournisseur,              -- nom tel qu'il figure sur la pièce
               fournisseur_code,
               date, echeance,
               ht_abs  * signe AS ht,
               ttc_abs * signe AS ttc,
               (signe < 0)     AS est_avoir,
               mode_regl,                -- libellé ERP brut : aucun indicateur ne l'exploite
               tva_abs * signe AS tva,
               piece_externe
        FROM dedup WHERE rang = 1
    """)


def _fait_ligne_achat(con) -> None:
    # Toutes les lignes sont conservées : c'est l'indicateur ERP
    # `INDICMVTSTOCK` qui dit lesquelles génèrent un mouvement de stock, et sa
    # valeur est établie empiriquement par ml_engine/stock/flux_reels.py.
    con.execute("""
        CREATE OR REPLACE TABLE fait_ligne_achat AS
        SELECT mouv_id, piece_no, fournisseur_code, reference, designation,
               indic_mvt_stock, date, qte, montant
        FROM stg_achats_lignes
    """)


def _fait_devis(con) -> None:
    # Même dédoublonnage que les ventes et les achats, sur les valeurs
    # exportées. ETATPIECE = 8 : devis TRANSFORMÉ en facture — interprétation
    # validée empiriquement (89,4 % des devis en état 8 ont une facture du même
    # client au même montant à ± 1 %, contre 37,4 % pour l'état 1).
    con.execute("""
        CREATE OR REPLACE TABLE fait_devis AS
        WITH dedup AS (
            SELECT *, row_number() OVER (
                PARTITION BY CASE WHEN piece_no = '' THEN ent_id_brut ELSE piece_no END,
                             client, date_brute, ttc_brut
                ORDER BY ent_id
            ) AS rang
            FROM stg_devis
            WHERE date IS NOT NULL
        )
        SELECT client AS client_code, piece_no, date,
               -- Un devis n'a pas d'avoir ; le signe est repris par cohérence.
               ht_abs  * signe AS ht,
               ttc_abs * signe AS ttc,
               status, etat_piece,
               coalesce(etat_piece = '8', FALSE) AS transforme
        FROM dedup WHERE rang = 1
    """)


def _fait_livraison(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE fait_livraison AS
        SELECT client AS client_code, date, nbr_article
        FROM stg_livraisons
    """)
