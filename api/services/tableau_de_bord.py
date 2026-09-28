"""
api/services/tableau_de_bord.py
===============================
Indicateurs du tableau de bord et synthèse écrite.

Chaîne de repli, du plus riche au plus simple :

  1. le COPILOTE orchestre les outils et produit tout (indicateurs, scoring ML,
     prévision, anomalies) avec une trace d'exécution visible ;
  2. le moteur d'indicateurs direct, sans orchestration ;
  3. sinon, une erreur explicite. Il n'existe qu'UN entrepôt et qu'un jeu de
     règles de calcul : afficher des chiffres calculés autrement (l'ancien
     calcul pandas comptait les avoirs comme des ventes) serait pire que de
     dire que l'entrepôt est indisponible.

La requête reçue est déjà réduite au périmètre de l'utilisateur
(`perimetre.restreindre`) ; seules les options de filtre le sont ici.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from api.auth.models import User
from api.core import moteurs
from api.schemas.filtres import FilterRequest
from api.services.filtres import filtres_moteur, resume_filtres
from api.services.perimetre import options_visibles
from api.services.rapport import build_dynamic_report
from api.services.serialisation import json_safe

logger = logging.getLogger("api")

_ENTREPOT_INDISPONIBLE = ("Entrepôt de données indisponible : lancer "
                          "python -m etl.construire, puis réessayer.")


def indicateurs(req: FilterRequest, user: User) -> Dict[str, Any]:
    """Indicateurs, options de filtre et, si l'agent répond, sa trace."""
    if moteurs.agent_disponible():
        try:
            out = moteurs.copilote.tableau_de_bord(filtres_moteur(req))
            return {
                "kpis": json_safe(out["kpis"]),
                "filters": options_visibles(moteurs.kpi_engine.get_filter_options(), user),
                "active_filters": resume_filtres(req),
                "agent_trace": out["trace"],
                "agent": out["meta"],
            }
        except Exception as e:
            logger.warning("[dashboard] copilote indisponible (%s); repli moteur direct.", e)

    if moteurs.moteur_disponible():
        try:
            kpis = moteurs.kpi_engine.compute_dashboard(filtres_moteur(req))
            return {
                "kpis": json_safe(kpis),
                "filters": options_visibles(moteurs.kpi_engine.get_filter_options(), user),
                "active_filters": resume_filtres(req),
            }
        except Exception as e:
            logger.warning("[dashboard] moteur d'indicateurs indisponible (%s).", e)

    return {"error": _ENTREPOT_INDISPONIBLE + (f" ({moteurs.ERREUR_MOTEUR})"
                                               if moteurs.ERREUR_MOTEUR else "")}


def synthese(req: FilterRequest) -> Dict[str, Any]:
    """Synthèse écrite, en mode HYBRIDE.

    - couche LLM (Groq) si une clé est présente → réponse en langage naturel ;
    - sinon repli déterministe (`build_dynamic_report`) → synthèse fiable codée.
    """
    if moteurs.agent_disponible():
        try:
            res = moteurs.copilote.repondre(filtres_moteur(req))
            kpis = json_safe(res["kpis"])
            insight = res["text"] or build_dynamic_report(kpis)
            return {"insight": insight, "kpis_used": kpis,
                    "via": res["via"], "active_filters": resume_filtres(req)}
        except Exception as e:
            logger.warning("[ai_insight] copilote indisponible (%s); repli moteur direct.", e)

    kpis = None
    if moteurs.moteur_disponible():
        try:
            kpis = json_safe(moteurs.kpi_engine.compute_dashboard(filtres_moteur(req)))
        except Exception as e:
            logger.warning("[ai_insight] moteur d'indicateurs indisponible (%s).", e)
    if kpis is None:
        return {"error": _ENTREPOT_INDISPONIBLE}

    return {"insight": build_dynamic_report(kpis), "kpis_used": kpis,
            "via": "regles", "active_filters": resume_filtres(req)}
