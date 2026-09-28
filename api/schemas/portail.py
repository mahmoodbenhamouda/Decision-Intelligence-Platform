"""
api/schemas/portail.py
======================
Portail client : demandes en texte libre et actions structurées.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RequestCreate(BaseModel):
    type: str = Field(default="contact")
    sujet: str = Field(min_length=3, max_length=200)
    message: str = Field(min_length=3, max_length=2000)
    invoice_ref: Optional[str] = Field(default=None, max_length=64)


class ActionCreate(BaseModel):
    """Une action structurée, déclenchée depuis un écran précis du portail."""

    type: str = Field(description="promesse_paiement | reclamation | devis_reponse "
                                  "| interet_produit | reservation_stock")
    reference: Optional[str] = Field(default=None, max_length=64,
        description="Facture, devis ou produit concerné")
    libelle: Optional[str] = Field(default=None, max_length=200,
        description="Intitulé lisible (nom du produit, objet du devis)")
    montant_dt: Optional[float] = Field(default=None, ge=0)
    date_prevue: Optional[str] = Field(default=None,
        description="Date promise (AAAA-MM-JJ), pour une promesse de paiement")
    quantite: Optional[float] = Field(default=None, ge=0)
    reponse: Optional[str] = Field(default=None, max_length=20,
        description="accepte | refuse | modification — pour une réponse à un devis")
    message: Optional[str] = Field(default=None, max_length=2000)
