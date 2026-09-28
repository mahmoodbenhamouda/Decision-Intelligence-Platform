"""
api/services/perimetre.py
=========================
ISOLATION CÔTÉ SERVEUR du périmètre de données.

Pour un compte `client`, le périmètre est FORCÉ sur son `client_code`, quelles
que soient les valeurs envoyées par le navigateur ; le `directeur` garde la
main sur ses filtres. Manipuler la requête ne change rien : le filtre n'est pas
masqué dans l'interface, il est réécrit ici.

Toutes les routes analytiques filtrables passent par ce module — tableau de
bord, synthèse, copilote (question et fichier joint), briefing, scénarios
d'encaissement, recommandations. Le décrochage, le portail et l'OCR, dont le
filtrage porte sur des lignes précises, appliquent la même règle dans leur
propre service.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.auth.models import ROLE_DIRECTEUR, ROLE_EMPLOYE, User
from api.schemas.filtres import FilterRequest
from api.services.erreurs import AccesRefuse


def code_client_impose(user: User) -> Optional[str]:
    """Code client auquel l'utilisateur est restreint ; None pour le directeur.

    - `directeur` : aucune restriction (vue globale ou filtrée à sa guise) ;
    - `employe`   : refus. Un employé travaille sur des TÂCHES : aucun
      périmètre de données ne lui est ouvert, plutôt qu'une vue vide qu'un
      oubli d'interface pourrait remplir ;
    - `client`    : son `client_code` ; sans code, refus — aucune donnée
      plutôt que toutes.
    """
    if user.role == ROLE_DIRECTEUR:
        return None
    if user.role == ROLE_EMPLOYE:
        raise AccesRefuse("Un compte employé n'a pas accès aux tableaux de bord.")
    if not user.client_code:
        raise AccesRefuse("Compte client sans code client associé.")
    return user.client_code


def restreindre(req: FilterRequest, user: User) -> FilterRequest:
    """La requête de filtres, réduite au périmètre de l'utilisateur."""
    code = code_client_impose(user)
    if code is not None:
        req.selected_clients = [code]
    return req


def restreindre_filtres(filtres: Dict[str, Any], user: User) -> Dict[str, Any]:
    """Même règle, pour des filtres reçus sous forme de dictionnaire."""
    code = code_client_impose(user)
    if code is None:
        return filtres
    return {**filtres, "selected_clients": [code]}


def options_visibles(options: Dict[str, Any], user: User) -> Dict[str, Any]:
    """Un client ne doit pas voir la liste des autres clients dans les filtres."""
    if user.role == ROLE_DIRECTEUR or not isinstance(options, dict):
        return options
    options = dict(options)
    code = user.client_code
    options["available_clients"] = [code] if code else []
    names = options.get("client_names") or {}
    if isinstance(names, dict):
        options["client_names"] = {code: names.get(code, code)} if code else {}
    return options
