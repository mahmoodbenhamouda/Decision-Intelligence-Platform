"""
api/services/admin.py
=====================
Administration (directeur) : comptes, demandes clients, journal d'audit.

- Comptes : un client HISTORIQUE (code ERP existant) ou NOUVEAU (code libre,
  pas encore de facture dans l'entrepôt). Un code client = un seul compte ; un
  compte interne n'a pas de code client ; le directeur ne peut ni se
  désactiver, ni se supprimer, ni supprimer le dernier directeur actif.
- Demandes clients : statut (en_cours/traitee/rejetee) + réponse.
- Journal d'audit : consultation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import (REQUEST_STATUS, ROLE_CLIENT, ROLE_DIRECTEUR,
                             ROLE_EMPLOYE, ROLES, AuditLog, ClientRequest,
                             EvenementTache, RevokedToken, Tache, User)
from api.auth.security import hash_password, password_policy_errors
from api.donnees import entrepot
from api.schemas.admin import RequestUpdate, UserCreate, UserOut, UserUpdate
from api.services.erreurs import Conflit, DonneesInvalides, Introuvable


def _codes_erp() -> set[str]:
    """Codes clients présents dans l'entrepôt (vide si l'entrepôt est absent)."""
    try:
        return entrepot.codes_clients()
    except Exception:
        return set()


def _dans_erp(code: Optional[str], codes: Optional[set[str]] = None) -> Optional[bool]:
    if not code:
        return None
    return code.strip().upper() in (codes if codes is not None else _codes_erp())


# ── Comptes ─────────────────────────────────────────────────────────────────
def lister_comptes(db: Session) -> List[UserOut]:
    """Tous les comptes, avec l'info « présent dans l'ERP » pour distinguer
    les clients historiques des nouveaux."""
    users = db.execute(select(User).order_by(User.role, User.email)).scalars().all()
    codes = _codes_erp()
    return [UserOut.of(u, in_erp=_dans_erp(u.client_code, codes)) for u in users]


def creer_compte(db: Session, admin: User, body: UserCreate) -> UserOut:
    """Contrôles : rôle valide, `client_code` obligatoire et UNIQUE pour un
    client (deux comptes ne peuvent pas viser le même périmètre de données),
    email unique, politique de mot de passe."""
    if body.role not in ROLES:
        raise DonneesInvalides(f"Rôle invalide (attendu : {', '.join(ROLES)}).")

    code = (body.client_code or "").strip()
    if body.role == ROLE_CLIENT:
        if not code:
            raise DonneesInvalides("Un compte client doit avoir un code client.")
        if len(code) > 64:
            raise DonneesInvalides("Code client trop long (64 caractères max).")
        dup = db.execute(select(User).where(
            func.upper(User.client_code) == code.upper())).scalar_one_or_none()
        if dup is not None:
            raise Conflit(f"Le code client « {code} » est déjà attribué au compte {dup.email}.")
    elif code:
        raise DonneesInvalides("Un compte interne (directeur ou employé) ne doit pas "
                               "avoir de code client.")

    errs = password_policy_errors(body.password)
    if errs:
        raise DonneesInvalides("Mot de passe trop faible : " + ", ".join(errs) + ".")
    email = body.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise Conflit("Un compte existe déjà avec cet email.")

    u = User(email=email, password_hash=hash_password(body.password),
             full_name=(body.full_name or "").strip() or None, role=body.role,
             client_code=code or None,
             phone=(body.phone or "").strip() or None,
             poste=((body.poste or "").strip() or None) if body.role == ROLE_EMPLOYE else None,
             is_active=True)
    db.add(u)
    db.commit()
    in_erp = _dans_erp(code)
    audit(db, user=admin, action="admin_create_user", resource="/api/admin/users",
          detail=(f"création {email} ({body.role}"
                  f"{f', code={code}, ERP={in_erp}' if code else ''})"))
    return UserOut.of(u, in_erp=in_erp)


def modifier_compte(db: Session, admin: User, user_id: int, body: UserUpdate) -> UserOut:
    """Nom, identifiant, code client, téléphone, poste, activité, mot de passe."""
    u = db.get(User, user_id)
    if u is None:
        raise Introuvable("Compte introuvable.")
    if u.id == admin.id and body.is_active is False:
        raise DonneesInvalides("Impossible de désactiver son propre compte.")
    if body.email:
        # Changement d'identifiant (ex. établissement renommé) : unicité
        # vérifiée en minuscules, mot de passe et historique conservés.
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
        # Révocation GLOBALE : tous les jetons émis avant ce changement
        # deviennent invalides (token_version incrémentée, vérifiée à chaque requête).
        u.token_version = (u.token_version or 0) + 1
    if body.client_code is not None:
        code = body.client_code.strip()
        if u.role == ROLE_CLIENT and not code:
            raise DonneesInvalides("Un compte client doit garder un code client.")
        if code and code.upper() != (u.client_code or "").upper():
            dup = db.execute(select(User).where(
                func.upper(User.client_code) == code.upper(),
                User.id != u.id)).scalar_one_or_none()
            if dup is not None:
                raise Conflit(f"Le code client « {code} » est déjà attribué à {dup.email}.")
        u.client_code = code or None
    for field in ("full_name", "phone", "poste", "is_active"):
        v = getattr(body, field)
        if v is not None:
            setattr(u, field, v)
    db.commit()
    audit(db, user=admin, action="admin_update_user", resource="/api/admin/users",
          detail=f"maj compte #{user_id} ({u.email})")
    return UserOut.of(u, in_erp=_dans_erp(u.client_code))


def supprimer_compte(db: Session, admin: User, user_id: int, definitif: bool) -> Dict[str, Any]:
    """Deux modes :

    - `definitif=False` : **désactivation**. Le compte ne peut plus se connecter
      mais reste en base : historique, demandes et audit intacts, réactivation
      possible. C'est le mode recommandé.
    - `definitif=True` : **suppression DÉFINITIVE**. Les demandes du compte et
      ses jetons révoqués sont supprimés ; le journal d'audit est CONSERVÉ mais
      anonymisé (`user_id` mis à NULL, l'email reste comme trace) ; les tâches
      survivent au compte.
    """
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

    email, code = u.email, u.client_code

    if not definitif:
        u.is_active = False
        db.commit()
        audit(db, user=admin, action="admin_deactivate_user",
              resource="/api/admin/users", detail=f"désactivation {email}")
        return {"ok": True, "email": email, "is_active": False, "deleted": False}

    # Les tâches SURVIVENT au compte : le travail et son résultat appartiennent
    # à l'entreprise, pas à la personne. Celles qui étaient en cours redeviennent
    # « à affecter », sinon elles disparaîtraient de tous les écrans avec leur
    # responsable.
    n_taches = db.execute(
        sa_update(Tache).where(Tache.assigne_id == u.id,
                               Tache.statut.in_(("a_faire", "en_cours", "bloquee")))
        .values(assigne_id=None, statut="a_affecter")).rowcount or 0
    db.execute(sa_update(Tache).where(Tache.assigne_id == u.id).values(assigne_id=None))
    db.execute(sa_update(Tache).where(Tache.cree_par_id == u.id).values(cree_par_id=None))
    db.execute(sa_update(EvenementTache).where(
        EvenementTache.user_id == u.id).values(user_id=None))

    # Une demande client supprimée ne doit pas laisser une tâche pointer dans le vide.
    req_ids = [r for (r,) in db.execute(
        select(ClientRequest.id).where(ClientRequest.user_id == u.id)).all()]
    if req_ids:
        db.execute(sa_update(Tache).where(Tache.request_id.in_(req_ids))
                   .values(request_id=None))
    n_req = db.execute(delete(ClientRequest).where(
        ClientRequest.user_id == u.id)).rowcount or 0
    db.execute(delete(RevokedToken).where(RevokedToken.user_id == u.id))
    # L'audit survit à la suppression : on coupe seulement la clé étrangère.
    n_audit = db.execute(
        sa_update(AuditLog).where(AuditLog.user_id == u.id).values(user_id=None)
    ).rowcount or 0
    db.delete(u)
    db.commit()
    audit(db, user=admin, action="admin_delete_user_permanent",
          resource="/api/admin/users",
          detail=(f"suppression définitive {email}"
                  f"{f' (code {code})' if code else ''} — "
                  f"{n_req} demande(s) supprimée(s), {n_audit} entrée(s) d'audit anonymisée(s), "
                  f"{n_taches} tâche(s) remise(s) à affecter"))
    return {"ok": True, "email": email, "deleted": True,
            "demandes_supprimees": n_req, "audit_anonymise": n_audit,
            "taches_a_reaffecter": n_taches}


def clients_erp() -> Dict[str, Any]:
    """Codes clients réels de l'entrepôt (pour créer un compte relié à l'ERP)."""
    try:
        return {"clients": entrepot.clients_principaux(limite=100)}
    except Exception as e:
        return {"clients": [], "error": str(e)}


# ── Demandes clients ────────────────────────────────────────────────────────
def _demande_dict(r: ClientRequest, u: Optional[User]) -> Dict[str, Any]:
    return {
        "id": r.id, "type": r.type, "sujet": r.sujet, "message": r.message,
        "invoice_ref": r.invoice_ref, "status": r.status, "reponse": r.reponse,
        "client_code": r.client_code,
        "client_nom": (u.full_name or u.email) if u else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def lister_demandes(db: Session, statut: Optional[str]) -> Dict[str, Any]:
    q = select(ClientRequest).order_by(ClientRequest.created_at.desc())
    if statut:
        q = q.where(ClientRequest.status == statut)
    reqs = db.execute(q).scalars().all()
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    return {"requests": [_demande_dict(r, users.get(r.user_id)) for r in reqs]}


def traiter_demande(db: Session, admin: User, req_id: int, body: RequestUpdate) -> Dict[str, Any]:
    r = db.get(ClientRequest, req_id)
    if r is None:
        raise Introuvable("Demande introuvable.")
    if body.status is not None:
        if body.status not in REQUEST_STATUS:
            raise DonneesInvalides(f"Statut invalide (attendu : {', '.join(REQUEST_STATUS)}).")
        r.status = body.status
    if body.reponse is not None:
        r.reponse = body.reponse
    r.updated_at = datetime.now(timezone.utc)
    db.commit()
    audit(db, user=admin, action="admin_update_request", resource="/api/admin/requests",
          detail=f"demande #{req_id} → {r.status}")
    return _demande_dict(r, db.get(User, r.user_id))


# ── Audit ───────────────────────────────────────────────────────────────────
def journal_audit(db: Session, limite: int) -> Dict[str, Any]:
    """Dernières entrées du journal d'audit (qui a fait quoi, quand)."""
    limite = max(1, min(500, limite))
    rows = db.execute(select(AuditLog).order_by(AuditLog.at.desc()).limit(limite)
                      ).scalars().all()
    return {"audit": [{"id": a.id, "email": a.email, "action": a.action,
                       "resource": a.resource, "detail": a.detail,
                       "at": a.at.isoformat() if a.at else None} for a in rows]}
