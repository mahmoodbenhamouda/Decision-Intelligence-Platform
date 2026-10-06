"""Corps des requêtes de la boucle d'approvisionnement."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CommandeCreate(BaseModel):
    """Une proposition de réassort à soumettre au directeur."""

    reference: str = Field(min_length=1, max_length=64)
    designation: Optional[str] = Field(default=None, max_length=255)
    fournisseur_code: Optional[str] = Field(default=None, max_length=64)
    fournisseur_nom: Optional[str] = Field(default=None, max_length=255)
    motif: Optional[str] = Field(default=None, max_length=1000)
    qte_proposee: float = Field(default=0.0, ge=0)
    montant_estime_dt: float = Field(default=0.0, ge=0)


class Decision(BaseModel):
    """Le verdict du directeur. Un refus doit porter son motif : c'est lui qui
    apprend à l'analyse ce qu'elle a mal jugé."""

    valide: bool
    motif_refus: str = Field(default="", max_length=500)


class Reception(BaseModel):
    """La marchandise arrive. La date est posée par le serveur, pas déclarée."""

    qte_recue: Optional[float] = Field(default=None, ge=0)
    commentaire: str = Field(default="", max_length=1000)


class Commentaire(BaseModel):
    commentaire: str = Field(default="", max_length=1000)
