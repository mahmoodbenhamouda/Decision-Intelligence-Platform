"""La BOUCLE D'ACTION : une alerte devient une tâche, la tâche est confiée, puis son résultat est…"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import (EVENEMENT_TYPES, RESULTAT_LABEL, RESULTATS_GAGNANTS,
                             ROLE_DIRECTEUR, ROLE_EMPLOYE, STATUTS_OUVERTS,
                             TACHE_RESULTATS, TACHE_STATUTS, TACHE_TYPE_LABEL,
                             TACHE_TYPES, EvenementTache, Tache, User)
from api.schemas.taches import TacheCreate, TacheUpdate
from api.services.erreurs import (AccesRefuse, Conflit, DonneesInvalides,
                                  Introuvable)

DELAI_PAR_SEVERITE = {"critique": 2, "haute": 5, "moyenne": 10, "faible": 20}


ORIGINES = ("direction", "flotte")


def origine_de(t: Tache) -> str:
    """`flotte` si la délégation autonome l'a confiée, `direction` sinon."""
    return "flotte" if t.delegation_auto else "direction"


def _evt(db: Session, tache: Tache, user: Optional[User], type_: str,
         detail: str) -> None:
    """Ajoute une ligne d'histoire (sans commit : le geste appelant commite)."""
    if type_ not in EVENEMENT_TYPES:
        type_ = "commentaire"
    db.add(EvenementTache(tache_id=tache.id, user_id=user.id if user else None,
                          email=user.email if user else None,
                          type=type_, detail=detail[:500]))


def echeance_par_defaut(severite: str) -> datetime:
    """Aujourd'hui + le délai accordé à cette gravité."""
    jours = DELAI_PAR_SEVERITE.get(severite, 10)
    return datetime.now(timezone.utc) + timedelta(days=jours)


def _lire_echeance(valeur: Optional[str], severite: str) -> datetime:
    """Échéance demandée, sinon délai par défaut lié à la gravité."""
    if valeur:
        try:
            d = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            raise DonneesInvalides("Date d'échéance invalide (format attendu : AAAA-MM-JJ).")
    return echeance_par_defaut(severite)


def _en_retard(t: Tache) -> bool:
    if t.statut in ("terminee",) or t.echeance is None:
        return False
    ech = t.echeance if t.echeance.tzinfo else t.echeance.replace(tzinfo=timezone.utc)
    return ech < datetime.now(timezone.utc)


def _tache_dict(t: Tache, users: Dict[int, User]) -> Dict[str, Any]:
    a = users.get(t.assigne_id) if t.assigne_id else None
    c = users.get(t.cree_par_id) if t.cree_par_id else None
    return {
        "id": t.id,
        "client_code": t.client_code,
        "client_nom": t.client_nom or t.client_code,
        "origine_categorie": t.origine_categorie,
        "origine_titre": t.origine_titre,
        "delegation_auto": bool(t.delegation_auto),
        "type": t.type,
        "type_label": TACHE_TYPE_LABEL.get(t.type, t.type),
        "titre": t.titre,
        "details": t.details,
        "montant_dt": float(t.montant_dt or 0),
        "severite": t.severite,
        "assigne_id": t.assigne_id,
        "assigne_nom": (a.full_name or a.email) if a else None,
        "cree_par": (c.full_name or c.email) if c else None,
        "echeance": t.echeance.isoformat() if t.echeance else None,
        "en_retard": _en_retard(t),
        "statut": t.statut,
        "resultat": t.resultat,
        "resultat_label": RESULTAT_LABEL.get(t.resultat or "", None),
        "resultat_montant_dt": float(t.resultat_montant_dt) if t.resultat_montant_dt is not None else None,
        "resultat_commentaire": t.resultat_commentaire,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
    }


def _users_index(db: Session) -> Dict[int, User]:
    return {u.id: u for u in db.execute(select(User)).scalars().all()}


def _tache_visible(db: Session, tache_id: int, user: User) -> Tache:
    """La tâche, si cet utilisateur a le droit de la voir — `Introuvable` sinon."""
    t = db.get(Tache, tache_id)
    if t is None:
        raise Introuvable("Tâche introuvable.")
    if user.role != ROLE_DIRECTEUR and t.assigne_id != user.id:
        audit(db, user=user, action="forbidden", detail=f"tâche #{tache_id} hors périmètre")
        raise Introuvable("Tâche introuvable.")
    return t


def _employe_actif(db: Session, user_id: int) -> User:
    a = db.get(User, user_id)
    if a is None or a.role != ROLE_EMPLOYE or not a.is_active:
        raise DonneesInvalides("Responsable inconnu ou inactif.")
    return a


def employes(db: Session) -> Dict[str, Any]:
    """Employés actifs, avec le nombre de tâches ouvertes de chacun."""
    emps = db.execute(
        select(User).where(User.role == ROLE_EMPLOYE, User.is_active.is_(True))
        .order_by(User.full_name, User.email)).scalars().all()
    charges = dict(db.execute(
        select(Tache.assigne_id, func.count(Tache.id))
        .where(Tache.statut.in_(STATUTS_OUVERTS))
        .group_by(Tache.assigne_id)).all())
    return {"employes": [{
        "id": e.id,
        "nom": e.full_name or e.email,
        "email": e.email,
        "poste": e.poste,
        "taches_ouvertes": int(charges.get(e.id, 0)),
    } for e in emps]}


def impact(db: Session, user: User) -> Dict[str, Any]:
    """Mesure de la boucle : sans elle, personne ne saurait si tout ce travail sert à quelque chose."""
    q = select(Tache)
    if user.role != ROLE_DIRECTEUR:
        q = q.where(Tache.assigne_id == user.id)
    taches = db.execute(q).scalars().all()

    ouvertes = [t for t in taches if t.statut in STATUTS_OUVERTS]
    terminees = [t for t in taches if t.statut == "terminee"]
    gagnees = [t for t in terminees if (t.resultat or "") in RESULTATS_GAGNANTS]

    par_resultat: Dict[str, Dict[str, float]] = {}
    for t in terminees:
        r = t.resultat or "autre"
        e = par_resultat.setdefault(r, {"resultat": r, "label": RESULTAT_LABEL.get(r, r),
                                        "nombre": 0, "montant_dt": 0.0,
                                        "montant_en_jeu_dt": 0.0})
        e["nombre"] += 1
        e["montant_dt"] += float(t.resultat_montant_dt or 0)
        e["montant_en_jeu_dt"] += float(t.montant_dt or 0)

    par_mois: Dict[str, Dict[str, float]] = {}
    for t in gagnees:
        d = t.closed_at or t.updated_at
        if not d:
            continue
        mois = d.strftime("%Y-%m")
        e = par_mois.setdefault(mois, {"mois": mois, "montant_dt": 0.0, "nombre": 0})
        e["montant_dt"] += float(t.resultat_montant_dt or 0)
        e["nombre"] += 1

    par_origine: Dict[str, Dict[str, Any]] = {}
    for t in taches:
        o = origine_de(t)
        e = par_origine.setdefault(o, {"origine": o, "taches": 0, "terminees": 0,
                                        "gagnees": 0, "recupere_dt": 0.0})
        e["taches"] += 1
        if t.statut == "terminee":
            e["terminees"] += 1
            if (t.resultat or "") in RESULTATS_GAGNANTS:
                e["gagnees"] += 1
                e["recupere_dt"] += float(t.resultat_montant_dt or 0)
    for e in par_origine.values():
        e["recupere_dt"] = round(e["recupere_dt"], 2)
        e["taux_reussite"] = (round(100 * e["gagnees"] / e["terminees"], 1)
                              if e["terminees"] else None)

    delais = []
    for t in terminees:
        if t.created_at and t.closed_at:
            a = t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=timezone.utc)
            b = t.closed_at if t.closed_at.tzinfo else t.closed_at.replace(tzinfo=timezone.utc)
            delais.append(max(0.0, (b - a).total_seconds() / 86400))

    return {
        "taches_total": len(taches),
        "taches_ouvertes": len(ouvertes),
        "taches_en_retard": sum(1 for t in ouvertes if _en_retard(t)),
        "taches_terminees": len(terminees),
        "en_jeu_dt": round(sum(float(t.montant_dt or 0) for t in ouvertes), 2),
        "recupere_dt": round(sum(float(t.resultat_montant_dt or 0) for t in gagnees), 2),
        "promesses_dt": round(sum(float(t.resultat_montant_dt or t.montant_dt or 0)
                                  for t in terminees if t.resultat == "promesse"), 2),
        "taux_reussite": round(100 * len(gagnees) / len(terminees), 1) if terminees else None,
        "delai_moyen_j": round(sum(delais) / len(delais), 1) if delais else None,
        "par_resultat": sorted(par_resultat.values(), key=lambda e: -e["nombre"]),
        "par_mois": sorted(par_mois.values(), key=lambda e: e["mois"]),
        "par_origine": [par_origine[o] for o in ORIGINES if o in par_origine],
    }


def boucle(db: Session) -> Dict[str, Any]:
    """Ce qui est déjà reparti vers les modèles."""
    try:
        from ml_engine.boucle import resume
        r = resume()
    except Exception as e:
        return {"disponible": False, "motif": f"indisponible ({type(e).__name__})"}

    terminees = db.execute(select(func.count()).select_from(Tache)
                           .where(Tache.statut == "terminee")).scalar_one()
    r["resultats_enregistres"] = int(terminees)
    r["en_attente_de_transfert"] = max(
        0, int(terminees) - int(r.get("taches_terminees", 0) or 0))
    return r


def confiees(db: Session) -> Dict[str, Any]:
    """Les alertes déjà transformées en tâche, pour que le tableau de bord affiche « Confiée à … » au…"""
    taches = db.execute(
        select(Tache)
        .where(Tache.statut != "terminee", Tache.origine_titre.isnot(None))
        .order_by(Tache.created_at.desc())).scalars().all()
    users = _users_index(db)

    out: Dict[str, Dict[str, Any]] = {}
    for t in taches:
        cle = (t.origine_titre or "").strip()
        if not cle or cle in out:
            continue
        a = users.get(t.assigne_id) if t.assigne_id else None
        out[cle] = {
            "id": t.id,
            "assigne_nom": (a.full_name or a.email) if a else None,
            "statut": t.statut,
            "echeance": t.echeance.isoformat() if t.echeance else None,
            "par_la_flotte": bool(t.delegation_auto),
        }
    return {"confiees": out}


def lister(db: Session, user: User, statut: Optional[str], client_code: Optional[str],
           assigne_id: Optional[int], limite: int) -> Dict[str, Any]:
    """Les tâches visibles par l'utilisateur, les plus urgentes d'abord."""
    q = select(Tache)
    if user.role != ROLE_DIRECTEUR:
        q = q.where(Tache.assigne_id == user.id)
    elif assigne_id is not None:
        q = q.where(Tache.assigne_id == assigne_id)
    if statut:
        if statut not in TACHE_STATUTS and statut != "ouvertes":
            raise DonneesInvalides(f"Statut invalide (attendu : {', '.join(TACHE_STATUTS)}).")
        q = q.where(Tache.statut.in_(STATUTS_OUVERTS) if statut == "ouvertes"
                    else Tache.statut == statut)
    if client_code:
        q = q.where(func.upper(Tache.client_code) == client_code.strip().upper())

    taches = db.execute(q.order_by(Tache.echeance.asc().nulls_last(),
                                   Tache.created_at.desc())
                        .limit(max(1, min(1000, limite)))).scalars().all()
    users = _users_index(db)
    lignes = [_tache_dict(t, users) for t in taches]
    compte = {s: sum(1 for ligne in lignes if ligne["statut"] == s) for s in TACHE_STATUTS}
    return {
        "taches": lignes,
        "compte_par_statut": compte,
        "en_retard": sum(1 for ligne in lignes if ligne["en_retard"]),
        "role": user.role,
    }


def creer(db: Session, user: User, body: TacheCreate) -> Dict[str, Any]:
    """Confie une tâche (le directeur répartit le travail)."""
    if body.type not in TACHE_TYPES:
        raise DonneesInvalides(f"Type invalide (attendu : {', '.join(TACHE_TYPES)}).")

    origine = (body.origine_titre or "").strip() or None
    if origine:
        deja = db.execute(
            select(Tache).where(Tache.origine_titre == origine,
                                Tache.statut != "terminee")).scalars().first()
        if deja is not None:
            a = db.get(User, deja.assigne_id) if deja.assigne_id else None
            qui = (a.full_name or a.email) if a else "quelqu'un (reste à affecter)"
            raise Conflit(f"Cette alerte est déjà confiée à {qui}. "
                          "Terminez la tâche en cours avant d'en ouvrir une autre.")

    assigne: Optional[User] = None
    if body.assigne_id is not None:
        assigne = _employe_actif(db, body.assigne_id)

    t = inserer_tache(
        db, auteur=user, assigne=assigne,
        titre=body.titre, type_=body.type, details=body.details,
        client_code=body.client_code, client_nom=body.client_nom,
        origine_categorie=body.origine_categorie, origine_titre=origine,
        montant_dt=body.montant_dt, severite=body.severite or "moyenne",
        echeance=_lire_echeance(body.echeance, body.severite or "moyenne"),
    )
    audit(db, user=user, action="tache_create", resource="/api/taches",
          detail=f"#{t.id} {t.titre[:60]} → {assigne.email if assigne else 'à affecter'}")
    return _tache_dict(t, _users_index(db))


def inserer_tache(db: Session, *, auteur: Optional[User], assigne: Optional[User],
                  titre: str, type_: str, details: Optional[str],
                  client_code: Optional[str], client_nom: Optional[str],
                  origine_categorie: Optional[str], origine_titre: Optional[str],
                  montant_dt: float, severite: str, echeance: datetime,
                  delegation_auto: bool = False,
                  evenement_creation: Optional[str] = None,
                  evenement_affectation: Optional[str] = None,
                  commentaire: Optional[str] = None) -> Tache:
    """Écrit une tâche et le début de son histoire — un seul chemin pour le directeur (`creer`) et pour…"""
    t = Tache(
        client_code=(client_code or "").strip() or None,
        client_nom=(client_nom or "").strip() or None,
        origine_categorie=(origine_categorie or "").strip() or None,
        origine_titre=(origine_titre or "").strip() or None,
        type=type_, titre=titre.strip()[:200],
        details=(details or "").strip()[:2000] or None,
        montant_dt=float(montant_dt or 0), severite=severite or "moyenne",
        assigne_id=assigne.id if assigne else None,
        cree_par_id=auteur.id if auteur else None,
        echeance=echeance,
        statut="a_faire" if assigne else "a_affecter",
        delegation_auto=bool(delegation_auto),
    )
    db.add(t)
    db.commit()
    _evt(db, t, auteur, "creation",
         evenement_creation or f"Tâche créée à partir de : {t.origine_titre or t.titre}")
    if assigne:
        _evt(db, t, auteur, "affectation",
             evenement_affectation or f"Confiée à {assigne.full_name or assigne.email}")
    if commentaire:
        _evt(db, t, auteur, "commentaire", commentaire)
    db.commit()
    return t


def detail(db: Session, user: User, tache_id: int) -> Dict[str, Any]:
    """Détail d'une tâche + son histoire complète."""
    t = _tache_visible(db, tache_id, user)
    users = _users_index(db)
    evts = db.execute(select(EvenementTache)
                      .where(EvenementTache.tache_id == t.id)
                      .order_by(EvenementTache.at.asc())).scalars().all()
    d = _tache_dict(t, users)
    d["historique"] = [{"type": e.type, "detail": e.detail, "par": e.email,
                        "at": e.at.isoformat() if e.at else None} for e in evts]
    return d


def modifier(db: Session, user: User, tache_id: int, body: TacheUpdate) -> Dict[str, Any]:
    """Fait avancer une tâche."""
    t = _tache_visible(db, tache_id, user)
    est_dir = user.role == ROLE_DIRECTEUR
    changements: List[str] = []

    if body.assigne_id is not None:
        if not est_dir:
            raise AccesRefuse("Seul le directeur peut réaffecter une tâche.")
        a = _employe_actif(db, body.assigne_id)
        t.assigne_id = a.id
        if t.statut == "a_affecter":
            t.statut = "a_faire"
        _evt(db, t, user, "affectation", f"Confiée à {a.full_name or a.email}")
        changements.append("responsable")

    if body.echeance is not None:
        if not est_dir:
            raise AccesRefuse("Seul le directeur peut déplacer l'échéance.")
        t.echeance = _lire_echeance(body.echeance, t.severite)
        _evt(db, t, user, "statut", f"Échéance au {t.echeance.strftime('%d/%m/%Y')}")
        changements.append("échéance")

    if body.statut is not None:
        if body.statut not in TACHE_STATUTS:
            raise DonneesInvalides(f"Statut invalide (attendu : {', '.join(TACHE_STATUTS)}).")
        if body.statut != "a_affecter" and t.assigne_id is None and body.assigne_id is None:
            raise DonneesInvalides("Confiez d'abord la tâche à un responsable.")
        if body.statut == "terminee":
            resultat = body.resultat or t.resultat
            if not resultat:
                raise DonneesInvalides("Indiquez le résultat obtenu avant de clôturer.")
            if resultat not in TACHE_RESULTATS:
                raise DonneesInvalides(
                    f"Résultat invalide (attendu : {', '.join(TACHE_RESULTATS)}).")
            t.resultat = resultat
            t.closed_at = datetime.now(timezone.utc)
        else:
            t.closed_at = None
        t.statut = body.statut
        _evt(db, t, user, "statut", f"Statut : {t.statut}")
        changements.append("statut")

    if body.resultat is not None and body.statut != "terminee":
        if body.resultat not in TACHE_RESULTATS:
            raise DonneesInvalides(
                f"Résultat invalide (attendu : {', '.join(TACHE_RESULTATS)}).")
        t.resultat = body.resultat
        changements.append("résultat")
    if body.resultat_montant_dt is not None:
        t.resultat_montant_dt = float(body.resultat_montant_dt)
    if body.resultat_commentaire is not None:
        t.resultat_commentaire = body.resultat_commentaire.strip() or None
    if t.statut == "terminee":
        _evt(db, t, user, "resultat",
             f"{RESULTAT_LABEL.get(t.resultat or '', t.resultat or '—')}"
             + (f" — {float(t.resultat_montant_dt):.0f} DT" if t.resultat_montant_dt else ""))

    if body.commentaire:
        _evt(db, t, user, "commentaire", body.commentaire.strip())

    t.updated_at = datetime.now(timezone.utc)
    db.commit()

    audit(db, user=user, action="tache_update", resource="/api/taches",
          detail=f"#{t.id} → {t.statut} ({', '.join(changements) or 'commentaire'})")
    return _tache_dict(t, _users_index(db))
