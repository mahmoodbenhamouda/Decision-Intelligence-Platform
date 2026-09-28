"""
agents/copilote/outils.py
=========================
Les outils du copilote : les MÊMES briques que le reste de la plateforme.

* indicateurs du périmètre (moteur KPI sur l'entrepôt) ;
* radar financier (actions prioritaires chiffrées) ;
* prévision du chiffre d'affaires (régression linéaire sur 12 mois) ;
* stock réel reconstruit des factures, fin de commercialisation, stock par
  client ; demande et dépendance fournisseur.

Aucun outil n'importe un module de modèle : les sorties de modèles passent par
`ml_engine.passerelle`, qui applique les décisions du registre.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ml_engine.analytics import kpi_engine


def fmt(v, suffix="DT") -> str:
    """Montant lisible : 12.35 M DT, 763.4 K DT, 812.00 DT ; « N/D » si absent."""
    if v is None:
        return "N/D"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"{v / 1_000_000:.2f} M {suffix}"
    if abs(v) >= 1_000:
        return f"{v / 1_000:.1f} K {suffix}"
    return f"{v:.2f} {suffix}"


def codes_perimetre(filters: Optional[Dict[str, Any]]) -> List[str]:
    """Codes clients du périmètre (vide = tous)."""
    return [str(c) for c in ((filters or {}).get("selected_clients") or [])]


def dt_montant(v: Any) -> str:
    """Montant exact en dinars, séparateur de milliers : « 1 403 200 DT »."""
    try:
        return f"{float(v):,.0f} DT".replace(",", " ")
    except Exception:
        return "N/D"


# ── Indicateurs et radar ─────────────────────────────────────────────────────
def indicateurs(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Indicateurs du périmètre, calculés sur l'entrepôt."""
    kpis = kpi_engine.compute_dashboard(filters)
    return kpis if isinstance(kpis, dict) else {}


def radar(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Actions prioritaires chiffrées, mesurées sur les seules données internes."""
    return kpi_engine.finance_radar({}, filters)


# ── Prévision (régression linéaire 12 mois → 3 mois) ─────────────────────
def prevision_lineaire(monthly: List[Dict[str, Any]], horizon: int = 3) -> List[Dict[str, Any]]:
    """Projection du CA : régression linéaire sur les 12 derniers mois."""
    pts = [float(m.get("revenue") or 0) for m in (monthly or [])][-12:]
    periods = [m.get("period") for m in (monthly or [])][-12:]
    if len(pts) < 3:
        return []
    n = len(pts)
    xs = list(range(n))
    sx, sy = sum(xs), sum(pts)
    sxy = sum(x * y for x, y in zip(xs, pts))
    sxx = sum(x * x for x in xs)
    denom = (n * sxx - sx * sx) or 1
    a = (n * sxy - sx * sy) / denom
    b = (sy - a * sx) / n
    try:
        y, mo = map(int, str(periods[-1]).split("-")[:2])
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for k in range(1, horizon + 1):
        m2 = mo + k
        y2 = y + (m2 - 1) // 12
        m2 = ((m2 - 1) % 12) + 1
        out.append({"period": f"{y2:04d}-{m2:02d}", "montant": float(max(0.0, a * (n - 1 + k) + b))})
    return out


# ── Stock et approvisionnement ───────────────────────────────────────────────
def contexte_stock_reel(kpis: Dict[str, Any]) -> Dict[str, Any]:
    """Réponse aux questions de risque de stock SANS le modèle retiré.

    Le copilote importait `score_stock_risk` directement : un modèle retiré par
    le registre, dont la cible dépend de dates de péremption simulées. Il passe
    désormais par la passerelle, qui renvoie la carte du modèle (retiré) et
    jamais ses scores ; les chiffres viennent des flux RÉELS reconstruits des
    factures et de la règle de fin de commercialisation.
    """
    from ml_engine import passerelle as pw
    rs = pw.risque_stock()
    flux = kpis.get("stock_flux_reel") or {}
    fdv = pw.fin_de_vie(limite=5)
    return {"risque_stock": rs, "flux": flux, "fin_de_vie": fdv}


def demande_et_fournisseurs() -> Dict[str, Any]:
    """Dépendance fournisseur et prévision de demande (articles par mois)."""
    try:
        from ml_engine.analytics.demand_engine import compute_supply_demand
        return compute_supply_demand()
    except Exception:
        return {}


def stock_par_client(limite: int = 5) -> Dict[str, Any]:
    """Croisement client × stock (stock simulé, demande réelle)."""
    try:
        from ml_engine.stock import classer_clients_par_risque
        return classer_clients_par_risque(limit=limite)
    except Exception as e:
        return {"error": str(e)}

