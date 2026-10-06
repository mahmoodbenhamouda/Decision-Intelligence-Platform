"""Copilote conversationnel FinBot : questions en langage naturel et fichiers joints (CSV, PDF…"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from api.auth.models import User
from api.core import moteurs
from api.schemas.filtres import CopilotRequest
from api.services.fichiers import extract_from_csv, extract_from_pdf
from api.services.filtres import filtres_moteur, resume_filtres

logger = logging.getLogger("api")

QUESTION_PAR_DEFAUT = "Quelles sont mes priorités financières du moment ?"


def repondre(req: CopilotRequest) -> Dict[str, Any]:
    """Réponse à une question, avec l'historique de la conversation."""
    q = (req.question or "").strip() or QUESTION_PAR_DEFAUT
    if not moteurs.agent_disponible():
        return {"answer": "Le copilote est indisponible.", "via": "error"}
    try:
        res = moteurs.copilote.repondre(filtres_moteur(req), question=q,
                                        historique=req.history or [])
        return {
            "answer": res["text"] or "Je n'ai pas pu générer une réponse.",
            "via": res["via"],
            "question": q,
            "active_filters": resume_filtres(req),
        }
    except Exception as e:
        return {"answer": f"Désolé, une erreur est survenue : {e}", "via": "error"}


def analyser_document(nom: str, extension: str, contenu: bytes, question: str,
                      filtres_json: str, user: User) -> Dict[str, Any]:
    """Analyse un CSV ou un PDF textuel et répond à la question posée, en croisant avec les indicateurs…"""
    try:
        filtres: Dict[str, Any] = json.loads(filtres_json) if filtres_json.strip() else {}
    except json.JSONDecodeError:
        filtres = {}
    if not isinstance(filtres, dict):
        filtres = {}

    extraction = (extract_from_csv(contenu, nom) if extension == ".csv"
                  else extract_from_pdf(contenu, nom))

    if extraction.get("scanned"):
        return {
            "answer": (
                f"## PDF scanné détecté : `{nom}`\n\n"
                "Ce document ne contient pas de texte : c'est une image scannée.\n\n"
                "**Utilisez l'onglet « Documents »** — il extrait le texte, "
                "reconnaît les champs d'une facture (n°, dates, HT/TVA/TTC) et la "
                "rapproche automatiquement de vos écritures."),
            "via": "regles", "file_type": "pdf", "filename": nom,
            "extracted_text": "", "radar": [],
        }

    texte = extraction.get("extracted_text", "")
    resume_fichier = extraction.get("summary", "")

    kpis: Dict[str, Any] = {}
    radar: List[Any] = []
    try:
        kpis = moteurs.kpi_engine.compute_dashboard(filtres) or {}
        radar = kpis.get("finance_radar", [])
    except Exception:
        pass

    answer, via = "", "regles"
    try:
        from agents.copilote import analyser_fichier
        answer = analyser_fichier(question, extension, resume_fichier, texte, kpis) or ""
        if answer:
            via = "llm"
    except Exception as e:
        logger.warning("[upload] copilote indisponible : %s", e)

    if not answer:
        via = "regles"
        if extension == ".csv":
            answer = (f"## Analyse du fichier CSV : `{nom}`\n\n{texte}\n\n"
                      f"**Synthèse locale** : {extraction.get('rows', 0)} lignes, "
                      f"{extraction.get('cols', 0)} colonnes. Dimensions, colonnes et "
                      "premiers indicateurs numériques extraits.")
        else:
            answer = (f"## Analyse du PDF : `{nom}`\n\n"
                      f"### Contenu extrait\n```text\n{texte[:1500]}\n```\n\n"
                      "### Synthèse locale\n"
                      "- Le texte du document a été extrait et nettoyé.\n"
                      "- Montants, dates et libellés sont exploitables par le copilote.\n"
                      "- Pour un contrôle comptable, vérifiez totaux, taxes et remises.")

    return {
        "answer": answer,
        "via": via,
        "file_type": extension.lstrip("."),
        "filename": nom,
        "extracted_text": (texte[:500] + "…") if len(texte) > 500 else texte,
        "radar": [{k: v for k, v in r.items()
                   if k in ("titre", "categorie", "severite", "montant_dt", "montant_label")}
                  for r in (radar or [])[:4]],
    }
