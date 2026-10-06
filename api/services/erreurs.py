"""Erreurs métier levées par les services."""

from __future__ import annotations

from typing import Any


class ErreurMetier(Exception):
    """Base de toutes les erreurs métier."""

    def __init__(self, detail: Any):
        super().__init__(detail if isinstance(detail, str) else repr(detail))
        self.detail = detail


class DonneesInvalides(ErreurMetier):
    """La demande est lisible mais ne respecte pas une règle (valeur hors liste…)."""


class IdentifiantsInvalides(ErreurMetier):
    """Adresse ou mot de passe incorrect."""


class AccesRefuse(ErreurMetier):
    """L'utilisateur est authentifié mais n'a pas droit à cette opération."""


class Introuvable(ErreurMetier):
    """L'objet demandé n'existe pas — ou n'est pas visible par cet utilisateur."""


class Conflit(ErreurMetier):
    """L'opération contredit l'état actuel (doublon, déjà confié, retiré…)."""


class TropDeTentatives(ErreurMetier):
    """Limite de tentatives atteinte (protection contre la force brute)."""


class ErreurInterne(ErreurMetier):
    """Défaut de configuration du serveur (dépendance absente, liste désalignée)."""
