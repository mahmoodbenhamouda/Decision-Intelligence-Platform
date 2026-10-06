"""Le processus d'approvisionnement, et ce que l'ERP en enregistre vraiment.

Un processus d'achat type compte cinq étapes : repérer des fournisseurs,
demander des échantillons, commander et facturer, planifier la logistique,
gérer le stock. L'ERP d'Overlyne n'en trace que trois, et à des degrés
différents. Ce module publie les trois qu'il couvre AVEC leur donnée, et nomme
les deux autres AVEC la raison de leur absence.

Afficher cinq étapes dont deux seraient inventées serait pire que d'en afficher
trois : un directeur qui découvre en réunion qu'une étape ne repose sur rien
cesse de croire aux quatre autres.

Ce module ne PRÉDIT rien. Il compte des factures d'achat et des mouvements. Les
prévisions de stock relèvent de `ml_engine.stock`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Nombre de lignes au-delà duquel une liste cesse d'être une liste d'action.
N_LIGNES = 12

#: Part d'achats au-delà de laquelle un fournisseur unique devient un risque
#: structurel : son arrêt, sa hausse de prix ou sa rupture se répercutent
#: intégralement. Seuil déclaré ici, pas dans l'interface.
SEUIL_DEPENDANCE_PCT = 30.0

#: De combien un réassort doit dépasser son rythme pour mériter une alerte.
#: Au ras du rythme, tout produit acheté « un peu tard » est signalé : 89 % du
#: chiffre d'affaires d'un client passait en alerte, donc plus rien ne ressortait.
MARGE_RETARD = 1.5


def _connect():
    import duckdb

    from ml_engine.analytics.kpi_engine import STORE_PATH
    return duckdb.connect(str(STORE_PATH), read_only=True)


def _clause_dates(f: Optional[Dict[str, Any]], colonne: str = "date") -> str:
    f = f or {}
    c = ""
    if f.get("selected_years"):
        annees = ",".join(str(int(y)) for y in f["selected_years"])
        c += f" AND year({colonne}) IN ({annees})"
    if f.get("date_start"):
        c += f" AND {colonne} >= DATE '{f['date_start']}'"
    if f.get("date_end"):
        c += f" AND {colonne} <= DATE '{f['date_end']}'"
    return c


# ── Étape 01 : repérage et dépendance fournisseurs ───────────────────────────

def fournisseurs(con, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Qui fournit quoi, pour combien, et à quel point on en dépend."""
    w = "1=1" + _clause_dates(filtres)

    lignes = con.execute(f"""
        WITH achats AS (
            SELECT a.fournisseur_code, a.fournisseur, a.ttc, a.payment_delay_days,
                   a.piece_no, a.date
            FROM purchases a WHERE {w}
        ),
        refs AS (
            SELECT fournisseur_code, count(DISTINCT reference) n_refs
            FROM fait_ligne_achat GROUP BY 1
        )
        SELECT any_value(a.fournisseur)                      AS nom,
               a.fournisseur_code,
               any_value(f.pays)                             AS pays,
               sum(a.ttc)                                    AS montant,
               count(*)                                      AS n_factures,
               any_value(r.n_refs)                           AS n_references,
               sum(a.ttc * a.payment_delay_days)
                   / nullif(sum(a.ttc), 0)                   AS delai_obtenu_j,
               max(a.date)                                   AS dernier_achat
        FROM achats a
        LEFT JOIN dim_fournisseur f ON f.fournisseur_code = a.fournisseur_code
        LEFT JOIN refs r            ON r.fournisseur_code = a.fournisseur_code
        GROUP BY a.fournisseur_code
        ORDER BY montant DESC NULLS LAST
    """).fetchall()

    total = sum(float(r[3] or 0) for r in lignes) or 1.0
    top = [{
        "nom": (r[0] or r[1] or "—")[:40],
        "code": r[1],
        "pays": r[2] or "non renseigné",
        "montant_dt": round(float(r[3] or 0), 0),
        "part_pct": round(float(r[3] or 0) / total * 100, 1),
        "n_factures": int(r[4] or 0),
        "n_references": int(r[5] or 0),
        "delai_obtenu_j": round(float(r[6]), 0) if r[6] is not None else None,
        "dernier_achat": str(r[7]) if r[7] else None,
    } for r in lignes[:N_LIGNES]]

    # Indice de concentration : somme des carrés des parts. 10 000 = monopole.
    hhi = sum((float(r[3] or 0) / total * 100) ** 2
              for r in lignes if (r[3] or 0) > 0)

    pays = con.execute(f"""
        SELECT coalesce(f.pays, 'non renseigné') AS pays,
               count(DISTINCT a.fournisseur_code) AS nf,
               sum(a.ttc)                         AS montant
        FROM purchases a
        LEFT JOIN dim_fournisseur f ON f.fournisseur_code = a.fournisseur_code
        WHERE {w}
        GROUP BY 1 ORDER BY montant DESC NULLS LAST LIMIT 8
    """).fetchall()

    premier = top[0] if top else None
    return {
        "top": top,
        "n_fournisseurs": len(lignes),
        "achats_total_dt": round(total, 0),
        "hhi": round(hhi, 0),
        "par_pays": [{
            "pays": p[0], "n_fournisseurs": int(p[1] or 0),
            "montant_dt": round(float(p[2] or 0), 0),
            "part_pct": round(float(p[2] or 0) / total * 100, 1),
        } for p in pays],
        "dependance": {
            "fournisseur": premier["nom"] if premier else None,
            "part_pct": premier["part_pct"] if premier else None,
            "critique": bool(premier and premier["part_pct"] >= SEUIL_DEPENDANCE_PCT),
            "seuil_pct": SEUIL_DEPENDANCE_PCT,
        },
    }


def mono_source(con, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Références approvisionnées chez un seul fournisseur.

    C'est le risque le plus concret du processus amont : une référence
    mono-source n'a pas de solution de repli. Classées par montant acheté, pour
    que la liste commence par celles qui comptent."""
    w = "1=1" + _clause_dates(filtres)
    lignes = con.execute(f"""
        WITH par_ref AS (
            SELECT l.reference,
                   any_value(l.designation)              AS designation,
                   count(DISTINCT l.fournisseur_code)    AS n_fournisseurs,
                   sum(l.montant)                        AS montant,
                   max(l.date)                           AS dernier_achat,
                   any_value(l.fournisseur_code)         AS fournisseur_code
            FROM fait_ligne_achat l
            WHERE l.reference IS NOT NULL AND l.reference <> ''
              AND 1=1 {_clause_dates(filtres, 'l.date')}
            GROUP BY l.reference
        )
        SELECT p.reference, p.designation, p.n_fournisseurs, p.montant,
               p.dernier_achat, coalesce(f.nom, p.fournisseur_code) AS fournisseur
        FROM par_ref p
        LEFT JOIN dim_fournisseur f ON f.fournisseur_code = p.fournisseur_code
        ORDER BY p.n_fournisseurs ASC, p.montant DESC NULLS LAST
    """).fetchall()
    # `w` sert à la cohérence de signature ; le filtre de dates est appliqué
    # dans la CTE, sur la table de lignes.
    del w

    uniques = [r for r in lignes if int(r[2] or 0) == 1]
    total = len(lignes) or 1
    return {
        "n_references": len(lignes),
        "n_mono_source": len(uniques),
        "part_mono_source_pct": round(len(uniques) / total * 100, 1),
        "montant_mono_source_dt": round(
            sum(float(r[3] or 0) for r in uniques), 0),
        "top": [{
            "reference": r[0],
            "designation": (r[1] or r[0])[:50],
            "fournisseur": (r[5] or "—")[:34],
            "montant_dt": round(float(r[3] or 0), 0),
            "dernier_achat": str(r[4]) if r[4] else None,
        } for r in uniques[:N_LIGNES]],
        "lecture": (
            "Une référence mono-source n'a pas de repli : si ce fournisseur "
            "cesse de la livrer, l'activité qui en dépend s'arrête. Le chiffre "
            "ne dit pas si un second fournisseur EXISTE, seulement qu'aucun "
            "autre n'a été utilisé."),
    }


# ── Étape 04 : rythme de réapprovisionnement ─────────────────────────────────

def reapprovisionnement(con, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """À quel rythme chaque référence est rachetée.

    CE N'EST PAS UN DÉLAI DE LIVRAISON. L'ERP enregistre la facture d'achat,
    jamais la date de réception ni le bon de commande : l'intervalle mesuré est
    celui entre deux achats, c'est-à-dire la fréquence de réapprovisionnement.
    Un vrai délai commande → réception n'est pas calculable ici."""
    stats = con.execute(f"""
        WITH achats AS (
            SELECT DISTINCT reference, date FROM fait_ligne_achat
            WHERE reference IS NOT NULL AND reference <> ''
              AND 1=1 {_clause_dates(filtres)}
        ),
        ecarts AS (
            SELECT reference, date,
                   datediff('day', lag(date) OVER (PARTITION BY reference
                                                   ORDER BY date), date) AS j
            FROM achats
        )
        SELECT median(j), avg(j), count(*), count(DISTINCT reference)
        FROM ecarts WHERE j IS NOT NULL AND j > 0
    """).fetchone() or (None, None, 0, 0)

    fin = con.execute("SELECT max(date) FROM fait_ligne_achat").fetchone()[0]

    # Liste D'ACTION, et non de curiosité. Quatre conditions, chacune pour
    # écarter un faux positif rencontré sur ces données :
    #
    #   * référence ENCORE VENDUE dans les 12 derniers mois — sans quoi la
    #     liste remonte des fournitures d'art arrêtées depuis huit ans, dont le
    #     « retard de réassort » atteint 96 fois le rythme et ne veut rien dire ;
    #   * référence effectivement REVENDUE — un contrat de maintenance se
    #     refacture, il ne se réapprovisionne pas ;
    #   * au moins trois réassorts, sans quoi un « rythme » n'existe pas ;
    #   * rythme d'au moins 7 jours, pour écarter les refacturations en rafale.
    en_retard = con.execute(f"""
        WITH revendus AS (
            SELECT reference, max(date) AS derniere_vente
            FROM fait_ligne_vente
            WHERE reference IS NOT NULL AND reference <> ''
            GROUP BY reference
            HAVING max(date) >= (SELECT max(date) FROM fait_ligne_vente)
                                - INTERVAL 12 MONTH
        ),
        achats AS (
            SELECT DISTINCT a.reference, a.designation, a.date
            FROM fait_ligne_achat a
            JOIN revendus v ON v.reference = a.reference
            WHERE a.reference IS NOT NULL AND a.reference <> ''
              AND upper(a.designation) NOT LIKE '%CONTRAT%'
              AND upper(a.designation) NOT LIKE '%MAINTENANCE%'
              AND 1=1 {_clause_dates(filtres, 'a.date')}
        ),
        ecarts AS (
            SELECT reference,
                   any_value(designation) OVER (PARTITION BY reference) AS d,
                   datediff('day', lag(date) OVER (PARTITION BY reference
                                                   ORDER BY date), date) AS j,
                   max(date) OVER (PARTITION BY reference) AS dernier
            FROM achats
        ),
        rythme AS (
            SELECT reference, any_value(d) AS designation,
                   median(j) AS med, count(*) AS n, any_value(dernier) AS dernier
            FROM ecarts WHERE j IS NOT NULL AND j > 0
            GROUP BY reference HAVING count(*) >= 3 AND median(j) >= 7
        ),
        -- Quantité et coût du DERNIER réassort réel : c'est la proposition la
        -- plus défendable, celle que l'entreprise a elle-même retenue la fois
        -- précédente. Aucune optimisation inventée.
        dernier_lot AS (
            SELECT reference, qte, montant, date,
                   row_number() OVER (PARTITION BY reference ORDER BY date DESC) AS rg
            FROM fait_ligne_achat
            WHERE reference IS NOT NULL AND reference <> '' AND qte > 0
        ),
        fournisseur_habituel AS (
            SELECT reference, fournisseur_code, n,
                   row_number() OVER (PARTITION BY reference ORDER BY n DESC) AS rg
            FROM (SELECT reference, fournisseur_code, count(*) AS n
                  FROM fait_ligne_achat
                  WHERE reference IS NOT NULL AND reference <> ''
                  GROUP BY 1, 2)
        )
        SELECT r.reference, r.designation, round(r.med, 0), r.n, r.dernier,
               datediff('day', r.dernier, DATE '{fin}') AS depuis,
               datediff('day', r.dernier, DATE '{fin}') / nullif(r.med, 0) AS ratio,
               v.derniere_vente,
               l.qte                AS qte_dernier_lot,
               l.montant            AS montant_dernier_lot,
               fh.fournisseur_code,
               fo.nom               AS fournisseur_nom
        FROM rythme r
        JOIN revendus v              ON v.reference = r.reference
        LEFT JOIN dernier_lot l      ON l.reference = r.reference AND l.rg = 1
        LEFT JOIN fournisseur_habituel fh ON fh.reference = r.reference AND fh.rg = 1
        LEFT JOIN dim_fournisseur fo ON fo.fournisseur_code = fh.fournisseur_code
        WHERE datediff('day', r.dernier, DATE '{fin}') > r.med
        ORDER BY ratio DESC NULLS LAST LIMIT {N_LIGNES}
    """).fetchall() if fin else []

    return {
        "intervalle_median_j": round(float(stats[0]), 0) if stats[0] else None,
        "intervalle_moyen_j": round(float(stats[1]), 0) if stats[1] else None,
        "n_intervalles": int(stats[2] or 0),
        "n_references": int(stats[3] or 0),
        "derniere_donnee": str(fin) if fin else None,
        "a_recommander": [{
            "reference": r[0],
            "designation": (r[1] or r[0])[:50],
            "intervalle_median_j": int(r[2] or 0),
            "n_reappros": int(r[3] or 0),
            "dernier_achat": str(r[4]) if r[4] else None,
            "jours_depuis": int(r[5] or 0),
            "retard_x": round(float(r[6]), 1) if r[6] else None,
            "derniere_vente": str(r[7]) if r[7] else None,
            # Proposition : le dernier lot réellement acheté. Pas une quantité
            # optimale calculée, celle que l'entreprise a elle-même retenue.
            "qte_proposee": round(float(r[8]), 0) if r[8] else None,
            "montant_estime_dt": round(float(r[9]), 0) if r[9] else None,
            "fournisseur_code": r[10],
            "fournisseur_nom": (r[11] or r[10] or "—") if (r[10] or r[11]) else None,
        } for r in en_retard],
        "base_de_la_proposition": (
            "Quantité et montant du dernier lot effectivement acheté pour cette "
            "référence, chez son fournisseur habituel. Ce n'est pas une "
            "quantité optimale calculée : c'est celle que l'entreprise a "
            "elle-même retenue la fois précédente, à ajuster avant de commander."),
        "regle": (
            "Sont listées les références encore vendues ces douze derniers "
            "mois dont le dernier achat remonte à plus longtemps que leur "
            "propre rythme de réassort, mesuré sur au moins trois "
            "réapprovisionnements. Les contrats de maintenance et les produits "
            "qui ne se vendent plus sont écartés : leur « retard » ne mesure "
            "qu'un abandon."),
        "ce_n_est_pas": (
            "un délai de livraison. Ni bon de commande ni date de réception ne "
            "sont consignés : seul l'écart entre deux FACTURES d'achat est "
            "mesurable. Un retard de réassort peut aussi vouloir dire que le "
            "produit ne se vend plus."),
    }


# ── Les cinq étapes, et ce que la donnée en dit ──────────────────────────────

def etapes(f: Dict[str, Any], m: Dict[str, Any],
           r: Dict[str, Any], stock: Dict[str, Any]) -> List[Dict[str, Any]]:
    """L'état de couverture de chaque étape, chiffres à l'appui.

    Les codes et les chiffres sont produits ici ; la rédaction destinée au
    directeur appartient à la couche API."""
    dep = f.get("dependance") or {}
    return [
        {"rang": 1, "code": "sourcing", "couverte": True,
         "chiffres": {
             "n_fournisseurs": f.get("n_fournisseurs"),
             "achats_total_dt": f.get("achats_total_dt"),
             "premier_fournisseur": dep.get("fournisseur"),
             "premier_fournisseur_part_pct": dep.get("part_pct"),
             "hhi": f.get("hhi"),
             "n_mono_source": m.get("n_mono_source"),
             "part_mono_source_pct": m.get("part_mono_source_pct"),
         }},
        {"rang": 2, "code": "echantillons", "couverte": False,
         "chiffres": {}},
        {"rang": 3, "code": "commande_facturation", "couverte": "partielle",
         "chiffres": {
             "n_factures": sum(x["n_factures"] for x in f.get("top") or []),
             "delai_obtenu_j": (f.get("top") or [{}])[0].get("delai_obtenu_j"),
         }},
        {"rang": 4, "code": "logistique", "couverte": "partielle",
         "chiffres": {
             "intervalle_median_j": r.get("intervalle_median_j"),
             "n_references_suivies": r.get("n_references"),
         }},
        {"rang": 5, "code": "stock", "couverte": True,
         "chiffres": stock},
    ]


def position_de_stock(con) -> Dict[str, Any]:
    """Position de stock réelle, et pourquoi tant de valeurs sont négatives.

    L'ERP n'exporte aucun inventaire d'ouverture : la position est reconstruite
    à partir des entrées (achats) et des sorties (ventes) depuis 2019. Un
    produit déjà en stock avant cette date affiche donc plus de sorties que
    d'entrées. Une position négative signifie « on a vendu plus qu'on n'a
    acheté depuis 2019 », pas « le stock est négatif »."""
    r = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE rapproche),
               count(*) FILTER (WHERE position < 0),
               count(*) FILTER (WHERE conso_mensuelle > 0),
               min(dernier_achat), max(dernier_achat)
        FROM stock_flux_reel WHERE NOT est_service
    """).fetchone() or (0, 0, 0, 0, None, None)
    return {
        "n_produits": int(r[0] or 0),
        "n_rapproches": int(r[1] or 0),
        "n_position_negative": int(r[2] or 0),
        "n_avec_consommation": int(r[3] or 0),
        "part_rapprochee_pct": (round(int(r[1] or 0) / int(r[0]) * 100, 1)
                                if r[0] else None),
        "premier_achat": str(r[4]) if r[4] else None,
        "dernier_achat": str(r[5]) if r[5] else None,
        "pourquoi_negatif": (
            "Aucun inventaire d'ouverture n'a été consigné. La position est "
            "reconstruite depuis 2019 à partir des achats et des ventes : un "
            "produit déjà en magasin avant cette date affiche plus de sorties "
            "que d'entrées. Une position négative mesure cet écart de "
            "reconstruction, pas un stock réellement négatif."),
    }


def consommation_client(con, clients: List[str],
                        limite: int = N_LIGNES) -> Dict[str, Any]:
    """Ce que ces clients consomment, et lequel de leurs produits est menacé.

    Le stock est une analyse par PRODUIT : filtrer sur un client n'avait donc
    aucun sens et l'écran se masquait. C'est une réponse paresseuse — ce qu'un
    directeur veut savoir d'un client dans ce volet existe parfaitement : ce
    qu'il achète, et si l'approvisionnement de ces produits-là tient.

    Un produit est signalé quand son dernier réassort remonte à plus d'une fois
    et demie son rythme habituel : le client continue de l'acheter, la chaîne
    amont s'est arrêtée. C'est une rupture qui vient, pour un chiffre
    d'affaires identifié.

    DEUX PIÈGES, tous deux rencontrés sur ces données :

      * l'ancienneté d'un achat se compte depuis le DERNIER ACHAT CONNU, pas
        depuis la dernière vente. Les achats s'arrêtent trente jours avant les
        ventes : compter depuis la vente ajoutait ces trente jours à chaque
        produit et signalait 89 % du chiffre d'affaires du client ;
      * un simple dépassement du rythme ne suffit pas. Il faut une marge — une
        fois et demie — sinon tout produit acheté « un peu tard » devient une
        alerte, et une alerte permanente n'est plus une alerte.
    """
    if not clients:
        return {}
    vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in clients)

    lignes = con.execute(f"""
        WITH fin AS (SELECT max(date) AS d FROM sales_lines),
        fin_achat AS (SELECT max(date) AS d FROM fait_ligne_achat),
        conso AS (
            SELECT reference,
                   any_value(designation)                    AS designation,
                   sum(qte)                                  AS qte,
                   sum(montant)                              AS ca,
                   count(DISTINCT strftime(date, '%Y-%m'))   AS mois_actifs,
                   max(date)                                 AS derniere_vente
            FROM sales_lines
            WHERE client IN ({vals}) AND montant > 0
              AND date >= (SELECT d FROM fin) - INTERVAL 12 MONTH
              AND reference IS NOT NULL AND reference <> ''
            GROUP BY reference
        ),
        achats AS (
            SELECT reference, max(date) AS dernier_achat, count(*) AS n_achats
            FROM (SELECT DISTINCT reference, date FROM fait_ligne_achat
                  WHERE reference IS NOT NULL AND reference <> '')
            GROUP BY reference
        ),
        rythme AS (
            SELECT reference, median(j) AS med FROM (
                SELECT reference,
                       datediff('day', lag(date) OVER (PARTITION BY reference
                                                       ORDER BY date), date) AS j
                FROM (SELECT DISTINCT reference, date FROM fait_ligne_achat
                      WHERE reference IS NOT NULL AND reference <> '')
            ) WHERE j IS NOT NULL AND j > 0
            GROUP BY reference HAVING count(*) >= 3
        )
        SELECT c.reference, c.designation, c.qte, c.ca, c.mois_actifs,
               c.derniere_vente, a.dernier_achat, round(r.med, 0) AS rythme,
               datediff('day', a.dernier_achat, (SELECT d FROM fin_achat)) AS depuis
        FROM conso c
        LEFT JOIN achats a ON a.reference = c.reference
        LEFT JOIN rythme r ON r.reference = c.reference
        ORDER BY c.ca DESC
    """).fetchall()

    produits: List[Dict[str, Any]] = []
    for r in lignes:
        rythme = float(r[7]) if r[7] else None
        depuis = int(r[8]) if r[8] is not None else None
        menace = bool(rythme and depuis is not None
                      and depuis > rythme * MARGE_RETARD)
        produits.append({
            "reference": r[0],
            "designation": (r[1] or r[0])[:50],
            "quantite": round(float(r[2] or 0), 0),
            "ca_dt": round(float(r[3] or 0), 0),
            "mois_actifs": int(r[4] or 0),
            "derniere_vente": str(r[5]) if r[5] else None,
            "dernier_achat": str(r[6]) if r[6] else None,
            "rythme_reassort_j": int(rythme) if rythme else None,
            "jours_depuis_achat": depuis,
            "approvisionnement_menace": menace,
        })

    menaces = [p for p in produits if p["approvisionnement_menace"]]
    ca_total = sum(p["ca_dt"] for p in produits)
    ca_menace = sum(p["ca_dt"] for p in menaces)

    return {
        "n_clients": len(clients),
        "n_produits": len(produits),
        "ca_total_dt": round(ca_total, 0),
        "n_produits_menaces": len(menaces),
        "ca_menace_dt": round(ca_menace, 0),
        "part_menacee_pct": (round(ca_menace / ca_total * 100, 1)
                             if ca_total else None),
        "produits": produits[:limite],
        "menaces": menaces[:limite],
        "lecture": (
            "Un produit est signalé quand le client continue de l'acheter "
            "alors que son réassort s'est arrêté depuis plus longtemps que "
            "d'habitude. C'est une rupture qui vient, sur un chiffre "
            "d'affaires identifié."),
        "periode": "douze derniers mois",
    }


def analyser(filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Le processus d'approvisionnement, étape par étape, sur ta donnée."""
    con = _connect()
    try:
        f = fournisseurs(con, filtres)
        if not f["top"]:
            return {"servi": False,
                    "motif": "aucune facture d'achat sur ce périmètre"}
        m = mono_source(con, filtres)
        r = reapprovisionnement(con, filtres)
        s = position_de_stock(con)
        # L'analyse amont ne dépend pas du client ; en revanche, ce que les
        # clients filtrés consomment en dépend entièrement. Les deux coexistent.
        clients = list((filtres or {}).get("selected_clients") or [])
        return {
            "servi": True,
            "nature": "comptage",
            "fournisseurs": f,
            "mono_source": m,
            "reapprovisionnement": r,
            "stock": s,
            "consommation_client": consommation_client(con, clients),
            "etapes": etapes(f, m, r, s),
        }
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}
    finally:
        con.close()
