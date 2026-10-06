"""Moteur de KPIs financiers haute performance basé sur **DuckDB**."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

import duckdb

from etl.sources import DOSSIER_SOURCES as _DEFAULT_DATA_DIR
from etl.sources import ENTREPOT
from ml_engine.typologie import condition_sql_hopital_public

_log = logging.getLogger(__name__)

STORE_PATH = ENTREPOT


def _connect(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Connexion en LECTURE à l'entrepôt, reconstruit d'abord s'il est périmé."""
    from etl.construire import assurer_a_jour
    assurer_a_jour(STORE_PATH, data_dir or _DEFAULT_DATA_DIR)
    return duckdb.connect(str(STORE_PATH), read_only=True)


def _sales_where(f: Dict[str, Any]) -> str:
    f = f or {}
    clauses: List[str] = ["1=1"]
    years = f.get("selected_years") or []
    if years:
        clauses.append("year IN (" + ",".join(str(int(y)) for y in years) + ")")
    if f.get("date_start"):
        clauses.append(f"date >= DATE '{f['date_start']}'")
    if f.get("date_end"):
        clauses.append(f"date <= DATE '{f['date_end']}'")
    clients = f.get("selected_clients") or []
    if clients:
        vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in clients)
        clauses.append(f"client IN ({vals})")
    modes = f.get("payment_modes") or []
    if modes:
        vals = ",".join("'" + str(m).replace("'", "''") + "'" for m in modes)
        clauses.append(f"mode_regl IN ({vals})")
    if f.get("min_amount") is not None:
        clauses.append(f"ttc >= {float(f['min_amount'])}")
    if f.get("max_amount") is not None:
        clauses.append(f"ttc <= {float(f['max_amount'])}")
    risk = f.get("risk_level") or "Tous"
    if risk and risk != "Tous":
        if "heure" in risk:
            clauses.append("payment_delay_days <= 0")
        elif "30" in risk:
            clauses.append("payment_delay_days > 30")
        elif "90" in risk:
            clauses.append("payment_delay_days > 90")
    return " AND ".join(clauses)


def _clause_dates(f: Dict[str, Any], colonne: str) -> str:
    """Restriction de dates commune aux tables autres que `sales`."""
    c = ""
    if f.get("date_start"):
        c += f" AND {colonne} >= DATE '{f['date_start']}'"
    if f.get("date_end"):
        c += f" AND {colonne} <= DATE '{f['date_end']}'"
    return c


def _apply_fidelity(con, where: str, fidelity: str) -> str:
    """Renvoie une clause supplémentaire restreignant aux clients du segment de fidélité."""
    if not fidelity or fidelity == "Tous":
        return ""
    rows = con.execute(f"""
        SELECT client, count(*) n FROM sales WHERE {where} GROUP BY client
    """).fetchall()
    if "Fid" in fidelity:
        keep = [r[0] for r in rows if r[1] > 5]
    elif "gul" in fidelity or "égul" in fidelity or "Regul" in fidelity:
        keep = [r[0] for r in rows if 2 <= r[1] <= 5]
    else:
        keep = [r[0] for r in rows if r[1] == 1]
    if not keep:
        return " AND 1=0"
    vals = ",".join("'" + str(c).replace("'", "''") + "'" for c in keep)
    return f" AND client IN ({vals})"


def get_filter_options(data_dir: Path | None = None) -> Dict[str, Any]:
    con = _connect(data_dir)
    years = [int(r[0]) for r in con.execute(
        "SELECT DISTINCT year FROM sales WHERE year IS NOT NULL ORDER BY year").fetchall()]
    client_rows = con.execute(
        "SELECT client, any_value(client_name) FROM sales GROUP BY client ORDER BY sum(ttc) DESC NULLS LAST LIMIT 400").fetchall()
    clients = [r[0] for r in client_rows if r[0]]
    client_names = {r[0]: (r[1] or r[0]) for r in client_rows if r[0]}
    modes = [r[0] for r in con.execute(
        "SELECT DISTINCT mode_regl FROM sales WHERE mode_regl IS NOT NULL AND mode_regl <> '' ORDER BY 1").fetchall()]
    max_amount = con.execute("SELECT max(ttc) FROM sales").fetchone()[0] or 0.0
    con.close()
    return {
        "available_years": years,
        "available_clients": clients,
        "client_names": client_names,
        "fidelity_options": ["Tous", "Fidèles (> 5 achats)", "Réguliers (2-5 achats)", "Occasionnels (1 achat)"],
        "available_payment_modes": modes,
        "risk_levels": ["Tous", "Payé à l'heure", "Retard > 30j", "Critique > 90j"],
        "max_amount_possible": float(max_amount),
    }


def _scalar(con, sql: str, default=0):
    r = con.execute(sql).fetchone()
    return r[0] if r and r[0] is not None else default


def _raisons_credit(v: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pourquoi ce client apparaît dans les priorités de recouvrement."""
    try:
        from ml_engine.explication import raisons_seuils
    except Exception:
        return []
    valeurs = {"avg_delay": float(v.get("avg_delay") or 0),
               "exposure": float(v.get("exposure") or 0),
               "n": float(v.get("n") or 0)}
    # Aucune phrase n'est écrite ici : `raisons_seuils` compose « libellé :
    # valeur — au-dessus de seuil » depuis ces déclarations. Recopier le seuil
    # dans une phrase laissait les deux se désynchroniser au premier changement.
    return raisons_seuils(valeurs, [
        {"variable": "avg_delay", "seuil": 90, "sens": "sup", "poids": 3.0},
        {"variable": "avg_delay", "seuil": 60, "sens": "sup", "poids": 2.0},
        {"variable": "exposure", "seuil": 50_000, "sens": "sup", "poids": 2.0},
        {"variable": "n", "seuil": 20, "sens": "sup", "poids": 1.0},
    ], n=3)


def _load_client_risk() -> Dict[str, Any]:
    """Scores de risque crédit par client (produits par credit_risk_model.train())."""
    path = Path(os.environ.get("CLIENT_RISK_PATH", STORE_PATH.parent / "client_risk.json"))
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _charger_churn_si_servi(limite: int = 10, clients: List[str] | None = None) -> Dict[str, Any]:
    """Clients à risque de décrochage, classés par ENJEU FINANCIER."""
    try:
        from ml_engine.registre import est_deploye
        if not est_deploye("churn"):
            return {"servi": False,
                    "motif": "modèle de décrochage non servi par le registre"}
    except Exception:
        return {"servi": False, "motif": "registre indisponible"}

    try:
        from ml_engine.analytics.churn_model import load_client_churn
        scores = load_client_churn()
    except Exception:
        return {"servi": False, "motif": "scores de décrochage illisibles"}

    if not scores:
        return {"servi": False, "motif": "aucun score disponible"}
    if clients is not None:
        garde = {str(c) for c in clients}
        scores = {c: v for c, v in scores.items() if str(c) in garde}

    noms: Dict[str, str] = {}
    try:
        con = _connect()
        try:
            noms = {str(c): str(n) for c, n in con.execute(
                "SELECT client, any_value(client_name) FROM sales "
                "WHERE client_name IS NOT NULL GROUP BY client").fetchall()}
        finally:
            con.close()
    except Exception:
        pass

    classes = sorted(
        ({"code": code, "nom": noms.get(code, code), **v}
         for code, v in scores.items()),
        key=lambda c: -float(c.get("enjeu_dt") or 0))[:limite]

    # Les poids ne sont PLUS renormalisés ici : `ml_engine.explication` publie
    # déjà des parts qui totalisent 100 %, et le facteur en sens inverse porte
    # volontairement `poids: None`. Le recalcul transformait ce None en 0,0 —
    # soit une barre « 0 % » à l'écran pour le seul facteur qui n'en a pas.

    n_alerte = sum(1 for v in scores.values()
                   if float(v.get("probabilite_decrochage") or 0) >= 0.5)
    enjeu_total = sum(float(v.get("enjeu_dt") or 0) for v in scores.values())

    return {
        "servi": True,
        "n_clients_scores": len(scores),
        "n_au_dessus_de_0_5": n_alerte,
        "enjeu_total_dt": round(enjeu_total, 0),
        "top": classes,
        "lecture": (
            "Probabilité qu'un client ACTIF cesse de commander dans les 90 jours. "
            "Le classement suit l'enjeu financier (probabilité × CA 12 mois), pas "
            "la probabilité seule : c'est ce qui permet de hiérarchiser les relances."),
    }


def _charger_flux_reels(con) -> Dict[str, Any]:
    """Position de stock reconstruite des flux réels, si la table existe."""
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "stock_flux_reel" not in tables:
            return {"disponible": False,
                    "motif": "table absente — lancer ml_engine.stock.flux_reels"}

        g = con.execute("""
            SELECT
                count(*) FILTER (WHERE position > 0 AND NOT est_service),
                sum(position * cout_unitaire) FILTER (
                    WHERE position > 0 AND NOT est_service AND cout_unitaire IS NOT NULL),
                count(*) FILTER (WHERE position > 0 AND NOT est_service
                                 AND conso_mensuelle > 0
                                 AND position / conso_mensuelle > 24)
            FROM stock_flux_reel
        """).fetchone()

        top = con.execute("""
            SELECT produit,
                   position,
                   position * cout_unitaire        AS valeur_dt,
                   conso_mensuelle,
                   position / conso_mensuelle      AS mois_couverture
            FROM stock_flux_reel
            WHERE position > 0 AND NOT est_service
              AND cout_unitaire IS NOT NULL AND conso_mensuelle > 0
            ORDER BY position * cout_unitaire DESC NULLS LAST
            LIMIT 12
        """).fetchall()
    except Exception as e:
        return {"disponible": False, "motif": f"lecture impossible ({type(e).__name__})"}

    try:
        from ml_engine.stock.flux_reels import (detecter_obsolescence,
                                                detecter_ruptures)
        ruptures = detecter_ruptures(con)
        obsoletes = detecter_obsolescence(con)
    except Exception:
        ruptures, obsoletes = [], []

    n_pos, valeur, n_dormant = g
    return {
        "disponible": True,
        "ruptures": ruptures[:25],
        "n_ruptures": len(ruptures),
        "n_ruptures_critiques": sum(
            1 for r in ruptures if r["gravite"] in ("rupture_probable", "critique")),
        "budget_commandes_dt": round(sum(
            r["quantite_suggeree"] * r["cout_unitaire_dt"] for r in ruptures), 0),
        "obsolescence": obsoletes[:20],
        "n_obsoletes": len(obsoletes),
        "perte_probable_dt": round(
            sum(o["perte_probable_dt"] for o in obsoletes), 0),
        "perte_quasi_certaine_dt": round(sum(
            o["perte_probable_dt"] for o in obsoletes
            if o["gravite"] == "perte_quasi_certaine"), 0),
        "n_obsoletes_certains": sum(
            1 for o in obsoletes if o["gravite"] == "perte_quasi_certaine"),
        "n_references_accumulees": int(n_pos or 0),
        "valeur_immobilisee_dt": round(float(valeur or 0), 0),
        "n_references_plus_de_2_ans": int(n_dormant or 0),
        "top": [{
            "produit": p,
            "position": round(float(pos or 0), 0),
            "valeur_dt": round(float(v or 0), 0),
            "conso_mensuelle": round(float(cm or 0), 1),
            "mois_couverture": round(float(mc or 0), 1),
        } for p, pos, v, cm, mc in top],
        "nature": (
            "Quantités entrées moins quantités sorties, calculées sur les "
            "factures réelles. Variation cumulée et non inventaire : le stock "
            "antérieur à l'historique reste inconnu, donc ce montant est un "
            "minorant."),
    }


def _charger_conversion_devis_si_servie() -> Dict[str, Any]:
    """Devis à relancer en priorité, si le registre l'autorise."""
    try:
        from ml_engine.analytics.conversion_devis import predire
        return predire()
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _charger_marge_client_si_servie() -> Dict[str, Any]:
    """Clients dont la marge va s'éroder, si le registre l'autorise."""
    try:
        from ml_engine.analytics.marge_client import predire
        return predire()
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _charger_reappro_si_servi() -> Dict[str, Any]:
    """Besoin de réapprovisionnement à 3 mois, si le registre l'autorise."""
    try:
        from ml_engine.stock.reappro_model import predire
        return predire()
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _charger_segmentation_si_servie() -> Dict[str, Any]:
    """Typologie de clientèle, avec son croisement au décrochage."""
    try:
        from ml_engine.registre import est_deploye
        if not est_deploye("segmentation"):
            return {"servi": False, "motif": "segmentation non servie par le registre"}
    except Exception:
        return {"servi": False, "motif": "registre indisponible"}

    try:
        import json as _json
        p = Path(__file__).resolve().parents[2] / "reports" / "segmentation_metrics.json"
        if not p.exists():
            return {"servi": False, "motif": "rapport absent"}
        r = _json.load(open(p, encoding="utf-8"))
    except Exception:
        return {"servi": False, "motif": "rapport illisible"}

    segments = r.get("segments") or []
    if not segments:
        return {"servi": False, "motif": "aucun segment"}

    risques = {c["segment"]: c for c in
               ((r.get("croisement_decrochage") or {}).get("par_segment") or [])}

    return {
        "servi": True,
        "n_segments": len(segments),
        "n_clients": r.get("n_clients"),
        "qualite": r.get("qualite", {}).get("silhouette"),
        "stabilite": r.get("qualite", {}).get("stabilite_rand_ajuste"),
        "segments": [{
            **s,
            "part_menacee_pct": (risques.get(s["segment"], {})
                                 .get("part_menacee_pct")),
            "ca_menace_dt": risques.get(s["segment"], {}).get("ca_menace_dt"),
        } for s in segments],
    }


def _part_publique_carnet(data_dir: Path | None, origine: int, cible: int) -> float | None:
    """Part (en %) des établissements de santé publics dans les créances DÉJÀ inscrites au carnet pour…"""
    public = condition_sql_hopital_public("client_name")
    try:
        con = _connect(data_dir)
        try:
            tot, pub = con.execute(f"""
                SELECT sum(ttc), sum(ttc) FILTER (WHERE {public})
                FROM sales
                WHERE date IS NOT NULL AND echeance IS NOT NULL AND NOT est_avoir
                  AND year(echeance) BETWEEN 2016 AND 2035
                  AND echeance >= date
                  AND year(date) * 12 + month(date) - 1 <= ?
                  AND year(echeance) * 12 + month(echeance) - 1 = ?
            """, [origine, cible]).fetchone()
        finally:
            con.close()
    except Exception as e:
        _log.warning("radar : part publique du carnet indisponible (%s: %s)",
                     type(e).__name__, e)
        return None
    if not tot:
        return None
    return float(pub or 0) / float(tot) * 100


#: Part du chiffre d'affaires annuel au-delà de laquelle un enjeu passe en
#: sévérité haute. Déclarée ici, en un seul endroit, plutôt que répétée dans
#: chaque carte sous forme de montant absolu qui vieillit.
PART_CA_SEVERITE_HAUTE = 0.05


def _severite(enjeu_dt: float, ca_annuel_dt: float) -> str:
    if not ca_annuel_dt or enjeu_dt <= 0:
        return "faible"
    return ("haute" if enjeu_dt / ca_annuel_dt >= PART_CA_SEVERITE_HAUTE
            else "moyenne")


def _cartes_des_modeles(ca_annuel_dt: float) -> List[Dict[str, Any]]:
    """Une carte par modèle SERVI, avec son enjeu chiffré.

    Le radar ne portait que deux cartes de trésorerie : les modèles déployés
    calculaient un enjeu en dinars que rien ne remontait à l'écran de décision.
    Chaque carte nomme son modèle, et n'existe pas si le registre le refuse — la
    décision de servir reste au registre, jamais ici.
    """
    cartes: List[Dict[str, Any]] = []

    def ajouter(carte: Dict[str, Any]) -> None:
        cartes.append(carte)

    # ── Décrochage client ────────────────────────────────────────────────────
    try:
        churn = _charger_churn_si_servi(limite=3)
        if churn.get("servi") and (churn.get("n_au_dessus_de_0_5") or 0) > 0:
            enjeu = float(churn.get("enjeu_total_dt") or 0)
            tops = churn.get("top") or []
            noms = ", ".join((c.get("nom") or c.get("code") or "")[:34]
                             for c in tops[:3])
            action = next((c["contrefactuel"]["phrase"] for c in tops
                           if (c.get("contrefactuel") or {}).get("phrase")), None)
            ajouter({
                "id": "churn_clients", "categorie": "Rétention",
                "severite": _severite(enjeu, ca_annuel_dt),
                "titre": "Clients en risque de décrochage",
                "montant_dt": round(enjeu, 0),
                "montant_label": "chiffre d'affaires annuel des clients signalés",
                "constat": (f"{churn['n_au_dessus_de_0_5']} client(s) au-dessus de "
                            f"0,5 de probabilité de ne plus commander dans les "
                            f"90 jours, sur {churn.get('n_clients_scores', 0)} "
                            f"clients actifs scorés."),
                "signal_externe": "Modèle de décrochage (AUC hors période)",
                "action": (f"Appeler {noms}."
                           + (f" {action.capitalize()} pour le premier."
                              if action else "")),
                "top": [{"client": (c.get("nom") or c.get("code")),
                         "montant": float(c.get("enjeu_dt") or 0)}
                        for c in tops[:3]],
                "modele": "churn",
            })
    except Exception as e:
        _log.warning("radar : carte « décrochage » indisponible (%s: %s)",
                     type(e).__name__, e)

    # ── Érosion de marge ─────────────────────────────────────────────────────
    try:
        marge = _charger_marge_client_si_servie()
        tops = marge.get("top") or []
        if marge.get("servi") and tops:
            enjeu = sum(float(c.get("marge_en_jeu_dt") or 0) for c in tops)
            ajouter({
                "id": "erosion_marge", "categorie": "Rentabilité",
                "severite": _severite(enjeu, ca_annuel_dt),
                "titre": "Érosion de marge attendue à 3 mois",
                "montant_dt": round(enjeu, 0),
                "montant_label": "marge en jeu sur les clients signalés",
                "constat": (f"{len(tops)} client(s) dont la marge du trimestre à "
                            f"venir devrait tomber sous "
                            f"{marge.get('seuil_marge_basse_pct', 0):.1f} %, "
                            f"sur {marge.get('n_clients', 0)} clients suivis."),
                "signal_externe": "Modèle d'érosion de marge (gradient boosting)",
                "action": ("Revoir les conditions tarifaires de ces clients avant "
                           "la prochaine commande, pas après."),
                "top": [{"client": c.get("client"),
                         "montant": float(c.get("marge_en_jeu_dt") or 0)}
                        for c in tops[:3]],
                "modele": "marge_client",
            })
    except Exception as e:
        _log.warning("radar : carte « marge » indisponible (%s: %s)",
                     type(e).__name__, e)

    # ── Devis à relancer ─────────────────────────────────────────────────────
    try:
        devis = _charger_conversion_devis_si_servie()
        tops = devis.get("top") or []
        if devis.get("servi") and tops:
            enjeu = float(devis.get("esperance_totale_dt") or 0)
            ajouter({
                "id": "devis_a_relancer", "categorie": "Commercial",
                "severite": _severite(enjeu, ca_annuel_dt),
                "titre": "Devis ouverts à relancer en priorité",
                "montant_dt": round(enjeu, 0),
                "montant_label": "espérance de signature sur les devis ouverts",
                "constat": (f"{devis.get('n_devis', 0)} devis encore ouverts ; "
                            f"les {len(tops)} premiers concentrent l'essentiel de "
                            "l'espérance de signature."),
                "signal_externe": "Modèle de conversion des devis",
                "action": ("Relancer ces devis dans l'ordre affiché : le "
                           "classement combine probabilité et montant."),
                "top": [{"client": c.get("client"),
                         "montant": float(c.get("montant_ht_dt") or 0)}
                        for c in tops[:3]],
                "modele": "conversion_devis",
            })
    except Exception as e:
        _log.warning("radar : carte « devis » indisponible (%s: %s)",
                     type(e).__name__, e)

    # ── Mouvements attendus dans le top 10 ───────────────────────────────────
    try:
        from ml_engine.analytics.ca_client import predire_top
        top = predire_top(n=10, horizon=12)
        if top.get("servi") and (top.get("entrants") or top.get("sortants")):
            sortants = top.get("sortants") or []
            entrants = top.get("entrants") or []
            perte = sum(float(c.get("ca_12m_constate_dt") or 0)
                        for c in (top.get("top_predit") or [])
                        if c.get("rang_constate") is None)
            ajouter({
                "id": "mouvements_top_10", "categorie": "Portefeuille",
                "severite": "moyenne" if sortants else "faible",
                "titre": "Mouvements attendus dans le top 10 clients",
                "montant_dt": round(perte, 0),
                "montant_label": "chiffre d'affaires des clients entrants",
                "constat": (
                    f"{len(sortants)} client(s) devraient sortir du top 10 et "
                    f"{len(entrants)} y entrer sur les 12 prochains mois. Le top "
                    "constaté est un décompte du passé ; celui-ci est une "
                    "prévision."),
                "signal_externe": "Modèle de chiffre d'affaires à 12 mois",
                "action": (
                    ("Sécuriser " + ", ".join(
                        (c.get("nom") or c.get("client") or "")[:34]
                        for c in sortants[:3]) + " avant la sortie du top 10.")
                    if sortants else
                    "Accompagner la montée des entrants."),
                "top": [{"client": (c.get("nom") or c.get("client")),
                         "montant": 0.0} for c in sortants[:3]],
                "modele": "ca_client_12m",
            })
    except Exception as e:
        _log.warning("radar : carte « top 10 » indisponible (%s: %s)",
                     type(e).__name__, e)

    return cartes


def finance_radar(mi: Dict[str, Any] | None, filters: Dict[str, Any] | None = None,
                  data_dir: Path | None = None) -> List[Dict[str, Any]]:
    """RADAR FINANCIER — cartes d'action chiffrées sur les données de l'ERP."""
    mi = mi or {}
    filters = filters or {}
    cards: List[Dict[str, Any]] = []
    try:
        con = _connect(data_dir)
    except Exception:
        return []

    public = condition_sql_hopital_public("client_name")
    try:
        base_where = _sales_where(filters)
        try:
            W = base_where + _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
        except Exception:
            W = base_where
        filtre_actif = W.strip() not in ("1=1", "")
        suffixe_perim = " (périmètre filtré)" if filtre_actif else ""

        try:
            expo, expo_pub, crit_pub, nb_pub, ref_mois = con.execute(f"""
                WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
                SELECT sum(ttc) FILTER (WHERE payment_delay_days > 60),
                       sum(ttc) FILTER (WHERE payment_delay_days > 60 AND {public}),
                       sum(ttc) FILTER (WHERE payment_delay_days > 90 AND {public}),
                       count(DISTINCT client) FILTER (WHERE payment_delay_days > 60 AND {public}),
                       strftime((SELECT md FROM ref), '%Y-%m')
                FROM sales
                WHERE {W} AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
            """).fetchone()
            pub_risque, pub_crit = float(expo_pub or 0), float(crit_pub or 0)
            pub_nb, expo_totale = int(nb_pub or 0), float(expo or 0)
            top = con.execute(f"""
                WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
                SELECT any_value(client_name) nom,
                       sum(ttc) FILTER (WHERE payment_delay_days > 60) m
                FROM sales
                WHERE {W} AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
                  AND client_name IS NOT NULL AND {public}
                GROUP BY client HAVING m > 0 ORDER BY m DESC, nom LIMIT 3
            """).fetchall()
            top_debiteurs = [{"client": (r[0] or "—")[:34], "montant": float(r[1] or 0)}
                             for r in top]
        except Exception as e:
            _log.warning("radar : carte « recouvrement public » indisponible (%s: %s)",
                         type(e).__name__, e)
            pub_risque = pub_crit = expo_totale = 0.0
            pub_nb, ref_mois, top_debiteurs = 0, None, []

        sante = ((mi.get("macro") or {}).get("sante_pct_pib") or {}).get("value")
        if pub_risque > 0:
            sev = "haute" if pub_crit > 0 else "moyenne"
            part = pub_risque / expo_totale * 100 if expo_totale else 0.0
            periode = f"échéances des six mois jusqu'à {ref_mois}" if ref_mois else "six derniers mois"
            noms = ", ".join(d["client"] for d in top_debiteurs) or "vos principaux comptes publics"
            ext = (f"Budget santé public à {sante}% du PIB — capacité de paiement du secteur adossée aux "
                   f"finances publiques (délais structurellement longs)."
                   if sante is not None else
                   "Payeurs publics : délais de règlement structurellement longs.")
            cards.append({
                "id": "recouvrement_public", "categorie": "Recouvrement", "severite": sev,
                "titre": "Risque de recouvrement — établissements de santé publics" + suffixe_perim,
                "montant_dt": round(pub_risque, 0),
                "montant_label": "exposition récente à terme long (>60j)",
                "constat": (f"{pub_risque/1e6:.2f} M DT d'exposition récente à terme long (>60j) "
                            f"sur {pub_nb} établissement(s) de santé public(s), soit {part:.0f} % "
                            f"de l'exposition récente ({periode}), dont "
                            f"{pub_crit/1e6:.2f} M DT à plus de 90 jours."),
                "signal_externe": ext,
                "action": (f"Prioriser le recouvrement de {noms}. Exiger un acompte ou une garantie de paiement "
                           f"sur les nouveaux marchés publics à terme long."),
                "top": top_debiteurs,
            })
    finally:
        try:
            con.close()
        except Exception:
            pass


    try:
        from ml_engine.forecasting.carnet_echeances import charger_factures, prevoir
        from ml_engine.registre import est_deploye

        if est_deploye("echeancier"):
            factures = charger_factures()
            echeances = sorted({e for _, e, _ in factures})
            emissions = sorted({em for em, _, _ in factures})
            origine = max(emissions) - 1
            sortie = prevoir(factures, origine, 1, echeances[0])
            if sortie:
                prevu, _regime, maturite = sortie
                part_pub = _part_publique_carnet(data_dir, origine, origine + 1)
                phrase_pub = ("" if part_pub is None else
                              f" Les établissements de santé publics en portent "
                              f"{part_pub:.0f} % de la part déjà inscrite.")
                cards.append({
                    "id": "echeancier_1m", "categorie": "Trésorerie", "severite": "moyenne",
                    "titre": "Créances exigibles le mois prochain",
                    "montant_dt": round(prevu, 0),
                    "montant_label": "montant arrivant à échéance",
                    "constat": (
                        f"{prevu/1e6:.2f} M DT de créances deviennent exigibles le mois "
                        f"prochain. {maturite:.0%} de ce montant est déjà inscrit au "
                        "carnet : il est lu dans les factures émises, non estimé."
                        + phrase_pub),
                    "signal_externe": "Échéances contractuelles des factures déjà émises",
                    "action": ("Caler les relances sur ce montant : ce sont des créances "
                               "exigibles, pas des encaissements garantis — les "
                               "n'enregistre aucune date de règlement."),
                    "top": [],
                })
    except Exception as e:
        _log.warning("radar : carte « échéancier » indisponible (%s: %s)",
                     type(e).__name__, e)

    # Les modèles servis ne dépendent pas du périmètre filtré : ils sont
    # entraînés sur tout l'historique. Leurs cartes ne portent donc pas le
    # suffixe de périmètre, et ne sont ajoutées qu'en l'absence de filtre, pour
    # qu'un écran filtré ne mélange pas deux périmètres.
    if not filtre_actif:
        try:
            cards += _cartes_des_modeles(_ca_annuel(data_dir))
        except Exception as e:
            _log.warning("radar : cartes des modèles indisponibles (%s: %s)",
                         type(e).__name__, e)

    order = {"haute": 0, "moyenne": 1, "faible": 2}
    cards.sort(key=lambda c: (order.get(c.get("severite"), 3), -(c.get("montant_dt") or 0)))
    for i, c in enumerate(cards):
        c["priorite"] = i + 1
    return cards


def _ca_annuel(data_dir: Path | None = None) -> float:
    """Chiffre d'affaires des 12 derniers mois, pour calibrer la sévérité."""
    try:
        con = _connect(data_dir)
        try:
            return float(con.execute("""
                WITH ref AS (SELECT max(date) md FROM sales)
                SELECT coalesce(sum(ttc), 0) FROM sales
                WHERE NOT est_avoir
                  AND date >= (SELECT md FROM ref) - INTERVAL 12 MONTH
            """).fetchone()[0] or 0.0)
        finally:
            con.close()
    except Exception:
        return 0.0


PERIODES = {
    "12m": "12 derniers mois",
    "annee": "Année en cours",
    "tout": "Tout l'historique",
}


def periode_reference(con, filters: Dict[str, Any]) -> Dict[str, Any]:
    """Période sur laquelle portent les indicateurs, et sa période de comparaison.

    Un directeur ouvre son tableau de bord pour savoir où il en est MAINTENANT :
    un chiffre d'affaires cumulé depuis 2017 ne lui dit rien. Par défaut, les
    indicateurs portent donc sur les 12 derniers mois (comptés depuis la dernière
    facture de l'entrepôt), comparés aux 12 mois précédents. Une année ou des
    dates choisies à la main priment toujours sur ce défaut.
    """
    from datetime import date as _date, timedelta
    if filters.get("selected_years") or filters.get("date_start") or filters.get("date_end"):
        return {"code": "personnalisee", "libelle": "Période choisie", "debut": None, "fin": None}
    code = str(filters.get("periode") or "12m")
    if code not in PERIODES:
        code = "12m"
    if code == "tout":
        return {"code": code, "libelle": PERIODES[code], "debut": None, "fin": None}
    fin = con.execute("SELECT max(date) FROM sales").fetchone()[0]
    if fin is None:
        return {"code": "tout", "libelle": PERIODES["tout"], "debut": None, "fin": None}

    def _moins_un_an(d: _date) -> _date:
        try:
            return d.replace(year=d.year - 1)
        except ValueError:            # 29 février
            return d.replace(year=d.year - 1, day=28)

    debut = (_moins_un_an(fin) + timedelta(days=1)) if code == "12m" else _date(fin.year, 1, 1)
    return {"code": code, "libelle": PERIODES[code],
            "debut": debut.isoformat(), "fin": fin.isoformat(),
            "comparaison_debut": _moins_un_an(debut).isoformat(),
            "comparaison_fin": _moins_un_an(fin).isoformat()}


#: Tranches de délai accordé, et ce que chacune signifie pour la trésorerie.
TRANCHES_DELAI = [
    ("comptant", "Comptant", "payment_delay_days <= 0",
     "Encaissé à l'émission : aucune trésorerie avancée."),
    ("j30", "1 à 30 jours", "payment_delay_days > 0 AND payment_delay_days <= 30",
     "Délai court, usage courant du secteur privé."),
    ("j60", "31 à 60 jours", "payment_delay_days > 30 AND payment_delay_days <= 60",
     "Délai standard des établissements publics."),
    ("j90", "61 à 90 jours", "payment_delay_days > 60 AND payment_delay_days <= 90",
     "Au-delà du seuil de 60 jours retenu dans ce tableau de bord comme limite "
     "de surveillance."),
    ("j90p", "plus de 90 jours", "payment_delay_days > 90",
     "Trésorerie avancée plus d'un trimestre sur une vente déjà livrée."),
]


def _delais(con, where_ventes: str, where_achats: str,
            periode: Dict[str, Any]) -> Dict[str, Any]:
    """Délais accordés aux clients et obtenus des fournisseurs, sans ambiguïté.

    TROIS PRÉCISIONS que le chiffre seul ne portait pas, et sans lesquelles il
    ne se décide pas :

      * LE SENS. « Délai moyen » ne disait pas qui attend qui. Le délai accordé
        est celui qu'Overlyne consent à ses clients — de la trésorerie qu'elle
        avance. Le délai obtenu est celui que ses fournisseurs lui consentent —
        de la trésorerie qu'on lui avance.
      * LA PONDÉRATION. Une moyenne par facture compte une facture de 500 DT
        comme une de 500 000 DT. Financièrement, seule la moyenne pondérée par
        le montant a un sens : c'est elle qui dit combien de jours de chiffre
        d'affaires sont réellement immobilisés.
      * LA NATURE. `payment_delay_days` est l'écart entre la date de facture et
        la date d'échéance : le délai INSCRIT à l'émission. L'ERP n'enregistre
        aucune date de règlement, donc aucun retard réel n'est mesurable ici.
        Un client peut payer en avance ou ne jamais payer : ce chiffre ne le
        dira pas.
    """
    v = con.execute(f"""
        SELECT avg(payment_delay_days),
               sum(ttc * payment_delay_days) / nullif(sum(ttc), 0),
               count(*), sum(ttc)
        FROM sales
        WHERE {where_ventes} AND NOT est_avoir AND payment_delay_days IS NOT NULL
    """).fetchone() or (None, None, 0, 0)
    a = con.execute(f"""
        SELECT avg(payment_delay_days),
               sum(ttc * payment_delay_days) / nullif(sum(ttc), 0),
               count(*), sum(ttc)
        FROM purchases
        WHERE {where_achats} AND NOT est_avoir AND payment_delay_days IS NOT NULL
    """).fetchone() or (None, None, 0, 0)

    cas = ", ".join(f"sum(ttc) FILTER (WHERE {c}) AS {code}, "
                    f"count(*) FILTER (WHERE {c}) AS n_{code}"
                    for code, _, c, _ in TRANCHES_DELAI)
    rep = con.execute(f"""
        SELECT {cas} FROM sales
        WHERE {where_ventes} AND NOT est_avoir AND payment_delay_days IS NOT NULL
    """).fetchone()
    total_reparti = sum(float(rep[i * 2] or 0) for i in range(len(TRANCHES_DELAI)))

    accorde_pondere = float(v[1] or 0)
    obtenu_pondere = float(a[1] or 0)
    ecart = accorde_pondere - obtenu_pondere

    # Trésorerie que l'entreprise finance elle-même : les jours d'écart,
    # appliqués au chiffre d'affaires quotidien de la période. C'est un ordre de
    # grandeur, pas un solde de compte — l'ERP ne porte pas les encaissements.
    ca_periode = float(v[3] or 0)
    jours_periode = None
    if periode.get("debut") and periode.get("fin"):
        from datetime import date as _d
        d1, d2 = _d.fromisoformat(periode["debut"]), _d.fromisoformat(periode["fin"])
        jours_periode = max(1, (d2 - d1).days + 1)
    ca_par_jour = (ca_periode / jours_periode) if jours_periode else None

    return {
        "accorde_aux_clients": {
            "moyenne_par_facture_j": round(float(v[0] or 0), 1),
            "moyenne_ponderee_j": round(accorde_pondere, 1),
            "n_factures": int(v[2] or 0),
            "montant_dt": round(ca_periode, 0),
            "sens": ("ce qu'Overlyne accorde à ses clients : de la trésorerie "
                     "avancée"),
        },
        "obtenu_des_fournisseurs": {
            "moyenne_par_facture_j": round(float(a[0] or 0), 1),
            "moyenne_ponderee_j": round(obtenu_pondere, 1),
            "n_factures": int(a[2] or 0),
            "montant_dt": round(float(a[3] or 0), 0),
            "sens": ("ce que les fournisseurs accordent à Overlyne : de la "
                     "trésorerie reçue"),
        },
        "ecart_j": round(ecart, 1),
        "ecart_sens": ("positif" if ecart > 0 else "négatif" if ecart < 0 else "nul"),
        "ecart_lecture": (
            "Overlyne paie ses fournisseurs avant d'être payée par ses clients : "
            f"l'écart de {abs(ecart):.0f} jours est financé sur sa propre "
            "trésorerie." if ecart > 0 else
            "Overlyne encaisse avant de payer ses fournisseurs : ce sont eux qui "
            "financent le cycle." if ecart < 0 else
            "Les deux délais s'équilibrent."),
        # Signé : positif = trésorerie avancée par Overlyne, négatif =
        # trésorerie que les fournisseurs lui avancent. Le libellé suit le
        # signe, sinon un nombre négatif sous « trésorerie immobilisée » se lit
        # à contresens.
        "tresorerie_cycle_dt": (round(ca_par_jour * ecart, 0)
                                if ca_par_jour is not None else None),
        "tresorerie_cycle_libelle": ("Trésorerie avancée par Overlyne"
                                     if ecart > 0 else
                                     "Trésorerie avancée par les fournisseurs"),
        "tresorerie_cycle_methode": (
            "jours d'écart × chiffre d'affaires quotidien de la période. Ordre "
            "de grandeur : les encaissements ne sont pas enregistrés, donc aucun "
            "solde réel n'est calculable."),
        "repartition": [{
            "code": code, "tranche": libelle, "signification": sens,
            "montant_dt": round(float(rep[i * 2] or 0), 0),
            "n_factures": int(rep[i * 2 + 1] or 0),
            "part_pct": (round(float(rep[i * 2] or 0) / total_reparti * 100, 1)
                         if total_reparti else None),
        } for i, (code, libelle, _, sens) in enumerate(TRANCHES_DELAI)],
        "nature": "délai ACCORDÉ, inscrit sur la facture à l'émission",
        "ce_n_est_pas": (
            "un retard de paiement. Aucune date de règlement n'est enregistrée : "
            "impossible de savoir ici si un client a payé, payé en "
            "avance, ou jamais payé."),
        "seuil_surveillance_j": 60,
        "part_au_dela_du_seuil_pct": (
            round(sum(float(rep[i * 2] or 0)
                      for i, (c, _, _, _) in enumerate(TRANCHES_DELAI)
                      if c in ("j90", "j90p")) / total_reparti * 100, 1)
            if total_reparti else None),
    }


def compute_dashboard(filters: Dict[str, Any] | None = None, data_dir: Path | None = None) -> Dict[str, Any]:
    """Calcule l'ensemble des KPIs et séries graphiques sur le périmètre filtré.

    Les INDICATEURS portent sur la période de référence (12 derniers mois par
    défaut) ; les SÉRIES d'évolution gardent tout l'historique, pour la tendance."""
    filters = filters or {}
    con = _connect(data_dir)
    periode = periode_reference(con, filters)
    historique = filters
    if periode.get("debut"):
        filters = {**filters, "date_start": periode["debut"], "date_end": periode["fin"]}
    base_where = _sales_where(filters)
    fid_clause = _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
    W = base_where + fid_clause
    hist_where = _sales_where(historique)
    WH = hist_where + _apply_fidelity(con, hist_where, historique.get("fidelity_filter", "Tous"))
    is_client_scope = bool(filters.get("selected_clients"))
    marge_non_attribuable = bool(
        filters.get("selected_clients") or filters.get("payment_modes")
        or (filters.get("risk_level") and filters.get("risk_level") != "Tous")
        or filters.get("min_amount") is not None or filters.get("max_amount") is not None
        or (filters.get("fidelity_filter") and filters.get("fidelity_filter") != "Tous")
    )

    k: Dict[str, Any] = {"monthly_sales": [], "top_clients": [], "anomalies_details": []}

    row = con.execute(f"""
        SELECT sum(ttc) ttc, sum(ht) ht,
               count(*) FILTER (WHERE NOT est_avoir)  nb,
               count(*) FILTER (WHERE est_avoir)      nb_avoirs,
               sum(-ttc) FILTER (WHERE est_avoir)     mt_avoirs,
               count(DISTINCT client) clients,
               avg(payment_delay_days) FILTER (WHERE NOT est_avoir) dso
        FROM sales WHERE {W}
    """).fetchone()
    ca_ttc, ca_ht, nb_fact, nb_avoirs, mt_avoirs, nb_clients, dso = (
        row or (0, 0, 0, 0, 0, 0, 0))
    k["ca_total_ttc"] = float(ca_ttc or 0)
    k["ca_total_ht"] = float(ca_ht or 0)
    k["nb_factures_vente"] = int(nb_fact or 0)
    k["nb_avoirs"] = int(nb_avoirs or 0)
    k["taux_avoirs_pct"] = (float(mt_avoirs or 0) / k["ca_total_ttc"] * 100
                            if k["ca_total_ttc"] else 0.0)
    k["nb_clients"] = int(nb_clients or 0)
    k["panier_moyen"] = (k["ca_total_ttc"] / k["nb_factures_vente"]) if k["nb_factures_vente"] else 0
    k["dso_jours"] = float(dso or 0)

    monthly = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) revenue, sum(ht) ht
        FROM sales WHERE {WH} GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["monthly_sales"] = [{"period": m[0], "revenue": float(m[1] or 0)} for m in monthly]
    if len(monthly) >= 2:
        last, prev = float(monthly[-1][1] or 0), float(monthly[-2][1] or 0)
        k["mom_growth"] = ((last - prev) / prev * 100) if prev else 0
        k["tendance"] = "Haussiere" if last >= prev else "Baissiere"
    else:
        k["mom_growth"] = 0
        k["tendance"] = "Stable"

    yearly = con.execute(f"SELECT year, sum(ttc) FROM sales WHERE {WH} GROUP BY year ORDER BY year").fetchall()
    k["yearly_sales"] = [{"year": int(y[0]), "revenue": float(y[1] or 0)} for y in yearly if y[0] is not None]
    ttm = con.execute(f"""
        WITH m AS (SELECT max(date) mx FROM sales WHERE {WH})
        SELECT
          sum(ttc) FILTER (WHERE date >  (SELECT mx FROM m) - INTERVAL '12 months')                                  AS ttm_v,
          sum(ttc) FILTER (WHERE date <= (SELECT mx FROM m) - INTERVAL '12 months'
                             AND date >  (SELECT mx FROM m) - INTERVAL '24 months')                                 AS prev_v
        FROM sales WHERE {WH}
    """).fetchone()
    ttm_v, prior_v = float(ttm[0] or 0), float(ttm[1] or 0)
    k["ttm_revenue"] = ttm_v
    k["yoy_growth"] = ((ttm_v - prior_v) / prior_v * 100) if prior_v else 0

    if periode.get("comparaison_debut"):
        comp = {**historique, "date_start": periode["comparaison_debut"],
                "date_end": periode["comparaison_fin"]}
        cw = _sales_where(comp)
        cw += _apply_fidelity(con, cw, comp.get("fidelity_filter", "Tous"))
        crow = con.execute(f"SELECT sum(ttc), count(DISTINCT client) FROM sales WHERE {cw}").fetchone()
        ca_prec = float(crow[0] or 0)
        periode["ca_precedent_dt"] = round(ca_prec, 0)
        periode["clients_precedent"] = int(crow[1] or 0)
        periode["evolution_pct"] = ((k["ca_total_ttc"] - ca_prec) / ca_prec * 100) if ca_prec else None
        periode["libelle_comparaison"] = ("vs les 12 mois précédents" if periode["code"] == "12m"
                                          else "vs la même période l'an dernier")
    else:
        periode["evolution_pct"] = k["yoy_growth"]
        periode["libelle_comparaison"] = "sur 12 mois glissants"
    k["periode_reference"] = periode

    yrs = [int(r[0]) for r in con.execute(
        f"SELECT DISTINCT year FROM sales WHERE {WH} AND year IS NOT NULL ORDER BY year DESC").fetchall()]
    mois_lbl = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    if yrs:
        cy = yrs[0]
        py = yrs[1] if len(yrs) > 1 else None
        prev_expr = f"sum(ttc) FILTER (WHERE year = {py})" if py is not None else "NULL"
        rows = con.execute(f"""
            SELECT month(date) m, sum(ttc) FILTER (WHERE year = {cy}) cur, {prev_expr} prev
            FROM sales WHERE {WH} GROUP BY 1 ORDER BY 1
        """).fetchall()
        k["yoy_comparison"] = {
            "current_year": cy, "previous_year": py,
            "data": [{
                "month": mois_lbl[int(r[0]) - 1],
                "courante": (float(r[1]) if r[1] is not None else None),
                "precedente": (float(r[2]) if r[2] is not None else None),
            } for r in rows if r[0]],
        }
        ca_cur = sum((d["courante"] or 0) for d in k["yoy_comparison"]["data"])
        ca_prev = sum((d["precedente"] or 0) for d in k["yoy_comparison"]["data"])
        k["yoy_comparison"]["delta_pct"] = ((ca_cur - ca_prev) / ca_prev * 100) if ca_prev else None
    else:
        k["yoy_comparison"] = {"current_year": None, "previous_year": None, "data": [], "delta_pct": None}

    seas = con.execute(f"""
        SELECT month(date) m, sum(ttc) total, count(DISTINCT year) ny
        FROM sales WHERE {WH} GROUP BY 1 ORDER BY 1
    """).fetchall()
    mois = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    k["seasonality"] = [{"month": mois[int(s[0]) - 1], "revenue": float((s[1] or 0) / (s[2] or 1))} for s in seas if s[0]]

    drow = con.execute(f"""
        SELECT
          count(*) FILTER (WHERE payment_delay_days > 90 AND NOT est_avoir)  c90,
          count(*) FILTER (WHERE payment_delay_days > 60 AND NOT est_avoir)  c60,
          count(*) FILTER (WHERE payment_delay_days > 30 AND NOT est_avoir)  c30,
          count(*) FILTER (WHERE payment_delay_days IS NOT NULL
                             AND NOT est_avoir)                              tot,
          sum(ttc) FILTER (WHERE payment_delay_days > 60 AND NOT est_avoir)  montant_risque,
          sum(ttc) FILTER (WHERE payment_delay_days > 90 AND NOT est_avoir)  montant_critique
        FROM sales WHERE {W}
    """).fetchone()
    # `payment_delay_days` vaut `datediff(date_facture, echeance)` : c'est le délai
    # ACCORDÉ, inscrit sur la facture à l'émission. Ce n'est PAS un retard de
    # paiement — l'ERP n'enregistre aucune date de règlement. Les noms disaient
    # « retards » et le copilote en déduisait « réglé avec retard », ce qui est faux.
    c90, c60, c30, tot_delay, mt_risque, mt_crit = drow
    k["factures_delai_sup_90j"] = int(c90 or 0)
    k["factures_delai_sup_60j"] = int(c60 or 0)
    k["factures_delai_sup_30j"] = int(c30 or 0)
    k["part_factures_delai_sup_60j_pct"] = (
        float((c60 or 0) / tot_delay * 100) if tot_delay else 0)
    k["montant_delai_sup_60j_ttc"] = float(mt_risque or 0)
    k["montant_delai_sup_90j_ttc"] = float(mt_crit or 0)

    rec = con.execute(f"""
        WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
        SELECT sum(ttc) FILTER (WHERE payment_delay_days > 60) expo,
               sum(ttc) FILTER (WHERE payment_delay_days > 90) crit,
               count(*) FILTER (WHERE payment_delay_days > 60) cnt,
               strftime((SELECT md FROM ref), '%Y-%m') ref_mois
        FROM sales
        WHERE {W} AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
    """).fetchone()
    k["exposition_recente_dt"] = float(rec[0] or 0)
    k["exposition_recente_critique_dt"] = float(rec[1] or 0)
    k["exposition_recente_count"] = int(rec[2] or 0)
    k["exposition_recente_periode"] = f"échéances des 6 mois jusqu'à {rec[3]}" if rec[3] else "6 derniers mois"

    k["clients_relance"] = [{
        "client": r[0], "nom": r[1] or r[0], "montant_risque": float(r[2] or 0), "factures": int(r[3] or 0),
    } for r in con.execute(f"""
        WITH ref AS (SELECT max(echeance) md FROM sales WHERE {W})
        SELECT client, any_value(client_name) nom,
               sum(ttc) FILTER (WHERE payment_delay_days > 60) m,
               count(*) FILTER (WHERE payment_delay_days > 60) n
        FROM sales
        WHERE {W} AND client_name IS NOT NULL
          AND echeance >= (SELECT md FROM ref) - INTERVAL 6 MONTH
        GROUP BY client HAVING m > 0 ORDER BY m DESC NULLS LAST LIMIT 10
    """).fetchall()]

    aging = con.execute(f"""
        SELECT
          sum(ttc) FILTER (WHERE payment_delay_days <= 0)                         AS comptant,
          sum(ttc) FILTER (WHERE payment_delay_days > 0  AND payment_delay_days <= 30) AS j30,
          sum(ttc) FILTER (WHERE payment_delay_days > 30 AND payment_delay_days <= 60) AS j60,
          sum(ttc) FILTER (WHERE payment_delay_days > 60 AND payment_delay_days <= 90) AS j90,
          sum(ttc) FILTER (WHERE payment_delay_days > 90)                          AS j90p
        FROM sales WHERE {W} AND NOT est_avoir
    """).fetchone()
    labels = ["Comptant", "0-30 j", "31-60 j", "61-90 j", "90 j +"]
    k["echelonnement_delais_accordes"] = [{"bucket": labels[i], "montant": float(aging[i] or 0)} for i in range(5)]

    top = con.execute(f"""
        SELECT client, any_value(client_name) nom, sum(ttc) revenue,
               count(*) FILTER (WHERE NOT est_avoir)                  invoices,
               count(*) FILTER (WHERE est_avoir)                      avoirs,
               sum(ttc) FILTER (WHERE payment_delay_days > 30
                                  AND NOT est_avoir)                  risque
        FROM sales WHERE {W} GROUP BY client ORDER BY revenue DESC NULLS LAST LIMIT 10
    """).fetchall()
    g = k["ca_total_ttc"] or 1
    k["top_clients"] = [{
        "client": t[0], "nom": t[1] or t[0], "revenue": float(t[2] or 0), "invoices": int(t[3] or 0),
        "avoirs": int(t[4] or 0),
        "share": float((t[2] or 0) / g * 100), "rank": i + 1,
        "risque": float(t[5] or 0),
    } for i, t in enumerate(top)]
    k["top_clients_revenue_share"] = float(sum(c["revenue"] for c in k["top_clients"][:5]) / g * 100)

    fideles = con.execute(f"""
        SELECT client, any_value(client_name) nom, sum(ttc) revenue,
               count(*) FILTER (WHERE NOT est_avoir) invoices,
               count(DISTINCT strftime(date, '%Y-%m')) FILTER (WHERE NOT est_avoir) mois_actifs,
               strftime(min(date) FILTER (WHERE NOT est_avoir), '%Y-%m') premier,
               strftime(max(date) FILTER (WHERE NOT est_avoir), '%Y-%m') dernier
        FROM sales WHERE {W} AND client_name IS NOT NULL AND date IS NOT NULL
          AND client_name NOT ILIKE '%passager%' AND client_name NOT ILIKE '%comptant%'
          AND client_name NOT ILIKE '%divers%' AND client_name NOT ILIKE '%espèce%'
        GROUP BY client
        HAVING count(*) >= 2
        ORDER BY mois_actifs DESC, invoices DESC, revenue DESC NULLS LAST
        LIMIT 8
    """).fetchall()
    k["clients_fideles"] = [{
        "client": r[0], "nom": r[1] or r[0], "revenue": float(r[2] or 0),
        "invoices": int(r[3] or 0), "mois_actifs": int(r[4] or 0),
        "premier": r[5], "dernier": r[6], "share": float((r[2] or 0) / g * 100),
    } for r in fideles]

    decroche = con.execute(f"""
        WITH ref AS (SELECT max(date) md FROM sales WHERE {W}),
        pc AS (
          SELECT client, any_value(client_name) nom, max(date) last_date,
                 count(DISTINCT strftime(date, '%Y-%m')) mois_actifs,
                 sum(ttc) FILTER (WHERE date >= (SELECT md FROM ref) - INTERVAL 90 DAY) ca_recent,
                 sum(ttc) FILTER (WHERE date >= (SELECT md FROM ref) - INTERVAL 180 DAY
                                   AND date <  (SELECT md FROM ref) - INTERVAL 90 DAY) ca_prev
          FROM sales WHERE {W} AND client_name IS NOT NULL AND date IS NOT NULL
            AND client_name NOT ILIKE '%passager%' AND client_name NOT ILIKE '%comptant%'
            AND client_name NOT ILIKE '%divers%'
          GROUP BY client
        )
        SELECT nom, strftime(last_date, '%Y-%m') dernier, mois_actifs,
               coalesce(ca_recent, 0) cr, coalesce(ca_prev, 0) cp,
               datediff('day', last_date, (SELECT md FROM ref)) jours_inactif,
               client
        FROM pc
        WHERE mois_actifs >= 6 AND coalesce(ca_prev, 0) > 0
          AND coalesce(ca_recent, 0) < ca_prev * 0.4
        ORDER BY (ca_prev - coalesce(ca_recent, 0)) DESC NULLS LAST
        LIMIT 8
    """).fetchall()
    k["clients_decrochent"] = [{
        "nom": d[0], "dernier": d[1], "mois_actifs": int(d[2] or 0),
        "ca_recent": float(d[3] or 0), "ca_prev": float(d[4] or 0),
        "jours_inactif": int(d[5] or 0),
        "code": d[6],
        "chute_pct": float((1 - (d[3] or 0) / d[4]) * 100) if d[4] else 0.0,
    } for d in decroche]

    # Les modèles suivent la règle de portée des filtres (ml_engine.portee) :
    # restreints aux clients filtrés, ou masqués quand le filtre n'a pas de
    # sens pour une prévision (période passée, critère de facture).
    from ml_engine import portee as _po
    # Les dates de la période de référence ne sont pas un choix de l'utilisateur :
    # la portée se juge sur les filtres reçus, pas sur ceux complétés ici.
    p = _po.portee(historique)
    cl = p["clients"]
    k["portee_modeles"] = {"mode": p["mode"], "motif": p["motif"]}
    if p["mode"] == _po.MASQUE:
        k["churn_anticipe"] = _po.masque(p)
        k["conversion_devis"] = _po.masque(p)
        k["marge_client"] = _po.masque(p)
    else:
        k["churn_anticipe"] = _po.annoter(_charger_churn_si_servi(clients=cl), p)
        try:
            from ml_engine.analytics.conversion_devis import predire as _pd
            k["conversion_devis"] = _po.annoter(_pd(clients=cl), p)
        except Exception as e:
            k["conversion_devis"] = {"servi": False, "motif": f"indisponible ({type(e).__name__})"}
        try:
            from ml_engine.analytics.marge_client import predire as _pm
            k["marge_client"] = _po.annoter(_pm(clients=cl), p)
        except Exception as e:
            k["marge_client"] = {"servi": False, "motif": f"indisponible ({type(e).__name__})"}

    k["segmentation"] = _po.pour_analyse_globale(p) or _charger_segmentation_si_servie()

    k["stock_flux_reel"] = _charger_flux_reels(con)

    k["reappro"] = _po.pour_analyse_globale(p) or _charger_reappro_si_servi()

    conc = con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client),
        ranked AS (
          SELECT r, sum(r) OVER () tot, sum(r) OVER (ORDER BY r DESC) cum,
                 row_number() OVER (ORDER BY r DESC) rn, count(*) OVER () n
          FROM s WHERE r > 0
        )
        SELECT min(rn) FILTER (WHERE cum >= 0.8 * tot), max(n) FROM ranked
    """).fetchone()
    k["clients_pour_80pct"] = int(conc[0] or 0)
    k["nb_clients_ca"] = int(conc[1] or 0)

    hhi = con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client),
             pos AS (SELECT r FROM s WHERE r > 0),
             tot AS (SELECT sum(r) t FROM pos)
        SELECT sum(power(r/(SELECT t FROM tot)*100, 2)) FROM pos
        WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_clients"] = float(hhi or 0)

    pareto = con.execute(f"""
        WITH s AS (
          SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client
          HAVING sum(ttc) > 0      -- voir HHI : un solde net négatif n'est pas du CA
        ), ranked AS (
          SELECT r, row_number() OVER (ORDER BY r DESC) rn, count(*) OVER () n,
                 sum(r) OVER () tot, sum(r) OVER (ORDER BY r DESC) cum
          FROM s
        )
        SELECT round(rn*100.0/n) pct_clients, max(cum/tot*100) pct_ca
        FROM ranked GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["client_pareto"] = [{"pct_clients": float(p[0]), "pct_ca": float(p[1] or 0)} for p in pareto if p[0] % 5 == 0]

    mix = con.execute(f"""
        SELECT coalesce(NULLIF(mode_regl, ''), 'Non renseigné') AS mode_label,
               sum(ttc) montant, count(*) nb
        FROM sales WHERE {W} GROUP BY 1 ORDER BY montant DESC NULLS LAST LIMIT 8
    """).fetchall()
    k["payment_mix"] = [{"mode": m[0], "montant": float(m[1] or 0), "count": int(m[2] or 0)} for m in mix]

    cash = con.execute(f"""
        SELECT strftime(echeance, '%Y-%m') m, sum(ttc) montant
        FROM sales WHERE {W} AND echeance IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["cash_forecast"] = [{"period": c[0], "montant": float(c[1] or 0)} for c in cash][-18:]

    dist = con.execute(f"""
        SELECT CASE
                 WHEN ttc < 500   THEN '< 500'
                 WHEN ttc < 1000  THEN '0.5-1K'
                 WHEN ttc < 5000  THEN '1-5K'
                 WHEN ttc < 10000 THEN '5-10K'
                 WHEN ttc < 50000 THEN '10-50K'
                 ELSE '50K +' END tranche,
               count(*) nb
        FROM sales WHERE {W}
        GROUP BY 1
    """).fetchall()
    order = {'< 500': 0, '0.5-1K': 1, '1-5K': 2, '5-10K': 3, '10-50K': 4, '50K +': 5}
    k["amount_distribution"] = sorted(
        [{"tranche": d[0], "count": int(d[1] or 0)} for d in dist],
        key=lambda x: order.get(x["tranche"], 9))

    purch_where = "1=1"
    if filters.get("selected_years"):
        purch_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    # Série mensuelle (graphique d'évolution) : tout l'historique, comme les ventes.
    purch_hist = purch_where + _clause_dates(historique, "date")
    purch_where += _clause_dates(filters, "date")
    prow = con.execute(f"""
        SELECT sum(ttc) ttc,
               count(*) FILTER (WHERE NOT est_avoir)                nb,
               count(*) FILTER (WHERE est_avoir)                    nb_av,
               count(DISTINCT fournisseur)                          nf,
               avg(payment_delay_days) FILTER (WHERE NOT est_avoir) dpo
        FROM purchases WHERE {purch_where}
    """).fetchone()
    k["achats_total_ttc"] = float(prow[0] or 0)
    k["nb_factures_achat"] = int(prow[1] or 0)
    k["nb_avoirs_achat"] = int(prow[2] or 0)
    k["nb_fournisseurs"] = int(prow[3] or 0)
    k["dpo_jours"] = float(prow[4] or 0)

    k["delais"] = _delais(con, W, purch_where, periode)

    k["top_fournisseurs"] = [{
        "fournisseur": (r[0] or r[1] or "—")[:32], "montant": float(r[2] or 0),
        "share": float((r[2] or 0) / (k["achats_total_ttc"] or 1) * 100), "rank": i + 1,
    } for i, r in enumerate(con.execute(f"""
        SELECT fournisseur, fournisseur_code, sum(ttc) m
        FROM purchases WHERE {purch_where} GROUP BY 1,2 ORDER BY m DESC NULLS LAST LIMIT 8
    """).fetchall())]
    hhi_f = con.execute(f"""
        WITH s AS (SELECT fournisseur, sum(ttc) r FROM purchases WHERE {purch_where} GROUP BY 1),
             pos AS (SELECT r FROM s WHERE r > 0),
             tot AS (SELECT sum(r) t FROM pos)
        SELECT sum(power(r/(SELECT t FROM tot)*100,2)) FROM pos WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_fournisseurs"] = float(hhi_f or 0)

    pm = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) achats
        FROM purchases WHERE {purch_hist} GROUP BY 1 ORDER BY 1
    """).fetchall()
    pm_map = {p[0]: float(p[1] or 0) for p in pm}
    k["sales_vs_purchases"] = [
        {"period": m["period"], "ventes": m["revenue"], "achats": pm_map.get(m["period"], 0)}
        for m in k["monthly_sales"]
    ]

    def _where_marge(f: Dict[str, Any]) -> List[str]:
        w = ["1=1"]
        if f.get("selected_years"):
            w.append("year IN (" + ",".join(str(int(y)) for y in f["selected_years"]) + ")")
        if f.get("selected_clients"):
            vals = ",".join("'" + str(c).replace("'", "''") + "'"
                            for c in f["selected_clients"])
            w.append(f"client IN ({vals})")
        if f.get("date_start"):
            w.append(f"period >= '{str(f['date_start'])[:7]}'")
        if f.get("date_end"):
            w.append(f"period <= '{str(f['date_end'])[:7]}'")
        return w

    marge_row = None
    mw_hist = _where_marge(historique)
    try:
        mw = _where_marge(filters)
        marge_row = con.execute(
            f"SELECT sum(ca_ligne), sum(cout_revient), sum(marge), sum(n_lignes) "
            f"FROM client_margin WHERE {' AND '.join(mw)}").fetchone()
    except Exception:
        marge_row = None

    if marge_row and marge_row[0] and float(marge_row[0]) > 0:
        ca_lignes = float(marge_row[0])
        marge = float(marge_row[2] or 0)
        k["marge_brute"] = round(marge, 0)
        k["taux_marge"] = float(marge / ca_lignes * 100)
        k["marge_quality_score"] = float(max(0, min(100, k["taux_marge"])))
        k["marge_ca_reference_dt"] = round(ca_lignes, 0)
        k["marge_cout_revient_dt"] = round(float(marge_row[1] or 0), 0)
        k["marge_source"] = "cout_revient_erp"
        k["marge_note"] = (
            "Marge réelle : chiffre d'affaires des lignes de vente moins le coût de "
            "revient porté sur chaque ligne de facture, attribuable par client. "
            "Les lignes dont le coût "
            "dépasse 5× le prix de vente (erreurs de saisie) sont écartées.")
        try:
            q = con.execute("SELECT lignes_exclues, lignes_facturees "
                            "FROM margin_quality").fetchone()
            if q and q[1]:
                k["marge_lignes_exclues"] = int(q[0] or 0)
                k["marge_lignes_exclues_pct"] = round(float(q[0] or 0) / float(q[1]) * 100, 2)
        except Exception:
            pass
    else:
        k["marge_brute"] = None
        k["taux_marge"] = None
        k["marge_quality_score"] = None
        k["marge_source"] = "indisponible"
        k["marge_note"] = ("Marge non calculable sur ce périmètre : aucune ligne de vente "
                           "avec coût de revient exploitable.")

    try:
        mm = con.execute(
            f"SELECT period, sum(marge) FROM client_margin "
            f"WHERE {' AND '.join(mw_hist)} GROUP BY period ORDER BY period").fetchall()
        mm_map = {r[0]: float(r[1] or 0) for r in mm}
        k["monthly_margin"] = [{"period": m["period"], "marge": mm_map.get(m["period"], 0.0)}
                               for m in k["monthly_sales"]]
    except Exception:
        k["monthly_margin"] = []

    if k.get("marge_brute") is not None and k.get("marge_ca_reference_dt"):
        k["waterfall"] = [
            {"step": "CA (lignes)", "value": float(k["marge_ca_reference_dt"]), "kind": "start"},
            {"step": "Coût de revient", "value": -float(k["marge_cout_revient_dt"]), "kind": "neg"},
            {"step": "Marge brute", "value": float(k["marge_brute"]), "kind": "total"},
        ]
    else:
        k["waterfall"] = []

    dwhere = "1=1"
    if filters.get("selected_years"):
        dwhere = "year(date) IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    dwhere += _clause_dates(filters, "date")
    drow = con.execute(f"SELECT count(*), sum(ttc), count(DISTINCT client) FROM devis WHERE {dwhere}").fetchone()
    k["nb_devis"] = int(drow[0] or 0)
    k["montant_devis_total"] = float(drow[1] or 0)
    nb_clients_devis = int(drow[2] or 0)
    conv = con.execute(f"""
        SELECT count(*) FILTER (WHERE transforme) AS transformes,
               count(*)                            AS total
        FROM devis WHERE {dwhere}
    """).fetchone()
    n_transf, n_devis_tot = int(conv[0] or 0), int(conv[1] or 0)
    converted = n_transf
    k["devis_transformes"] = n_transf
    k["taux_conversion_devis"] = float(n_transf / n_devis_tot * 100) if n_devis_tot else 0.0
    k["taux_conversion_source"] = "etat_piece_erp"
    k["taux_conversion_note"] = (
        "Part des devis effectivement TRANSFORMÉS en facture, d'après le "
        "statut du devis — concordance vérifiée à 89 % sur le couple "
        "montant/client.")
    k["nb_bl"] = int(_scalar(con, "SELECT count(*) FROM bl"))
    k["funnel"] = [
        {"etape": "Devis", "valeur": k["nb_devis"]},
        {"etape": "Clients convertis", "valeur": converted},
        {"etape": "Clients facturés", "valeur": k["nb_clients"]},
    ]

    prod_where = "1=1"
    if filters.get("selected_years"):
        prod_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    # Les marts produit/famille sont annuels : une période au jour près se lit
    # sur les lignes de vente, avec les mêmes règles que les marts.
    source_prod, source_fam = "product_sales", "product_family"
    if filters.get("date_start") or filters.get("date_end"):
        from etl.regles import FAMILLES_HORS_ACTIVITE
        lw = "1=1" + _clause_dates(filters, "date")
        source_prod = (f"(SELECT designation AS produit, year(date) AS year, montant AS ca, qte "
                       f"FROM sales_lines WHERE designation IS NOT NULL AND designation <> '' "
                       f"AND {lw})")
        source_fam = (f"(SELECT famille, year(date) AS year, montant AS ca, qte FROM sales_lines "
                      f"WHERE famille IS NOT NULL AND famille <> '' "
                      f"AND NOT regexp_matches(upper(famille), '{FAMILLES_HORS_ACTIVITE}') AND {lw})")
    prods = con.execute(f"""
        SELECT produit, sum(ca) ca, sum(qte) qte FROM {source_prod}
        WHERE {prod_where} GROUP BY produit ORDER BY ca DESC NULLS LAST LIMIT 10
    """).fetchall()
    k["top_produits"] = [{
        "produit": (p[0] or "—").strip()[:38], "ca": float(p[1] or 0), "qte": float(p[2] or 0),
    } for p in prods]
    k["nb_produits"] = int(_scalar(con, f"SELECT count(DISTINCT produit) FROM {source_prod} WHERE {prod_where}"))

    fam = con.execute(f"""
        SELECT famille, sum(ca) ca FROM {source_fam}
        WHERE {prod_where} GROUP BY famille ORDER BY ca DESC NULLS LAST LIMIT 6
    """).fetchall()
    k["top_familles"] = [{"famille": (f[0] or "—").strip()[:28], "ca": float(f[1] or 0)} for f in fam]

    k["clients_a_risque"] = [{
        "client": r[0], "nom": r[1] or r[0], "montant_risque": float(r[2] or 0), "factures": int(r[3] or 0),
    } for r in con.execute(f"""
        SELECT client, any_value(client_name) nom,
               sum(ttc) FILTER (WHERE payment_delay_days > 60) m,
               count(*) FILTER (WHERE payment_delay_days > 60) n
        FROM sales WHERE {W} GROUP BY client HAVING m > 0 ORDER BY m DESC LIMIT 8
    """).fetchall()]

    name_map = {r[0]: (r[1] or r[0]) for r in con.execute("SELECT client_code, client_name FROM dim_client").fetchall()}

    risk_map = _load_client_risk()
    if risk_map:
        for c in k["top_clients"]:
            c["risk_score"] = risk_map.get(c["client"], {}).get("score")
        for c in k["clients_a_risque"]:
            c["risk_score"] = risk_map.get(c["client"], {}).get("score")
        scope_clients = [r[0] for r in con.execute(f"SELECT DISTINCT client FROM sales WHERE {W}").fetchall()]
        enriched = []
        expo_ponderee = 0.0
        nb_high = 0
        for cl in scope_clients:
            v = risk_map.get(cl)
            if not v:
                continue
            score = float(v.get("score", 0))
            expo = float(v.get("exposure", 0))
            priority = score / 100.0 * expo
            expo_ponderee += priority
            if score > 70:
                nb_high += 1
            enriched.append({
                "client": cl, "nom": name_map.get(cl, cl), "score": score, "exposure": expo,
                "avg_delay": float(v.get("avg_delay", 0)), "priority": priority,
                "raisons": _raisons_credit(v),
            })
        k["nb_clients_risque_predit"] = nb_high
        k["exposition_risque_ponderee"] = expo_ponderee
        k["risk_ranking"] = sorted(enriched, key=lambda x: -x["priority"])[:10]
        k["risk_model_active"] = True
    else:
        k["nb_clients_risque_predit"] = None
        k["exposition_risque_ponderee"] = None
        k["risk_ranking"] = []
        k["risk_model_active"] = False

    neg = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc < 0"))
    zero = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc = 0"))
    if k["factures_delai_sup_90j"]:
        k["anomalies_details"].append(f"{k['factures_delai_sup_90j']} facture(s) avec délai accordé > 90 jours.")
    warn = k["factures_delai_sup_30j"] - k["factures_delai_sup_90j"]
    if warn > 0:
        k["anomalies_details"].append(f"{warn} facture(s) avec délai accordé de 30 à 90 jours.")
    if neg:
        k["anomalies_details"].append(f"{neg} facture(s) avec montant négatif (avoirs).")
    if zero:
        k["anomalies_details"].append(f"{zero} facture(s) avec montant nul.")
    if k["hhi_clients"] > 2500:
        k["anomalies_details"].append(f"Forte concentration client (HHI={k['hhi_clients']:.0f} > 2500).")
    k["anomalies_detectees"] = int(k["factures_delai_sup_90j"] + neg + zero)
    if not k["anomalies_details"]:
        k["anomalies_details"] = ["Aucune anomalie majeure détectée."]

    k["cash_conversion_cycle"] = float(k["dso_jours"] - k["dpo_jours"])

    k["import_ocr"] = {"n_factures": 0, "total_ttc_dt": 0.0, "factures": []}
    try:
        clients_filtre = (filters or {}).get("selected_clients") or []
        colonnes = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'factures_importees'").fetchall()}
        conds = ["coalesce(sens, 'vente') = 'vente'"] if "sens" in colonnes else []
        if clients_filtre:
            conds.append("(client_code IN ? OR client_name IN ?)")
        rows = con.execute(f"""
            SELECT numero, client_code, client_name, date, ht, tva, ttc,
                   net_a_payer, confiance_ocr, fichier_source
            FROM factures_importees
            {("WHERE " + " AND ".join(conds)) if conds else ""}
            ORDER BY date DESC NULLS LAST, numero ASC
            LIMIT 50
        """, ([clients_filtre, clients_filtre] if clients_filtre else [])).fetchall()
        k["import_ocr"] = {
            "n_factures": len(rows),
            "total_ttc_dt": round(sum(float(r[6] or 0) for r in rows), 3),
            "factures": [{
                "numero": r[0], "client_code": r[1], "client_name": r[2],
                "date": r[3].isoformat() if r[3] else None,
                "ht": r[4], "tva": r[5], "ttc": r[6], "net_a_payer": r[7],
                "confiance_ocr": r[8], "fichier": r[9],
            } for r in rows],
            "note": ("Factures scannées et validées à l'import. Comptabilisées "
                     "à part des indicateurs de facturation, dont elles ne modifient aucun total."),
        }
    except Exception:
        pass

    try:
        from ml_engine.ocr.echeancier import echeancier as _echeancier
        e = _echeancier()
        k["echeancier_ocr"] = {c: e[c] for c in (
            "a_payer_dt", "a_encaisser_dt", "a_payer_en_retard_dt", "a_encaisser_en_retard_dt",
            "n_factures", "n_echeances_deduites", "mois", "note")}
    except Exception:
        k["echeancier_ocr"] = {"n_factures": 0, "mois": []}

    try:
        from ml_engine.analytics.data_quality import controler_integrite
        k["integrite"] = controler_integrite(k)
    except Exception as exc:
        k["integrite"] = {"statut": "inconnu", "erreurs": [], "alertes": [],
                          "infos": [], "resume": f"contrôle indisponible : {exc}"}

    con.close()
    return k


def con_row_ht(con, where: str, period: str) -> float:
    r = con.execute(f"SELECT sum(ht) FROM sales WHERE {where} AND strftime(date,'%Y-%m') = '{period}'").fetchone()
    return float(r[0] or 0) if r else 0.0


if __name__ == "__main__":
    print("Calcul des KPIs (sans filtre)…")
    kpis = compute_dashboard({})
    preview = {key: v for key, v in kpis.items() if not isinstance(v, list)}
    print(json.dumps(preview, indent=2, ensure_ascii=False, default=str))
    print("\nSéries:", {key: len(v) for key, v in kpis.items() if isinstance(v, list)})
