"""Création du schéma + comptes de démonstration : un directeur et trois employés."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.auth.database import get_db, init_db  # noqa: E402
from api.auth.journal import audit  # noqa: E402
from api.auth.models import ROLE_DIRECTEUR, ROLE_EMPLOYE, ROLES, User  # noqa: E402
from api.auth.security import hash_password, password_policy_errors  # noqa: E402

DIRECTOR_EMAIL = "directeur@overlyne.tn"
DIRECTOR_PASSWORD = "Directeur#2026"

EMPLOYES = [
    ("recouvrement@overlyne.tn", "Sami Recouvrement", "recouvrement"),
    ("commercial@overlyne.tn", "Nadia Commerciale", "commercial"),
    ("logistique@overlyne.tn", "Karim Logistique", "logistique"),
]
EMPLOYEE_PASSWORD = "Employe#2026"


def seed(verbose: bool = True) -> dict:
    """Crée le schéma et les comptes de l'équipe ; désactive les comptes d'un rôle retiré."""
    init_db()
    created: dict[str, str] = {}
    db = next(get_db())
    try:
        if not db.query(User).filter(User.email == DIRECTOR_EMAIL).first():
            assert not password_policy_errors(DIRECTOR_PASSWORD)
            db.add(User(email=DIRECTOR_EMAIL,
                        password_hash=hash_password(DIRECTOR_PASSWORD),
                        role=ROLE_DIRECTEUR, is_active=True,
                        full_name="Direction Overlyne"))
            created[DIRECTOR_EMAIL] = DIRECTOR_PASSWORD

        for email, nom, poste in EMPLOYES:
            emp = db.query(User).filter(User.email == email).first()
            if emp is not None:
                if not emp.poste:
                    emp.poste = poste
                continue
            assert not password_policy_errors(EMPLOYEE_PASSWORD)
            db.add(User(email=email, password_hash=hash_password(EMPLOYEE_PASSWORD),
                        role=ROLE_EMPLOYE, is_active=True,
                        full_name=nom, poste=poste))
            created[email] = EMPLOYEE_PASSWORD
            if verbose:
                print(f"[seed] compte employé → {email} ({nom}, {poste})")

        # Le rôle « client » a été retiré : ses comptes existants sont désactivés
        # (jamais supprimés : le journal d'audit les référence).
        for u in db.query(User).filter(User.role.notin_(ROLES), User.is_active.is_(True)).all():
            u.is_active = False
            audit(db, user=u, action="seed_role_retire", detail=f"rôle « {u.role} » retiré")
            if verbose:
                print(f"[seed] compte désactivé (rôle retiré) → {u.email}")
        db.commit()
    finally:
        db.close()

    if verbose:
        print(f"[seed] {len(created)} compte(s) créé(s).")
        for email, pwd in created.items():
            print(f"    {email}  /  {pwd}")
    return created


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed de la base d'authentification")
    ap.parse_args()
    seed()
