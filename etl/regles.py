"""
etl/regles.py
=============
Règles de nettoyage partagées, écrites UNE fois et appliquées partout.

Chaque règle corrige un défaut mesuré sur les exports réels (voir
docs/DATA_WAREHOUSE.md, « Règles de nettoyage ») :

* dates au format américain non complété (`1/7/2024`), avec deux replis ;
* signe comptable porté par `MONTANTSIGNE_DEV` et non par les montants, qui
  sont toujours positifs, y compris sur un avoir ;
* libellés de mode de règlement incohérents (casse, espaces, `90JOURS`,
  `NULL`), regroupés sous une clé normalisée ;
* valeurs textuelles `NULL` exportées à la place d'un vide.
"""

from __future__ import annotations


def date(col: str) -> str:
    """Parsing de date robuste : format US M/D/Y d'abord, puis ISO, puis J/M/A."""
    return (f"COALESCE("
            f"TRY_STRPTIME({col}, '%m/%d/%Y'), "
            f"TRY_STRPTIME({col}, '%Y-%m-%d'), "
            f"TRY_STRPTIME({col}, '%d/%m/%Y'))::DATE")


def echeance(col: str) -> str:
    """Date d'échéance, écartée si elle tombe hors de 2000-2035 (saisie aberrante)."""
    return f"CASE WHEN year({date(col)}) BETWEEN 2000 AND 2035 THEN {date(col)} END"


def signe(col: str = "MONTANTSIGNE_DEV") -> str:
    """-1 pour un avoir (montant signé négatif), +1 sinon."""
    return f"CASE WHEN TRY_CAST({col} AS DOUBLE) < 0 THEN -1 ELSE 1 END"


def montant(col: str) -> str:
    return f"TRY_CAST({col} AS DOUBLE)"


def texte(col: str) -> str:
    """Texte nettoyé : espaces retirés, vide et `NULL` littéral ramenés à NULL."""
    return f"CASE WHEN upper(trim({col})) IN ('', 'NULL') THEN NULL ELSE trim({col}) END"


# ── Modes de règlement ───────────────────────────────────────────────────────
# La clé normalisée regroupe les variantes (« Virement 60 JOURS » et
# « Virement 60 jours ») ; le libellé affiché est la variante réelle la plus
# fréquente de chaque groupe (dim_mode_reglement).
def _mode_propre(col: str) -> str:
    return (f"regexp_replace(regexp_replace(trim({col}), '\\s+', ' ', 'g'), "
            f"'([0-9])(JOURS)', '\\1 \\2', 'g')")


def mode_cle(col: str = "MODEREGLLIBELLE") -> str:
    return (f"CASE WHEN {col} IS NULL OR upper(trim({col})) IN ('', 'NULL') "
            f"THEN 'NON RENSEIGNE' ELSE upper({_mode_propre(col)}) END")


def mode_libelle(col: str = "MODEREGLLIBELLE") -> str:
    return (f"CASE WHEN {col} IS NULL OR upper(trim({col})) IN ('', 'NULL') "
            f"THEN 'Non renseigné' ELSE {_mode_propre(col)} END")


#: Familles d'articles de démonstration résiduelles (fournitures d'art, < 1 %
#: du CA) écartées des agrégats par famille.
FAMILLES_HORS_ACTIVITE = "(^_)|PEINTURE|LITHOGRAPH|CHEVALET|PINCEAU|BROSSE|AQUARELLE|HUILE"
