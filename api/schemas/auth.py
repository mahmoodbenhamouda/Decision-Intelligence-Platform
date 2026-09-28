"""
api/schemas/auth.py
===================
Connexion et profil courant.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str
    full_name: str | None = None
    client_code: str | None = None


class MeResponse(BaseModel):
    email: str
    role: str
    full_name: str | None
    client_code: str | None
    last_login: str | None
