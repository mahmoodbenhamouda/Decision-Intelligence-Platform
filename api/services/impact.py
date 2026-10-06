"""Ce que la plateforme identifie en dinars — lecture seule, agrégée.

Le service ne calcule rien : il lit la passerelle, qui lit le module d'impact,
qui lit les autres modèles. C'est la règle du projet (`ml_engine/passerelle.py`)
et elle vaut ici plus qu'ailleurs : un montant affiché au directeur ne doit pas
pouvoir différer du montant que produit `python -m ml_engine.analytics.impact`.
"""

from __future__ import annotations

from typing import Any, Dict

from ml_engine import passerelle as pw


def impact_financier() -> Dict[str, Any]:
    """Postes, hypothèses déclarées, totaux et phrases prêtes à citer."""
    try:
        return pw.impact_financier()
    except Exception as e:  # pragma: no cover
        return {"servi": False, "motif": f"indisponible : {e}"}
