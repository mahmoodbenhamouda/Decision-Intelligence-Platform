"""Boucle d'action : confier une tâche, la faire avancer."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class TacheCreate(BaseModel):
    titre: str = Field(min_length=3, max_length=200)
    client_code: Optional[str] = Field(default=None, max_length=64)
    client_nom: Optional[str] = Field(default=None, max_length=255)
    type: str = Field(default="appel")
    details: Optional[str] = Field(default=None, max_length=2000)
    montant_dt: float = 0.0
    severite: str = "moyenne"
    origine_categorie: Optional[str] = Field(default=None, max_length=60)
    origine_titre: Optional[str] = Field(default=None, max_length=255)
    assigne_id: Optional[int] = None
    echeance: Optional[str] = Field(default=None,
        description="Date ISO (AAAA-MM-JJ). Absente → calculée depuis la gravité.")


class TacheUpdate(BaseModel):
    statut: Optional[str] = None
    assigne_id: Optional[int] = None
    echeance: Optional[str] = None
    resultat: Optional[str] = None
    resultat_montant_dt: Optional[float] = None
    resultat_commentaire: Optional[str] = Field(default=None, max_length=2000)
    commentaire: Optional[str] = Field(default=None, max_length=500)


class DelegationReglages(BaseModel):
    """Réglages de la délégation autonome (directeur)."""
    active: Optional[bool] = None
    heure: Optional[str] = Field(default=None, max_length=5,
        description="Heure du passage quotidien, HH:MM (heure du serveur).")
