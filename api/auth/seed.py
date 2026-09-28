"""
api/auth/seed.py
================
Création du schéma + comptes de démonstration, mappés sur des `client_code`
RÉELS de l'entrepôt DuckDB (top clients par chiffre d'affaires).

Usage :
    python -m api.auth.seed                # crée directeur + 3 clients
    python -m api.auth.seed --clients 5    # nombre de comptes clients

Comptes créés (mots de passe à changer hors démo, conformes à la politique) :
    directeur@overlyne.tn                     /  Directeur#2026
    recouvrement|commercial|logistique@…      /  Employe#2026  (équipe interne)
    <nom-de-l-hopital>@overlyne.tn            /  Client#2026<n>
    (ex. hopital-militaire-de-tunis@overlyne.tn, chu-charles-nicolle@overlyne.tn)

Idempotent ET migrant : un compte client existant est retrouvé par son
`client_code` ; si son adresse suit encore l'ancien schéma
(client.<code>@…), elle est RENOMMÉE vers le nouveau schéma basé sur le nom
de l'établissement — mot de passe et historique conservés, renommage audité.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.auth.database import get_db, init_db  # noqa: E402
from api.auth.journal import audit  # noqa: E402
from api.auth.models import (ROLE_CLIENT, ROLE_DIRECTEUR, ROLE_EMPLOYE,  # noqa: E402
                             User)
from api.auth.security import hash_password, password_policy_errors  # noqa: E402

DIRECTOR_EMAIL = "directeur@overlyne.tn"
DIRECTOR_PASSWORD = "Directeur#2026"

#: Équipe interne à qui le directeur confie les tâches. Trois métiers, qui
#: correspondent aux trois familles d'alertes du tableau de bord : encaisser,
#: vendre, approvisionner.
EMPLOYES = [
    ("recouvrement@overlyne.tn", "Sami Recouvrement", "recouvrement"),
    ("commercial@overlyne.tn", "Nadia Commerciale", "commercial"),
    ("logistique@overlyne.tn", "Karim Logistique", "logistique"),
]
EMPLOYEE_PASSWORD = "Employe#2026"


def top_client_codes(n: int = 3) -> List[Tuple[str, str, float]]:
    """(code, raison sociale, CA) des top clients réels de l'entrepôt DuckDB."""
    try:
        import duckdb
        from ml_engine.analytics.kpi_engine import STORE_PATH
        con = duckdb.connect(str(STORE_PATH), read_only=True)
        rows = con.execute(
            "SELECT client, max(client_name) nom, sum(ttc) ca FROM sales "
            "WHERE client IS NOT NULL GROUP BY client ORDER BY ca DESC LIMIT ?",
            [n]).fetchall()
        con.close()
        return [(str(r[0]), str(r[1] or r[0]).strip(), float(r[2] or 0)) for r in rows]
    except Exception as e:  # pragma: no cover
        print(f"[seed] entrepôt indisponible ({e}) — codes de démonstration.")
        return [(f"CLI{i:03d}", f"Client démo {i}", 0.0) for i in range(1, n + 1)]


def seed(n_clients: int = 3, verbose: bool = True) -> dict:
    """Crée le schéma et les comptes ; MIGRE les adresses vers le schéma
    « nom d'hôpital ». Retourne {email: mot_de_passe} des comptes créés."""
    from api.auth.emails import email_for_client

    init_db()
    created: dict[str, str] = {}
    db = next(get_db())
    try:
        # ── Directeur (adresse fixe, retrouvé par email) ──
        if not db.query(User).filter(User.email == DIRECTOR_EMAIL).first():
            assert not password_policy_errors(DIRECTOR_PASSWORD)
            db.add(User(email=DIRECTOR_EMAIL,
                        password_hash=hash_password(DIRECTOR_PASSWORD),
                        role=ROLE_DIRECTEUR, client_code=None, is_active=True,
                        full_name="Direction Overlyne"))
            created[DIRECTOR_EMAIL] = DIRECTOR_PASSWORD

        # ── Équipe interne : les personnes à qui confier les tâches ──
        for email, nom, poste in EMPLOYES:
            emp = db.query(User).filter(User.email == email).first()
            if emp is not None:
                if not emp.poste:            # compte antérieur à la boucle d'action
                    emp.poste = poste
                continue
            assert not password_policy_errors(EMPLOYEE_PASSWORD)
            db.add(User(email=email, password_hash=hash_password(EMPLOYEE_PASSWORD),
                        role=ROLE_EMPLOYE, client_code=None, is_active=True,
                        full_name=nom, poste=poste))
            created[email] = EMPLOYEE_PASSWORD
            if verbose:
                print(f"[seed] compte employé → {email} ({nom}, {poste})")

        # ── Clients : retrouvés par client_code (l'email peut changer) ──
        taken = {u.email for u in db.query(User).all()}
        for i, (code, nom, ca) in enumerate(top_client_codes(n_clients), 1):
            existing = (db.query(User)
                        .filter(User.role == ROLE_CLIENT, User.client_code == code)
                        .first())
            target = email_for_client(nom, code,
                                      taken - ({existing.email} if existing else set()))
            if existing:
                if not existing.full_name:
                    existing.full_name = nom
                if existing.email != target:
                    # Migration d'adresse : mot de passe et historique CONSERVÉS.
                    old = existing.email
                    taken.discard(old)
                    existing.email = target
                    taken.add(target)
                    audit(db, user=existing, action="seed_rename_email",
                          detail=f"{old} → {target}")
                    if verbose:
                        print(f"[seed] adresse migrée : {old} → {target}")
                continue
            password = f"Client#2026{i}"
            assert not password_policy_errors(password), f"mot de passe faible: {target}"
            db.add(User(email=target, password_hash=hash_password(password),
                        role=ROLE_CLIENT, client_code=code, is_active=True,
                        full_name=nom))
            taken.add(target)
            created[target] = password
            if verbose:
                print(f"[seed] compte client → {target} ({nom}, code={code}, CA={ca:,.0f} DT)")
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
    ap.add_argument("--clients", type=int, default=3)
    args = ap.parse_args()
    seed(args.clients)
