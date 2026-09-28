"""
api/services/commercial.py
==========================
Devis à relancer, marge à surveiller, produits à proposer.

Les listes sont classées par ENJEU (probabilité × montant), jamais par
probabilité seule : un devis quasi certain à 400 DT n'appelle aucune relance,
un devis probable à 200 000 DT en appelle une. Chaque modèle n'est servi que si
le registre l'autorise (`ml_engine.passerelle`).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from api.auth.models import User
from api.services.perimetre import code_client_impose
from api.services.serialisation import json_safe
from ml_engine import passerelle as pw


def _avec_noms(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ajoute le nom d'établissement à chaque ligne : un directeur lit des noms,
    pas des codes ERP."""
    try:
        noms = pw.noms_clients()
        for ligne in data.get("top") or []:
            code = str(ligne.get("client") or "")
            ligne["nom"] = noms.get(code, code)
    except Exception:
        pass
    return data


def devis_a_relancer(limite: int) -> Dict[str, Any]:
    """Devis ouverts, classés par espérance de chiffre d'affaires (probabilité
    de signature × montant HT).

    La cible est un état ERP décodé (`ETATPIECE=8`), validé empiriquement à
    89,4 % d'appariement facture. Les devis de moins de six mois sont exclus de
    l'APPRENTISSAGE — ils n'ont pas eu le temps d'être signés — mais ce sont
    précisément ceux renvoyés ici : les seuls encore relançables."""
    try:
        return _avec_noms(pw.devis_a_relancer(limite=max(1, min(100, limite))))
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def marge_a_surveiller(limite: int) -> Dict[str, Any]:
    """Clients dont la marge risque de s'éroder au prochain trimestre, classés
    par marge en jeu (probabilité × CA 12 mois × taux de marge).

    Le modèle ne dit pas POURQUOI la marge s'érode : la décision tarifaire reste
    commerciale, le modèle désigne où regarder."""
    try:
        return _avec_noms(pw.marge_a_surveiller(limite=max(1, min(100, limite))))
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def recommandations(client: Optional[str], limite: int, user: User) -> Dict[str, Any]:
    """Produits qu'un client n'a jamais achetés et qu'il est susceptible
    d'adopter (précalculés : l'API ne dépend pas de PyTorch).

    Un compte client ne reçoit que SES recommandations, quel que soit le
    paramètre `client` envoyé."""
    impose = code_client_impose(user)
    if impose is not None:
        client = impose
    try:
        if client:
            return json_safe(pw.recommandations(client=str(client)))
        return json_safe(pw.recommandations(n_clients=max(1, min(100, limite))))
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}
