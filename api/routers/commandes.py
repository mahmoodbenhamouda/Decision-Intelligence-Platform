"""La boucle d'approvisionnement : /api/commandes (directeur).

L'analyse propose, le directeur tranche, la commande part, la réception se
saisit. Les deux dates que l'ERP ne porte pas — commande et réception — naissent
ici, et leur écart donne le délai de livraison réel.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur, require_interne
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.commandes import (Commentaire, CommandeCreate, Decision,
                                   Reception)
from api.services import commandes
from api.services.filtres import filtres_depuis_query

router = APIRouter(tags=["commandes"])


@router.get("/api/commandes/recommandations")
def recommandations(filtres: str = "{}",
                    user: User = Depends(require_directeur),
                    db: Session = Depends(get_db)):
    """Réassorts proposés par l'analyse, moins ceux déjà décidés."""
    audit(db, user=user, action="access", resource="/api/commandes/recommandations")
    return commandes.recommandations(db, filtres_depuis_query(filtres))


@router.get("/api/commandes")
def lister(statut: str | None = None, limit: int = 100,
           user: User = Depends(require_interne),
           db: Session = Depends(get_db)):
    """Lisible par l'employé : il doit voir les commandes qu'il exécute."""
    return commandes.lister(db, statut, limit)


@router.get("/api/commandes/bilan")
def bilan(user: User = Depends(require_directeur),
          db: Session = Depends(get_db)):
    """Ce que la boucle a produit, délai de livraison réel compris."""
    return commandes.bilan(db)


@router.post("/api/commandes")
def creer(corps: CommandeCreate,
          user: User = Depends(require_directeur),
          db: Session = Depends(get_db)):
    audit(db, user=user, action="create", resource="/api/commandes")
    return commandes.creer(db, user, corps.model_dump(), origine="ia")


@router.post("/api/commandes/{commande_id}/decision")
def decider(commande_id: int, corps: Decision,
            user: User = Depends(require_directeur),
            db: Session = Depends(get_db)):
    audit(db, user=user, action="update",
          resource=f"/api/commandes/{commande_id}/decision")
    return commandes.decider(db, user, commande_id, corps.valide, corps.motif_refus)


# Passer la commande et saisir la réception sont des gestes d'EXÉCUTION :
# l'employé logistique qui a reçu la tâche doit pouvoir les faire. Seule la
# décision — valider ou refuser — reste réservée à la direction.
@router.post("/api/commandes/{commande_id}/commander")
def passer_commande(commande_id: int, corps: Commentaire,
                    user: User = Depends(require_interne),
                    db: Session = Depends(get_db)):
    audit(db, user=user, action="update",
          resource=f"/api/commandes/{commande_id}/commander")
    return commandes.passer_commande(db, user, commande_id, corps.commentaire)


@router.post("/api/commandes/{commande_id}/reception")
def receptionner(commande_id: int, corps: Reception,
                 user: User = Depends(require_interne),
                 db: Session = Depends(get_db)):
    audit(db, user=user, action="update",
          resource=f"/api/commandes/{commande_id}/reception")
    return commandes.receptionner(db, user, commande_id,
                                  corps.qte_recue, corps.commentaire)


@router.post("/api/commandes/{commande_id}/annulation")
def annuler(commande_id: int, corps: Commentaire,
            user: User = Depends(require_directeur),
            db: Session = Depends(get_db)):
    audit(db, user=user, action="update",
          resource=f"/api/commandes/{commande_id}/annulation")
    return commandes.annuler(db, user, commande_id, corps.commentaire)


@router.get("/api/commandes/{commande_id}/histoire")
def histoire(commande_id: int,
             user: User = Depends(require_directeur),
             db: Session = Depends(get_db)):
    return commandes.histoire(db, commande_id)
