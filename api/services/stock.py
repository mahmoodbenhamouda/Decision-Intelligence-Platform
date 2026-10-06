"""Stock, approvisionnement et volumes à prévoir."""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.services.erreurs import Conflit
from ml_engine import passerelle as pw
from ml_engine import portee as po


def _masque_global(filtres: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Stock, demande et fournisseurs sont des analyses de l'entreprise entière :
    masquées dès qu'un filtre restreint le périmètre."""
    cache = po.pour_analyse_globale(po.portee(filtres))
    return {**cache, "error": cache["motif"]} if cache else None


def indicateurs_stock(filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cache = _masque_global(filtres)
    if cache:
        return cache
    reponse: Dict[str, Any] = {"is_simulated": False,
                               "origine": ("factures d'achat et de vente — aucune "
                                           "simulation, aucune date inventée")}
    try:
        reponse["flux_reel"] = pw.flux_de_stock_reels()
    except Exception as e:
        reponse["flux_reel"] = {"disponible": False,
                                "motif": f"indisponible ({type(e).__name__})"}

    try:
        reponse["reappro"] = pw.reapprovisionnement_servi()
    except Exception as e:
        reponse["reappro"] = {"servi": False,
                              "motif": f"indisponible ({type(e).__name__})"}

    try:
        reponse["fin_de_vie"] = pw.fin_de_vie_servie()
    except Exception as e:
        reponse["fin_de_vie"] = {"servi": False,
                                 "motif": f"indisponible ({type(e).__name__})"}
    return reponse


def risque_produit(client: Optional[str], limite: int) -> Dict[str, Any]:
    """Scoring du risque produit — **RETIRÉ DU SERVICE**."""
    etat = pw.etat_du_modele("stock_risque")
    if not etat["deploye"]:
        raise Conflit({
            "retire": bool(etat.get("retire")),
            "motif": etat.get("motif"),
            "remplace_par": "/api/stock",
            "ce_qui_est_servi_a_la_place": [
                "capital immobilisé — achats moins ventes, coût d'achat réel",
                "ruptures — référence encore vendue, approvisionnement arrêté",
                "stock non écoulable — plus de 2 ans de consommation constatée",
                "fin de commercialisation — règle mesurée, lift 5,5 au décile",
            ],
        })

    try:
        return pw.risque_stock_par_produit(client=client, limite=max(1, min(200, limite)))
    except Exception as e:
        return {"error": str(e), "is_simulated": True, "produits": []}


def prevision_demande(produit: Optional[str], limite: int,
                      filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Volumes CUMULÉS à 30, 60 et 90 jours, par produit."""
    cache = _masque_global(filtres)
    if cache:
        return {**cache, "previsions": []}
    n = max(1, min(200, limite))
    try:
        dem = pw.demande_par_reference()
        if dem.get("servi"):
            refs = dem.get("references") or []
            if produit:
                q = produit.strip().upper()
                refs = [r for r in refs if q in str(r.get("designation", "")).upper()
                        or q == str(r.get("reference", "")).upper()]
            res = [{
                "produit": r["designation"], "reference": r["reference"],
                "derniere_periode": dem.get("origine"),
                "demande_observee_dernier_mois": r.get("dernier_mois"),
                "moyenne_3m": r.get("moyenne_3_mois"),
                "prevision_30j": r["prevision"][0],
                "prevision_60j": round(r["prevision"][0] + r["prevision"][1], 1),
                "prevision_90j": r["cumul_3_mois"],
                "borne_haute_90j": r["borne_haute_3_mois"],
            } for r in refs][:n]
            carte = dem.get("modele") or {}
            return {"previsions": res, "is_simulated": False,
                    "modeles": {"demande_reference": {
                        "methode": dem.get("methode"), "wape_1_mois_pct": dem.get("wape_h1_pct"),
                        "nature": carte.get("nature"), "motif": carte.get("motif")}},
                    "note": ("Prévisions issues des ventes RÉELLES, par référence ; borne haute "
                             "à 90 jours dépassée dans 2 cas sur 10.")}
    except Exception:
        pass
    try:
        res = pw.demande_par_produit_historique(produit)
        res = sorted(res, key=lambda r: -r["prevision_90j"])[:n]
        try:
            meta = pw.metriques_demande_historique()
        except Exception:
            meta = {}
        return {"previsions": res, "modeles": meta, "is_simulated": False,
                "note": ("Prévisions issues des ventes RÉELLES (6 ans). "
                         "Le stock auquel elles sont comparées est simulé.")}
    except Exception as e:
        return {"error": str(e), "previsions": []}


def demande_et_approvisionnement(filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Prévision de demande + concentration et dépendance fournisseur.

    N'est plus masquée sous un filtre client : la demande d'un établissement se
    prévoit, elle aussi. Le moteur restreint la série au périmètre et refuse
    lui-même quand l'historique devient trop court — un refus motivé vaut mieux
    qu'un écran vide."""
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        return compute_supply_demand(filtres)
    except Exception as e:
        return {"error": str(e)}
