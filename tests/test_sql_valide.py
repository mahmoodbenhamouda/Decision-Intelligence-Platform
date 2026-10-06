"""Toute requête écrite dans le code doit être analysable par le moteur.

Ce garde-fou naît d'une faute réelle : un nettoyage de vocabulaire a appliqué
une expression régulière à l'ensemble des fichiers pour retirer une mention
technique d'un TEXTE affiché. Elle a aussi frappé du CODE, transformant
`sum(nbr_article)` en `sum` dans deux requêtes. Le tableau de bord affichait
alors « Referenced column "sum" not found » à l'utilisateur.

Les tests fonctionnels ne l'ont pas vu : ces deux requêtes vivent dans un
chemin que la suite n'exerçait pas. Un contrôle de FORME les aurait vues tout
de suite, sans base de données ni jeu d'essai — c'est ce qu'on ajoute ici.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIERS = ("api", "ml_engine", "agents", "etl")

#: Une chaîne est tenue pour une requête si elle commence par un verbe SQL.
DEBUT_SQL = re.compile(r"^\s*(WITH|SELECT|CREATE|INSERT|UPDATE|DELETE|DROP)\b",
                       re.IGNORECASE)

#: Fonctions d'agrégat : toujours suivies d'une parenthèse ouvrante.
AGREGATS = ("sum", "avg", "count", "min", "max", "median", "stddev_samp",
            "mode", "any_value", "coalesce", "round", "abs")


def _requetes(chemin: Path):
    """Chaînes du module qui ressemblent à des requêtes."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
            if DEBUT_SQL.match(noeud.value):
                yield noeud.lineno, noeud.value


def _toutes_les_requetes():
    for dossier in DOSSIERS:
        for chemin in sorted((RACINE / dossier).rglob("*.py")):
            for ligne, requete in _requetes(chemin):
                yield chemin, ligne, requete


def test_aucun_agregat_sans_parentheses():
    """`sum q` au lieu de `sum(q)` : la faute exacte qui a cassé l'écran.

    Le détecteur est d'abord vérifié sur la requête fautive d'origine — un
    contrôle incapable de voir ce qu'il surveille ne vaut rien.
    """
    motif = re.compile(r"\b(" + "|".join(AGREGATS) + r")\s+(?!\()",
                       re.IGNORECASE)

    fautive = "SELECT strftime(date,'%Y-%m') m, sum q FROM sales GROUP BY m"
    assert motif.search(fautive), "le détecteur ne reconnaît plus la faute d'origine"
    saine = "SELECT strftime(date,'%Y-%m') m, sum(nbr_article) q FROM sales GROUP BY m"
    assert not motif.search(saine), "le détecteur signale une requête correcte"

    fautifs = []
    for chemin, ligne, requete in _toutes_les_requetes():
        # Les mots-clés qui suivent légitimement un agrégat dans une clause.
        nettoyee = re.sub(r"\b(sum|avg|count|min|max|median)\s+(AS|FROM|BY|OVER)\b",
                          "", requete, flags=re.IGNORECASE)
        if motif.search(nettoyee):
            extrait = " ".join(requete.split())[:100]
            fautifs.append(f"{chemin.relative_to(RACINE)}:{ligne} — {extrait}")

    assert not fautifs, (
        "Agrégat sans parenthèses (la requête échouera à l'exécution) :\n    "
        + "\n    ".join(fautifs))


def test_les_requetes_du_moteur_de_demande_s_executent():
    """Les deux requêtes cassées sont vérifiées À L'EXÉCUTION, pas en forme.

    Un contrôle syntaxique général produisait trop de faux positifs : beaucoup
    de requêtes du projet sont des FRAGMENTS assemblés ailleurs, que l'analyseur
    refuse isolément. Un test qui signale à tort finit ignoré, ce qui est pire
    que pas de test. On exerce donc le chemin réel, celui qui a cassé."""
    from ml_engine.analytics.demand_engine import compute_supply_demand
    from ml_engine.forecasting import demande_hybride as dh

    mois, serie = dh.charger_serie()
    assert len(mois) == len(serie)
    assert len(serie) > 12, "série de demande vide : la requête ne renvoie rien"
    assert serie.sum() > 0, "demande nulle sur tout l'historique"

    r = compute_supply_demand()
    assert not r.get("error"), r.get("error")
    assert r["demande_mensuelle"], "aucune demande mensuelle"
    assert all(p["qte"] >= 0 for p in r["demande_mensuelle"])


@pytest.mark.parametrize("agregat", ["sum", "count", "avg", "median"])
def test_le_motif_couvre_les_agregats_courants(agregat):
    """Une liste trouée ne protège que ce dont on se souvient."""
    assert agregat in AGREGATS
