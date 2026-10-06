"""GET /api/stock capital immobilisé, ruptures, non écoulable, fin de vie GET /api/stock/risk…"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.services import approvisionnement, commandes, stock
from api.services.filtres import filtres_depuis_query

router = APIRouter(tags=["stock"])


@router.get("/api/stock")
def stock_kpis(famille: str | None = None,
               client: str | None = None, filtres: str = "{}",
               user: User = Depends(require_directeur),
               db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock")
    return stock.indicateurs_stock(filtres_depuis_query(filtres))


@router.get("/api/stock/risk")
def stock_risk_scoring(client: str | None = None, limit: int = 25,
                       user: User = Depends(require_directeur),
                       db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock/risk")
    return stock.risque_produit(client, limit)


@router.get("/api/stock/forecast")
def stock_demand_forecast(produit: str | None = None, limit: int = 20, filtres: str = "{}",
                          user: User = Depends(require_directeur),
                          db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/stock/forecast")
    return stock.prevision_demande(produit, limit, filtres_depuis_query(filtres))


@router.get("/api/supply")
def supply_demand(filtres: str = "{}", user: User = Depends(require_directeur)):
    return stock.demande_et_approvisionnement(filtres_depuis_query(filtres))


@router.get("/api/stock/approvisionnement")
def processus_approvisionnement(filtres: str = "{}",
                                user: User = Depends(require_directeur),
                                db: Session = Depends(get_db)):
    """Le processus amont : fournisseurs, dépendance, réassort, étapes couvertes.

    La couverture des étapes dépend de ce que la BOUCLE a produit : une étape
    que l'ERP ne documente pas devient mesurée dès que la plateforme a
    enregistré une commande, puis une réception."""
    audit(db, user=user, action="access", resource="/api/stock/approvisionnement")
    b = commandes.bilan(db)
    par_statut = {x["statut"]: x["n"] for x in b["par_statut"]}
    boucle = {
        "n_commandes": par_statut.get("commandee", 0) + par_statut.get("recue", 0),
        "n_receptions": par_statut.get("recue", 0),
        "n_ouvertes": b["n_ouvertes"],
        "montant_engage_dt": b["montant_engage_dt"],
        "delai_livraison": b["delai_livraison"],
    }
    return approvisionnement.processus(filtres_depuis_query(filtres), boucle)
