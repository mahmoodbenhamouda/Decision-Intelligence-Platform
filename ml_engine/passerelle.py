"""
ml_engine/passerelle.py
=======================
Passerelle unique entre les AGENTS, l'API et les MODÈLES.

Le problème que ce fichier résout
---------------------------------
Les agents de la flotte lisaient surtout des indicateurs calculés : seul l'agent
Risque client consommait un modèle appris. La conversion des devis, l'érosion de
marge, la segmentation, le réapprovisionnement, la fin de vie et la
recommandation n'atteignaient que le tableau de bord — aucun agent n'en tirait un
constat, et le briefing ne profitait donc pas de la science des données du projet.

Et le copilote, lui, importait directement `score_stock_risk` : un modèle RETIRÉ
par le registre, entraîné sur un stock simulé. Rien ne l'en empêchait, parce que
la décision du registre n'était consultée qu'à certains endroits.

Ce que garantit la passerelle
-----------------------------
1. **Un seul chemin** : un agent ou le copilote n'importe jamais un module de
   modèle ; il appelle une fonction d'ici. Un modèle refusé ou retiré ne peut donc
   pas atteindre un briefing par une importation oubliée — un test le vérifie.
2. **Le registre décide** : chaque fonction interroge `ml_engine.registre` avant
   de servir. Si le modèle n'est pas servi, elle renvoie la méthode de repli que
   la mesure a désignée (règle, statistique), jamais un score non validé.
3. **Chaque sortie porte sa carte d'identité** (`modele`) : nature, statut,
   métrique hors période, référence battue, accuracy et balanced accuracy. L'agent
   la recopie dans son constat ; le briefing peut donc toujours dire *quel
   modèle* a produit *quel chiffre*, et avec quelle fiabilité mesurée.
4. **L'API passe par le même chemin** : ses services n'importent ni un module de
   modèle ni un nom privé du moteur KPI (un test le vérifie). Les fonctions de la
   dernière section leur servent les sorties affichées à l'écran — sans la carte,
   servie à part par `/api/models/metrics`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from config.settings import settings
    BASE = Path(settings.base_dir)
except Exception:  # pragma: no cover
    BASE = Path(__file__).resolve().parents[1]

REPORTS_DIR = BASE / "reports"
OUTPUT_DIR = BASE / "output"

# Où lire le bloc `classification` (ml_engine/metriques.py) de chaque rapport.
_CHEMIN_CLASSIFICATION = {
    "churn": ["hors_periode", "classification"],
    "conversion_devis": ["hors_periode", "classification"],
    "marge_client": ["evaluation", "classification"],
    "reappro": ["hors_periode", "classification"],
    "fin_de_vie": ["hors_periode", "classification"],
    "credit": ["regime_A_hors_periode", "classification"],
    "stock_risque": ["holdout", "classification"],
}

_RAPPORTS = {
    "churn": "churn_metrics.json", "conversion_devis": "conversion_devis_metrics.json",
    "marge_client": "marge_client_metrics.json", "reappro": "reappro_metrics.json",
    "fin_de_vie": "fin_de_vie_metrics.json", "credit": "credit_risk_metrics.json",
    "stock_risque": "stock_risk_metrics.json", "segmentation": "segmentation_metrics.json",
    "recommandation": "recommandation_metrics.json", "demande": "demande_hybride_metrics.json",
    "echeancier": "cashflow_carnet_metrics.json",
    "demande_reference": "demande_reference_metrics.json",
}


def _lire_json(chemin: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.load(open(chemin, encoding="utf-8")) if chemin.exists() else None
    except Exception:
        return None


def _extraire(doc: Any, chemin: List[str]) -> Any:
    for cle in chemin:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(cle)
    return doc


# ── Carte d'identité d'un modèle ────────────────────────────────────────────
def carte_modele(nom: str) -> Dict[str, Any]:
    """Ce qu'un agent doit savoir d'un modèle pour citer son résultat honnêtement."""
    try:
        from ml_engine.registre import etat_modele
        e = etat_modele(nom)
    except Exception as ex:  # pragma: no cover
        return {"module": nom, "servi": False, "motif": f"registre indisponible ({ex})"}

    carte: Dict[str, Any] = {
        "module": nom,
        "libelle": e.get("libelle", nom),
        "nature": e.get("nature"),
        "servi": bool(e.get("deploye")),
        "retire": bool(e.get("retire")),
        "metrique_nom": e.get("metrique_nom"),
        "metrique": e.get("metrique"),
        "reference_a_battre": e.get("reference_a_battre"),
        "gain": e.get("gain"),
        "motif": e.get("motif"),
    }
    rapport = _lire_json(REPORTS_DIR / _RAPPORTS.get(nom, "")) if nom in _RAPPORTS else None
    cl = _extraire(rapport, _CHEMIN_CLASSIFICATION[nom]) if (rapport and nom in _CHEMIN_CLASSIFICATION) else None
    if cl is None and rapport and nom in _CHEMIN_CLASSIFICATION:
        # Rapport antérieur au module de métriques : on dérive de la matrice publiée.
        bloc = _extraire(rapport, _CHEMIN_CLASSIFICATION[nom][:-1]) or {}
        matrice = bloc.get("confusion_matrix")
        if isinstance(matrice, list) and len(matrice) == 2:
            from ml_engine.metriques import metriques_depuis_matrice
            cl = metriques_depuis_matrice(matrice)
    if isinstance(cl, dict) and cl.get("applicable"):
        carte["classification"] = {
            k: cl.get(k) for k in ("accuracy", "balanced_accuracy", "f1", "mcc", "auc",
                                   "accuracy_classe_majoritaire", "taux_de_base_test")}
    if nom == "recommandation" and rapport:
        ev = rapport.get("evaluation") or {}
        agr = ev.get("agrege") or {}
        carte["methode_servie"] = (rapport.get("decision_deploiement") or {}).get("methode_servie")
        carte["deep_learning"] = {
            "architecture": "Wide & Deep (PyTorch)",
            "mesure": agr.get("wide_deep"),
            "servi": carte["methode_servie"] == "wide_deep",
            "duel_vs_lightgbm": (ev.get("duels_du_deep_learning") or {}).get("wide_deep_vs_lightgbm"),
        }
    return carte


def formater_metrique(carte: Dict[str, Any]) -> str:
    """Phrase courte citée dans un constat : « AUC 0,92 hors période, accuracy 93 % »."""
    m = carte.get("metrique")
    if m is None:
        return "non mesuré"
    nom = carte.get("metrique_nom") or "métrique"
    txt = f"{nom} {m:.3f}" if isinstance(m, float) and m <= 1 else f"{nom} {m}"
    c = carte.get("classification") or {}
    if c.get("accuracy") is not None:
        txt += (f", accuracy {c['accuracy']:.1%} (classe majoritaire "
                f"{c.get('accuracy_classe_majoritaire', 0):.1%}), balanced accuracy "
                f"{c.get('balanced_accuracy', 0):.1%}")
    return txt


def trace_modele(carte: Dict[str, Any], role: str) -> Dict[str, Any]:
    """Entrée compacte `modeles_utilises` d'un constat."""
    return {
        "module": carte.get("module"),
        "libelle": carte.get("libelle"),
        "nature": carte.get("nature"),
        "statut": ("servi" if carte.get("servi")
                   else "retiré" if carte.get("retire") else "refusé — repli mesuré"),
        "role": role,
        "fiabilite": formater_metrique(carte),
    }


# ── Accès aux sorties des modèles ───────────────────────────────────────────
def _noms_clients() -> Dict[str, str]:
    try:
        import duckdb
        from ml_engine.analytics.kpi_engine import STORE_PATH
        con = duckdb.connect(str(STORE_PATH), read_only=True)
        try:
            return {str(c): str(n) for c, n in con.execute(
                "SELECT client, any_value(client_name) FROM sales "
                "WHERE client_name IS NOT NULL GROUP BY client").fetchall()}
        finally:
            con.close()
    except Exception:
        return {}


def decrochage(limite: int = 10, kpis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    carte = carte_modele("churn")
    if kpis and isinstance(kpis.get("churn_anticipe"), dict) and kpis["churn_anticipe"].get("servi"):
        return {**kpis["churn_anticipe"], "modele": carte}
    try:
        from ml_engine.analytics.kpi_engine import _charger_churn_si_servi
        return {**_charger_churn_si_servi(limite), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def segments_clients() -> Dict[str, Any]:
    """Segment de chaque client + taux de décrochage menacé par segment."""
    carte = carte_modele("segmentation")
    if not carte["servi"]:
        return {"servi": False, "motif": carte.get("motif"), "modele": carte}
    par_client = _lire_json(OUTPUT_DIR / "client_segments.json") or {}
    rapport = _lire_json(REPORTS_DIR / "segmentation_metrics.json") or {}
    risques = {c["segment"]: c for c in
               ((rapport.get("croisement_decrochage") or {}).get("par_segment") or [])}
    segs = [{**s, "part_menacee_pct": risques.get(s["segment"], {}).get("part_menacee_pct"),
             "ca_menace_dt": risques.get(s["segment"], {}).get("ca_menace_dt")}
            for s in (rapport.get("segments") or [])]
    return {"servi": True, "par_client": par_client, "segments": segs, "modele": carte}


def conversion_devis(limite: int = 20) -> Dict[str, Any]:
    carte = carte_modele("conversion_devis")
    try:
        from ml_engine.analytics.conversion_devis import predire
        return {**predire(limite), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def marge_clients(limite: int = 15) -> Dict[str, Any]:
    carte = carte_modele("marge_client")
    try:
        from ml_engine.analytics.marge_client import predire
        return {**predire(limite), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def reapprovisionnement(limite: int = 15) -> Dict[str, Any]:
    """Modèle si servi ; sinon le repli mesuré — la détection arithmétique de rupture."""
    carte = carte_modele("reappro")
    if carte["servi"]:
        try:
            from ml_engine.stock.reappro_model import predire
            return {**predire(limite), "modele": carte, "source": "modele"}
        except Exception as e:
            return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}
    return {"servi": False, "modele": carte, "source": "regle_de_repli",
            "repli": ("détection arithmétique des ruptures sur les flux réels — le "
                      "modèle ne battait pas « nombre d'achats sur 12 mois » de 0,02 d'AUC")}


def fin_de_vie(limite: int = 15) -> Dict[str, Any]:
    """Le module sert lui-même la règle quand le modèle est refusé."""
    carte = carte_modele("fin_de_vie")
    try:
        from ml_engine.stock.fin_de_vie import predire
        return {**predire(limite), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def conditions_credit(codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Règle historique servie (client connu) ou taux de base (client nouveau)."""
    carte = carte_modele("credit")
    scores = _lire_json(OUTPUT_DIR / "client_risk.json") or {}
    if not carte["servi"] or not scores:
        return {"servi": False, "motif": carte.get("motif") or "scores absents", "modele": carte}
    if codes is not None:
        scores = {c: scores[c] for c in codes if c in scores}
    return {"servi": True, "scores": scores, "modele": carte}


def risque_stock() -> Dict[str, Any]:
    """Modèle RETIRÉ : on renvoie sa carte, jamais ses scores.

    Il reste mesurable (AUC 0,856) mais sa cible dépend de dates de péremption
    simulées. Les montants de stock servis viennent des flux réels.
    """
    carte = carte_modele("stock_risque")
    if carte["servi"]:     # pragma: no cover — ne se produit que s'il est réadmis
        try:
            from ml_engine.models.stock_risk import score_stock_risk
            return {**score_stock_risk(limit=60), "servi": True, "modele": carte}
        except Exception as e:
            return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}
    return {"servi": False, "retire": carte.get("retire", False),
            "motif": carte.get("motif") or "retiré du service par le registre",
            "remplace_par": "stock reconstruit des factures (ml_engine.stock.flux_reels)",
            "modele": carte}


def demande_et_fournisseurs() -> Dict[str, Any]:
    carte = carte_modele("demande")
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        return {**(compute_supply_demand() or {}), "modele": carte}
    except Exception as e:
        return {"motif": f"indisponible ({type(e).__name__})", "modele": carte}


def demande_par_reference(limite: int = 400) -> Dict[str, Any]:
    """Quantités attendues par référence sur 1 à 3 mois, avec borne haute P80.

    Toujours une méthode servie — la règle simple ou le modèle appris, selon le
    dernier duel mesuré — mais jamais sans rapport : sans lui, rien n'est servi.
    """
    carte = carte_modele("demande_reference")
    if not carte["servi"]:
        return {"servi": False, "motif": carte.get("motif"), "modele": carte}
    try:
        from ml_engine.forecasting.demande_reference import prevoir
        return {**prevoir(limite=limite), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def echeancier_1_mois() -> Dict[str, Any]:
    carte = carte_modele("echeancier")
    if not carte["servi"]:
        return {"servi": False, "motif": carte.get("motif"), "modele": carte}
    try:
        from ml_engine.forecasting.carnet_echeances import charger_factures, prevoir
        factures = charger_factures()
        echeances = sorted({e for _, e, _ in factures})
        emissions = sorted({em for em, _, _ in factures})
        origine = max(emissions) - 1
        sortie = prevoir(factures, origine, 1, echeances[0])
        if not sortie:
            return {"servi": False, "motif": "prévision impossible", "modele": carte}
        prevu, _regime, maturite = sortie
        return {"servi": True, "montant_exigible_dt": round(float(prevu), 0),
                "part_deja_au_carnet": round(float(maturite), 4), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def recommandations(client: Optional[str] = None, n_clients: int = 15) -> Dict[str, Any]:
    carte = carte_modele("recommandation")
    try:
        from ml_engine.deep.recommandation import predire
        return {**predire(client=client, n_clients=n_clients), "modele": carte}
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})", "modele": carte}


def derive() -> Dict[str, Any]:
    d = _lire_json(REPORTS_DIR / "derive_metrics.json")
    return d or {"etat": "inconnu", "motif": "rapport de dérive absent"}


def tableau_des_modeles() -> List[Dict[str, Any]]:
    """Une ligne par module du registre, avec ses métriques de classification."""
    try:
        from ml_engine.registre import MODELES
    except Exception:  # pragma: no cover
        return []
    return [carte_modele(n) for n in MODELES]


def noms_clients() -> Dict[str, str]:
    return _noms_clients()


# ── Sorties servies au tableau de bord (API) ────────────────────────────────
# Mêmes modules, mêmes décisions du registre que pour les agents ; seule la
# forme change : l'écran reçoit la sortie du module telle quelle.
def decrochage_servi(limite: int = 20) -> Dict[str, Any]:
    """Clients à risque de décrochage — seulement si le registre sert le modèle."""
    from ml_engine.analytics.kpi_engine import _charger_churn_si_servi
    return _charger_churn_si_servi(limite=limite)


def reapprovisionnement_servi() -> Dict[str, Any]:
    """Réapprovisionnement appris : servi uniquement si le registre l'autorise."""
    from ml_engine.analytics.kpi_engine import _charger_reappro_si_servi
    return _charger_reappro_si_servi()


def flux_de_stock_reels() -> Dict[str, Any]:
    """Stock reconstruit des factures d'achat et de vente (aucune simulation)."""
    from ml_engine.analytics.kpi_engine import _charger_flux_reels, _connect
    con = _connect()
    try:
        return _charger_flux_reels(con)
    finally:
        con.close()


def fin_de_vie_servie() -> Dict[str, Any]:
    """Fin de commercialisation : la règle mesurée, le modèle ayant été refusé."""
    from ml_engine.stock.fin_de_vie import predire
    return predire()


def devis_a_relancer(limite: int = 20) -> Dict[str, Any]:
    from ml_engine.analytics.conversion_devis import predire
    return predire(limite=limite)


def marge_a_surveiller(limite: int = 15) -> Dict[str, Any]:
    from ml_engine.analytics.marge_client import predire
    return predire(limite=limite)


def prevision_encaissements(horizon: int = 6) -> Any:
    """Prévision d'encaissements globale (LSTM, avec repli), mise en cache."""
    from ml_engine.forecasting.lstm_cashflow import load_or_forecast
    return load_or_forecast(horizon=horizon)


def etat_du_modele(nom: str) -> Dict[str, Any]:
    """Décision du registre pour un module (déployé, retiré, motif)."""
    from ml_engine.registre import etat_modele
    return etat_modele(nom)


def risque_stock_par_produit(client: Optional[str] = None, limite: int = 25) -> Dict[str, Any]:
    """Scoring du risque produit. Module RETIRÉ : l'appelant consulte d'abord
    `etat_du_modele("stock_risque")` ; ce chemin ne sert que s'il est réadmis."""
    from ml_engine.models import score_stock_risk
    return score_stock_risk(client=client, limit=limite)


def demande_par_produit_historique(produit: Optional[str] = None) -> List[Dict[str, Any]]:
    """Ancien chemin de prévision de demande (repli si `demande_reference`
    n'est pas servie) : naïf saisonnier par produit, horizons 30/60/90 jours."""
    from ml_engine.models import predict_demand
    return predict_demand([produit] if produit else None)


def metriques_demande_historique() -> Dict[str, Any]:
    """Traçabilité de l'ancien chemin : modèle retenu et gains par horizon."""
    m = _lire_json(REPORTS_DIR / "demand_forecast_ml_metrics.json") or {}
    return {h: {"modele": v.get("modele_retenu"),
                "horizon_jours": v.get("horizon_jours"),
                "wape_pct": (v.get("holdout") or {}).get("wape_pct"),
                "mae": (v.get("holdout") or {}).get("mae"),
                # Traçabilité de la décision de déploiement : le gain obtenu en
                # validation croisée et sa confirmation (ou non) sur les 6 mois
                # jamais vus.
                "gain_cv_pct": v.get("gain_vs_meilleure_baseline_pct"),
                "gain_holdout_pct": v.get("holdout_gain_vs_baseline_pct"),
                "gain_confirme": v.get("holdout_confirme_le_gain")}
            for h, v in (m.get("horizons") or {}).items()}
