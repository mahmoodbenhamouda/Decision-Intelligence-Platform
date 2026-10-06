"""Position de stock reconstruite à partir des flux RÉELS — plus aucune simulation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[2]

REPORTS_DIR = BASE / "reports"

LIGNES_ACHAT = "fait_ligne_achat"

_MOTIFS_SERVICE = re.compile(
    r"\b(CONTRAT|MAINTENANCE|P\.?M\.?\s|FORMATION|INSTALLATION|DEPLACEMENT|"
    r"MAIN\s*D.?\s*OEUVRE|PRESTATION|FRAIS|TRANSPORT|LOCATION|ABONNEMENT)\b",
    re.IGNORECASE)


def _connect():
    from ml_engine.analytics.kpi_engine import STORE_PATH
    import duckdb
    return duckdb.connect(str(STORE_PATH))


def _lignes_achat_chargees(con) -> bool:
    try:
        return con.execute(f"SELECT count(*) FROM {LIGNES_ACHAT}").fetchone()[0] > 0
    except Exception:
        return False


def identifier_valeur_mouvement(con) -> Dict[str, Any]:
    """Quelle valeur d'`INDICMVTSTOCK` correspond à un vrai mouvement de stock ?"""
    rows = con.execute(f"""
        SELECT indic_mvt_stock AS ind,
               designation     AS produit,
               count(*)        AS n
        FROM {LIGNES_ACHAT}
        WHERE designation <> ''
        GROUP BY 1, 2
    """).fetchall()

    stats: Dict[str, Dict[str, int]] = {}
    for ind, produit, n in rows:
        ind = "(vide)" if ind is None or str(ind).strip() == "" else str(ind).strip()
        d = stats.setdefault(ind, {"lignes": 0, "services": 0, "refs": 0})
        d["lignes"] += int(n)
        d["refs"] += 1
        if _MOTIFS_SERVICE.search(produit or ""):
            d["services"] += int(n)

    for ind, d in stats.items():
        d["part_services_pct"] = round(d["services"] / max(d["lignes"], 1) * 100, 2)

    candidates = {k: v for k, v in stats.items()
                  if v["lignes"] >= 50 and k != "(vide)"}
    valeur = (min(candidates, key=lambda k: candidates[k]["part_services_pct"])
              if candidates else None)

    return {
        "valeur_retenue": valeur,
        "detail_par_valeur": stats,
        "methode": (
            "La valeur correspondant aux mouvements de stock est identifiée "
            "empiriquement : c'est celle qui contient la plus faible part de "
            "libellés de prestation (contrat, maintenance, formation…). Un "
            "contrat ne génère pas de mouvement de stock, un réactif si."),
    }


def construire(con=None) -> Dict[str, Any]:
    """Calcule la position de stock par produit et la matérialise dans l'entrepôt."""
    fermer = con is None
    con = con or _connect()

    if not _lignes_achat_chargees(con):
        if fermer:
            con.close()
        return {"error": f"table {LIGNES_ACHAT} absente ou vide — lancer python -m etl.construire"}

    diag = identifier_valeur_mouvement(con)
    val_mvt = diag["valeur_retenue"]
    if val_mvt is None:
        if fermer:
            con.close()
        return {"error": "impossible d'identifier la valeur de mouvement de stock"}

    con.execute(f"""
        CREATE OR REPLACE TABLE achats_lignes AS
        SELECT
            upper(designation)                              AS cle,
            any_value(designation)                          AS produit,
            sum(qte)                                        AS qte_entree,
            sum(montant)                                    AS montant_entree,
            count(*)                                        AS n_lignes,
            max(date)                                       AS dernier_achat
        FROM {LIGNES_ACHAT}
        WHERE designation <> ''
          AND indic_mvt_stock = '{val_mvt}'
          AND qte IS NOT NULL
        GROUP BY 1
    """)

    con.execute("""
        CREATE OR REPLACE TABLE stock_flux_reel AS
        WITH ventes AS (
            SELECT upper(trim(designation)) AS cle,
                   any_value(trim(designation)) AS produit,
                   sum(qte)                  AS qte_sortie,
                   sum(montant)              AS montant_sortie,
                   count(*)                  AS n_lignes_vente,
                   max(date)                 AS derniere_vente,
                   count(DISTINCT strftime(date, '%Y-%m')) AS mois_actifs
            FROM sales_lines
            WHERE designation IS NOT NULL AND trim(designation) <> '' AND qte > 0
            GROUP BY 1
        )
        SELECT
            COALESCE(a.cle, v.cle)                       AS cle,
            COALESCE(a.produit, v.produit)               AS produit,
            COALESCE(a.qte_entree, 0)                    AS qte_entree,
            COALESCE(v.qte_sortie, 0)                    AS qte_sortie,
            COALESCE(a.qte_entree, 0) - COALESCE(v.qte_sortie, 0) AS position,
            COALESCE(a.montant_entree, 0)                AS montant_entree,
            COALESCE(v.montant_sortie, 0)                AS montant_sortie,
            -- Coût unitaire d'entrée : sert à valoriser la position. Calculé sur
            -- les achats réels, jamais estimé.
            CASE WHEN COALESCE(a.qte_entree, 0) > 0
                 THEN a.montant_entree / a.qte_entree END AS cout_unitaire,
            a.dernier_achat,
            v.derniere_vente,
            COALESCE(v.mois_actifs, 0)                   AS mois_actifs,
            -- Consommation mensuelle moyenne sur les mois OÙ LE PRODUIT A BOUGÉ.
            -- Diviser par la durée totale de l'historique écraserait la demande
            -- des références saisonnières ou récentes.
            CASE WHEN COALESCE(v.mois_actifs, 0) > 0
                 THEN v.qte_sortie / v.mois_actifs END    AS conso_mensuelle,
            (a.cle IS NOT NULL AND v.cle IS NOT NULL)     AS rapproche,
            regexp_matches(upper(COALESCE(a.produit, v.produit)),
                           '(CONTRAT|MAINTENANCE|FORMATION|INSTALLATION|PRESTATION|FRAIS|TRANSPORT|LOCATION|ABONNEMENT)')
                                                         AS est_service
        FROM achats_lignes a
        FULL OUTER JOIN ventes v ON v.cle = a.cle
    """)

    try:
        from ml_engine.stock.nomenclature import (PRESTATION, charger_familles_erp,
                                                  classer)
        charger_familles_erp(con)
        lignes_ref = con.execute(
            "SELECT cle, produit FROM stock_flux_reel").fetchall()
        services = [(c,) for c, p in lignes_ref if classer(p) == PRESTATION]
        if services:
            con.execute("CREATE OR REPLACE TEMP TABLE _services(cle VARCHAR)")
            con.executemany("INSERT INTO _services VALUES (?)", services)
            con.execute("""
                UPDATE stock_flux_reel
                SET est_service = TRUE
                WHERE cle IN (SELECT cle FROM _services)
            """)
    except Exception as e:      # pragma: no cover
        print(f"[flux_reels] AVERTISSEMENT — classement des prestations par la "
              f"famille de produit indisponible ({type(e).__name__}). Le repli par "
              f"expression régulière reste actif, moins fiable.")

    g = con.execute("""
        SELECT
            count(*)                                                    AS n_refs,
            count(*) FILTER (WHERE rapproche)                           AS n_rapproches,
            count(*) FILTER (WHERE est_service)                          AS n_services,
            count(*) FILTER (WHERE position > 0 AND NOT est_service)     AS n_position_positive,
            count(*) FILTER (WHERE position < 0 AND NOT est_service)     AS n_position_negative,
            sum(position * cout_unitaire)
                FILTER (WHERE position > 0 AND NOT est_service
                        AND cout_unitaire IS NOT NULL)                   AS valeur_accumulee,
            sum(qte_sortie) FILTER (WHERE rapproche)                     AS vol_rapproche,
            sum(qte_sortie)                                              AS vol_total
        FROM stock_flux_reel
    """).fetchone()

    (n_refs, n_rappr, n_serv, n_pos, n_neg, valeur, vol_r, vol_t) = g

    top = con.execute("""
        SELECT produit, position, cout_unitaire,
               position * cout_unitaire AS valeur_dt,
               conso_mensuelle,
               CASE WHEN conso_mensuelle > 0
                    THEN position / conso_mensuelle END AS mois_de_couverture
        FROM stock_flux_reel
        WHERE position > 0 AND NOT est_service AND cout_unitaire IS NOT NULL
          AND conso_mensuelle > 0
        ORDER BY position * cout_unitaire DESC NULLS LAST
        LIMIT 20
    """).fetchall()

    metriques = {
        "version": 1,
        "nature": "flux réels reconstruits — AUCUNE simulation",
        "portee": (
            "Position = quantités entrées − quantités sorties depuis le début de "
            "l'historique. C'est une VARIATION CUMULÉE, non un inventaire : le "
            "stock détenu avant la première facture connue reste inconnu. Une "
            "position négative signifie donc qu'un stock préexistait, pas qu'il "
            "est négatif."),
        "identification_mouvement_stock": diag,
        "n_references": int(n_refs or 0),
        "n_rapprochees_achat_vente": int(n_rappr or 0),
        "n_services_exclus": int(n_serv or 0),
        "n_position_positive": int(n_pos or 0),
        "n_position_negative": int(n_neg or 0),
        "couverture_volume_pct": round(float(vol_r or 0) / float(vol_t or 1) * 100, 1),
        "valeur_accumulee_dt": round(float(valeur or 0), 0),
        "interpretation_valeur": (
            "Valorisation des positions POSITIVES au coût d'achat réel. C'est un "
            "minorant du capital immobilisé : les références à position négative "
            "en détiennent aussi, mais leur niveau n'est pas calculable."),
        "top_immobilisations": [{
            "produit": p, "position": round(float(pos or 0), 0),
            "cout_unitaire_dt": round(float(cu or 0), 2),
            "valeur_dt": round(float(v or 0), 0),
            "conso_mensuelle": round(float(cm or 0), 1),
            "mois_de_couverture": round(float(mc or 0), 1),
        } for p, pos, cu, v, cm, mc in top],
        "obsolescence": {
            "principe": (
                "AUCUNE date d'expiration n'est enregistrée, et ce module refuse "
                "d'en simuler une. Un raisonnement donne pourtant une certitude "
                "équivalente : un consommable dont le stock dépasse deux ans de "
                "consommation périmera avant d'être vendu. On perd la date "
                "exacte, on gagne un signal mesuré."),
            "seuils_mois": {"certain": SEUIL_OBSOLESCENCE_CERTAINE,
                            "probable": SEUIL_OBSOLESCENCE_PROBABLE},
            "origine_des_seuils": (
                "ordres de grandeur du diagnostic in vitro — DÉCLARÉS, non "
                "mesurés sur les données. Modifiables si l'entreprise fournit "
                "les durées de conservation réelles."),
            "equipements_exclus": (
                "Un automate ne périme pas, il s'amortit. Les inclure ferait "
                "passer un investissement à rotation lente pour une perte."),
            "perte_calculee_sur": (
                "l'EXCÉDENT au-delà du seuil, non la position totale : un "
                "produit à 30 mois de couverture perdra 6 mois de stock, pas 30."),
        },
    }

    try:
        metriques["sensibilite_seuils"] = sensibilite_seuils(con)
    except Exception as e:      # pragma: no cover — annexe, jamais bloquante
        metriques["sensibilite_seuils"] = {"erreur": type(e).__name__}

    try:
        from ml_engine.stock.nomenclature import exporter_pour_validation, mesurer
        metriques["nomenclature"] = mesurer(con)
        exporter_pour_validation(con)
    except Exception as e:      # pragma: no cover
        metriques["nomenclature"] = {"erreur": type(e).__name__}

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(metriques, open(REPORTS_DIR / "stock_flux_metrics.json", "w",
                              encoding="utf-8"), indent=2, ensure_ascii=False)
    if fermer:
        con.close()
    return metriques


def detecter_ruptures(con=None, seuil_mois: float = 2.0) -> List[Dict[str, Any]]:
    """Ruptures probables, détectées SANS connaître le niveau de stock."""
    fermer = con is None
    con = con or _connect()
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_flux_reel" not in tables:
            return []

        rows = con.execute(f"""
            SELECT
                produit,
                position,
                conso_mensuelle,
                dernier_achat,
                derniere_vente,
                cout_unitaire,
                -- Mois écoulés depuis le dernier approvisionnement.
                datediff('month', dernier_achat,
                         (SELECT max(derniere_vente) FROM stock_flux_reel)) AS mois_sans_achat,
                -- Couverture restante : ce que la position permet encore de
                -- servir, au rythme de consommation constaté.
                CASE WHEN conso_mensuelle > 0
                     THEN position / conso_mensuelle END AS couverture_mois
            FROM stock_flux_reel
            WHERE NOT est_service
              AND conso_mensuelle > 0
              AND dernier_achat IS NOT NULL
              AND derniere_vente IS NOT NULL
              -- Le produit doit être ENCORE vendu : un produit abandonné qu'on
              -- n'achète plus n'est pas une rupture, c'est une fin de vie.
              AND datediff('month', derniere_vente,
                           (SELECT max(derniere_vente) FROM stock_flux_reel)) <= 3
        """).fetchall()
    finally:
        if fermer:
            con.close()

    alertes: List[Dict[str, Any]] = []
    for (produit, pos, conso, d_achat, d_vente, cout,
         mois_sans_achat, couverture) in rows:
        couverture = float(couverture) if couverture is not None else -1.0
        mois_sans_achat = int(mois_sans_achat or 0)

        if couverture >= seuil_mois:
            continue

        if couverture < 0:
            gravite, lecture = "rupture_probable", (
                "plus de sorties que d'entrées sur l'historique : le stock "
                "initial est probablement épuisé")
        elif couverture < 1:
            gravite, lecture = "critique", (
                f"moins d'un mois de couverture au rythme actuel "
                f"({conso:.0f} unités/mois)")
        else:
            gravite, lecture = "a_commander", (
                f"{couverture:.1f} mois de couverture restants")

        alertes.append({
            "produit": produit,
            "position": round(float(pos or 0), 0),
            "conso_mensuelle": round(float(conso or 0), 1),
            "couverture_mois": round(couverture, 1) if couverture >= 0 else None,
            "mois_sans_approvisionnement": mois_sans_achat,
            "dernier_achat": str(d_achat) if d_achat else None,
            "derniere_vente": str(d_vente) if d_vente else None,
            "cout_unitaire_dt": round(float(cout or 0), 2),
            "quantite_suggeree": round(max(float(conso or 0) * 3
                                           - max(float(pos or 0), 0), 0), 0),
            "gravite": gravite,
            "lecture": lecture,
        })

    ordre = {"rupture_probable": 0, "critique": 1, "a_commander": 2}
    alertes.sort(key=lambda a: (ordre.get(a["gravite"], 3),
                                -a["conso_mensuelle"]))
    return alertes


SEUIL_OBSOLESCENCE_CERTAINE = 24
SEUIL_OBSOLESCENCE_PROBABLE = 12

def _est_perissable(produit: str) -> bool:
    """Un réactif périme ; un automate s'amortit ; une pièce se conserve."""
    from ml_engine.stock.nomenclature import est_perissable
    return est_perissable(produit)


def detecter_obsolescence(con=None) -> List[Dict[str, Any]]:
    """Produits qui périmeront avant d'être écoulés — SANS date d'expiration."""
    fermer = con is None
    con = con or _connect()
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_flux_reel" not in tables:
            return []

        try:
            from ml_engine.stock.nomenclature import charger_familles_erp
            charger_familles_erp(con)
        except Exception:
            pass

        rows = con.execute(f"""
            SELECT produit, position, conso_mensuelle, cout_unitaire,
                   position / conso_mensuelle AS mois_couverture,
                   position * cout_unitaire   AS valeur_dt,
                   derniere_vente
            FROM stock_flux_reel
            WHERE NOT est_service
              AND position > 0
              AND conso_mensuelle > 0
              AND cout_unitaire IS NOT NULL
              AND position / conso_mensuelle >= {SEUIL_OBSOLESCENCE_PROBABLE}
        """).fetchall()
    finally:
        if fermer:
            con.close()

    alertes: List[Dict[str, Any]] = []
    exclus: List[str] = []
    for produit, pos, conso, cout, mois, valeur, d_vente in rows:
        if not _est_perissable(produit):
            exclus.append(produit)
            continue

        mois = float(mois or 0)
        valeur = float(valeur or 0)

        if mois >= SEUIL_OBSOLESCENCE_CERTAINE:
            gravite = "perte_quasi_certaine"
            excedent = max(float(pos) - float(conso) * SEUIL_OBSOLESCENCE_CERTAINE, 0)
            lecture = (f"{mois:.0f} mois de stock — aucun réactif ne se conserve "
                       "aussi longtemps")
        else:
            gravite = "rotation_lente"
            excedent = max(float(pos) - float(conso) * SEUIL_OBSOLESCENCE_PROBABLE, 0)
            lecture = f"{mois:.0f} mois de stock — écoulement incertain"

        perte = excedent * float(cout or 0)
        if perte < 100:
            continue

        alertes.append({
            "produit": produit,
            "position": round(float(pos or 0), 0),
            "conso_mensuelle": round(float(conso or 0), 1),
            "mois_couverture": round(mois, 1),
            "valeur_stock_dt": round(valeur, 0),
            "quantite_excedentaire": round(excedent, 0),
            "perte_probable_dt": round(perte, 0),
            "derniere_vente": str(d_vente) if d_vente else None,
            "gravite": gravite,
            "lecture": lecture,
        })

    alertes.sort(key=lambda a: -a["perte_probable_dt"])
    if alertes:
        alertes[0]["_references_ecartees"] = sorted(set(exclus))[:20]
        alertes[0]["_motif_exclusion"] = (
            "équipements et pièces détachées : ils ne périment pas comme un "
            "réactif")
    return alertes


def sensibilite_seuils(con=None,
                       seuils: tuple = (18, 24, 30, 36)) -> Dict[str, Any]:
    """Que devient la perte annoncée si le seuil de deux ans est faux ?"""
    global SEUIL_OBSOLESCENCE_CERTAINE
    d_origine = SEUIL_OBSOLESCENCE_CERTAINE
    fermer = con is None
    con = con or _connect()

    resultats: Dict[str, Any] = {}
    classements: Dict[int, List[str]] = {}
    try:
        for s in seuils:
            SEUIL_OBSOLESCENCE_CERTAINE = s
            obs = detecter_obsolescence(con)
            certains = [o for o in obs if o["gravite"] == "perte_quasi_certaine"]
            resultats[f"{s}_mois"] = {
                "n_references": len(certains),
                "perte_quasi_certaine_dt": round(
                    sum(o["perte_probable_dt"] for o in certains), 0),
            }
            classements[s] = [o["produit"] for o in certains[:10]]
    finally:
        SEUIL_OBSOLESCENCE_CERTAINE = d_origine
        if fermer:
            con.close()

    ref = set(classements.get(d_origine, []))
    stabilite = {}
    for s, noms in classements.items():
        if s == d_origine or not ref:
            continue
        communs = len(ref & set(noms))
        stabilite[f"{s}_mois"] = {
            "references_communes_sur_10": communs,
            "part_pct": round(communs / max(len(ref), 1) * 100, 0),
        }

    return {
        "seuil_servi_mois": d_origine,
        "resultats": resultats,
        "stabilite_du_classement_vs_seuil_servi": stabilite,
        "lecture": (
            "Le montant total dépend du seuil, l'ORDRE des références beaucoup "
            "moins. Or une direction n'agit pas sur un total : elle traite les "
            "premières lignes d'une liste. Tant que ces lignes sont les mêmes sur "
            "toute la plage plausible, l'incertitude sur le seuil ne change "
            "aucune décision — elle ne change que le chiffre qu'on annonce."),
        "ce_qui_leverait_cette_hypothese": (
            "Les durées de conservation réelles, que le fournisseur imprime sur "
            "chaque conditionnement. Une information dans l'export les rendrait "
            "mesurées au lieu de déclarées."),
    }


def afficher() -> None:
    m = construire()
    if m.get("error"):
        print(f"\nErreur : {m['error']}\n")
        return

    def dt(v: float) -> str:
        return f"{v:,.0f} DT".replace(",", " ")

    print("\n" + "=" * 78)
    print("  POSITION DE STOCK — reconstruite des flux réels")
    print("=" * 78)

    d = m["identification_mouvement_stock"]
    print(f"\n  Valeur d'INDICMVTSTOCK retenue : « {d['valeur_retenue']} »")
    for val, s in sorted(d["detail_par_valeur"].items(), key=lambda kv: str(kv[0])):
        marque = "  <- retenue" if val == d["valeur_retenue"] else ""
        print(f"    « {val} » : {s['lignes']:>6} lignes · "
              f"{s['part_services_pct']:>5.2f} % de prestations{marque}")

    print(f"\n  Références traitées        : {m['n_references']:,}".replace(",", " "))
    print(f"  Rapprochées achat ↔ vente  : {m['n_rapprochees_achat_vente']:,}".replace(",", " "))
    print(f"  Prestations écartées       : {m['n_services_exclus']:,}".replace(",", " "))
    print(f"  Couverture en volume       : {m['couverture_volume_pct']} %")
    print(f"\n  Position positive (accumulation) : {m['n_position_positive']:,}".replace(",", " "))
    print(f"  Position négative (stock antérieur) : {m['n_position_negative']:,}".replace(",", " "))
    print(f"\n  VALEUR ACCUMULÉE : {dt(m['valeur_accumulee_dt'])}")
    print("  (minorant : les positions négatives immobilisent aussi du capital,")
    print("   mais leur niveau n'est pas calculable sans inventaire initial)")

    print("\n  Dix plus fortes immobilisations :")
    print(f"  {'produit':<44}{'valeur':>14}{'couverture':>13}")
    for t in m["top_immobilisations"][:10]:
        print(f"  {t['produit'][:42]:<44}{dt(t['valeur_dt']):>14}"
              f"{t['mois_de_couverture']:>10.1f} m")

    obs = detecter_obsolescence()
    if obs:
        certains = [o for o in obs if o["gravite"] == "perte_quasi_certaine"]
        perte_c = sum(o["perte_probable_dt"] for o in certains)
        perte_t = sum(o["perte_probable_dt"] for o in obs)

        print("\n" + "-" * 78)
        print("  STOCK QUI NE SERA PAS ÉCOULÉ")
        print("  (aucune date d'expiration enregistrée : un consommable dont le")
        print("   stock dépasse 2 ans de consommation périmera, quelle qu'elle soit)")
        print(f"\n  Perte quasi certaine : {dt(perte_c)}   "
              f"sur {len(certains)} référence(s)")
        print(f"  Rotation lente       : {dt(perte_t - perte_c)}   "
              f"sur {len(obs) - len(certains)} référence(s)")

        print(f"\n  {'produit':<44}{'perte':>13}{'couverture':>13}")
        for o in obs[:10]:
            print(f"  {o['produit'][:42]:<44}{dt(o['perte_probable_dt']):>13}"
                  f"{o['mois_couverture']:>10.0f} m")
        ecartees = obs[0].get("_references_ecartees") or []
        if ecartees:
            print(f"\n  {len(ecartees)} référence(s) écartée(s) — "
                  "équipements et pièces détachées :")
            for e in ecartees[:6]:
                print(f"    · {e[:66]}")
            print("  Un automate s'amortit, un joint se conserve : ni l'un ni")
            print("  l'autre ne périme comme un réactif.")

    sens = m.get("sensibilite_seuils") or {}
    res = sens.get("resultats") or {}
    if res:
        print("\n" + "-" * 78)
        print("  ET SI LE SEUIL DE DEUX ANS ÉTAIT FAUX ?")
        print("  (il est DÉCLARÉ, non mesuré — voici comment la perte se déplace)")
        print(f"\n  {'seuil':<12}{'références':>12}{'perte annoncée':>20}"
              f"{'top 10 inchangé':>20}")
        stab = sens.get("stabilite_du_classement_vs_seuil_servi") or {}
        for cle, d in res.items():
            s = stab.get(cle, {})
            part = (f"{s['references_communes_sur_10']}/10"
                    if s else "— (seuil servi)")
            print(f"  {cle:<12}{d['n_references']:>12}"
                  f"{dt(d['perte_quasi_certaine_dt']):>20}{part:>20}")
        print("\n  Le TOTAL dépend du seuil ; l'ORDRE des références beaucoup")
        print("  moins. Une direction traite les premières lignes d'une liste,")
        print("  pas un total : l'incertitude sur le seuil ne change donc pas")
        print("  la décision, seulement le chiffre annoncé.")

    nom = m.get("nomenclature") or {}
    if nom.get("disponible"):
        print("\n" + "-" * 78)
        print("  FIABILITÉ DU CLASSEMENT PRODUIT")
        print(f"\n  Couverture en valeur : {nom['couverture_valeur_pct']} % "
              "des références portent un libellé reconnu")
        print(f"  Valeur exposée à une erreur de classement : "
              f"{dt(nom['valeur_consommable_par_defaut_dt'])} "
              f"({nom['part_consommable_par_defaut_pct']} %)")
        print("  — classée « consommable » par défaut, donc susceptible d'être")
        print("    annoncée en perte à tort. Grille de correction :")
        print("    reports/nomenclature_a_valider.csv")

    print("=" * 78 + "\n")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    afficher()
