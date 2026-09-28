"""
ml_engine/stock/stock_engine.py
===============================
Indicateurs de GESTION DE STOCK, calculés sur les données **simulées**.

⚠️ Chaque sortie porte `is_simulated: True`. Voir `docs/STOCK_SIMULE.md`.

Indicateurs produits (tous des standards de la gestion de stock) :

| Indicateur | Formule | Décision qu'il éclaire |
|---|---|---|
| Couverture (jours) | `stock ÷ demande_jour` | combien de temps je tiens |
| Taux de rotation | `demande_annuelle ÷ stock` | mon stock tourne-t-il ? |
| Taux de service estimé | part des produits au-dessus du stock de sécurité | risque de rupture client |
| Valeur immobilisée | `Σ stock × coût_unitaire` | trésorerie bloquée |
| Jours avant rupture | `(stock − stock_sécurité) ÷ demande_jour` | urgence de la commande |
| Quantité à commander | `niveau_cible − stock` (si `stock ≤ point_commande`) | combien commander |
| Péremption à risque | lots expirant avant écoulement du stock | perte sèche à venir |

Le dernier indicateur est **spécifique au diagnostic in vitro** : un réactif
périmé est une perte totale. On compare la date de péremption à la date
d'écoulement prévisionnelle (`stock ÷ demande_jour`) : si le lot expire avant
d'être consommé, la quantité excédentaire est perdue.
"""

from __future__ import annotations

from datetime import date, timedelta
import re
from typing import Any, Dict, List, Optional

AVERTISSEMENT = (
    "DONNÉES SIMULÉES — l'ERP d'Overlyne ne contient aucune donnée de stock. "
    "Ces valeurs sont générées par un modèle (s,S) calibré sur la demande réelle "
    "(6 ans, 1 973 produits) pour démontrer la chaîne de gestion ; elles ne "
    "mesurent aucun stock observé. Modèle : docs/STOCK_SIMULE.md."
)


def _connect():
    import duckdb
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return duckdb.connect(str(STORE_PATH), read_only=True)


def stock_available() -> bool:
    """True si le stock simulé a été généré."""
    try:
        con = _connect()
        n = con.execute("SELECT count(*) FROM stock_simule").fetchone()[0]
        con.close()
        return bool(n)
    except Exception:
        return False


def compute_stock_kpis(famille: Optional[str] = None,
                       client: Optional[str] = None,
                       limit_alertes: int = 12) -> Dict[str, Any]:
    """Indicateurs de stock + alertes priorisées.

    Args:
        famille: restreint à une famille de produits (REACTIF, EQUIPEMENT…).
        client: restreint au stock d'un client / hôpital.
        limit_alertes: nombre d'alertes retournées par catégorie.
    """
    if not stock_available():
        # Message destiné à un UTILISATEUR, pas à un développeur : l'ancien
        # libellé affichait une commande Python dans l'interface du directeur.
        # La régénération est de toute façon automatique au prochain cycle de
        # maintenance, personne n'a de commande à taper.
        return {"error": "Les estimations de stock sont en cours de reconstruction.",
                "is_simulated": True, "avertissement": AVERTISSEMENT}

    con = _connect()
    if client and client.strip():
        safe_client = client.strip().replace("'", "''")
        where = (
            f"(client = '{safe_client}' "
            f"OR client = (SELECT DISTINCT client_name FROM sales WHERE client = '{safe_client}' AND client_name IS NOT NULL LIMIT 1) "
            f"OR client = (SELECT DISTINCT client FROM sales WHERE client_name = '{safe_client}' AND client IS NOT NULL LIMIT 1))"
        )
    else:
        where = "(client IS NULL OR client = '')"

    if famille:
        where += f" AND upper(famille) = upper('{famille.replace(chr(39), chr(39) * 2)}')"

    ref = con.execute("SELECT max(date) FROM sales").fetchone()[0] or date.today()

    # ── Indicateurs globaux ──
    g = con.execute(f"""
        SELECT count(*)                                              AS n_produits,
               sum(valeur_stock)                                     AS valeur_totale,
               sum(stock_actuel * demande_jour) / NULLIF(sum(demande_jour), 0)
                                                                     AS couverture_ponderee,
               count(*) FILTER (WHERE stock_actuel <= point_commande
                                  AND niveau_cible - stock_actuel >= 1) AS a_commander,
               count(*) FILTER (WHERE stock_actuel < stock_securite
                                  AND demande_jour > 0)                AS sous_securite,
               -- Une RUPTURE suppose une demande à satisfaire. Sans la condition
               -- `demande_jour > 0`, toute référence dormante — vendue deux fois
               -- il y a quatre ans, jamais depuis — était comptée en rupture au
               -- seul motif que son stock est nul. Le compteur annonçait ainsi
               -- des centaines de ruptures là où il n'y avait aucun client en
               -- attente, et le briefing recommandait d'écouler des produits...
               -- manquants.
               count(*) FILTER (WHERE stock_actuel <= 0
                                  AND demande_jour > 0)                AS ruptures,
               count(*) FILTER (WHERE stock_actuel <= 0
                                  AND demande_jour <= 0)               AS dormants,
               count(*) FILTER (WHERE stock_actuel > niveau_cible)    AS surstock,
               sum(valeur_stock) FILTER (WHERE stock_actuel > niveau_cible) AS valeur_surstock,
               sum(demande_jour * 365 * cout_unitaire)                AS cout_annuel_ecoule
        FROM stock_simule WHERE {where}
    """).fetchone()

    n_prod = int(g[0] or 0)
    if not n_prod:
        con.close()
        return {"error": f"Aucun produit en stock sur ce périmètre{' (' + client + ')' if client else ''}.",
                "is_simulated": True, "avertissement": AVERTISSEMENT, "client": client}

    valeur = float(g[1] or 0)
    cout_annuel = float(g[9] or 0)

    k: Dict[str, Any] = {
        "is_simulated": True,
        "avertissement": AVERTISSEMENT,
        "client": client,
        "date_observation": ref.isoformat() if isinstance(ref, date) else str(ref),
        "n_produits": n_prod,
        "valeur_stock_dt": round(valeur, 0),
        "couverture_moyenne_jours": round(float(g[2] or 0), 1),
        "n_a_commander": int(g[3] or 0),
        "n_sous_securite": int(g[4] or 0),
        "n_ruptures": int(g[5] or 0),
        # Références à stock nul SANS demande : ce ne sont pas des ruptures mais
        # du catalogue mort. Exposé séparément pour que la distinction reste
        # visible plutôt que d'être silencieusement absorbée.
        "n_references_dormantes": int(g[6] or 0),
        "n_surstock": int(g[7] or 0),
        "valeur_surstock_dt": round(float(g[8] or 0), 0),
        # Rotation = coût annuel écoulé ÷ valeur du stock (nb de fois par an)
        "taux_rotation": round(cout_annuel / valeur, 2) if valeur > 0 else 0.0,
        # Taux de service estimé : part des produits au-dessus du stock de sécurité
        "taux_service_estime_pct": round(
            (n_prod - int(g[4] or 0)) / n_prod * 100, 1),
    }
    # Délai moyen d'écoulement du stock (jours)
    k["jours_de_stock"] = round(365 / k["taux_rotation"], 0) if k["taux_rotation"] else None

    # ── Alertes : produits à commander, triés par urgence ──
    k["alertes_reappro"] = [{
        "produit": r[0], "famille": r[1],
        "stock_actuel": round(float(r[2]), 1),
        "point_commande": round(float(r[3]), 1),
        "quantite_a_commander": round(float(r[4]), 0),
        "jours_avant_rupture": round(float(r[5]), 1) if r[5] is not None else None,
        "valeur_commande_dt": round(float(r[6]), 0),
        "lead_time_jours": int(r[7]),
    } for r in con.execute(f"""
        SELECT produit, famille, stock_actuel, point_commande,
               greatest(0, niveau_cible - stock_actuel)                  AS a_commander,
               CASE WHEN demande_jour > 0
                    THEN greatest(0, (stock_actuel - stock_securite) / demande_jour) END AS jours_rupture,
               greatest(0, niveau_cible - stock_actuel) * cout_unitaire  AS valeur_cmd,
               lead_time_jours
        FROM stock_simule
        WHERE {where} AND stock_actuel <= point_commande
          -- On n'alerte pas pour une commande < 1 unité : ce sont des produits
          -- à rotation très lente (équipements vendus à l'unité), pour lesquels
          -- un réapprovisionnement automatique n'a pas de sens.
          AND niveau_cible - stock_actuel >= 1
        ORDER BY jours_rupture NULLS FIRST, valeur_cmd DESC
        LIMIT {int(limit_alertes)}
    """).fetchall()]

    # ── Alertes péremption : lots qui expireront avant d'être consommés ──
    k["alertes_peremption"] = [{
        "produit": r[0], "famille": r[1],
        "date_peremption": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
        "jours_restants": int(r[3]),
        "jours_ecoulement": round(float(r[4]), 0) if r[4] is not None else None,
        "quantite_perdue": round(float(r[5]), 1),
        "perte_estimee_dt": round(float(r[6]), 0),
    } for r in con.execute(f"""
        SELECT produit, famille, date_peremption,
               datediff('day', DATE '{ref}', date_peremption)            AS jours_restants,
               CASE WHEN demande_jour > 0 THEN stock_actuel / demande_jour END AS jours_ecoul,
               greatest(0, stock_actuel - demande_jour *
                        datediff('day', DATE '{ref}', date_peremption))  AS qte_perdue,
               greatest(0, stock_actuel - demande_jour *
                        datediff('day', DATE '{ref}', date_peremption)) * cout_unitaire AS perte
        FROM stock_simule
        WHERE {where} AND date_peremption IS NOT NULL
          AND datediff('day', DATE '{ref}', date_peremption) > 0
          AND stock_actuel > demande_jour * datediff('day', DATE '{ref}', date_peremption)
        ORDER BY perte DESC
        LIMIT {int(limit_alertes)}
    """).fetchall()]

    perte = con.execute(f"""
        SELECT coalesce(sum(greatest(0, stock_actuel - demande_jour *
                 datediff('day', DATE '{ref}', date_peremption)) * cout_unitaire), 0)
        FROM stock_simule
        WHERE {where} AND date_peremption IS NOT NULL
          AND datediff('day', DATE '{ref}', date_peremption) > 0
    """).fetchone()[0]
    k["perte_peremption_estimee_dt"] = round(float(perte or 0), 0)

    # ── Répartition par famille et par situation ──
    k["par_famille"] = [{
        "famille": r[0], "n_produits": int(r[1]),
        "valeur_dt": round(float(r[2] or 0), 0),
        "couverture_jours": round(float(r[3] or 0), 1),
    } for r in con.execute(f"""
        SELECT famille, count(*), sum(valeur_stock),
               avg(CASE WHEN demande_jour > 0 THEN stock_actuel / demande_jour END)
        FROM stock_simule WHERE {where} GROUP BY famille ORDER BY 3 DESC NULLS LAST
    """).fetchall()]

    k["par_situation"] = [{
        "situation": r[0], "n_produits": int(r[1]),
        "valeur_dt": round(float(r[2] or 0), 0),
    } for r in con.execute(f"""
        SELECT situation, count(*), sum(valeur_stock)
        FROM stock_simule WHERE {where} GROUP BY situation ORDER BY 2 DESC
    """).fetchall()]

    # ── Top immobilisations (trésorerie bloquée) ──
    k["top_immobilisations"] = [{
        "produit": r[0], "valeur_dt": round(float(r[1]), 0),
        "couverture_jours": round(float(r[2]), 0) if r[2] is not None else None,
    } for r in con.execute(f"""
        SELECT produit, valeur_stock,
               CASE WHEN demande_jour > 0 THEN stock_actuel / demande_jour END
        FROM stock_simule WHERE {where} AND stock_actuel > niveau_cible
        ORDER BY valeur_stock DESC LIMIT 8
    """).fetchall()]

    # Métadonnées de génération (traçabilité)
    try:
        m = con.execute("SELECT seed, genere_le, modele FROM stock_simule_meta "
                        "ORDER BY genere_le DESC LIMIT 1").fetchone()
        if m:
            k["simulation"] = {"seed": int(m[0]), "genere_le": str(m[1]),
                               "modele": m[2]}
    except Exception:
        pass

    con.close()
    return k


# Code client brut de l'ERP (CP000884, T0421…), par opposition à un libellé.
_RE_CODE_CLIENT = re.compile(r"[A-Z]{1,3}\d{4,}")


def classer_clients_par_risque(limit: int = 5, min_references: int = 3) -> Dict[str, Any]:
    """Classe les clients selon l'état de leur stock — sains d'un côté, exposés de l'autre.

    Chaque ligne du stock simulé porte déjà un client et une `situation`
    (`sain`, `a_commander`, `rupture`, `surstock`). L'information existait donc,
    mais rien ne l'agrégeait au niveau du client : à la question « quels clients
    n'ont pas de risque de stock ? », le copilote répondait « donnée non
    disponible » alors qu'elle était là.

    Un client est dit **sain** lorsque AUCUNE de ses références n'est en rupture,
    en surstock ni à commander. Le classement se fait ensuite par valeur de
    stock décroissante : entre deux clients sans risque, le plus significatif
    est celui qui immobilise le plus de valeur.

    Args:
        limit: nombre de clients retournés dans chaque liste.
        min_references: seuil sous lequel un client est ignoré. Un client avec
            une seule référence saine n'est pas un « client sans risque », c'est
            un client sans données — l'inclure fausserait le classement.
    """
    if not stock_available():
        return {"error": "Les estimations de stock sont en cours de reconstruction.",
                "is_simulated": True, "avertissement": AVERTISSEMENT}

    con = _connect()
    # LEFT JOIN sur dim_client : le stock est rattaché tantôt à un libellé,
    # tantôt à un code (CP000884…). Certains comptes n'ont AUCUN libellé dans
    # l'ERP — le code est alors le seul identifiant existant, et `nom_resolu`
    # le signale plutôt que de laisser croire à un échec de jointure.
    rows = con.execute(f"""
        SELECT s.client,
               max(d.client_name)                                            nom,
               max(d.ville)                                                  ville,
               count(*)                                                      n_references,
               sum(s.valeur_stock)                                           valeur_stock,
               sum(CASE WHEN s.situation = 'rupture'     THEN 1 ELSE 0 END)  n_rupture,
               sum(CASE WHEN s.situation = 'surstock'    THEN 1 ELSE 0 END)  n_surstock,
               sum(CASE WHEN s.situation = 'a_commander' THEN 1 ELSE 0 END)  n_a_commander,
               sum(CASE WHEN s.situation = 'sain'        THEN 1 ELSE 0 END)  n_sain,
               sum(CASE WHEN s.situation = 'surstock' THEN s.valeur_stock ELSE 0 END) valeur_surstock
        FROM stock_simule s
        LEFT JOIN dim_client d
               ON d.client_code = s.client OR d.client_name = s.client
        WHERE s.client IS NOT NULL AND s.client <> ''
        GROUP BY s.client
        HAVING count(*) >= {int(min_references)}
        -- 's.client ASC' départage les ex æquo de valeur : sans lui, deux
        -- exécutions peuvent renvoyer des classements différents.
        ORDER BY valeur_stock DESC, s.client ASC
    """).fetchall()
    con.close()

    clients = []
    for (cle, nom, ville, n_ref, val, n_rup, n_sur, n_cmd, n_sain, val_sur) in rows:
        n_risque = int(n_rup) + int(n_sur) + int(n_cmd)
        libelle = (nom or "").strip() or cle
        # Le stock stocke tantôt un libellé, tantôt un code. Ce qui compte pour
        # l'affichage n'est pas de savoir si la jointure a trouvé une ligne,
        # mais si l'étiquette finale est lisible par un humain : certains
        # comptes n'ont AUCUN libellé dans l'ERP et le code est alors leur seul
        # identifiant — ce n'est pas une donnée manquante.
        resolu = not _RE_CODE_CLIENT.fullmatch(libelle)
        clients.append({
            "client": libelle,
            "code": cle,
            "ville": (ville or "").strip() or None,
            "nom_resolu": resolu,
            "n_references": int(n_ref),
            "valeur_stock_dt": round(float(val or 0), 2),
            "n_rupture": int(n_rup), "n_surstock": int(n_sur),
            "n_a_commander": int(n_cmd), "n_sain": int(n_sain),
            "n_a_risque": n_risque,
            "valeur_surstock_dt": round(float(val_sur or 0), 2),
            "part_saine_pct": round(int(n_sain) / int(n_ref) * 100, 1),
            "sans_risque": n_risque == 0,
        })

    sains = [c for c in clients if c["sans_risque"]]
    exposes = sorted([c for c in clients if not c["sans_risque"]],
                     key=lambda c: (-c["n_a_risque"], -c["valeur_stock_dt"], c["client"]))

    return {
        "n_clients_analyses": len(clients),
        "n_clients_sans_risque": len(sains),
        "n_clients_exposes": len(exposes),
        "min_references": int(min_references),
        # Déjà triés par valeur de stock décroissante par la requête.
        "clients_sans_risque": sains[:limit],
        "clients_les_plus_exposes": exposes[:limit],
        # Lecture inverse : parmi les plus gros détenteurs de stock, lesquels
        # sont sains ? C'est la question réellement posée par « top 5 clients ».
        "top_par_valeur": clients[:limit],
        "is_simulated": True,
        "avertissement": AVERTISSEMENT,
    }


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    k = compute_stock_kpis()
    if k.get("error"):
        print(k["error"])
        sys.exit(1)
    print("\n=== STOCK (SIMULÉ) ===")
    print(f"{k['n_produits']} produits · valorisation {k['valeur_stock_dt']:,.0f} DT"
          .replace(",", " "))
    print(f"Couverture moyenne : {k['couverture_moyenne_jours']} j · "
          f"rotation {k['taux_rotation']}×/an · service estimé {k['taux_service_estime_pct']} %")
    print(f"À commander : {k['n_a_commander']} · sous sécurité : {k['n_sous_securite']} · "
          f"surstock : {k['n_surstock']} ({k['valeur_surstock_dt']:,.0f} DT immobilisés)"
          .replace(",", " "))
    print(f"Perte par péremption estimée : {k['perte_peremption_estimee_dt']:,.0f} DT"
          .replace(",", " "))
    print("\nTop 5 réapprovisionnements urgents :")
    for a in k["alertes_reappro"][:5]:
        print(f"  {a['produit'][:34]:34} stock={a['stock_actuel']:>7} "
              f"rupture dans {a['jours_avant_rupture']:>5} j → commander "
              f"{a['quantite_a_commander']:>7,.0f}".replace(",", " "))
    print(f"\n⚠ {k['avertissement'][:100]}…")
