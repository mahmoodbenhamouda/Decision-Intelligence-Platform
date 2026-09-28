"""
agents/copilote/verification.py
===============================
Garde-fou de dernier recours : tout montant cité par le modèle de langage doit
provenir du contexte qu'on lui a fourni.
"""

from __future__ import annotations

import re
from typing import List

# Un séparateur de milliers est suivi d'EXACTEMENT trois chiffres collés ; une
# virgule suivie d'une espace termine donc le nombre. Sans cette contrainte,
# « En 2026, 2614 factures » était lu comme le seul nombre « 2026,2614 ».
_RE_NOMBRE = re.compile("\\d+(?:[\u0020\u00a0\u202f,]\\d{3})*(?:[.,]\\d{1,2})?")
_RE_ECHELLE = re.compile(r"^\s*(M|K)\b", re.IGNORECASE)
_RE_MILLIERS = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def _valeurs_numeriques(texte: str) -> List[float]:
    """Extrait les valeurs numériques d'un texte, échelles M/K comprises.

    « 11.22 M DT », « 11 218 990 DT », « 30,396,136 » et « 2,83 M » doivent
    produire des valeurs comparables : c'est ce qui permet de vérifier qu'un
    montant cité par le modèle provient bien du contexte qu'on lui a fourni.
    """
    valeurs: List[float] = []
    for m in _RE_NOMBRE.finditer(texte):
        norm = m.group(0)
        for espace in ("\u0020", "\u00a0", "\u202f"):
            norm = norm.replace(espace, "")
        if _RE_MILLIERS.match(norm):
            norm = norm.replace(",", "")          # 30,396,136 -> milliers
        elif norm.count(",") == 1 and "." not in norm:
            norm = norm.replace(",", ".")         # 2,83 -> décimal français
        else:
            norm = norm.replace(",", "")
        try:
            v = float(norm)
        except ValueError:
            continue
        suite = _RE_ECHELLE.match(texte[m.end():])
        if suite:
            v *= 1_000_000 if suite.group(1).upper() == "M" else 1_000
        valeurs.append(v)
    return valeurs


def chiffres_non_sources(reponse: str, contexte: str,
                         seuil: float = 1000.0, tolerance: float = 0.02) -> List[float]:
    """Montants cités dans la réponse qui ne proviennent PAS du contexte fourni.

    Garde-fou de dernier recours. Le prompt interdit déjà au modèle d'inventer
    ou de calculer des montants, mais une consigne n'est pas une garantie : sur
    une question de stock, le copilote a annoncé « exposition secteur public
    30 396 136 DT » — un montant qui ne correspond à AUCUN indicateur (la vraie
    exposition récente vaut 11,2 M DT, et les établissements publics de la liste
    de relance pèsent 2,8 M DT). Toute réponse contenant un montant intraçable
    est écartée au profit du repli déterministe.

    Seuls les montants (≥ `seuil`) sont contrôlés : pourcentages, jours et
    compteurs sont trop souvent des reformulations légitimes pour être vérifiés
    de cette manière sans faux positifs.
    """
    refs = [v for v in _valeurs_numeriques(contexte) if abs(v) >= seuil]
    orphelins = []
    for v in _valeurs_numeriques(reponse):
        if abs(v) < seuil:
            continue
        if any(abs(v - r) <= tolerance * max(abs(r), 1.0) for r in refs):
            continue
        # Une année n'est pas un montant.
        if 1900 <= v <= 2100 and float(v).is_integer():
            continue
        orphelins.append(v)
    return orphelins
