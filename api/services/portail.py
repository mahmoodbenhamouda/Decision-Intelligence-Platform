"""
api/services/portail.py
=======================
Portail CLIENT : des actions concrètes sur SES données.

Pourquoi des actions séparées des demandes
------------------------------------------
Une demande est du texte libre : quelqu'un doit la lire pour savoir quoi en
faire. Une action est STRUCTURÉE — un type, une référence, un montant, une date
— donc le serveur sait immédiatement quelle tâche créer, pour quel montant, et
le résultat de cette tâche pourra plus tard être comparé à ce que le client
avait annoncé. C'est cette différence qui permet de mesurer, par exemple, la
part des promesses de paiement réellement tenues.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import (REQUEST_TYPES, ROLE_DIRECTEUR, ClientRequest,
                             EvenementTache, Tache, User)
from api.donnees import entrepot
from api.schemas.portail import ActionCreate, RequestCreate
from api.services.erreurs import AccesRefuse, DonneesInvalides, ErreurInterne
from api.services.taches import echeance_par_defaut
from ml_engine import passerelle as pw


def code_effectif(user: User, client_code: Optional[str]) -> str:
    """Code client effectif : le sien (client), ou celui demandé (directeur)."""
    if user.role == ROLE_DIRECTEUR:
        if not client_code:
            raise DonneesInvalides("client_code requis pour le directeur.")
        return client_code
    if not user.client_code:
        raise AccesRefuse("Compte client sans code client associé.")
    return user.client_code   # isolation : le paramètre est IGNORÉ pour un client


def exiger_code_client(user: User) -> str:
    """Les écrans réservés au client exigent un compte relié à un code client."""
    if not user.client_code:
        raise AccesRefuse("Compte client sans code client associé.")
    return user.client_code


# ── Factures ────────────────────────────────────────────────────────────────
def _statut_facture(delai) -> str:
    if delai is None:
        return "n/d"
    d = float(delai)
    return "critique" if d > 90 else "retard" if d > 30 else "a_l_heure"


def factures(code: str, limite: int) -> Dict[str, Any]:
    """Factures réelles du périmètre, les plus récentes d'abord, avec statut."""
    limite = max(1, min(200, limite))
    try:
        rows, tot = entrepot.factures_client(code, limite)
    except Exception as e:
        return {"error": f"Entrepôt indisponible : {e}", "invoices": []}
    return {
        "client_code": code,
        "invoices": [{"date": r[0], "echeance": r[1],
                      "montant_ttc": float(r[2] or 0),
                      "delai_jours": float(r[3]) if r[3] is not None else None,
                      "mode_reglement": (r[4] or "").strip() or None,
                      "statut": _statut_facture(r[3])} for r in rows],
        "total_factures": int(tot[0]), "total_ttc": float(tot[1]),
        "encours_retard_ttc": float(tot[2]),
    }


# ── Demandes ────────────────────────────────────────────────────────────────
def creer_demande(db: Session, user: User, body: RequestCreate) -> Dict[str, Any]:
    """Dépose une demande (action concrète du client vers la direction)."""
    if body.type not in REQUEST_TYPES:
        raise DonneesInvalides(f"Type invalide (attendu : {', '.join(REQUEST_TYPES)}).")
    r = ClientRequest(user_id=user.id, client_code=user.client_code,
                      type=body.type, sujet=body.sujet.strip(),
                      message=body.message.strip(),
                      invoice_ref=(body.invoice_ref or "").strip() or None)
    db.add(r)
    db.commit()
    audit(db, user=user, action="portal_create_request",
          resource="/api/portal/requests", detail=f"{body.type} : {body.sujet[:80]}")
    return {"ok": True, "id": r.id, "status": r.status}


def mes_demandes(db: Session, user: User) -> Dict[str, Any]:
    """SES demandes uniquement (le directeur passe par l'administration)."""
    q = select(ClientRequest).order_by(ClientRequest.created_at.desc())
    if user.role != ROLE_DIRECTEUR:
        q = q.where(ClientRequest.user_id == user.id)   # isolation stricte
    reqs = db.execute(q).scalars().all()
    return {"requests": [{
        "id": r.id, "type": r.type, "sujet": r.sujet, "message": r.message,
        "invoice_ref": r.invoice_ref, "status": r.status, "reponse": r.reponse,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in reqs]}


# ── Actions du client sur ce qu'il consulte ─────────────────────────────────
#: Chaque action du client se traduit en une tâche interne d'un type donné,
#: avec sa gravité. La gravité décide ensuite du délai de traitement
#: (`DELAI_PAR_SEVERITE`) : une réclamation n'attend pas comme un « ce produit
#: m'intéresse ».
ACTIONS = {
    "promesse_paiement": {"tache": "echeancier", "severite": "haute",
                          "sujet": "Promesse de paiement"},
    "reclamation": {"tache": "reclamation", "severite": "haute",
                    "sujet": "Réclamation sur facture"},
    "devis_reponse": {"tache": "relance_devis", "severite": "haute",
                      "sujet": "Réponse à un devis"},
    "interet_produit": {"tache": "appel", "severite": "moyenne",
                        "sujet": "Produit qui intéresse le client"},
    "reservation_stock": {"tache": "commande", "severite": "moyenne",
                          "sujet": "Réservation de quantité"},
    "echeancier": {"tache": "echeancier", "severite": "haute",
                   "sujet": "Demande d'échéancier"},
}

_REPONSE_DEVIS = {"accepte": "accepte le devis", "refuse": "refuse le devis",
                  "modification": "demande une modification du devis"}


def resume_action(body: ActionCreate) -> str:
    """Phrase lisible par l'employé qui recevra la tâche (jamais du jargon)."""
    bouts = []
    if body.type == "promesse_paiement":
        bouts.append(f"Le client s'engage à payer {body.montant_dt:,.0f} DT"
                     .replace(",", " ") if body.montant_dt else "Le client s'engage à payer")
        if body.date_prevue:
            bouts.append(f"le {body.date_prevue}")
        if body.reference:
            bouts.append(f"(facture du {body.reference})")
    elif body.type == "devis_reponse":
        bouts.append("Le client " + _REPONSE_DEVIS.get(body.reponse or "", "a répondu au devis"))
        if body.libelle:
            bouts.append(f"« {body.libelle} »")
    elif body.type == "interet_produit":
        bouts.append(f"Le client souhaite une proposition sur « {body.libelle or body.reference} »")
    elif body.type == "reservation_stock":
        bouts.append(f"Le client réserve {body.quantite:.0f} unité(s) de "
                     f"« {body.libelle or body.reference} »" if body.quantite
                     else f"Le client veut réserver « {body.libelle or body.reference} »")
    elif body.type == "reclamation":
        bouts.append(f"Réclamation sur la facture {body.reference or '(non précisée)'}")
    else:
        bouts.append("Demande du client")
    if body.message:
        bouts.append(f"— {body.message.strip()}")
    return " ".join(b for b in bouts if b).strip()


def creer_action(db: Session, user: User, body: ActionCreate) -> Dict[str, Any]:
    """Enregistre l'action du client ET crée la tâche interne correspondante.

    La tâche naît SANS responsable (`statut = a_affecter`) : c'est le directeur
    qui décide à qui elle revient, en voyant la charge de chacun. Elle arrive
    donc en tête du tableau de suivi plutôt que dans une boîte mail.
    """
    if body.type not in ACTIONS:
        raise DonneesInvalides(f"Action inconnue (attendu : {', '.join(ACTIONS)}).")
    if body.type not in REQUEST_TYPES:  # garde-fou : les deux listes doivent rester alignées
        raise ErreurInterne("Type d'action non déclaré dans le schéma.")
    if user.role == ROLE_DIRECTEUR:
        raise AccesRefuse("Cette action appartient au client : "
                          "le directeur agit par les tâches.")
    if not user.client_code:
        raise AccesRefuse("Compte client sans code client associé.")

    regle = ACTIONS[body.type]
    resume = resume_action(body)
    nom = user.full_name or user.client_code

    r = ClientRequest(user_id=user.id, client_code=user.client_code, type=body.type,
                      sujet=regle["sujet"], message=resume,
                      invoice_ref=(body.reference or "").strip() or None)
    db.add(r)
    db.commit()

    t = Tache(
        client_code=user.client_code, client_nom=nom,
        origine_categorie="Demande client", origine_titre=regle["sujet"],
        request_id=r.id, type=regle["tache"],
        titre=f"{regle['sujet']} — {nom}",
        details=resume,
        montant_dt=float(body.montant_dt or 0), severite=regle["severite"],
        statut="a_affecter",
    )
    db.add(t)
    db.commit()
    db.add(EvenementTache(tache_id=t.id, user_id=user.id, email=user.email,
                          type="creation", detail=resume[:500]))
    # L'échéance suit la gravité, comme pour une tâche créée par le directeur.
    t.echeance = echeance_par_defaut(regle["severite"])
    db.commit()

    audit(db, user=user, action="portal_action", resource="/api/portal/actions",
          detail=f"{body.type} → tâche #{t.id}")
    return {"ok": True, "id": r.id, "status": r.status, "tache_id": t.id,
            "message": "Votre demande est enregistrée : l'équipe la traite.",
            "resume": resume}


# ── Produits proposés au client ─────────────────────────────────────────────
def produits_proposes(db: Session, user: User) -> Dict[str, Any]:
    """Produits proposés à CE client, sans aucun chiffre interne.

    L'écran commercial du directeur montre des scores et des espérances de
    signature ; ici, le client ne voit que des noms de produits et un bouton
    « ça m'intéresse ». Le même calcul, deux lectures différentes.
    """
    try:
        data = pw.recommandations(client=str(user.client_code)) or {}
    except Exception:
        return {"produits": []}
    produits = []
    for ligne in (data.get("produits") or [])[:8]:
        if not isinstance(ligne, dict):
            continue
        ref = ligne.get("reference")
        if not ref:
            continue
        produits.append({
            "reference": str(ref),
            "designation": str(ligne.get("designation") or ref),
            "famille": (ligne.get("famille") or "").strip() or None,
            # Aucun score, aucune probabilité : le client verrait une note
            # attribuée à son propre compte, ce qui n'est ni utile ni sain.
        })
    # Ce que le client a déjà signalé : on n'insiste pas deux fois.
    deja = {str(x or "").strip() for x in db.execute(
        select(ClientRequest.invoice_ref).where(
            ClientRequest.user_id == user.id,
            ClientRequest.type == "interet_produit")).scalars().all()}
    for p in produits:
        p["deja_signale"] = p["reference"] in deja
    return {"produits": produits}
