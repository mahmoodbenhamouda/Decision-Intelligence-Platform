"""
api/services/stock.py
=====================
Stock, approvisionnement et volumes à prévoir.

Une seule source, et elle est réelle
------------------------------------
Les indicateurs de stock servaient deux volets : les flux reconstruits des
factures, et un module (s,S) SIMULÉ pour la couverture, les points de commande
et les dates de péremption. Le second est retiré : un directeur ne distingue
pas, dans un tableau de bord, un chiffre mesuré d'un chiffre généré — même
marqué `is_simulated`. Ce qui reste :

  * capital immobilisé  = quantités achetées − vendues, au coût d'achat réel ;
  * ruptures            = référence encore vendue, approvisionnement arrêté ;
  * stock non écoulable = plus de deux ans de consommation constatée.

Ce qui est perdu, et assumé : les **dates de péremption à la référence**. Elles
n'existent nulle part dans l'ERP, et les simuler produisait une liste précise
mais inventée. Le raisonnement par rotation donne une certitude équivalente
sans inventer de date (cf. reports/METRICS_REPORT.md, §3 quater).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.services.erreurs import Conflit
from ml_engine import passerelle as pw


def indicateurs_stock() -> Dict[str, Any]:
    reponse: Dict[str, Any] = {"is_simulated": False,
                               "origine": ("factures d'achat et de vente — aucune "
                                           "simulation, aucune date inventée")}
    try:
        reponse["flux_reel"] = pw.flux_de_stock_reels()
    except Exception as e:
        reponse["flux_reel"] = {"disponible": False,
                                "motif": f"indisponible ({type(e).__name__})"}

    # Réapprovisionnement appris : c'est le registre qui répond, jamais ce
    # service — sans quoi la décision de déploiement redeviendrait une
    # recommandation.
    try:
        reponse["reappro"] = pw.reapprovisionnement_servi()
    except Exception as e:
        reponse["reappro"] = {"servi": False,
                              "motif": f"indisponible ({type(e).__name__})"}

    # Fin de commercialisation. Le modèle appris a été refusé — une règle d'une
    # variable le battait — et c'est donc la RÈGLE qui est servie, mesurée. Le
    # champ `nature` de la réponse dit laquelle des deux répond, pour qu'aucune
    # lecture ne prenne un ordre de priorité pour une probabilité.
    try:
        reponse["fin_de_vie"] = pw.fin_de_vie_servie()
    except Exception as e:
        reponse["fin_de_vie"] = {"servi": False,
                                 "motif": f"indisponible ({type(e).__name__})"}
    return reponse


def risque_produit(client: Optional[str], limite: int) -> Dict[str, Any]:
    """Scoring du risque produit — **RETIRÉ DU SERVICE**.

    Ce modèle atteignait 0,8562 d'AUC en hold-out groupé par produit, et passait
    donc ses seuils. Il est retiré pour une raison qu'aucune métrique ne peut
    voir : **11 576 de ses 18 071 cibles positives** reposent sur des dates de
    péremption GÉNÉRÉES, l'ERP n'en portant aucune, et ses variables de position
    viennent du module (s,S) simulé. Une AUC honnête sur une cible inventée
    reste une AUC sur une cible inventée.

    Le point d'entrée est conservé et répond 409 (`Conflit`) : le supprimer
    laisserait un appelant recevoir un 404 sans explication, alors que la raison
    du retrait est précisément ce qu'il faut transmettre.
    """
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

    # Chemin conservé pour le cas où le modèle serait un jour réentraîné sur des
    # positions réelles et réadmis par le registre.
    try:
        return pw.risque_stock_par_produit(client=client, limite=max(1, min(200, limite)))
    except Exception as e:
        return {"error": str(e), "is_simulated": True, "produits": []}


def prevision_demande(produit: Optional[str], limite: int) -> Dict[str, Any]:
    """Volumes CUMULÉS à 30, 60 et 90 jours, par produit.

    Source : la prévision par référence servie par le registre
    (`demande_reference` — voir docs/CRISP_DM_DEMANDE_REFERENCE.md). Mesurée sur
    18 mois de test, sa règle servie (médiane des 12 derniers mois) fait 38,3 %
    de WAPE à un mois, contre 49,4 % pour le naïf saisonnier que cette route
    servait auparavant. S'y ajoutent la borne haute à 90 jours et la méthode.
    Si le registre ne sert pas la prévision par référence, l'ancien chemin
    reprend la main.
    """
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
        pass   # repli sur l'ancien chemin ci-dessous
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


def demande_et_approvisionnement() -> Dict[str, Any]:
    """Prévision de demande (MAPE) + concentration/dépendance fournisseur."""
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        return compute_supply_demand()
    except Exception as e:
        return {"error": str(e)}
