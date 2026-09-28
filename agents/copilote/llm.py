"""
agents/copilote/llm.py
======================
Appels au modèle de langage (Groq, via `config.settings.get_llm`).

* `rediger` — réponse sur les données : modèle configuré, puis replis si un
  modèle est déprécié côté fournisseur, et CONTRÔLE des montants cités ;
* `interroger` — appel simple (base documentaire, fichier joint).

Sans clé, aucun appel n'est tenté : le copilote répond par ses règles.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from agents.copilote.verification import chiffres_non_sources

logger = logging.getLogger(__name__)

#: Modèle configuré (None), puis replis automatiques si un modèle est retiré
#: côté Groq (ex. retrait des llama-3.x en 2026).
MODELES = (None, "openai/gpt-oss-20b", "gemma2-9b-it")


def cle_disponible() -> bool:
    return bool(os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY"))


def _texte(res) -> str:
    return getattr(res, "content", str(res))


def _valide(txt: str) -> bool:
    return bool(txt) and "[Mode mock" not in txt


def rediger(prompt: str) -> Optional[str]:
    """Réponse du modèle, ou None si aucun modèle ne répond — ou si la réponse
    cite un montant absent du prompt : un chiffre faux discrédite l'ensemble, la
    réponse déterministe est alors préférée."""
    try:
        from config.settings import get_llm
        llm = get_llm()
    except Exception:
        return None
    for modele in MODELES:
        try:
            res = (get_llm(model=modele) if modele else llm).invoke(prompt)
            txt = _texte(res)
            if _valide(txt):
                orphelins = chiffres_non_sources(txt, prompt)
                if orphelins:
                    logger.warning(
                        "Réponse LLM écartée — %d montant(s) non traçable(s) : %s",
                        len(orphelins), ", ".join(f"{v:,.0f}" for v in orphelins[:5]))
                    return None
                return txt.strip()
        except Exception:
            continue
    return None


def interroger(prompt: str) -> Optional[str]:
    """Un appel, sans contrôle des montants (le contexte n'est pas chiffré)."""
    try:
        from config.settings import get_llm
        txt = _texte(get_llm().invoke(prompt))
        return txt.strip() if _valide(txt) else None
    except Exception:
        return None
