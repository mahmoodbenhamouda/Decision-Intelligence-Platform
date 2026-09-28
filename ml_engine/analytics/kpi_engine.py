"""
ml_engine/analytics/kpi_engine.py
=================================
Moteur de KPIs financiers haute performance basé sur **DuckDB**.

Pourquoi DuckDB ?
-----------------
Les datasets bruts pèsent ~2,5 Go (certains CSV de mouvements dépassent 500 Mo).
Les charger entièrement en mémoire avec pandas est impossible. DuckDB lit les CSV
directement sur disque, en colonnes, sans tout charger en RAM.

Architecture
------------
1. L'entrepôt (`output/analytics_store.duckdb`) est construit par l'ETL, un
   modèle en étoile (voir `etl/` et docs/DATA_WAREHOUSE.md). Ce module ne
   l'écrit jamais : `_connect()` demande seulement à l'ETL de le reconstruire
   s'il est périmé, puis l'ouvre en lecture.
2. `compute_dashboard(filters)` : interroge l'entrepôt (quelques
   millisecondes) en appliquant les filtres en SQL, et renvoie un dictionnaire
   complet de KPIs + séries prêtes pour les graphes du dashboard.

Toutes les datasets sont exploitées (ventes, achats, lignes produits, devis,
fournisseurs, paiements), contrairement à l'ancienne liste blanche qui en
excluait la majorité.
"""

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

#: Chemin de l'entrepôt lu par tout le projet (redirigé par les tests).
STORE_PATH = ENTREPOT


def _connect(data_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Connexion en LECTURE à l'entrepôt, reconstruit d'abord s'il est périmé.

    L'entrepôt est construit par l'ETL (`etl/`, `python -m etl.construire`) ;
    ce module ne fait que le lire."""
    from etl.construire import assurer_a_jour
    assurer_a_jour(STORE_PATH, data_dir or _DEFAULT_DATA_DIR)
    return duckdb.connect(str(STORE_PATH), read_only=True)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCTION DES FILTRES SQL
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONS DE FILTRES (pour l'UI)
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# CALCUL COMPLET DES KPIs
# ─────────────────────────────────────────────────────────────────────────────

def _scalar(con, sql: str, default=0):
    r = con.execute(sql).fetchone()
    return r[0] if r and r[0] is not None else default


def _raisons_credit(v: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pourquoi ce client apparaît dans les priorités de recouvrement.

    La règle servie repose sur trois observations : le délai moyen réellement
    constaté, l'encours exposé, et le nombre de factures qui fonde l'habitude.
    Les seuils sont ceux du module de crédit (60 et 90 jours), publiés dans
    `reports/credit_risk_metrics.json`.
    """
    try:
        from ml_engine.explication import raisons_seuils
    except Exception:
        return []
    valeurs = {"avg_delay": float(v.get("avg_delay") or 0),
               "exposure": float(v.get("exposure") or 0),
               "n": float(v.get("n") or 0)}
    return raisons_seuils(valeurs, [
        {"variable": "avg_delay", "seuil": 90, "sens": "sup", "poids": 3.0,
         "phrase": f"règle en moyenne à {valeurs['avg_delay']:.0f} jours, au-delà de 90"},
        {"variable": "avg_delay", "seuil": 60, "sens": "sup", "poids": 2.0,
         "phrase": f"règle en moyenne à {valeurs['avg_delay']:.0f} jours, au-delà de 60"},
        {"variable": "exposure", "seuil": 50_000, "sens": "sup", "poids": 2.0},
        {"variable": "n", "seuil": 20, "sens": "sup", "poids": 1.0,
         "phrase": f"habitude établie sur {valeurs['n']:.0f} factures"},
    ], n=3)


def _load_client_risk() -> Dict[str, Any]:
    """Scores de risque crédit par client (produits par credit_risk_model.train()).
    Vide si le modèle n'a pas encore été entraîné — l'intégration est optionnelle."""
    path = Path(os.environ.get("CLIENT_RISK_PATH", STORE_PATH.parent / "client_risk.json"))
    if path.exists():
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _charger_churn_si_servi(limite: int = 10) -> Dict[str, Any]:
    """Clients à risque de décrochage, classés par ENJEU FINANCIER.

    Le classement se fait sur `enjeu = probabilité × CA 12 mois`, et non sur la
    seule probabilité. La raison est opérationnelle : une probabilité de 0,9 sur
    un client à 2 000 DT ne mérite pas l'attention qu'exige 0,6 sur un client à
    2 M DT. Un score de risque sans montant ne permet pas de hiérarchiser l'action.

    Renvoie un dictionnaire vide si le registre ne déclare pas le modèle servi —
    ainsi un modèle refusé n'atteint jamais le tableau de bord.
    """
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

    # Le modèle indexe ses scores par CODE client ; le briefing et le tableau de
    # bord doivent afficher des NOMS. Sans cette jointure, le directeur lit
    # « CE000229 » et doit ouvrir l'ERP pour savoir de quel hôpital il s'agit.
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
        pass    # sans l'entrepôt, on affichera le code — jamais rien

    classes = sorted(
        ({"code": code, "nom": noms.get(code, code), **v}
         for code, v in scores.items()),
        key=lambda c: -float(c.get("enjeu_dt") or 0))[:limite]

    # Le modèle enregistre des contributions BRUTES (en unités de logit) : elles
    # ne se lisent pas telles quelles, et un écran qui afficherait « 683 % »
    # décrédibiliserait l'explication entière. On les convertit ici en PARTS de
    # l'influence retenue, qui totalisent 100 %.
    for c in classes:
        raisons = c.get("raisons") or []
        total = sum(abs(float(r.get("poids") or 0)) for r in raisons)
        if total > 0:
            c["raisons"] = [{**r, "poids": round(abs(float(r.get("poids") or 0)) / total, 3)}
                            for r in raisons]

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
    """Position de stock reconstruite des flux réels, si la table existe.

    La table `stock_flux_reel` est matérialisée par
    `python -m ml_engine.stock.flux_reels` : la lecture du CSV d'achats est trop
    lourde pour être refaite à chaque appel du tableau de bord.

    Renvoie `disponible: False` plutôt que de lever : le module est optionnel, et
    son absence ne doit pas empêcher le reste du tableau de bord de s'afficher.
    """
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

    # Ruptures détectées sur les flux réels : produits encore vendus dont
    # l'approvisionnement s'est interrompu. Aucun niveau de stock n'est requis.
    try:
        from ml_engine.stock.flux_reels import (detecter_obsolescence,
                                                detecter_ruptures)
        ruptures = detecter_ruptures(con)
        # Obsolescence détectée par ROTATION, sans date d'expiration : un
        # consommable dont le stock dépasse deux ans de consommation périmera,
        # quelle que soit sa date exacte.
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
        # Compté séparément : `n_obsoletes` inclut la rotation lente, dont la
        # perte n'est que probable. Associer le nombre total au montant quasi
        # certain ferait dire au chiffre autre chose que ce qu'il mesure.
        "n_obsoletes_certains": sum(
            1 for o in obsoletes if o["gravite"] == "perte_quasi_certaine"),
        "n_references_accumulees": int(n_pos or 0),
        "valeur_immobilisee_dt": round(float(valeur or 0), 0),
        # Au-delà de deux ans de consommation, une référence n'est plus du stock
        # de roulement : c'est du capital gelé.
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
    """Devis à relancer en priorité, si le registre l'autorise.

    Le registre est interrogé par le module lui-même : ce chargeur ne décide de
    rien. Toute erreur se résout en `servi: False` — une absence vaut mieux qu'un
    chiffre dont on ne sait pas s'il est autorisé.
    """
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
    """Besoin de réapprovisionnement à 3 mois, si le registre l'autorise.

    Le module est interrogé par le registre et jamais directement : un modèle
    refusé ne doit pas pouvoir alimenter le tableau de bord par une importation
    oubliée. Toute erreur se résout en `servi: False` — une absence est toujours
    préférable à un chiffre dont on ne sait pas s'il est autorisé.
    """
    try:
        from ml_engine.stock.reappro_model import predire
        return predire()
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def _charger_segmentation_si_servie() -> Dict[str, Any]:
    """Typologie de clientèle, avec son croisement au décrochage.

    Le croisement est la partie qui justifie le module : la segmentation dit qui
    sont les clients, le modèle de décrochage lesquels partent. Ensemble ils
    répondent à « quel TYPE de clientèle perdons-nous ? », question qu'aucun des
    deux ne traite seul et qui oriente une politique plutôt qu'une liste d'appels.
    """
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

    # Le croisement est indexé par identifiant de segment ; on le rattache au
    # nom pour que l'interface n'ait pas à refaire la jointure.
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


# Les trois fonctions suivantes ont été retirées avec la veille externe :
# - enrich_opportunities() : enrichissait les appels d'offres avec les clients ERP
# - fx_margin_sensitivity() : chiffrait l'exposition au change EUR/TND
# - macro_market_context() : recopiait l'exposition au budget santé public
# Motif : elles dépendaient de sources hors ERP (TUNEPS, taux de change, macro),
# dont la qualité ne pouvait être auditée (cf. reports/METRICS_REPORT.md, §2).


def _part_publique_carnet(data_dir: Path | None, origine: int, cible: int) -> float | None:
    """Part (en %) des établissements de santé publics dans les créances DÉJÀ
    inscrites au carnet pour le mois `cible` : factures émises au plus tard le
    mois `origine`, échéance au mois `cible`.

    Même périmètre et mêmes exclusions que `carnet_echeances.charger_factures`
    (portefeuille entier, avoirs exclus), et même index de mois (`année×12 +
    mois−1`) : numérateur et dénominateur portent sur les mêmes factures, le
    résultat est donc toujours compris entre 0 et 100. `None` si rien n'est
    inscrit.
    """
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
        # La phrase est un complément : son absence ne doit pas emporter la carte.
        _log.warning("radar : part publique du carnet indisponible (%s: %s)",
                     type(e).__name__, e)
        return None
    if not tot:
        return None
    return float(pub or 0) / float(tot) * 100


def finance_radar(mi: Dict[str, Any] | None, filters: Dict[str, Any] | None = None,
                  data_dir: Path | None = None) -> List[Dict[str, Any]]:
    """RADAR FINANCIER — cartes d'action chiffrées sur les données de l'ERP.

    Deux cartes, triées par sévérité puis par montant :

      1. Recouvrement des établissements de santé publics (`recouvrement_public`) :
         leur part de l'EXPOSITION RÉCENTE — factures à délai accordé > 60 j,
         échéances des 6 derniers mois —, calculée comme `exposition_recente_dt`
         et sur le MÊME périmètre filtré. Un établissement est public selon la
         règle unique de `ml_engine/typologie.py`.
      2. Créances exigibles le mois prochain (`echeancier_1m`), si le registre
         sert l'échéancier : lues dans le carnet des factures émises, sur tout
         le portefeuille, avec la part des établissements publics dans ce qui
         est déjà inscrit au carnet.

    `mi` : contexte externe facultatif (`{"macro": {"sante_pct_pib": {...}}}`).
    La veille externe ayant été retirée, les appelants passent `{}` et le
    signal externe se réduit au constat sur les délais des payeurs publics.
    """
    mi = mi or {}
    filters = filters or {}
    cards: List[Dict[str, Any]] = []
    try:
        con = _connect(data_dir)
    except Exception:
        return []

    public = condition_sql_hopital_public("client_name")
    try:
        # Périmètre dynamique : mêmes filtres que le tableau de bord
        base_where = _sales_where(filters)
        try:
            W = base_where + _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
        except Exception:
            W = base_where
        filtre_actif = W.strip() not in ("1=1", "")
        suffixe_perim = " (périmètre filtré)" if filtre_actif else ""

        # ── Carte 1 : recouvrement des établissements de santé publics ───────
        # Même fenêtre que `exposition_recente_dt` : cumuler l'historique (neuf
        # ans, sans aucune date de règlement dans l'ERP) donnerait un montant
        # qui n'est dû par personne aujourd'hui.
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
            # Visible dans le journal : une erreur avalée en silence a déjà
            # masqué cette carte pendant des semaines.
            _log.warning("radar : carte « recouvrement public » indisponible (%s: %s)",
                         type(e).__name__, e)
            pub_risque = pub_crit = expo_totale = 0.0
            pub_nb, ref_mois, top_debiteurs = 0, None, []

        # Contexte externe facultatif = budget santé public (Banque Mondiale),
        # proxy de la capacité de paiement du secteur public.
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
        # Fermée avant la carte 2 : le carnet ouvre sa propre connexion.
        try:
            con.close()
        except Exception:
            pass

    # Les leviers « exposition au change » et « pipeline d'appels d'offres » ont
    # été retirés avec la veille externe : tous deux dépendaient de sources hors
    # ERP — un taux EUR/TND et un scan de marchés publics — dont la qualité ne
    # pouvait pas être auditée comme l'est celle des données de facturation.
    # Le radar ne présente plus que des leviers mesurés sur l'entrepôt.

    # ── Carte 2 : échéancier du mois à venir ─────────────────────────────────
    #
    # Ce levier affichait une projection LSTM à 6 mois. Deux raisons de l'avoir
    # remplacée :
    #
    #   * le LSTM n'a jamais confirmé de gain sur une référence triviale, et rien
    #     dans le code ne l'empêchait d'être servi malgré ce refus ;
    #   * l'horizon de 6 mois est structurellement intenable. 99 % des factures
    #     ont un délai de paiement de 0 à 2 mois : au-delà, les encaissements
    #     proviennent de factures NON ENCORE ÉMISES, qu'aucune méthode ne peut
    #     lire. Annoncer six mois donnait une précision imaginaire.
    #
    # On sert désormais l'échéancier à un mois, mesuré à 1,3 % d'erreur en
    # walk-forward contre 11,9 % pour la meilleure référence triviale.
    try:
        from ml_engine.forecasting.carnet_echeances import charger_factures, prevoir
        from ml_engine.registre import est_deploye

        if est_deploye("echeancier"):
            factures = charger_factures()
            echeances = sorted({e for _, e, _ in factures})
            emissions = sorted({em for em, _, _ in factures})
            origine = max(emissions) - 1        # dernier mois à cible complète
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
                               "exigibles, pas des encaissements garantis — l'ERP "
                               "n'enregistre aucune date de règlement."),
                    "top": [],
                })
    except Exception as e:
        _log.warning("radar : carte « échéancier » indisponible (%s: %s)",
                     type(e).__name__, e)

    order = {"haute": 0, "moyenne": 1, "faible": 2}
    cards.sort(key=lambda c: (order.get(c.get("severite"), 3), -(c.get("montant_dt") or 0)))
    for i, c in enumerate(cards):
        c["priorite"] = i + 1
    return cards


def compute_dashboard(filters: Dict[str, Any] | None = None, data_dir: Path | None = None) -> Dict[str, Any]:
    """Calcule l'ensemble des KPIs et séries graphiques sur le périmètre filtré."""
    filters = filters or {}
    con = _connect(data_dir)
    base_where = _sales_where(filters)
    fid_clause = _apply_fidelity(con, base_where, filters.get("fidelity_filter", "Tous"))
    W = base_where + fid_clause  # clause ventes complète
    is_client_scope = bool(filters.get("selected_clients"))
    # La marge n'est fiable que globale ou filtrée par année (les achats suivent
    # l'année mais pas les filtres client/risque/montant/paiement/fidélité).
    marge_non_attribuable = bool(
        filters.get("selected_clients") or filters.get("payment_modes")
        or (filters.get("risk_level") and filters.get("risk_level") != "Tous")
        or filters.get("min_amount") is not None or filters.get("max_amount") is not None
        or (filters.get("fidelity_filter") and filters.get("fidelity_filter") != "Tous")
    )

    k: Dict[str, Any] = {"monthly_sales": [], "top_clients": [], "anomalies_details": []}

    # ── 1. Chiffre d'affaires ────────────────────────────────────────────────
    # `ttc` porte désormais le signe comptable : la somme est donc un CA NET,
    # avoirs déduits. En revanche un avoir n'est pas une vente — le compter
    # comme une facture gonflait le volume et faussait le panier moyen, qui
    # divisait un CA net par un nombre de pièces brut.
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
    k["montant_avoirs_ttc"] = float(mt_avoirs or 0)
    k["taux_avoirs_pct"] = (k["montant_avoirs_ttc"] / k["ca_total_ttc"] * 100
                            if k["ca_total_ttc"] else 0.0)
    k["nb_clients"] = int(nb_clients or 0)
    k["panier_moyen"] = (k["ca_total_ttc"] / k["nb_factures_vente"]) if k["nb_factures_vente"] else 0
    k["dso_jours"] = float(dso or 0)

    # ── 2. Tendance mensuelle CA + marge mensuelle ───────────────────────────
    monthly = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) revenue, sum(ht) ht
        FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["monthly_sales"] = [{"period": m[0], "revenue": float(m[1] or 0)} for m in monthly]
    if len(monthly) >= 2:
        last, prev = float(monthly[-1][1] or 0), float(monthly[-2][1] or 0)
        k["mom_growth"] = ((last - prev) / prev * 100) if prev else 0
        k["tendance"] = "Haussiere" if last >= prev else "Baissiere"
    else:
        k["mom_growth"] = 0
        k["tendance"] = "Stable"

    # ── 3. CA annuel + croissance YoY ────────────────────────────────────────
    yearly = con.execute(f"SELECT year, sum(ttc) FROM sales WHERE {W} GROUP BY year ORDER BY year").fetchall()
    k["yearly_sales"] = [{"year": int(y[0]), "revenue": float(y[1] or 0)} for y in yearly if y[0] is not None]
    # Croissance sur 12 mois glissants (robuste aux années partielles)
    ttm = con.execute(f"""
        WITH m AS (SELECT max(date) mx FROM sales WHERE {W})
        SELECT
          sum(ttc) FILTER (WHERE date >  (SELECT mx FROM m) - INTERVAL '12 months')                                  AS ttm_v,
          sum(ttc) FILTER (WHERE date <= (SELECT mx FROM m) - INTERVAL '12 months'
                             AND date >  (SELECT mx FROM m) - INTERVAL '24 months')                                 AS prev_v
        FROM sales WHERE {W}
    """).fetchone()
    ttm_v, prior_v = float(ttm[0] or 0), float(ttm[1] or 0)
    k["ttm_revenue"] = ttm_v
    k["yoy_growth"] = ((ttm_v - prior_v) / prior_v * 100) if prior_v else 0

    # ── 2bis. Comparaison année courante vs année précédente (par mois) ───────
    yrs = [int(r[0]) for r in con.execute(
        f"SELECT DISTINCT year FROM sales WHERE {W} AND year IS NOT NULL ORDER BY year DESC").fetchall()]
    mois_lbl = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    if yrs:
        cy = yrs[0]
        py = yrs[1] if len(yrs) > 1 else None
        prev_expr = f"sum(ttc) FILTER (WHERE year = {py})" if py is not None else "NULL"
        rows = con.execute(f"""
            SELECT month(date) m, sum(ttc) FILTER (WHERE year = {cy}) cur, {prev_expr} prev
            FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
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

    # ── 4. Saisonnalité (CA moyen par mois calendaire) ───────────────────────
    seas = con.execute(f"""
        SELECT month(date) m, sum(ttc) total, count(DISTINCT year) ny
        FROM sales WHERE {W} GROUP BY 1 ORDER BY 1
    """).fetchall()
    mois = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]
    k["seasonality"] = [{"month": mois[int(s[0]) - 1], "revenue": float((s[1] or 0) / (s[2] or 1))} for s in seas if s[0]]

    # ── 5. Délais de paiement / DSO / risque ─────────────────────────────────
    # NB : les données contiennent la date de pièce et la date d'échéance mais PAS
    # la date de paiement effective. `payment_delay_days` = délai de crédit ACCORDÉ.
    # On qualifie de "à risque" les termes longs (> 60 j) et de "critiques" (> 90 j),
    # car un délai accordé long accroît le DSO et l'exposition au risque de crédit.
    # `NOT est_avoir` partout : un avoir n'est pas une créance à recouvrer, et
    # son montant négatif viendrait en déduction d'une exposition qu'il ne
    # concerne pas.
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
    c90, c60, c30, tot_delay, mt_risque, mt_crit = drow
    k["retards_critiques"] = int(c90 or 0)
    k["retards_30j"] = int(c30 or 0)
    k["retards_60j"] = int(c60 or 0)
    k["paiements_total_analyses"] = int(tot_delay or 0)
    k["paiements_a_risque_count"] = int(c60 or 0)
    k["paiements_a_risque_pct"] = float((c60 or 0) / tot_delay * 100) if tot_delay else 0
    k["montant_risque_ttc"] = float(mt_risque or 0)
    k["montant_critique_ttc"] = float(mt_crit or 0)
    # Libellé honnête : montant_risque_ttc additionne le TTC de TOUTES les factures
    # de l'historique réglées avec >60j de retard → c'est un comportement de paiement,
    # PAS un encours dû aujourd'hui (le schéma n'a ni statut payé/impayé ni solde).
    k["ca_retard_historique_ttc"] = float(mt_risque or 0)
    k["ca_retard_historique_critique_ttc"] = float(mt_crit or 0)

    # ── Exposition RÉCENTE (proxy actionnable pour le recouvrement) ───────────
    # On borne aux échéances des 6 derniers mois (relatif à la dernière échéance
    # des données) → chiffre réaliste au lieu de 5 ans d'historique cumulé.
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

    # Clients à relancer, bornés à l'exposition récente
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
        GROUP BY client HAVING m > 0 ORDER BY m DESC NULLS LAST LIMIT 8
    """).fetchall()]

    # Structure des délais accordés (tranches) -> graphe empilé / barres
    # Ventes seulement : une tranche d'âge décrit des créances à encaisser, or
    # un avoir est une dette envers le client. L'y inclure retrancherait un
    # montant d'une tranche à laquelle il n'appartient pas.
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
    k["aging_creances"] = [{"bucket": labels[i], "montant": float(aging[i] or 0)} for i in range(5)]

    # ── 6. Top clients + concentration (HHI, Pareto) ─────────────────────────
    # `revenue` est un CA NET (avoirs déduits) ; `invoices` ne compte donc que
    # les ventes, sans quoi un client très remboursé afficherait beaucoup de
    # factures pour un chiffre faible.
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

    # ── Clients fidèles : la fidélité = RÉCURRENCE dans le temps, pas seulement
    # le CA. On classe par nb de mois d'achat distincts, puis nb de factures, puis CA.
    # La récurrence se mesure sur les VENTES : un avoir n'est pas un achat, et
    # un mois où le client n'a reçu qu'un avoir n'est pas un mois actif.
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

    # ── Clients qui décrochent : clients établis (>=6 mois d'activité) dont le CA
    # des 90 derniers jours a chuté de >60% vs les 90 jours précédents.
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

    # ── Décrochage ANTICIPÉ par le modèle ────────────────────────────────────
    # Les deux blocs répondent à deux questions différentes, et c'est pour cela
    # qu'ils coexistent :
    #
    #   * `clients_decrochent` CONSTATE — le chiffre d'affaires a déjà chuté de
    #     plus de 60 %. L'information arrive quand le client est déjà parti ;
    #   * `churn_anticipe` ANTICIPE — probabilité qu'un client encore actif cesse
    #     de commander dans les 90 jours. C'est là qu'une relance a un effet.
    #
    # Le modèle n'est lu QUE si le registre le déclare servi. Un modèle refusé
    # reste ainsi inaccessible au tableau de bord, même si son fichier existe.
    k["churn_anticipe"] = _charger_churn_si_servi()

    # ── Typologie de clientèle ───────────────────────────────────────────────
    # Le tableau de bord répond déjà à « quels clients ? ». La segmentation
    # répond à « quels TYPES de clients ? » — une liste de 938 comptes ne se
    # pilote pas, une poignée de segments oui.
    k["segmentation"] = _charger_segmentation_si_servie()

    # ── Cycle commercial et rentabilité ─────────────────────────────────────
    #
    # Deux modules servis par des modèles appris sur données réelles. Ils sont
    # chargés ici, dans le calcul que le frontend consomme, et non appelés
    # directement par une page : l'échéancier et la demande hybride sont restés
    # débranchés des semaines pour avoir manqué exactement cette ligne.
    k["conversion_devis"] = _charger_conversion_devis_si_servie()
    k["marge_client"] = _charger_marge_client_si_servie()

    # ── Immobilisations RÉELLES ──────────────────────────────────────────────
    # Reconstruites des factures d'achat et de vente, sans aucune simulation.
    # Elles remplacent le surstock simulé partout où un montant est annoncé à
    # l'utilisateur : un directeur ne déstocke pas sur une estimation.
    k["stock_flux_reel"] = _charger_flux_reels(con)

    # ── Réapprovisionnement appris ───────────────────────────────────────────
    # Complément et non substitut de la détection de rupture : celle-ci constate
    # ce qui manque déjà, le modèle anticipe ce qui sera commandé. Les deux se
    # servent en parallèle, et le second disparaît si le registre le refuse.
    k["reappro"] = _charger_reappro_si_servi()

    # ── Concentration du CA : nb de clients réalisant 80% du CA (règle de Pareto)
    # `r > 0` : un client au solde net négatif n'apporte pas de CA à concentrer.
    # Sans ce filtre, il abaisserait le total cumulé et ferait croire que moins
    # de clients suffisent à atteindre 80 % du chiffre.
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

    # HHI clients (indice de Herfindahl-Hirschman, sur 10000)
    # `r > 0` est indispensable depuis que le CA porte le signe des avoirs : un
    # client dont les avoirs dépassent les ventes a un CA net négatif, et le
    # carré d'une part négative redevient positif — il gonflerait donc l'indice
    # de concentration au lieu de le réduire. Un tel client ne pèse pas dans la
    # concentration : il est exclu du calcul, et compté à part.
    hhi = con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client),
             pos AS (SELECT r FROM s WHERE r > 0),
             tot AS (SELECT sum(r) t FROM pos)
        SELECT sum(power(r/(SELECT t FROM tot)*100, 2)) FROM pos
        WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_clients"] = float(hhi or 0)
    k["clients_solde_negatif"] = int(con.execute(f"""
        WITH s AS (SELECT client, sum(ttc) r FROM sales WHERE {W} GROUP BY client)
        SELECT count(*) FROM s WHERE r < 0
    """).fetchone()[0] or 0)

    # Courbe de Pareto (concentration) : part cumulée du CA par décile de clients
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
    # réduit à ~20 points pour le graphe
    k["client_pareto"] = [{"pct_clients": float(p[0]), "pct_ca": float(p[1] or 0)} for p in pareto if p[0] % 5 == 0]

    # ── 7. Mix des modes de paiement (camembert) ─────────────────────────────
    mix = con.execute(f"""
        SELECT coalesce(NULLIF(mode_regl, ''), 'Non renseigné') AS mode_label,
               sum(ttc) montant, count(*) nb
        FROM sales WHERE {W} GROUP BY 1 ORDER BY montant DESC NULLS LAST LIMIT 8
    """).fetchall()
    k["payment_mix"] = [{"mode": m[0], "montant": float(m[1] or 0), "count": int(m[2] or 0)} for m in mix]

    # ── 8. Prévision d'encaissement (échéances par mois) ─────────────────────
    cash = con.execute(f"""
        SELECT strftime(echeance, '%Y-%m') m, sum(ttc) montant
        FROM sales WHERE {W} AND echeance IS NOT NULL
        GROUP BY 1 ORDER BY 1
    """).fetchall()
    k["cash_forecast"] = [{"period": c[0], "montant": float(c[1] or 0)} for c in cash][-18:]

    # ── 9. Distribution des montants de facture (histogramme) ────────────────
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

    # ── 10. Achats / fournisseurs (toutes ventes hors périmètre client) ──────
    # Les achats ne dépendent pas du filtre client ; on applique l'année si choisie.
    purch_where = "1=1"
    if filters.get("selected_years"):
        purch_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    # Mêmes règles que pour les ventes : le montant est NET (avoirs fournisseur
    # déduits), le comptage et le DPO portent sur les seules factures d'achat.
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

    k["top_fournisseurs"] = [{
        "fournisseur": (r[0] or r[1] or "—")[:32], "montant": float(r[2] or 0),
        "share": float((r[2] or 0) / (k["achats_total_ttc"] or 1) * 100), "rank": i + 1,
    } for i, r in enumerate(con.execute(f"""
        SELECT fournisseur, fournisseur_code, sum(ttc) m
        FROM purchases WHERE {purch_where} GROUP BY 1,2 ORDER BY m DESC NULLS LAST LIMIT 8
    """).fetchall())]
    # `r > 0` : voir le HHI clients — le carré d'une part négative redevient
    # positif et gonflerait l'indice au lieu de le réduire.
    hhi_f = con.execute(f"""
        WITH s AS (SELECT fournisseur, sum(ttc) r FROM purchases WHERE {purch_where} GROUP BY 1),
             pos AS (SELECT r FROM s WHERE r > 0),
             tot AS (SELECT sum(r) t FROM pos)
        SELECT sum(power(r/(SELECT t FROM tot)*100,2)) FROM pos WHERE (SELECT t FROM tot) > 0
    """).fetchone()[0]
    k["hhi_fournisseurs"] = float(hhi_f or 0)

    # Tendance achats mensuelle (pour comparer à la vente)
    pm = con.execute(f"""
        SELECT strftime(date, '%Y-%m') period, sum(ttc) achats
        FROM purchases WHERE {purch_where} GROUP BY 1 ORDER BY 1
    """).fetchall()
    pm_map = {p[0]: float(p[1] or 0) for p in pm}
    # série combinée ventes vs achats alignée sur les mois de vente
    k["sales_vs_purchases"] = [
        {"period": m["period"], "ventes": m["revenue"], "achats": pm_map.get(m["period"], 0)}
        for m in k["monthly_sales"]
    ]

    # ── 11. Marge RÉELLE (coût de revient ERP, attribuable au client) ────────
    # Source : lignes de vente (MTCRSIGNE = coût de revient signé), agrégées dans
    # `client_margin`. Cette marge est ATTRIBUABLE : elle suit le filtre client,
    # contrairement à l'ancienne approximation « CA HT − achats TTC ».
    marge_row = None
    try:
        mw = ["1=1"]
        if filters.get("selected_years"):
            mw.append("year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")")
        if filters.get("selected_clients"):
            vals = ",".join("'" + str(c).replace("'", "''") + "'"
                            for c in filters["selected_clients"])
            mw.append(f"client IN ({vals})")
        if filters.get("date_start"):
            mw.append(f"period >= '{str(filters['date_start'])[:7]}'")
        if filters.get("date_end"):
            mw.append(f"period <= '{str(filters['date_end'])[:7]}'")
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
            "revient ERP (MTCRSIGNE), attribuable par client. Les lignes dont le coût "
            "dépasse 5× le prix de vente (erreurs de saisie) sont écartées.")
        # Signalement qualité (transparence sur le nettoyage appliqué)
        try:
            q = con.execute("SELECT lignes_exclues, lignes_facturees, lignes_offertes, "
                            "cout_offert FROM margin_quality").fetchone()
            if q and q[1]:
                k["marge_lignes_exclues"] = int(q[0] or 0)
                k["marge_lignes_exclues_pct"] = round(float(q[0] or 0) / float(q[1]) * 100, 2)
                k["marge_cout_articles_offerts_dt"] = round(float(q[3] or 0), 0)
        except Exception:
            pass
    else:
        # Aucune ligne exploitable sur ce périmètre (client sans lignes détaillées)
        k["marge_brute"] = None
        k["taux_marge"] = None
        k["marge_quality_score"] = None
        k["marge_source"] = "indisponible"
        k["marge_note"] = ("Marge non calculable sur ce périmètre : aucune ligne de vente "
                           "avec coût de revient exploitable.")

    # Marge mensuelle RÉELLE (issue des lignes, donc attribuable au client)
    try:
        mm = con.execute(
            f"SELECT period, sum(marge) FROM client_margin "
            f"WHERE {' AND '.join(mw)} GROUP BY period ORDER BY period").fetchall()
        mm_map = {r[0]: float(r[1] or 0) for r in mm}
        k["monthly_margin"] = [{"period": m["period"], "marge": mm_map.get(m["period"], 0.0)}
                               for m in k["monthly_sales"]]
    except Exception:
        k["monthly_margin"] = []

    # ── 11bis. Cascade « du CA à la marge » (waterfall P&L) ──────────────────
    # Construite sur la marge RÉELLE : CA des lignes − coût de revient.
    if k.get("marge_brute") is not None and k.get("marge_ca_reference_dt"):
        k["waterfall"] = [
            {"step": "CA (lignes)", "value": float(k["marge_ca_reference_dt"]), "kind": "start"},
            {"step": "Coût de revient", "value": -float(k["marge_cout_revient_dt"]), "kind": "neg"},
            {"step": "Marge brute", "value": float(k["marge_brute"]), "kind": "total"},
        ]
    else:
        k["waterfall"] = []

    # ── 12. Devis (pipeline) + taux de conversion ────────────────────────────
    dwhere = "1=1"
    if filters.get("selected_years"):
        dwhere = "year(date) IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    drow = con.execute(f"SELECT count(*), sum(ttc), count(DISTINCT client) FROM devis WHERE {dwhere}").fetchone()
    k["nb_devis"] = int(drow[0] or 0)
    k["montant_devis_total"] = float(drow[1] or 0)
    nb_clients_devis = int(drow[2] or 0)
    # ── Taux de conversion RÉEL : basé sur le statut ERP du devis ────────────
    # `transforme` = (ETATPIECE = '8'). Interprétation VALIDÉE empiriquement :
    # 89,4 % des devis en état 8 ont une facture du même client au même montant
    # (± 1 %), contre 37,4 % pour l'état 1 — l'écart ne laisse pas de doute.
    # L'ancienne heuristique (« le client a-t-il facturé quelque chose ? »)
    # surestimait massivement le taux (94,8 % au lieu de ~9 %).
    conv = con.execute(f"""
        SELECT count(*) FILTER (WHERE transforme) AS transformes,
               count(*)                            AS total,
               sum(ttc) FILTER (WHERE transforme)  AS montant_transforme
        FROM devis WHERE {dwhere}
    """).fetchone()
    n_transf, n_devis_tot = int(conv[0] or 0), int(conv[1] or 0)
    converted = n_transf
    k["devis_transformes"] = n_transf
    k["montant_devis_transforme"] = round(float(conv[2] or 0), 0)
    k["taux_conversion_devis"] = float(n_transf / n_devis_tot * 100) if n_devis_tot else 0.0
    k["taux_conversion_source"] = "etat_piece_erp"
    k["taux_conversion_note"] = (
        "Part des devis effectivement TRANSFORMÉS en facture (statut ERP "
        "ETATPIECE=8, validé empiriquement à 89 % d'appariement montant/client).")
    nb_bl = int(_scalar(con, "SELECT count(*) FROM bl"))
    k["nb_bl"] = nb_bl
    k["montant_bl_total"] = None
    k["funnel"] = [
        {"etape": "Devis", "valeur": k["nb_devis"]},
        {"etape": "Clients convertis", "valeur": converted},
        {"etape": "Clients facturés", "valeur": k["nb_clients"]},
    ]

    # ── 13. Top produits (respecte le filtre année) ──────────────────────────
    prod_where = "1=1"
    if filters.get("selected_years"):
        prod_where = "year IN (" + ",".join(str(int(y)) for y in filters["selected_years"]) + ")"
    prods = con.execute(f"""
        SELECT produit, sum(ca) ca, sum(qte) qte FROM product_sales
        WHERE {prod_where} GROUP BY produit ORDER BY ca DESC NULLS LAST LIMIT 10
    """).fetchall()
    k["top_produits"] = [{
        "produit": (p[0] or "—").strip()[:38], "ca": float(p[1] or 0), "qte": float(p[2] or 0),
    } for p in prods]
    k["nb_produits"] = int(_scalar(con, f"SELECT count(DISTINCT produit) FROM product_sales WHERE {prod_where}"))

    # Top familles de produits (REACTIF, EQUIPEMENT, SERVICE…)
    fam = con.execute(f"""
        SELECT famille, sum(ca) ca FROM product_family
        WHERE {prod_where} GROUP BY famille ORDER BY ca DESC NULLS LAST LIMIT 6
    """).fetchall()
    k["top_familles"] = [{"famille": (f[0] or "—").strip()[:28], "ca": float(f[1] or 0)} for f in fam]

    # ── 14. Clients à risque (exposition échue) ──────────────────────────────
    k["clients_a_risque"] = [{
        "client": r[0], "nom": r[1] or r[0], "montant_risque": float(r[2] or 0), "factures": int(r[3] or 0),
    } for r in con.execute(f"""
        SELECT client, any_value(client_name) nom,
               sum(ttc) FILTER (WHERE payment_delay_days > 60) m,
               count(*) FILTER (WHERE payment_delay_days > 60) n
        FROM sales WHERE {W} GROUP BY client HAVING m > 0 ORDER BY m DESC LIMIT 8
    """).fetchall()]

    # ── 15bis. Score de risque crédit PRÉDIT (modèle ML, si entraîné) ─────────
    # Table de noms clients (code -> nom) pour enrichir les classements
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
            # Exposition pondérée par le risque = probabilité × encours (argent à risque)
            priority = score / 100.0 * expo
            expo_ponderee += priority
            if score > 70:
                nb_high += 1
            enriched.append({
                "client": cl, "nom": name_map.get(cl, cl), "score": score, "exposure": expo,
                "avg_delay": float(v.get("avg_delay", 0)), "priority": priority,
                # Pourquoi ce client est en tête du classement. Ici aucun modèle
                # appris : une RÈGLE mesurée sur l'historique. L'explication est
                # donc la règle elle-même — la valeur observée et le seuil
                # franchi —, ce qui est plus vérifiable qu'une attribution.
                "raisons": _raisons_credit(v),
            })
        k["nb_clients_risque_predit"] = nb_high
        k["exposition_risque_ponderee"] = expo_ponderee
        # Classement par priorité de recouvrement (argent à risque), pas juste la proba
        k["risk_ranking"] = sorted(enriched, key=lambda x: -x["priority"])[:10]
        k["risk_model_active"] = True
    else:
        k["nb_clients_risque_predit"] = None
        k["exposition_risque_ponderee"] = None
        k["risk_ranking"] = []
        k["risk_model_active"] = False

    # ── 15. Anomalies ────────────────────────────────────────────────────────
    neg = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc < 0"))
    zero = int(_scalar(con, f"SELECT count(*) FROM sales WHERE {W} AND ttc = 0"))
    if k["retards_critiques"]:
        k["anomalies_details"].append(f"{k['retards_critiques']} facture(s) avec délai accordé > 90 jours.")
    warn = k["retards_30j"] - k["retards_critiques"]
    if warn > 0:
        k["anomalies_details"].append(f"{warn} facture(s) avec délai accordé de 30 à 90 jours.")
    if neg:
        k["anomalies_details"].append(f"{neg} facture(s) avec montant négatif (avoirs).")
    if zero:
        k["anomalies_details"].append(f"{zero} facture(s) avec montant nul.")
    if k["hhi_clients"] > 2500:
        k["anomalies_details"].append(f"Forte concentration client (HHI={k['hhi_clients']:.0f} > 2500).")
    k["anomalies_detectees"] = int(k["retards_critiques"] + neg + zero)
    if not k["anomalies_details"]:
        k["anomalies_details"] = ["Aucune anomalie majeure détectée."]

    # ── 16. BFR / cycle de trésorerie ────────────────────────────────────────
    k["cash_conversion_cycle"] = float(k["dso_jours"] - k["dpo_jours"])

    # ── 17. Factures importées par OCR ───────────────────────────────────────
    # Bloc SÉPARÉ, jamais fondu dans les totaux ci-dessus. Les indicateurs ERP
    # doivent rester rapprochables de l'export d'origine : une facture lue à
    # 70 % de confiance n'a pas le même statut probatoire qu'une ligne d'ERP.
    # L'interface et l'agent les présentent donc comme un apport distinct.
    k["import_ocr"] = {"n_factures": 0, "total_ttc_dt": 0.0, "factures": []}
    try:
        clients_filtre = (filters or {}).get("selected_clients") or []
        # Ce bloc parle de CLIENTS : seules les ventes y ont leur place. Un achat
        # importé (sens = 'achat') n'est pas du chiffre d'affaires. Les lignes
        # antérieures à la colonne `sens` sont des ventes.
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
            "note": ("Factures lues par OCR et validées à l'import. Comptabilisées "
                     "à part des indicateurs ERP, dont elles ne modifient aucun total."),
        }
    except Exception:
        # Table absente tant qu'aucune facture n'a été importée : cas normal.
        pass

    # ── 17 bis. Échéancier des factures OCR hors ERP ────────────────────────
    # Décaissements et encaissements à venir des factures lues et non encore
    # présentes dans l'ERP. Bloc séparé, comme ci-dessus : il ne modifie ni
    # `cash_forecast` (échéances ERP) ni aucun total.
    try:
        from ml_engine.ocr.echeancier import echeancier as _echeancier
        e = _echeancier()
        k["echeancier_ocr"] = {c: e[c] for c in (
            "a_payer_dt", "a_encaisser_dt", "a_payer_en_retard_dt", "a_encaisser_en_retard_dt",
            "n_factures", "n_echeances_deduites", "mois", "note")}
    except Exception:
        k["echeancier_ocr"] = {"n_factures": 0, "mois": []}

    # ── 17 ter. Exactitude de l'OCR en production ───────────────────────────
    try:
        from ml_engine.ocr.apprentissage import mesure_production
        k["qualite_ocr_production"] = mesure_production()
    except Exception:
        k["qualite_ocr_production"] = {"n_factures_relues": 0, "par_moteur": {}}

    # ── 18. Contrôle d'intégrité ─────────────────────────────────────────────
    # Le CA a été faux de 5,44 % pendant toute la durée du projet sans que rien
    # ne le signale : un montant erroné reste plausible. Les invariants sont
    # donc vérifiés à chaque calcul, et le résultat accompagne les indicateurs
    # plutôt que d'attendre un audit manuel.
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


# ─────────────────────────────────────────────────────────────────────────────
# CLI de test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Calcul des KPIs (sans filtre)…")
    kpis = compute_dashboard({})
    preview = {key: v for key, v in kpis.items() if not isinstance(v, list)}
    print(json.dumps(preview, indent=2, ensure_ascii=False, default=str))
    print("\nSéries:", {key: len(v) for key, v in kpis.items() if isinstance(v, list)})
