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
| mart_marge_categorie_mois     | client × catégorie × mois      | onglet Marge                |
| mart_marge_produit            | produit × client × année       | onglet Marge                |

Tous les montants sont SIGNÉS : une ligne de retour vient en déduction. Le
montant brut des lignes est toujours positif ; l'utiliser comptait les retours
comme des ventes, exactement comme les avoirs gonflaient le chiffre d'affaires.

Les deux marts de marge DÉCOMPOSÉE portent le code client et l'année : sans eux,
un filtre du tableau de bord ne pourrait pas s'appliquer et la décomposition
contredirait le total affiché juste au-dessus.
"""

from __future__ import annotations

from etl.regles import FAMILLES_HORS_ACTIVITE

#: Catégorie d'activité, regroupée sur les préfixes réels de la famille ERP.
#: Même expression que `ml_engine.analytics.marge_client` : les deux doivent
#: classer une ligne à l'identique, sinon la décomposition ne somme plus au
#: total. `autre` recueille la pollution « fournitures d'art », jamais devinée.
CATEGORIE_SQL = """
    CASE
        WHEN upper(trim(famille)) LIKE 'REACTIF%'    THEN 'reactif'
        WHEN upper(trim(famille)) LIKE 'EQUIPEMENT%' THEN 'equipement'
        WHEN upper(trim(famille)) LIKE 'SERVICE%'    THEN 'service'
        WHEN upper(trim(famille)) LIKE 'PRESTATION%' THEN 'service'
        ELSE 'autre'
    END
"""

#: Règle de nettoyage du coût de revient, identique à `mart_marge_client_mois`.
#: Un coût supérieur à 5 fois le prix de vente est une erreur de saisie ERP.
COUT_EXPLOITABLE = "cout IS NOT NULL AND abs(cout) <= 5 * abs(ca)"


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

    # MARGE PAR CATÉGORIE. Overlyne distribue du diagnostic in vitro : les
    # réactifs sont des consommables récurrents, l'équipement est l'automate qui
    # les consomme. Les deux n'ont pas du tout le même taux de marge, et un total
    # unique le cachait. Même règle de coût que le mart client × mois, donc la
    # somme des catégories redonne exactement la marge brute affichée.
    con.execute(f"""
        CREATE OR REPLACE TABLE mart_marge_categorie_mois AS
        WITH lignes AS (
            SELECT client_code                 AS client,
                   date,
                   {CATEGORIE_SQL}             AS categorie,
                   montant                     AS ca,
                   cout
            FROM fait_ligne_vente
            WHERE client_code IS NOT NULL AND client_code <> ''
        )
        SELECT client,
               categorie,
               year(date)                      AS year,
               strftime(date, '%Y-%m')         AS period,
               sum(ca)                         AS ca_ligne,
               sum(cout)                       AS cout_revient,
               sum(ca) - sum(cout)             AS marge,
               count(*) FILTER (WHERE ca >= 0) AS n_lignes
        FROM lignes
        WHERE ca IS NOT NULL AND ca <> 0 AND {COUT_EXPLOITABLE}
        GROUP BY client, categorie, year(date), strftime(date, '%Y-%m')
    """)

    # MARGE PAR PRODUIT. Le grain porte le client ET le mois pour que TOUS les
    # filtres du tableau de bord s'appliquent — période comprise. Sans le mois,
    # la liste des produits aurait porté sur tout l'historique pendant que le
    # total affiché juste au-dessus portait sur douze mois : les deux se
    # seraient contredits, ce qui est précisément le défaut qu'on corrige ici.
    #
    # `designation` est l'attribut dégénéré de la facture : une même référence
    # en porte parfois plusieurs, on garde la plus fréquente pour l'affichage
    # et on agrège sur la RÉFÉRENCE.
    con.execute(f"""
        CREATE OR REPLACE TABLE mart_marge_produit AS
        WITH lignes AS (
            SELECT client_code                 AS client,
                   reference,
                   designation,
                   date,
                   {CATEGORIE_SQL}             AS categorie,
                   montant                     AS ca,
                   cout, qte
            FROM fait_ligne_vente
            WHERE reference IS NOT NULL AND reference <> ''
              AND client_code IS NOT NULL AND client_code <> ''
        )
        SELECT reference,
               mode(designation)               AS designation,
               mode(categorie)                 AS categorie,
               client,
               year(date)                      AS year,
               strftime(date, '%Y-%m')         AS period,
               sum(ca)                         AS ca_ligne,
               sum(cout)                       AS cout_revient,
               sum(ca) - sum(cout)             AS marge,
               sum(qte)                        AS qte,
               count(*) FILTER (WHERE ca >= 0) AS n_lignes
        FROM lignes
        WHERE ca IS NOT NULL AND ca <> 0 AND {COUT_EXPLOITABLE}
        GROUP BY reference, client, year(date), strftime(date, '%Y-%m')
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
