"""
api/auth/emails.py
==================
Génération d'adresses de connexion à partir du NOM de l'établissement
(raison sociale ERP), au lieu du code client.

Exemples réels :
    "HOPITAL MILITAIRE DE TUNIS"   → hopital-militaire-de-tunis@overlyne.tn
    "C.H.U. CHARLES NICOLLE"       → chu-charles-nicolle@overlyne.tn
    "C.H.U. HABIB BOURGUIBA"       → chu-habib-bourguiba@overlyne.tn

Règles (attention aux détails) :
- minuscules, accents retirés (é→e, ô→o…), apostrophes/points supprimés ;
- "c.h.u" / "c h u" normalisés en "chu" ;
- tout caractère non alphanumérique devient un tiret, tirets consolidés ;
- longueur bornée à 40 caractères (coupée sur une frontière de mot) ;
- slug vide (nom illisible) → repli sur le code client ;
- COLLISION (deux établissements → même slug) → suffixe "-<code client>"
  en minuscules, garantissant l'unicité.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

EMAIL_DOMAIN = "overlyne.tn"
_MAX_SLUG = 40


def slugify_name(name: str) -> str:
    """Nom d'établissement → slug email (ascii, tirets)."""
    s = (name or "").strip().lower()
    # accents → ascii
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # C.H.U / c h u → chu (avant suppression générale de la ponctuation)
    s = re.sub(r"\bc[\.\s]*h[\.\s]*u\b\.?", "chu", s)
    # apostrophes collées ("l'hopital" → "l hopital" → tiret ensuite)
    s = s.replace("'", " ").replace("’", " ")
    # tout le reste non alphanumérique → tiret
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    # borne de longueur, coupée proprement sur un tiret
    if len(s) > _MAX_SLUG:
        s = s[:_MAX_SLUG].rsplit("-", 1)[0]
    return s


def email_for_client(name: Optional[str], client_code: str,
                     taken: Iterable[str] = ()) -> str:
    """Adresse de connexion unique pour un compte client.

    `taken` : adresses déjà attribuées (pour résoudre les collisions).
    """
    slug = slugify_name(name or "")
    if not slug:                                # nom vide/illisible → code
        slug = slugify_name(client_code) or "client"
    email = f"{slug}@{EMAIL_DOMAIN}"
    taken_l = {t.lower() for t in taken}
    if email.lower() in taken_l:
        # collision → suffixe code client (unique par construction ERP)
        code_slug = slugify_name(client_code) or "x"
        email = f"{slug}-{code_slug}@{EMAIL_DOMAIN}"
    return email
