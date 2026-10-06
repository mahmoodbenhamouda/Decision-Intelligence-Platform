"""La délégation autonome : la flotte d'agents confie elle-même le travail d'exécution, chaque…"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import (ROLE_EMPLOYE, STATUTS_OUVERTS, DelegationPassage,
                             Reglage, Tache, User)
from api.services.erreurs import Conflit, DonneesInvalides
from api.services.taches import echeance_par_defaut, inserer_tache

logger = logging.getLogger("delegation")

CHARGE_MAX = 10

CARENCE_JOURS = 14

HEURE_PAR_DEFAUT = "07:30"
CLE_ACTIVE = "delegation_active"
CLE_HEURE = "delegation_heure"

#: Jour de la semaine du passage planifié (0 = lundi).
#:
#: La délégation partait chaque matin. Sur un portefeuille d'hôpitaux qui
#: commandent par cycles de plusieurs semaines, les mêmes alertes revenaient
#: jour après jour : l'employé recevait du travail avant d'avoir fini celui de
#: la veille, et la carence de 14 jours faisait l'essentiel du filtrage. Un
#: passage hebdomadaire, en début de semaine, donne une charge qui se planifie.
JOUR_PASSAGE = 0
JOUR_LIBELLE = "lundi"

DECLENCHEURS = ("planifie", "manuel", "commande")

_VERROU = threading.Lock()


def _lire(db: Session, cle: str, defaut: str) -> str:
    r = db.get(Reglage, cle)
    return r.valeur if r is not None else defaut


def _ecrire(db: Session, cle: str, valeur: str, user: Optional[User]) -> None:
    r = db.get(Reglage, cle)
    if r is None:
        db.add(Reglage(cle=cle, valeur=valeur, modifie_par_id=user.id if user else None))
    else:
        r.valeur = valeur
        r.modifie_par_id = user.id if user else None
        r.modifie_le = datetime.now(timezone.utc)


def lire_heure(valeur: str) -> time:
    """« HH:MM » → heure ; `DonneesInvalides` sinon."""
    try:
        h, m = (int(x) for x in valeur.strip().split(":"))
        return time(h, m)
    except Exception:
        raise DonneesInvalides("Heure invalide (format attendu : HH:MM, par exemple 07:30).")


def reglages(db: Session) -> Dict[str, Any]:
    return {"active": _lire(db, CLE_ACTIVE, "0") == "1",
            "heure": _lire(db, CLE_HEURE, HEURE_PAR_DEFAUT)}


def modifier_reglages(db: Session, user: User, active: Optional[bool],
                      heure: Optional[str]) -> Dict[str, Any]:
    changements = []
    if heure is not None:
        h = lire_heure(heure)
        _ecrire(db, CLE_HEURE, f"{h.hour:02d}:{h.minute:02d}", user)
        changements.append(f"heure {h.hour:02d}:{h.minute:02d}")
    if active is not None:
        _ecrire(db, CLE_ACTIVE, "1" if active else "0", user)
        changements.append("activée" if active else "désactivée")
    db.commit()
    audit(db, user=user, action="delegation_reglage", resource="/api/taches/delegation",
          detail=", ".join(changements) or "aucun changement")
    return etat(db)


def jour_local(maintenant: datetime) -> str:
    """Clé de déduplication du passage planifié : la SEMAINE, pas le jour.

    Avec une clé journalière, un serveur arrêté le lundi sautait la semaine
    entière. Avec la semaine ISO, le passage se rattrape dès que la plateforme
    revient — il reste unique, il n'est plus perdu."""
    a, s, _ = maintenant.isocalendar()
    return f"{a}-S{s:02d}"


def passage_du(active: bool, heure: time, maintenant: datetime,
               deja_fait_cette_semaine: bool) -> bool:
    """Le passage hebdomadaire doit-il partir MAINTENANT ?

    Il part à partir du jour retenu — lundi — à l'heure réglée, et une seule
    fois par semaine. Au-delà du lundi, il se rattrape : mieux vaut une
    délégation en retard qu'une semaine sans."""
    if not active or deja_fait_cette_semaine:
        return False
    if maintenant.weekday() > JOUR_PASSAGE:
        return True
    return maintenant.weekday() == JOUR_PASSAGE and maintenant.time() >= heure


def prochain_passage(active: bool, heure: time, maintenant: datetime,
                     deja_fait_cette_semaine: bool) -> Optional[datetime]:
    """Date et heure du prochain passage hebdomadaire."""
    if not active:
        return None
    jours = (JOUR_PASSAGE - maintenant.weekday()) % 7
    candidat = datetime.combine(maintenant.date() + timedelta(days=jours), heure)
    # `jours > 0` place déjà le candidat dans la SEMAINE SUIVANTE : y ajouter
    # sept jours de plus renverrait au lundi d'après-encore. Le report ne vaut
    # donc que pour le créneau du jour même, passé ou déjà honoré.
    if jours == 0 and (deja_fait_cette_semaine
                       or candidat < maintenant.replace(second=0, microsecond=0)):
        candidat += timedelta(days=7)
    return candidat


def _deja_fait(db: Session, jour: str) -> bool:
    return db.execute(select(DelegationPassage.id)
                      .where(DelegationPassage.jour_planifie == jour)).first() is not None


def _passage_dict(p: DelegationPassage, users: Optional[Dict[int, User]] = None,
                  avec_briefing: bool = False) -> Dict[str, Any]:
    qui = None
    if p.lance_par_id and users:
        u = users.get(p.lance_par_id)
        qui = (u.full_name or u.email) if u else None
    try:
        detail = json.loads(p.detail) if p.detail else {}
    except ValueError:
        detail = {}
    d = {
        "id": p.id, "declencheur": p.declencheur, "lance_par": qui,
        "statut": p.statut, "moteur": p.moteur, "motif": p.motif,
        "debut": p.debut.isoformat() if p.debut else None,
        "fin": p.fin.isoformat() if p.fin else None,
        "n_propositions": p.n_propositions, "n_creees": p.n_creees,
        "n_deja_confiees": p.n_deja_confiees, "n_recentes": p.n_recentes,
        "n_decisions": p.n_decisions, "n_ecartees": p.n_ecartees,
        "lignes": detail.get("lignes", []),
        "decisions_direction": detail.get("decisions_direction", []),
        "ecartes": detail.get("ecartes", []),
    }
    if avec_briefing:
        d["briefing"] = p.briefing
    return d


def etat(db: Session, maintenant: Optional[datetime] = None, n_passages: int = 5) -> Dict[str, Any]:
    """Ce que le directeur voit : réglages, dernier passage, prochain passage."""
    maintenant = maintenant or datetime.now()
    r = reglages(db)
    h = lire_heure(r["heure"])
    fait = _deja_fait(db, jour_local(maintenant))
    prochain = prochain_passage(r["active"], h, maintenant, fait)
    passages = db.execute(select(DelegationPassage)
                          .order_by(DelegationPassage.debut.desc(), DelegationPassage.id.desc())
                          .limit(max(1, n_passages))).scalars().all()
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    return {
        **r,
        "prochain_passage": prochain.isoformat(timespec="minutes") if prochain else None,
        "regles": {"charge_max": CHARGE_MAX, "carence_jours": CARENCE_JOURS},
        "dernier": _passage_dict(passages[0], users, avec_briefing=True) if passages else None,
        "historique": [_passage_dict(p, users) for p in passages],
    }


def _flotte_globale() -> Dict[str, Any]:
    """Le briefing du périmètre complet — jamais celui d'un client."""
    from agents.fleet.graph import run_briefing
    return run_briefing({})


def _charges(db: Session) -> Dict[int, int]:
    return dict(db.execute(
        select(Tache.assigne_id, func.count(Tache.id))
        .where(Tache.statut.in_(STATUTS_OUVERTS), Tache.assigne_id.isnot(None))
        .group_by(Tache.assigne_id)).all())


def _choisir(employes: List[User], charges: Dict[int, int], poste: str):
    """L'employé actif de ce métier le moins chargé (à charge égale, le plus ancien compte), avec la…"""
    candidats = [e for e in employes if (e.poste or "") == poste]
    if not candidats:
        return None, f"aucun employé actif au poste « {poste} »"
    e = min(candidats, key=lambda u: (charges.get(u.id, 0), u.id))
    if charges.get(e.id, 0) >= CHARGE_MAX:
        return None, (f"équipe « {poste} » saturée ({charges.get(e.id, 0)} tâches "
                      f"ouvertes pour {e.full_name or e.email}, plafond {CHARGE_MAX})")
    if len(candidats) == 1:
        return e, f"seul employé au poste « {poste} »"
    return e, f"le moins chargé des {len(candidats)} employés au poste « {poste} »"


def executer(db: Session, *, declencheur: str, auteur: Optional[User] = None,
             lancer_flotte: Optional[Callable[[], Dict[str, Any]]] = None,
             maintenant: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Un passage complet. Renvoie le passage, ou None si le passage planifié du jour a déjà été pris…"""
    if declencheur not in DECLENCHEURS:
        raise DonneesInvalides(f"Déclencheur inconnu : {declencheur}")
    if not _VERROU.acquire(blocking=False):
        raise Conflit("Un passage de la délégation est déjà en cours.")
    try:
        return _executer(db, declencheur, auteur, lancer_flotte or _flotte_globale,
                         maintenant or datetime.now())
    finally:
        _VERROU.release()


def _executer(db: Session, declencheur: str, auteur: Optional[User],
              lancer_flotte: Callable[[], Dict[str, Any]],
              maintenant: datetime) -> Optional[Dict[str, Any]]:
    from agents.fleet.delegation import planifier

    passage = DelegationPassage(
        declencheur=declencheur,
        jour_planifie=jour_local(maintenant) if declencheur == "planifie" else None,
        lance_par_id=auteur.id if auteur else None, statut="en_cours")
    db.add(passage)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info("passage planifié du %s déjà pris", jour_local(maintenant))
        return None

    def _finir(statut: str, motif: Optional[str] = None) -> Dict[str, Any]:
        passage.statut = statut
        passage.motif = motif
        passage.fin = datetime.now(timezone.utc)
        db.commit()
        audit(db, user=auteur, action="delegation_auto", resource="/api/taches/delegation",
              email=None if auteur else "flotte d'agents",
              detail=(f"{declencheur} · {statut} · {passage.n_creees} tâche(s) confiée(s), "
                      f"{passage.n_deja_confiees} déjà en cours, "
                      f"{passage.n_decisions} décision(s) laissée(s) à la direction"
                      + (f" · {motif}" if motif else ""))[:500])
        users = {u.id: u for u in db.execute(select(User)).scalars().all()}
        return _passage_dict(passage, users, avec_briefing=True)

    try:
        sortie = lancer_flotte() or {}
    except Exception as e:  # pragma: no cover — la flotte a déjà ses filets
        logger.exception("flotte en échec pendant la délégation")
        return _finir("echec", f"la flotte n'a pas pu tourner ({type(e).__name__})")
    passage.moteur = str(sortie.get("engine") or "")[:40]
    passage.briefing = (sortie.get("briefing") or "")[:20000] or None
    if passage.moteur == "erreur":
        return _finir("echec", "la flotte a renvoyé une erreur : aucune tâche confiée")

    plan = planifier(sortie.get("findings") or [])
    if not plan.classement_disponible:
        return _finir("echec", "l'arbitre n'a pas statué : rien n'est confié sans "
                               "classement commun")

    employes = db.execute(select(User).where(User.role == ROLE_EMPLOYE,
                                             User.is_active.is_(True))).scalars().all()
    charges = _charges(db)
    limite_carence = datetime.now(timezone.utc) - timedelta(days=CARENCE_JOURS)
    lignes: List[Dict[str, Any]] = []
    n = {"creee": 0, "deja_confiee": 0, "recente": 0}

    for p in plan.propositions:
        ligne: Dict[str, Any] = {"rang": p.rang, "titre": p.origine_titre,
                                 "categorie": p.origine_categorie, "poste": p.poste,
                                 "montant_dt": p.montant_dt, "motif": p.motif}
        ouverte = db.execute(select(Tache).where(
            Tache.origine_titre == p.origine_titre,
            Tache.statut.in_(STATUTS_OUVERTS))).scalars().first()
        if ouverte is not None:
            a = db.get(User, ouverte.assigne_id) if ouverte.assigne_id else None
            ligne.update(issue="deja_confiee", tache_id=ouverte.id,
                         raison=("déjà confiée à " + (a.full_name or a.email)) if a
                         else "déjà ouverte, en attente d'affectation")
            n["deja_confiee"] += 1
            lignes.append(ligne)
            continue

        recente = db.execute(select(Tache).where(
            Tache.origine_titre == p.origine_titre, Tache.statut == "terminee",
            Tache.closed_at >= limite_carence)
            .order_by(Tache.closed_at.desc())).scalars().first()
        if recente is not None:
            ligne.update(issue="recente", tache_id=recente.id,
                         raison=(f"traitée le {recente.closed_at:%d/%m/%Y} : les données "
                                 f"ne le reflètent peut-être pas encore (carence de "
                                 f"{CARENCE_JOURS} jours)"))
            n["recente"] += 1
            lignes.append(ligne)
            continue

        employe, pourquoi = _choisir(employes, charges, p.poste)
        t = inserer_tache(
            db, auteur=None, assigne=employe,
            titre=p.titre, type_=p.type, details=p.details,
            client_code=p.client_code, client_nom=p.client_nom,
            origine_categorie=p.origine_categorie, origine_titre=p.origine_titre,
            montant_dt=p.montant_dt, severite=p.severite,
            echeance=echeance_par_defaut(p.severite),
            delegation_auto=True,
            evenement_creation=(f"Confiée d'office par la flotte d'agents "
                                f"({p.motif}) : {p.origine_titre}")[:500],
            evenement_affectation=(
                f"Confiée par la flotte à {employe.full_name or employe.email} — "
                f"métier « {p.poste} », {charges.get(employe.id, 0)} tâche(s) déjà en cours"
                if employe else None),
            commentaire=(f"Laissée à affecter par la flotte : {pourquoi}"
                         if employe is None else None),
        )
        if employe is not None:
            charges[employe.id] = charges.get(employe.id, 0) + 1
            ligne.update(issue="creee", tache_id=t.id,
                         assigne=employe.full_name or employe.email,
                         raison=pourquoi)
        else:
            ligne.update(issue="creee", tache_id=t.id, assigne=None, raison=pourquoi)
        n["creee"] += 1
        lignes.append(ligne)

    passage.n_propositions = len(plan.propositions)
    passage.n_creees = n["creee"]
    passage.n_deja_confiees = n["deja_confiee"]
    passage.n_recentes = n["recente"]
    passage.n_decisions = len(plan.decisions_direction)
    passage.n_ecartees = len(plan.ecartes)
    passage.detail = json.dumps({"lignes": lignes,
                                 "decisions_direction": plan.decisions_direction,
                                 "ecartes": plan.ecartes}, ensure_ascii=False)
    return _finir("ok")


def lancer(db: Session, user: User) -> Dict[str, Any]:
    """« Lancer maintenant » — le directeur déclenche un passage hors planning."""
    r = executer(db, declencheur="manuel", auteur=user)
    assert r is not None
    return r


def executer_si_du(maintenant: Optional[datetime] = None,
                   lancer_flotte: Optional[Callable[[], Dict[str, Any]]] = None
                   ) -> Optional[Dict[str, Any]]:
    """Appelé chaque minute par le planificateur de l'API (et par la ligne de commande) : lance le…"""
    from api.auth.database import get_db

    maintenant = maintenant or datetime.now()
    db = next(get_db())
    try:
        r = reglages(db)
        if not passage_du(r["active"], lire_heure(r["heure"]), maintenant,
                          _deja_fait(db, jour_local(maintenant))):
            return None
        try:
            return executer(db, declencheur="planifie", lancer_flotte=lancer_flotte,
                            maintenant=maintenant)
        except Conflit:
            return None
    finally:
        db.close()
