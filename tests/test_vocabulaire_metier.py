"""L'application parle gestion, jamais informatique.

Un directeur financier n'a pas à savoir quel logiciel stocke ses factures, ni
comment s'appelle la colonne qui porte le coût de revient. Chaque fois qu'un
texte affiché dit « l'ERP n'exporte pas » plutôt que « ce n'est pas
enregistré », il demande à son lecteur de comprendre l'outil avant de
comprendre son entreprise.

Ce test est un GARDE-FOU, pas un contrôle de style : il parcourt les chaînes de
caractères susceptibles d'être affichées et refuse le vocabulaire technique.
Les commentaires et les docstrings sont exclus — ils s'adressent au
développeur, qui a le droit de lire le nom réel des champs.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

#: Dossiers dont les chaînes peuvent remonter jusqu'à un écran.
DOSSIERS = ("api", "ml_engine", "agents")

#: Vocabulaire interdit dans un texte affiché, et ce qu'il faudrait dire.
INTERDITS = {
    r"\bERP\b": "dire « vos factures », « vos écritures » ou « la comptabilité »",
    r"\bMTCRSIGNE\b": "dire « le coût de revient de la ligne »",
    r"\bETATPIECE\b": "dire « le statut du devis »",
    r"\bDuckDB\b": "ne pas nommer la base de données",
    r"\bjoblib\b": "ne pas nommer la librairie",
    r"\bpickl\w+\b": "ne pas nommer le format de sérialisation",
    r"\bbackend\b": "dire « l'application »",
    r"\bfrontend\b": "dire « l'écran »",
}

#: Ce qui n'est pas un texte affiché : requêtes, chemins, commandes, journaux.
TECHNIQUE = re.compile(
    r"\bSELECT\b|\bFROM\b|\bCREATE\b|\bGROUP BY\b|\bWHERE\b|\bJOIN\b"
    r"|\.(json|joblib|csv|duckdb|py|parquet)\b|python -m |models/|reports/"
    r"|^\s*\[[a-z_]+\]|/api/|^https?://",
    re.IGNORECASE | re.MULTILINE)

#: En deçà, une chaîne est un identifiant ou une clé, pas une phrase.
LONGUEUR_MINIMALE = 20


def _textes_affichables(chemin: Path):
    """Chaînes du module hors docstrings, requêtes, chemins et journaux."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return

    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef,
                              ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(noeud, clean=False)
            if d:
                docstrings.add(d)

    for noeud in ast.walk(arbre):
        if not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)):
            continue
        texte = noeud.value
        if (texte in docstrings or len(texte) < LONGUEUR_MINIMALE
                or TECHNIQUE.search(texte)):
            continue
        yield noeud.lineno, texte


def test_aucun_jargon_informatique_dans_les_textes_affiches():
    """Le garde-fou est d'abord vérifié sur une phrase fautive connue.

    Un contrôle incapable de voir ce qu'il surveille ne vaut rien : celle-ci
    est l'ancienne formulation, retirée de l'application."""
    fautive = ("L'ERP n'enregistre aucune date de règlement : impossible de "
               "savoir si un client a payé.")
    assert any(re.search(m, fautive) for m in INTERDITS), (
        "le détecteur ne reconnaît plus le défaut d'origine")

    fautifs = []
    for dossier in DOSSIERS:
        for chemin in sorted((RACINE / dossier).rglob("*.py")):
            for ligne, texte in _textes_affichables(chemin):
                for motif, conseil in INTERDITS.items():
                    if re.search(motif, texte, re.IGNORECASE):
                        fautifs.append(
                            f"{chemin.relative_to(RACINE)}:{ligne} — "
                            f"{conseil}\n      « {' '.join(texte.split())[:110]} »")

    assert not fautifs, (
        "Vocabulaire informatique dans des textes affichés :\n    "
        + "\n    ".join(fautifs))


@pytest.mark.parametrize("terme", ["ERP", "MTCRSIGNE", "ETATPIECE"])
def test_le_vocabulaire_interdit_est_couvert(terme):
    """Chaque terme banni doit avoir son motif : une liste trouée ne protège
    que ce dont on se souvient."""
    assert any(re.search(m, terme) for m in INTERDITS)
