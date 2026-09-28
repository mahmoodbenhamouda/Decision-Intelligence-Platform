"""
etl/staging.py
==============
Zone de préparation (staging) : chaque source CSV projetée et typée, UNE fois.

Les tables `stg_*` sont TEMPORAIRES : elles n'existent que le temps de la
construction et ne sont jamais lues par l'application. Elles conservent TOUTES
les lignes de la source — aucune règle métier n'est appliquée ici, seulement le
typage (dates, montants) et le nettoyage des espaces. Les règles (signe,
dédoublonnage, rejet) appartiennent à la couche suivante (`faits.py`).

Certaines colonnes sont gardées sous leur forme BRUTE (`*_brut`) : la détection
des doublons d'en-tête compare les valeurs telles qu'exportées, avant tout
parsing, pour ne rien fusionner que l'ERP distinguait.
"""

from __future__ import annotations

from pathlib import Path

from etl import regles as R
from etl.sources import lecture


def construire(con, dossier: Path) -> None:
    lire = lambda role: lecture(role, dossier)  # noqa: E731

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_ventes_entetes AS
        SELECT
            TRY_CAST(ENT_ID AS BIGINT)        AS ent_id,
            trim(PIECENOFULL)                 AS piece_no,
            trim(TIERS)                       AS client,
            DATEPIECE                         AS date_brute,
            {R.date('DATEPIECE')}             AS date,
            {R.echeance('DATEECHEANCE')}      AS echeance,
            {R.signe()}                       AS signe,
            {R.montant('HT_DEV')}             AS ht_abs,
            {R.montant('TTC_DEV')}            AS ttc_abs,
            {R.mode_cle()}                    AS mode_cle,
            {R.mode_libelle()}                AS mode_libelle,
            {R.montant('NBREARTICLE')}        AS nbr_article,
            {R.texte('DEPOT')}                AS depot_code
        FROM {lire('ventes_entetes')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_ventes_lignes AS
        SELECT
            TRY_CAST(MOUV_ID AS BIGINT)       AS mouv_id,
            trim(NUMEROFULL)                  AS piece_no,
            trim(TIERS)                       AS client,
            trim(REFERENCE)                   AS reference,
            trim(DESIGNATION)                 AS designation,
            trim(ARTICLE_LIBELLE_FAM_STAT1)   AS famille,
            {R.date('DATEFACTURE')}           AS date,
            {R.montant('MONTANTSIGNE_DEV')}   AS montant,
            {R.montant('QUANTITESIGNEE')}     AS qte,
            {R.montant('MTCRSIGNE')}          AS cout,
            -- SENS ne peut valoir que 1 (retour) ou 2 (vente) : toute autre
            -- valeur trahit un décalage de colonnes (voir faits.py).
            trim(SENS) IN ('1', '2')          AS format_valide
        FROM {lire('ventes_lignes')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_achats_entetes AS
        SELECT
            TRY_CAST(ENT_ID AS BIGINT)        AS ent_id,
            trim(PIECENOFULL)                 AS piece_no,
            trim(FOURNISSEURNOM)              AS fournisseur,
            trim(CLE_FOURNISSEUR)             AS fournisseur_code,
            {R.date('DATEPIECE')}             AS date,
            {R.echeance('DATEECHEANCE')}      AS echeance,
            {R.signe()}                       AS signe,
            {R.montant('HT_DEV')}             AS ht_abs,
            {R.montant('TTC_DEV')}            AS ttc_abs,
            {R.montant('MONTANTTVAFOURNISSEUR_DEV')} AS tva_abs,
            trim(MODEREGLLIBELLE)             AS mode_regl,
            -- Numéro de la facture CHEZ LE FOURNISSEUR (83 % renseigné) :
            -- c'est celui qu'on lit sur le document. `piece_no` est interne.
            nullif(trim(PIECEEXTERNE), '')    AS piece_externe
        FROM {lire('achats_entetes')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_achats_lignes AS
        SELECT
            TRY_CAST(MOUV_ID AS BIGINT)       AS mouv_id,
            trim(NUMEROFULL)                  AS piece_no,
            trim(CLE_FOURNISSEUR)             AS fournisseur_code,
            trim(REFERENCE)                   AS reference,
            trim(DESIGNATION)                 AS designation,
            trim(INDICMVTSTOCK)               AS indic_mvt_stock,
            {R.date('DATEFACTURE')}           AS date,
            {R.montant('QUANTITESIGNEE')}     AS qte,
            {R.montant('MONTANTSIGNE_DEV')}   AS montant
        FROM {lire('achats_lignes')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_devis AS
        SELECT
            ENT_ID                            AS ent_id_brut,
            TRY_CAST(ENT_ID AS BIGINT)        AS ent_id,
            trim(PIECENOFULL)                 AS piece_no,
            trim(TIERS)                       AS client,
            DATEPIECE                         AS date_brute,
            TTC_DEV                           AS ttc_brut,
            {R.date('DATEPIECE')}             AS date,
            {R.signe()}                       AS signe,
            {R.montant('HT_DEV')}             AS ht_abs,
            {R.montant('TTC_DEV')}            AS ttc_abs,
            trim(STATUS)                      AS status,
            CAST(ETATPIECE AS VARCHAR)        AS etat_piece
        FROM {lire('devis')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_livraisons AS
        SELECT
            trim(ENT_CLIENT_CODE)             AS client,
            {R.date('ENT_DATE')}              AS date,
            {R.montant('ENT_NBR_ARTICLE')}    AS nbr_article
        FROM {lire('livraisons')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_gsl_factures AS
        SELECT
            ENT_CLIENT_CODE                   AS client_code_brut,
            trim(ENT_CLIENT_CODE)             AS client_code,
            trim(ENT_CLIENT_INTITULE)         AS client_name,
            trim(ENT_CLIENT_VILLE)            AS ville,
            ENT_DEPOT_CODE                    AS depot_code_brut,
            trim(ENT_DEPOT_CODE)              AS depot_code,
            trim(ENT_DEPOT_INTITULE)          AS depot_label
        FROM {lire('gsl_factures')}
    """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE stg_fournisseurs AS
        SELECT
            trim(CLE_FOURNISSEUR)             AS fournisseur_code,
            {R.texte('TIERS')}                AS tiers_code,
            {R.texte('NOMFOURNISSEUR')}       AS nom,
            {R.texte('VILLE')}                AS ville,
            {R.texte('PAYSLIBELLE')}          AS pays
        FROM {lire('fournisseurs')}
    """)
