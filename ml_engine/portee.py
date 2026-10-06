"""Portée des filtres du tableau de bord sur les modèles.

Les KPI se recalculent sur n'importe quel sous-ensemble de factures. Un modèle,
lui, prédit l'avenir de chaque CLIENT à partir de tout son historique. D'où une
règle unique, appliquée partout (API, tableau de bord, flotte d'agents) :

* filtre client ou fidélité  → les modèles PAR CLIENT se restreignent aux
  clients retenus ; les analyses GLOBALES (types de clients, demande, stock,
  fournisseurs, échéancier) sont masquées : elles ne parlent pas d'un client ;
* filtre de période          → toutes les prévisions sont masquées : elles
  portent sur les mois à venir et ne se recalculent pas pour le passé ;
* filtre de facture (mode de paiement, montant, niveau de retard)
                              → toutes les prévisions sont masquées : ces
  critères décrivent des factures, les modèles raisonnent par client.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

GLOBAL = "global"
CLIENTS = "clients"
MASQUE = "masque"

MOTIF_PERIODE = ("Les prévisions portent sur les mois à venir : elles ne se "
                 "recalculent pas pour une période passée. Retirez le filtre "
                 "d'année ou de dates pour les afficher.")
MOTIF_FACTURE = ("Les filtres mode de paiement, montant et retard décrivent des "
                 "factures, alors que les prévisions raisonnent par client. "
                 "Retirez-les pour afficher cette analyse.")
MOTIF_GLOBAL = ("Cette analyse porte sur toute l'entreprise, pas sur un client : "
                "retirez le filtre client ou fidélité pour l'afficher.")
MOTIF_VIDE = "Aucun des clients retenus par le filtre n'est concerné."


def _actif(v: Any) -> bool:
    return v not in (None, "", [], "Tous")


def clients_fidelite(fidelite: str) -> List[str]:
    """Clients du segment de fidélité, sur tout l'historique (même règle que les KPI)."""
    from ml_engine.analytics.kpi_engine import _connect
    con = _connect()
    try:
        rows = con.execute(
            "SELECT client, count(*) FROM sales WHERE client IS NOT NULL GROUP BY client"
        ).fetchall()
    finally:
        con.close()
    if "Fid" in fidelite:
        return [str(c) for c, n in rows if n > 5]
    if "gul" in fidelite:
        return [str(c) for c, n in rows if 2 <= n <= 5]
    return [str(c) for c, n in rows if n == 1]


def portee(filtres: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{mode, clients, motif} : ce que les modèles peuvent montrer sous ces filtres."""
    f = filtres or {}
    if _actif(f.get("selected_years")) or _actif(f.get("date_start")) or _actif(f.get("date_end")):
        return {"mode": MASQUE, "clients": None, "motif": MOTIF_PERIODE}
    if (_actif(f.get("payment_modes")) or _actif(f.get("risk_level"))
            or f.get("min_amount") is not None or f.get("max_amount") is not None):
        return {"mode": MASQUE, "clients": None, "motif": MOTIF_FACTURE}

    clients: Optional[List[str]] = None
    if _actif(f.get("selected_clients")):
        clients = [str(c) for c in f["selected_clients"]]
    if _actif(f.get("fidelity_filter")):
        try:
            fid = set(clients_fidelite(str(f["fidelity_filter"])))
        except Exception:
            fid = set()
        clients = [c for c in clients if c in fid] if clients is not None else sorted(fid)
    if clients is not None:
        return {"mode": CLIENTS, "clients": clients, "motif": MOTIF_GLOBAL}
    return {"mode": GLOBAL, "clients": None, "motif": ""}


def masque(p: Dict[str, Any], motif: Optional[str] = None) -> Dict[str, Any]:
    return {"servi": False, "masque": True, "portee": p["mode"],
            "motif": motif or p["motif"]}


def pour_analyse_globale(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Réponse de masquage d'une analyse globale, ou None si elle s'affiche."""
    return None if p["mode"] == GLOBAL else masque(p)


def pour_analyse_par_client(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Réponse de masquage d'une analyse par client, ou None si elle s'affiche."""
    return masque(p) if p["mode"] == MASQUE else None


def annoter(data: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
    """Signale au lecteur que la liste est restreinte au filtre (et pourquoi elle peut être vide)."""
    if not isinstance(data, dict):
        return data
    out = {**data, "portee": p["mode"]}
    if p["mode"] == CLIENTS:
        out["n_clients_filtre"] = len(p["clients"] or [])
        if data.get("servi") and not data.get("top"):
            out["motif"] = MOTIF_VIDE
    return out
