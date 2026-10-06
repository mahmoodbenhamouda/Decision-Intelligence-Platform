"""La boucle d'approvisionnement : recommander, décider, commander, réceptionner.

L'export ERP ne contient que des FACTURES d'achat. Ni bon de commande, ni date
de réception : trois étapes du processus d'approvisionnement n'y existent pas,
et aucun délai de livraison n'y est calculable.

Ce module les crée. L'analyse de réassort propose, le directeur tranche, la
commande se passe, la réception se saisit. L'écart entre la date de commande et
la date de réception EST le délai de livraison réel — une donnée qui n'existait
nulle part et que la plateforme produit elle-même, un tour de boucle à la fois.

Deux garde-fous :

  * le cycle est un ORDRE, pas un champ libre. Une commande ne se reçoit pas
    sans avoir été passée, ne se valide pas deux fois, et un refus est
    définitif. Les transitions permises sont déclarées dans le modèle ;
  * une recommandation ne se duplique pas. Tant qu'une référence a une commande
    ouverte, l'analyse ne la propose plus : sans ça, le directeur verrait
    chaque matin la même ligne qu'il a validée la veille.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.auth.models import (COMMANDE_ORIGINES, COMMANDE_OUVERTS,
                             COMMANDE_STATUTS, COMMANDE_TRANSITIONS,
                             CommandeFournisseur, EvenementCommande, User)
from api.services.erreurs import Conflit, DonneesInvalides, Introuvable

#: Libellé lisible de chaque étape du cycle.
STATUT_LABEL = {
    "recommandee": "Proposée par l'analyse",
    "validee": "Validée, à commander",
    "refusee": "Refusée",
    "commandee": "Commandée, en attente de réception",
    "recue": "Reçue",
    "annulee": "Annulée",
}

#: Ce que chaque étape attend comme geste suivant.
PROCHAIN_GESTE = {
    "recommandee": "Valider ou refuser",
    "validee": "Passer la commande au fournisseur",
    "commandee": "Saisir la réception",
    "refusee": "",
    "recue": "",
    "annulee": "",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _evt(db: Session, c: CommandeFournisseur, user: Optional[User],
         de: Optional[str], vers: str, detail: str = "") -> None:
    """Trace une transition. Sans commit : le geste appelant commite."""
    db.add(EvenementCommande(
        commande_id=c.id, user_id=user.id if user else None,
        email=user.email if user else None,
        de=de, vers=vers, detail=(detail or "")[:500]))


def _vue(c: CommandeFournisseur) -> Dict[str, Any]:
    return {
        "id": c.id,
        "reference": c.reference,
        "designation": c.designation,
        "fournisseur_code": c.fournisseur_code,
        "fournisseur_nom": c.fournisseur_nom,
        "origine": c.origine,
        "motif": c.motif,
        "qte_proposee": c.qte_proposee,
        "qte_recue": c.qte_recue,
        "montant_estime_dt": c.montant_estime_dt,
        "statut": c.statut,
        "statut_label": STATUT_LABEL.get(c.statut, c.statut),
        "prochain_geste": PROCHAIN_GESTE.get(c.statut, ""),
        "motif_refus": c.motif_refus,
        "commentaire": c.commentaire,
        "decide_at": c.decide_at.isoformat() if c.decide_at else None,
        "commande_at": c.commande_at.isoformat() if c.commande_at else None,
        "recue_at": c.recue_at.isoformat() if c.recue_at else None,
        "delai_livraison_j": c.delai_livraison_j,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "ouverte": c.statut in COMMANDE_OUVERTS,
    }


# ── Recommander ──────────────────────────────────────────────────────────────

def recommandations(db: Session,
                    filtres: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Réassorts proposés par l'analyse, moins ceux déjà traités.

    Une référence qui porte déjà une commande ouverte, ou refusée récemment,
    n'est plus proposée : une liste qui repropose chaque matin ce qu'on a
    décidé la veille cesse d'être lue."""
    from ml_engine.analytics import approvisionnement as ap

    try:
        analyse = ap.analyser(filtres)
    except Exception as e:
        return {"servi": False, "motif": f"indisponible ({type(e).__name__})"}
    if not analyse.get("servi"):
        return analyse

    propositions = (analyse.get("reapprovisionnement") or {}).get("a_recommander") or []

    deja = {r for (r,) in db.execute(
        select(CommandeFournisseur.reference)
        .where(CommandeFournisseur.statut.in_(COMMANDE_OUVERTS + ("refusee",)))
    ).all()}

    nouvelles = [p for p in propositions if p.get("reference") not in deja]
    return {
        "servi": True,
        "nature": "comptage",
        "propositions": nouvelles,
        "n_proposees": len(nouvelles),
        "n_deja_traitees": len(propositions) - len(nouvelles),
        "base_de_la_proposition": (
            analyse.get("reapprovisionnement") or {}).get("base_de_la_proposition"),
        "regle": (analyse.get("reapprovisionnement") or {}).get("regle"),
    }


def creer(db: Session, user: Optional[User], donnees: Dict[str, Any],
          origine: str = "ia") -> Dict[str, Any]:
    """Enregistre une proposition de réassort, en attente de décision."""
    reference = str(donnees.get("reference") or "").strip()
    if not reference:
        raise DonneesInvalides("La référence du produit est obligatoire.")
    if origine not in COMMANDE_ORIGINES:
        origine = "ia"

    ouverte = db.execute(
        select(CommandeFournisseur)
        .where(CommandeFournisseur.reference == reference,
               CommandeFournisseur.statut.in_(COMMANDE_OUVERTS))
    ).scalars().first()
    if ouverte:
        raise Conflit(
            f"Une commande est déjà en cours pour cette référence "
            f"(#{ouverte.id}, {STATUT_LABEL.get(ouverte.statut, ouverte.statut)}).")

    qte = float(donnees.get("qte_proposee") or 0)
    if qte < 0:
        raise DonneesInvalides("La quantité ne peut pas être négative.")

    c = CommandeFournisseur(
        reference=reference,
        designation=(donnees.get("designation") or None),
        fournisseur_code=(donnees.get("fournisseur_code") or None),
        fournisseur_nom=(donnees.get("fournisseur_nom") or None),
        origine=origine,
        motif=(donnees.get("motif") or None),
        qte_proposee=qte,
        montant_estime_dt=float(donnees.get("montant_estime_dt") or 0),
        statut="recommandee",
    )
    db.add(c)
    db.flush()
    _evt(db, c, user, None, "recommandee",
         "proposée par l'analyse de réassort" if origine == "ia"
         else "saisie manuellement")
    db.commit()
    db.refresh(c)
    return _vue(c)


# ── Décider et faire avancer ─────────────────────────────────────────────────

def _charger(db: Session, commande_id: int) -> CommandeFournisseur:
    c = db.get(CommandeFournisseur, commande_id)
    if c is None:
        raise Introuvable("Commande introuvable.")
    return c


def _transition(db: Session, c: CommandeFournisseur, user: Optional[User],
                vers: str, detail: str = "") -> None:
    """Applique une transition si le cycle l'autorise, sinon refuse.

    Le refus porte le chemin possible : un message qui dit seulement « interdit »
    oblige à lire le code pour comprendre."""
    if vers not in COMMANDE_STATUTS:
        raise DonneesInvalides(f"Statut inconnu : {vers}.")
    permis = COMMANDE_TRANSITIONS.get(c.statut, ())
    if vers not in permis:
        attendu = (", ".join(permis) if permis
                   else "aucune — cette commande est close")
        raise Conflit(
            f"Une commande « {STATUT_LABEL.get(c.statut, c.statut)} » ne peut "
            f"pas passer à « {STATUT_LABEL.get(vers, vers)} ». "
            f"Transitions possibles : {attendu}.")
    _evt(db, c, user, c.statut, vers, detail)
    c.statut = vers


def _confier_a_la_logistique(db: Session, user: Optional[User],
                             c: CommandeFournisseur) -> Optional[str]:
    """Passe la main à l'équipe logistique, qui exécutera la commande.

    Le directeur décide, il ne saisit pas. Une fois la proposition validée, le
    travail restant — passer la commande, suivre la livraison, saisir la
    réception — est un travail d'exécution : il part vers l'employé logistique
    le moins chargé et apparaît sur son écran.

    Sans équipe logistique configurée, la tâche reste à affecter plutôt que
    d'échouer : la commande est validée, c'est l'essentiel ; qui l'exécute se
    règle ensuite."""
    from api.services.delegation import _charges, _choisir
    from api.services.taches import echeance_par_defaut, inserer_tache

    employes = db.execute(
        select(User).where(User.role == "employe", User.is_active.is_(True))
    ).scalars().all()
    assigne, pourquoi = _choisir(list(employes), _charges(db), "logistique")

    titre = f"Commander {c.designation or c.reference}"
    inserer_tache(
        db, auteur=user, assigne=assigne,
        titre=titre, type_="commande",
        details=(f"Réassort validé par la direction : {c.qte_proposee:.0f} × "
                 f"{c.designation or c.reference} chez "
                 f"{c.fournisseur_nom or 'le fournisseur habituel'}, pour un "
                 f"montant estimé de {c.montant_estime_dt:,.0f} DT."
                 .replace(",", " ")
                 + (f"\n\nMotif du réassort : {c.motif}" if c.motif else "")
                 + "\n\nÀ faire : passer la commande, puis saisir la réception "
                   "à l'arrivée de la marchandise."),
        client_code=None, client_nom=None,
        origine_categorie="Approvisionnement",
        origine_titre=f"commande-{c.id}",
        montant_dt=float(c.montant_estime_dt or 0),
        severite="haute",
        echeance=echeance_par_defaut("haute"),
        evenement_creation=f"réassort validé — {pourquoi}",
    )
    return (assigne.full_name or assigne.email) if assigne else None


def decider(db: Session, user: Optional[User], commande_id: int,
            valide: bool, motif_refus: str = "") -> Dict[str, Any]:
    """Le directeur tranche : la proposition devient une commande, ou s'arrête.

    À la validation, l'exécution part vers l'équipe logistique : le directeur
    occupe une position de décision, pas de saisie."""
    c = _charger(db, commande_id)
    if not valide and not (motif_refus or "").strip():
        raise DonneesInvalides(
            "Un refus doit porter son motif : c'est lui qui apprend à "
            "l'analyse ce qu'elle a mal jugé.")
    _transition(db, c, user, "validee" if valide else "refusee",
                motif_refus.strip()[:500] if not valide else "")
    c.decide_at = _utcnow()
    c.decide_par_id = user.id if user else None
    if not valide:
        c.motif_refus = motif_refus.strip()[:500]

    # La DÉCISION est rendue durable AVANT la délégation. L'ordre compte :
    # `inserer_tache` commet pour son propre compte, donc l'envelopper dans un
    # point de sauvegarde ne protégerait rien. Si l'affectation échoue — aucun
    # employé logistique, équipe saturée — la commande reste validée et visible,
    # elle sera confiée à la main. Un défaut d'affectation n'a aucune raison de
    # défaire ce que le directeur a tranché.
    db.commit()
    db.refresh(c)

    confie_a = None
    if valide:
        try:
            confie_a = _confier_a_la_logistique(db, user, c)
        except Exception:
            db.rollback()
            confie_a = None

    return {**_vue(c), "confie_a": confie_a}


def passer_commande(db: Session, user: Optional[User], commande_id: int,
                    commentaire: str = "") -> Dict[str, Any]:
    """La commande part chez le fournisseur. C'est cette date qui manquait."""
    c = _charger(db, commande_id)
    _transition(db, c, user, "commandee", commentaire)
    c.commande_at = _utcnow()
    if commentaire:
        c.commentaire = commentaire.strip()[:1000]
    db.commit()
    db.refresh(c)
    return _vue(c)


def receptionner(db: Session, user: Optional[User], commande_id: int,
                 qte_recue: Optional[float] = None,
                 commentaire: str = "") -> Dict[str, Any]:
    """La marchandise arrive. Commande → réception = le délai réel, enfin mesuré."""
    c = _charger(db, commande_id)
    if qte_recue is not None and float(qte_recue) < 0:
        raise DonneesInvalides("La quantité reçue ne peut pas être négative.")
    _transition(db, c, user, "recue", commentaire)
    c.recue_at = _utcnow()
    c.qte_recue = (float(qte_recue) if qte_recue is not None else c.qte_proposee)
    if commentaire:
        c.commentaire = commentaire.strip()[:1000]
    db.commit()
    db.refresh(c)
    return _vue(c)


def annuler(db: Session, user: Optional[User], commande_id: int,
            motif: str = "") -> Dict[str, Any]:
    c = _charger(db, commande_id)
    _transition(db, c, user, "annulee", motif)
    db.commit()
    db.refresh(c)
    return _vue(c)


# ── Lire ─────────────────────────────────────────────────────────────────────

def lister(db: Session, statut: Optional[str] = None,
           limite: int = 100) -> List[Dict[str, Any]]:
    q = select(CommandeFournisseur).order_by(CommandeFournisseur.created_at.desc())
    if statut == "ouvertes":
        q = q.where(CommandeFournisseur.statut.in_(COMMANDE_OUVERTS))
    elif statut in COMMANDE_STATUTS:
        q = q.where(CommandeFournisseur.statut == statut)
    return [_vue(c) for c in db.execute(q.limit(max(1, min(500, limite)))).scalars()]


def histoire(db: Session, commande_id: int) -> List[Dict[str, Any]]:
    _charger(db, commande_id)
    lignes = db.execute(
        select(EvenementCommande)
        .where(EvenementCommande.commande_id == commande_id)
        .order_by(EvenementCommande.at)
    ).scalars()
    return [{
        "de": e.de, "vers": e.vers,
        "de_label": STATUT_LABEL.get(e.de or "", e.de),
        "vers_label": STATUT_LABEL.get(e.vers, e.vers),
        "detail": e.detail, "par": e.email,
        "at": e.at.isoformat() if e.at else None,
    } for e in lignes]


def bilan(db: Session) -> Dict[str, Any]:
    """Ce que la boucle a produit — y compris la donnée que l'ERP n'a pas.

    Tant qu'aucune commande n'a été reçue, le délai réel reste inconnu : on le
    dit, plutôt que d'afficher un zéro qui passerait pour une mesure."""
    par_statut = {s: 0 for s in COMMANDE_STATUTS}
    for statut, n in db.execute(
        select(CommandeFournisseur.statut, func.count())
        .group_by(CommandeFournisseur.statut)
    ).all():
        par_statut[statut] = int(n)

    recues = db.execute(
        select(CommandeFournisseur)
        .where(CommandeFournisseur.statut == "recue",
               CommandeFournisseur.commande_at.is_not(None),
               CommandeFournisseur.recue_at.is_not(None))
    ).scalars().all()
    delais = sorted(d for d in (c.delai_livraison_j for c in recues) if d is not None)

    montant_engage = float(db.execute(
        select(func.coalesce(func.sum(CommandeFournisseur.montant_estime_dt), 0.0))
        .where(CommandeFournisseur.statut.in_(("validee", "commandee")))
    ).scalar() or 0.0)

    n = len(delais)
    return {
        "par_statut": [{"statut": s, "label": STATUT_LABEL.get(s, s),
                        "n": par_statut[s]} for s in COMMANDE_STATUTS],
        "n_total": sum(par_statut.values()),
        "n_ouvertes": sum(par_statut[s] for s in COMMANDE_OUVERTS),
        "montant_engage_dt": round(montant_engage, 0),
        "delai_livraison": {
            "mesurable": n > 0,
            "n_receptions": n,
            "median_j": delais[n // 2] if n else None,
            "min_j": delais[0] if n else None,
            "max_j": delais[-1] if n else None,
            "origine": (
                "écart entre la date de commande et la date de réception, "
                "toutes deux saisies dans la plateforme. Cette donnée n'existe "
                "nulle part ailleurs : elle naît de vos saisies."),
            "motif_si_absent": (
                "aucune commande n'a encore été reçue. Le délai réel apparaîtra "
                "à la première réception saisie." if n == 0 else None),
        },
    }
