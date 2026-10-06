"""Garde-fou de dernier recours : tout montant cité par le modèle de langage doit provenir du…"""

from __future__ import annotations

import re
from typing import List

_RE_NOMBRE = re.compile("\\d+(?:[\u0020\u00a0\u202f,]\\d{3})*(?:[.,]\\d{1,2})?")
_RE_ECHELLE = re.compile(r"^\s*(M|K)\b", re.IGNORECASE)
_RE_MILLIERS = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def _valeurs_numeriques(texte: str) -> List[float]:
    """Extrait les valeurs numériques d'un texte, échelles M/K comprises."""
    valeurs: List[float] = []
    for m in _RE_NOMBRE.finditer(texte):
        norm = m.group(0)
        for espace in ("\u0020", "\u00a0", "\u202f"):
            norm = norm.replace(espace, "")
        if _RE_MILLIERS.match(norm):
            norm = norm.replace(",", "")
        elif norm.count(",") == 1 and "." not in norm:
            norm = norm.replace(",", ".")
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
    """Montants cités dans la réponse qui ne proviennent PAS du contexte fourni."""
    refs = [v for v in _valeurs_numeriques(contexte) if abs(v) >= seuil]
    orphelins = []
    for v in _valeurs_numeriques(reponse):
        if abs(v) < seuil:
            continue
        if any(abs(v - r) <= tolerance * max(abs(r), 1.0) for r in refs):
            continue
        if 1900 <= v <= 2100 and float(v).is_integer():
            continue
        orphelins.append(v)
    return orphelins
