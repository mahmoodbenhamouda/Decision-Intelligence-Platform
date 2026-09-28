"""
api/schemas/admin.py
====================
Administration : comptes et traitement des demandes clients.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from api.auth.models import ROLE_CLIENT, User


class UserOut(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    role: str
    client_code: Optional[str]
    phone: Optional[str]
    poste: Optional[str] = None
    is_active: bool
    created_at: Optional[str]
    last_login: Optional[str]
    in_erp: Optional[bool] = None      # le code existe-t-il dans l'entrepôt ?

    @classmethod
    def of(cls, u: User, in_erp: Optional[bool] = None) -> "UserOut":
        return cls(id=u.id, email=u.email, full_name=u.full_name, role=u.role,
                   client_code=u.client_code, phone=u.phone, poste=u.poste,
                   is_active=u.is_active,
                   created_at=u.created_at.isoformat() if u.created_at else None,
                   last_login=u.last_login.isoformat() if u.last_login else None,
                   in_erp=in_erp)


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    full_name: Optional[str] = None
    role: str = ROLE_CLIENT
    client_code: Optional[str] = None
    phone: Optional[str] = None
    poste: Optional[str] = Field(default=None, max_length=40,
        description="Métier de l'employé : recouvrement, commercial, logistique…")


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    client_code: Optional[str] = None
    phone: Optional[str] = None
    poste: Optional[str] = Field(default=None, max_length=40)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None, max_length=200)


class RequestUpdate(BaseModel):
    status: Optional[str] = None
    reponse: Optional[str] = Field(default=None, max_length=2000)
