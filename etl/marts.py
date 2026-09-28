"""
etl/marts.py
============
Magasins de données (data marts) : agrégats matérialisés, calculés une fois à
partir des faits, pour les écrans et les modèles qui les relisent souvent.

| Mart                          | Grain (une ligne =)            | Lu par                      |
|-------------------------------|--------------------------------|-----------------------------|
| mart_ventes_produit           | produit × année                | tableau de bord, stock      |
| mart_ventes_famille           | famille × année                | tableau de bord, stock      |
| mart_demande_client_produit   | client × produit               | segmentation, stock simulé  |
| mart_marge_client_mois        | client × mois                  | tableau de bord, qualité    |
| mart_qualite_marge            | une ligne : diagnostic global  | tableau de bord             |

Tous les montants sont SIGNÉS : une ligne de retour vient en déduction. Le
montant brut des lignes est toujours positif ; l'utiliser comptait les retours
comme des ventes, exactement comme les avoirs gonflaient le chiffre d'affaires.
"""

from __future__ import annotations

from etl.regles import FAMILLES_HORS_ACTIVITE


def construire(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE mart_ventes_produit AS
        SELECT
            designation                           AS produit,
            year(date)                            AS year,
            sum(montant)                          AS ca,
            sum(qte)                              AS qte,
            count(*) FILTER (WHERE montant >= 0)  AS lignes,
            count(*) FILTER (WHERE montant <  0)  AS lignes_retour
        FROM fait_ligne_vente
        WHERE designation IS NOT NULL AND designation <> ''
        GROUP BY 1, 2
    """)

    # Demande NETTE par client et par produit : un produit livré puis retourné
    # n'a pas été consommé. Une demande nette négative n'est pas exploitable.
    con.execute("""
        CREATE OR REPLACE TABLE mart_demande_client_produit AS
        SELECT
            client_code                           AS client,
            designation                           AS produit,
            sum(qte)                              AS qte_totale,
            sum(montant)                          AS ca_total,
            count(DISTINCT year(date))            AS n_annees
        FROM fait_ligne_vente
        WHERE client_code IS NOT NULL AND client_code <> ''
          AND designation IS NOT NULL AND designation <> ''
        GROUP BY 1, 2
        HAVING sum(qte) > 0
    """)

    # MARGE RÉELLE : les lignes de vente portent le coût de revient ERP
    # (MTCRSIGNE). Nettoyage indispensable : des coûts saisis à plus de 10 fois
    # le prix de vente (panel vendu 28 300 DT, coût déclaré 665 450 DT). On
    # écarte les lignes dont le coût dépasse 5 fois le CA, en VALEUR ABSOLUE,
    # pour garder les retours légitimes ; les lignes écartées sont comptées
    # dans mart_qualite_marge.
    con.execute("""
        CREATE OR REPLACE TABLE mart_marge_client_mois AS
        WITH lignes AS (
            SELECT client_code AS client, date, montant AS ca, cout
            FROM fait_ligne_vente
            WHERE client_code IS NOT NULL AND client_code <> ''
        )
        SELECT client,
               year(date)                               AS year,
               strftime(date, '%Y-%m')                  AS period,
               sum(ca)                                  AS ca_ligne,
               sum(cout)                                AS cout_revient,
               sum(ca) - sum(cout)                      AS marge,
               count(*) FILTER (WHERE ca >= 0)          AS n_lignes,
               count(*) FILTER (WHERE ca <  0)          AS n_lignes_retour
        FROM lignes
        WHERE ca IS NOT NULL AND ca <> 0
          AND cout IS NOT NULL AND abs(cout) <= 5 * abs(ca)
        GROUP BY client, year(date), strftime(date, '%Y-%m')
    """)

    con.execute("""
        CREATE OR REPLACE TABLE mart_qualite_marge AS
        SELECT
          count(*) FILTER (WHERE ca <> 0 AND abs(cout) > 5 * abs(ca)) AS lignes_exclues,
          count(*) FILTER (WHERE ca > 0)                         AS lignes_facturees,
          count(*) FILTER (WHERE ca < 0)                         AS lignes_retour,
          coalesce(sum(ca) FILTER (WHERE ca < 0), 0)             AS ca_retour,
          coalesce(sum(ca) FILTER (WHERE ca <> 0
                                     AND abs(cout) > 5 * abs(ca)), 0) AS ca_exclu,
          count(*) FILTER (WHERE ca = 0 AND cout > 0)            AS lignes_offertes,
          coalesce(sum(cout) FILTER (WHERE ca = 0 AND cout > 0), 0)    AS cout_offert
        FROM (SELECT montant AS ca, cout FROM fait_ligne_vente)
    """)

    # Familles de produits (REACTIF, EQUIPEMENT, SERVICE… ~99 % du CA), hors
    # familles de démonstration résiduelles.
    con.execute(f"""
        CREATE OR REPLACE TABLE mart_ventes_famille AS
        SELECT
            famille,
            year(date)     AS year,
            sum(montant)   AS ca,
            sum(qte)       AS qte
        FROM fait_ligne_vente
        WHERE famille IS NOT NULL AND famille <> ''
          AND NOT regexp_matches(upper(famille), '{FAMILLES_HORS_ACTIVITE}')
        GROUP BY 1, 2
    """)
