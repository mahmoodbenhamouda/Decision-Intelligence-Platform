"""Administration (directeur) : comptes de l'équipe et journal d'audit."""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import (ROLE_DIRECTEUR, ROLE_EMPLOYE, ROLES, AuditLog,
                             CommandeFournisseur, DelegationPassage,
                             EvenementCommande, EvenementTache, Reglage,
                             RevokedToken, Tache, User)
from api.auth.security import hash_password, password_policy_errors
from api.schemas.admin import UserCreate, UserOut, UserUpdate
from api.services.erreurs import Conflit, DonneesInvalides, Introuvable


def lister_comptes(db: Session, inclure_retires: bool = False) -> List[UserOut]:
    """Les comptes de l'équipe (directeurs et employés).

    Un compte dont le rôle n'est plus dans `ROLES` — le portail client, retiré —
    n'est PAS listé par défaut : il ne peut plus se connecter, l'afficher ne
    ferait que suggérer un rôle que la plateforme ne sert plus. `compter_roles_retires`
    dit combien il en reste, et `purger_roles_retires` les efface.
    """
    q = select(User)
    if not inclure_retires:
        q = q.where(User.role.in_(ROLES))
    users = db.execute(q.order_by(User.role, User.email)).scalars().all()
    return [UserOut.of(u) for u in users]


def compter_roles_retires(db: Session) -> int:
    """Combien de comptes subsistent en base avec un rôle que la plateforme ne sert plus."""
    return int(db.execute(
        select(func.count()).select_from(User).where(User.role.notin_(ROLES))
    ).scalar_one() or 0)


def creer_compte(db: Session, admin: User, body: UserCreate) -> UserOut:
    """Contrôles : rôle valide (directeur ou employé), mot de passe robuste, email unique."""
    if body.role not in ROLES:
        raise DonneesInvalides(f"Rôle invalide (attendu : {', '.join(ROLES)}).")

    errs = password_policy_errors(body.password)
    if errs:
        raise DonneesInvalides("Mot de passe trop faible : " + ", ".join(errs) + ".")
    email = body.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflit("Un compte existe déjà avec cet email.")

    u = User(email=email, password_hash=hash_password(body.password),
             full_name=(body.full_name or "").strip() or None, role=body.role,
             phone=(body.phone or "").strip() or None,
             poste=((body.poste or "").strip() or None) if body.role == ROLE_EMPLOYE else None,
             is_active=True)
    db.add(u)
    db.commit()
    audit(db, user=admin, action="admin_create_user", resource="/api/admin/users",
          detail=f"création {email} ({body.role})")
    return UserOut.of(u)


def modifier_compte(db: Session, admin: User, user_id: int, body: UserUpdate) -> UserOut:
    """Nom, identifiant, téléphone, poste, activité, mot de passe."""
    u = db.get(User, user_id)
    if u is None:
        raise Introuvable("Compte introuvable.")
    if u.id == admin.id and body.is_active is False:
        raise DonneesInvalides("Impossible de désactiver son propre compte.")
    if body.email:
        new_email = body.email.lower().strip()
        if new_email != u.email:
            clash = db.execute(select(User).where(User.email == new_email)).scalar_one_or_none()
            if clash is not None:
                raise Conflit("Un compte existe déjà avec cet identifiant.")
            audit(db, user=admin, action="admin_rename_email",
                  detail=f"{u.email} → {new_email}")
            u.email = new_email
    if body.password:
        errs = password_policy_errors(body.password)
        if errs:
            raise DonneesInvalides("Mot de passe trop faible : " + ", ".join(errs) + ".")
        u.password_hash = hash_password(body.password)
        u.token_version = (u.token_version or 0) + 1
    for field in ("full_name", "phone", "poste", "is_active"):
        v = getattr(body, field)
        if v is not None:
            setattr(u, field, v)
    db.commit()
    audit(db, user=admin, action="admin_update_user", resource="/api/admin/users",
          detail=f"maj compte #{user_id} ({u.email})")
    return UserOut.of(u)


def _detacher_et_effacer(db: Session, u: User) -> tuple[int, int]:
    """Efface un compte en préservant ce qui le référence.

    Le journal d'audit n'est JAMAIS amputé : ses entrées sont anonymisées
    (`user_id` à NULL, l'email reste écrit dans la ligne), sans quoi supprimer
    un compte effacerait la preuve de ce qu'il a fait. Les tâches encore
    ouvertes qui lui étaient confiées repassent à affecter plutôt que de
    disparaître avec lui.

    Retourne (tâches remises à affecter, entrées d'audit anonymisées).
    Ne valide pas la transaction : l'appelant décide quand committer.
    """
    n_taches = db.execute(
        sa_update(Tache).where(Tache.assigne_id == u.id,
                               Tache.statut.in_(("a_faire", "en_cours", "bloquee")))
        .values(assigne_id=None, statut="a_affecter")).rowcount or 0
    db.execute(sa_update(Tache).where(Tache.assigne_id == u.id).values(assigne_id=None))
    db.execute(sa_update(Tache).where(Tache.cree_par_id == u.id).values(cree_par_id=None))
    db.execute(sa_update(EvenementTache).where(
        EvenementTache.user_id == u.id).values(user_id=None))
    db.execute(sa_update(CommandeFournisseur).where(
        CommandeFournisseur.decide_par_id == u.id).values(decide_par_id=None))
    db.execute(sa_update(EvenementCommande).where(
        EvenementCommande.user_id == u.id).values(user_id=None))
    db.execute(sa_update(DelegationPassage).where(
        DelegationPassage.lance_par_id == u.id).values(lance_par_id=None))
    db.execute(sa_update(Reglage).where(
        Reglage.modifie_par_id == u.id).values(modifie_par_id=None))
    db.execute(delete(RevokedToken).where(RevokedToken.user_id == u.id))
    _effacer_demandes_portail(db, u.id)
    n_audit = db.execute(
        sa_update(AuditLog).where(AuditLog.user_id == u.id).values(user_id=None)
    ).rowcount or 0
    db.delete(u)
    return n_taches, n_audit


def _effacer_demandes_portail(db: Session, user_id: int) -> None:
    """Efface les demandes de l'ancien portail client, si la table subsiste.

    Le modèle `client_requests` a été retiré avec le portail, mais `create_all`
    ne supprime jamais une table : une base créée avant ce retrait la garde,
    avec `user_id NOT NULL` vers `users.id`. Sans ce nettoyage, PostgreSQL
    refuse d'effacer tout compte client qui avait déposé une demande.
    """
    if inspect(db.get_bind()).has_table("client_requests"):
        db.execute(text("DELETE FROM client_requests WHERE user_id = :u"),
                   {"u": user_id})


def purger_roles_retires(db: Session, admin: User) -> Dict[str, Any]:
    """Efface définitivement les comptes d'un rôle que la plateforme ne sert plus.

    Le rôle « client » (portail des établissements) a été retiré : la plateforme
    est désormais destinée au directeur et à ses employés. Les comptes créés sous
    ce rôle ne peuvent déjà plus se connecter — `ROLES` ne les contient plus —
    mais ils subsistaient en base. Cette opération les efface, journal d'audit
    préservé. Elle ne touche AUCUN compte de rôle en vigueur : un directeur ou un
    employé ne peut pas être emporté par une purge, même par erreur.
    """
    comptes = db.execute(select(User).where(User.role.notin_(ROLES))).scalars().all()
    if not comptes:
        return {"ok": True, "n_supprimes": 0, "emails": [],
                "message": "Aucun compte de rôle retiré en base."}

    efface: List[Dict[str, Any]] = []
    for u in comptes:
        email, role = u.email, u.role
        n_taches, n_audit = _detacher_et_effacer(db, u)
        efface.append({"email": email, "role": role,
                       "audit_anonymise": n_audit, "taches_a_reaffecter": n_taches})
    db.commit()
    audit(db, user=admin, action="admin_purge_roles_retires",
          resource="/api/admin/purger-roles-retires",
          detail=("suppression définitive de "
                  f"{len(efface)} compte(s) de rôle retiré : "
                  + ", ".join(f"{e['email']} ({e['role']})" for e in efface)))
    return {"ok": True, "n_supprimes": len(efface),
            "emails": [e["email"] for e in efface], "details": efface}


def supprimer_compte(db: Session, admin: User, user_id: int, definitif: bool) -> Dict[str, Any]:
    """Deux modes :"""
    u = db.get(User, user_id)
    if u is None:
        raise Introuvable("Compte introuvable.")
    if u.id == admin.id:
        raise DonneesInvalides("Impossible de supprimer son propre compte.")
    if u.role == ROLE_DIRECTEUR:
        autres = db.execute(
            select(func.count()).select_from(User).where(
                User.role == ROLE_DIRECTEUR, User.is_active.is_(True), User.id != u.id)
        ).scalar_one()
        if not autres:
            raise DonneesInvalides(
                "Impossible : ce compte est le dernier directeur actif de la plateforme.")

    email = u.email

    if not definitif:
        u.is_active = False
        db.commit()
        audit(db, user=admin, action="admin_deactivate_user",
              resource="/api/admin/users", detail=f"désactivation {email}")
        return {"ok": True, "email": email, "is_active": False, "deleted": False}

    n_taches, n_audit = _detacher_et_effacer(db, u)
    db.commit()
    audit(db, user=admin, action="admin_delete_user_permanent",
          resource="/api/admin/users",
          detail=(f"suppression définitive {email} — "
                  f"{n_audit} entrée(s) d'audit anonymisée(s), "
                  f"{n_taches} tâche(s) remise(s) à affecter"))
    return {"ok": True, "email": email, "deleted": True,
            "audit_anonymise": n_audit, "taches_a_reaffecter": n_taches}


def journal_audit(db: Session, limite: int) -> Dict[str, Any]:
    """Dernières entrées du journal d'audit (qui a fait quoi, quand)."""
    limite = max(1, min(500, limite))
    rows = db.execute(select(AuditLog).order_by(AuditLog.at.desc()).limit(limite)
                      ).scalars().all()
    return {"audit": [{"id": a.id, "email": a.email, "action": a.action,
                       "resource": a.resource, "detail": a.detail,
                       "at": a.at.isoformat() if a.at else None} for a in rows]}
