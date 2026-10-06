"""Devis à relancer, marge à surveiller, produits à proposer, CA attendu.

Chaque fonction applique la règle de portée des filtres (`ml_engine.portee`) :
restreinte aux clients filtrés, ou masquée quand le filtre n'a pas de sens pour
une prévision."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from api.services.serialisation import json_safe
from ml_engine import passerelle as pw
from ml_engine import portee as po


def _avec_noms(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ajoute le nom d'établissement à chaque ligne : un directeur lit des noms, pas des codes ERP."""
    try:
        noms = pw.noms_clients()
        for ligne in data.get("top") or []:
            code = str(ligne.get("client") or "")
            ligne["nom"] = ligne.get("nom") or noms.get(code, code)
    except Exception:
        pass
    return data


def _servir(filtres: Optional[Dict[str, Any]],
            calcul: Callable[[Optional[list]], Dict[str, Any]]) -> Dict[str, Any]:
    p = po.portee(filtres)
    cache = po.pour_analyse_par_client(p)
    if cache:
        return cache
    try:
        return po.annoter(_avec_noms(calcul(p["clients"])), p)
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}


def devis_a_relancer(limite: int, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Devis ouverts, classés par espérance de chiffre d'affaires (probabilité × montant HT).

    `limite` monte à 400 : la liste des devis ouverts se consulte en entier, un
    décompte sans liste ne permet aucune action. Les repères de conversion
    constatée l'accompagnent, parce qu'une espérance sans son taux de référence
    laisse croire qu'un devis de 500 K se signe comme un devis de 3 K."""
    n = max(1, min(400, limite))
    data = _servir(filtres, lambda cl: pw.devis_a_relancer(limite=n, clients=cl))
    if data.get("servi"):
        p = po.portee(filtres)
        try:
            data["reperes"] = pw.reperes_conversion(clients=p.get("clients"))
        except Exception:
            pass
        # La calibration ne dépend d'AUCUN filtre : elle est mesurée une fois
        # sur le test hors période du modèle. La filtrer par client n'aurait
        # pas de sens — et la recalculer sur trois clients non plus.
        try:
            data["calibration"] = pw.calibration_devis()
        except Exception:
            pass
    return data


def marge_a_surveiller(limite: int, filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Clients dont la marge risque de s'éroder au prochain trimestre, classés par marge en jeu."""
    n = max(1, min(100, limite))
    return _servir(filtres, lambda cl: pw.marge_a_surveiller(limite=n, clients=cl))


def recommandations(client: Optional[str], limite: int,
                    filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Produits qu'un client n'a jamais achetés et qu'il est susceptible d'adopter."""
    if client:
        try:
            return json_safe(pw.recommandations(client=str(client)))
        except Exception as e:
            return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}
    n = max(1, min(100, limite))
    return json_safe(_servir(filtres, lambda cl: pw.recommandations(n_clients=n, clients=cl)))


def ca_client(limite: int, horizon: int = 3,
              filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Chiffre d'affaires attendu par client sur les H prochains mois."""
    return _servir(filtres, lambda cl: pw.ca_client(horizon=horizon, limite=limite, clients=cl))
