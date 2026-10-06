"""Schéma relationnel de l'authentification (normalisé, documenté)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

ROLE_DIRECTEUR = "directeur"
ROLE_EMPLOYE = "employe"
# Deux rôles : le directeur décide, l'employé exécute. Le rôle « client » (portail
# des établissements) a été retiré : les acheteurs d'Overlyne sont des hôpitaux
# publics qui ne passent pas par le portail d'un fournisseur, et l'écran exposait
# des analyses internes (risque de départ, marge) au client concerné.
ROLES = (ROLE_DIRECTEUR, ROLE_EMPLOYE)

ROLES_INTERNES = ROLES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Compte utilisateur de la plateforme."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                  doc="Nom affiché")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_EMPLOYE)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    poste: Mapped[str | None] = mapped_column(String(40), nullable=True,
        doc="Métier d'un employé (recouvrement, commercial, logistique) — "
            "sert à proposer le bon responsable pour une tâche")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0,
        doc="Incrémenté au changement de mot de passe → révoque TOUS les JWT émis avant")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} role={self.role}>"


class RevokedToken(Base):
    """Liste de révocation des JWT (denylist par identifiant unique `jti`)."""

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LoginAttempt(Base):
    """Tentatives de connexion ÉCHOUÉES (anti-brute-force persistant)."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_attempts_key_at", "key", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False,
                                     doc="email OU 'ip:<adresse>'")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


TACHE_TYPES = ("appel", "relance_devis", "echeancier", "visite",
               "commande", "reclamation", "autre")
TACHE_TYPE_LABEL = {
    "appel": "Appeler le client",
    "relance_devis": "Relancer le devis",
    "echeancier": "Proposer un échéancier",
    "visite": "Passer voir le client",
    "commande": "Commander / réserver du stock",
    "reclamation": "Traiter une réclamation",
    "autre": "Autre action",
}

TACHE_STATUTS = ("a_affecter", "a_faire", "en_cours", "terminee", "bloquee")
STATUTS_OUVERTS = ("a_affecter", "a_faire", "en_cours", "bloquee")

TACHE_RESULTATS = ("paye", "promesse", "devis_signe", "devis_refuse",
                   "commande_passee", "client_retenu", "client_perdu",
                   "sans_reponse", "autre")
RESULTATS_GAGNANTS = ("paye", "devis_signe", "commande_passee", "client_retenu")
RESULTAT_LABEL = {
    "paye": "Payé",
    "promesse": "Promesse de paiement",
    "devis_signe": "Devis signé",
    "devis_refuse": "Devis refusé",
    "commande_passee": "Commande passée",
    "client_retenu": "Client retenu",
    "client_perdu": "Client perdu",
    "sans_reponse": "Sans réponse",
    "autre": "Autre",
}

EVENEMENT_TYPES = ("creation", "affectation", "statut", "resultat", "commentaire")


class Tache(Base):
    """Tâche confiée à un employé au sujet d'un client."""

    __tablename__ = "taches"
    __table_args__ = (
        Index("ix_taches_assigne_statut", "assigne_id", "statut"),
        Index("ix_taches_client_statut", "client_code", "statut"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    client_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_nom: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Raison sociale au moment de la création, pour rester lisible seule")

    origine_categorie: Mapped[str | None] = mapped_column(String(60), nullable=True,
        doc="Domaine de l'alerte : Recouvrement, Stock, Commercial…")
    origine_titre: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Intitulé de l'alerte d'où vient la tâche")
    delegation_auto: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False,
        doc="Confiée par la flotte d'agents, sans clic du directeur. NULL sur les "
            "tâches antérieures à la délégation autonome : lu comme faux.")

    type: Mapped[str] = mapped_column(String(30), nullable=False, default="appel")
    titre: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    montant_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
        doc="Montant en jeu constaté à la création")
    severite: Mapped[str] = mapped_column(String(20), nullable=False, default="moyenne")

    assigne_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    cree_par_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    echeance: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="a_faire", index=True)
    resultat: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resultat_montant_dt: Mapped[float | None] = mapped_column(Float, nullable=True,
        doc="Montant réellement obtenu (encaissé, signé, commandé)")
    resultat_commentaire: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tache #{self.id} {self.statut} client={self.client_code}>"


class EvenementTache(Base):
    """Histoire d'une tâche : chaque changement laisse une ligne."""

    __tablename__ = "evenements_tache"
    __table_args__ = (Index("ix_evt_tache_at", "tache_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tache_id: Mapped[int] = mapped_column(ForeignKey("taches.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Dénormalisé : l'histoire reste lisible même si le compte est supprimé")
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="commentaire")
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Approvisionnement : la boucle que l'ERP ne ferme pas ─────────────────────
#
# L'export ERP ne contient que des FACTURES d'achat. Ni bon de commande, ni date
# de réception : impossible d'y mesurer un délai de livraison, ni de repérer une
# commande restée sans suite. Ces étapes du processus d'approvisionnement
# n'existent pas dans la donnée source.
#
# La plateforme les crée. Une recommandation de réassort issue de l'analyse est
# soumise au directeur ; s'il la valide, elle devient une commande, puis une
# réception. L'écart entre ces deux dates EST le délai de livraison réel — une
# donnée qui n'existait nulle part et que l'application produit elle-même.
#
# C'est la différence entre lire un ERP et décider avec : la boucle se referme
# ici, et chaque tour l'enrichit.

COMMANDE_STATUTS = ("recommandee", "validee", "refusee", "commandee",
                    "recue", "annulee")

#: Transitions autorisées. Une commande ne peut pas être reçue sans avoir été
#: passée, ni validée deux fois : le cycle est un ordre, pas un champ libre.
COMMANDE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "recommandee": ("validee", "refusee"),
    "validee": ("commandee", "annulee"),
    "refusee": (),
    "commandee": ("recue", "annulee"),
    "recue": (),
    "annulee": (),
}

#: Statuts qui attendent encore une action.
COMMANDE_OUVERTS = ("recommandee", "validee", "commandee")

COMMANDE_ORIGINES = ("ia", "manuelle")


class CommandeFournisseur(Base):
    """Une proposition de réassort, de sa recommandation à sa réception."""

    __tablename__ = "commandes_fournisseur"
    __table_args__ = (
        Index("ix_cmd_statut_at", "statut", "created_at"),
        Index("ix_cmd_reference", "reference"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    reference: Mapped[str] = mapped_column(String(64), nullable=False,
        doc="Référence produit, telle qu'elle figure au catalogue")
    designation: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Libellé au moment de la recommandation, pour rester lisible seul")
    fournisseur_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fournisseur_nom: Mapped[str | None] = mapped_column(String(255), nullable=True)

    origine: Mapped[str] = mapped_column(String(20), nullable=False, default="ia",
        doc="`ia` : proposée par l'analyse de réassort. `manuelle` : saisie par un humain.")
    motif: Mapped[str | None] = mapped_column(String(1000), nullable=True,
        doc="Pourquoi ce réassort est proposé — le constat chiffré, pas un avis")

    qte_proposee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    montant_estime_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
        doc="Estimation au coût unitaire moyen constaté, pas un prix négocié")

    statut: Mapped[str] = mapped_column(String(20), nullable=False,
                                        default="recommandee", index=True)

    decide_par_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decide_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_refus: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Les deux dates que l'ERP ne porte pas, et dont l'écart est le délai réel.
    commande_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    qte_recue: Mapped[float | None] = mapped_column(Float, nullable=True)
    commentaire: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow)

    @property
    def delai_livraison_j(self) -> int | None:
        """Jours entre la commande et la réception — la donnée créée ici."""
        if self.commande_at and self.recue_at:
            return (self.recue_at - self.commande_at).days
        return None

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Commande #{self.id} {self.statut} {self.reference}>"


class EvenementCommande(Base):
    """Histoire d'une commande : chaque décision laisse une trace."""

    __tablename__ = "evenements_commande"
    __table_args__ = (Index("ix_evt_cmd_at", "commande_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commande_id: Mapped[int] = mapped_column(ForeignKey("commandes_fournisseur.id"),
                                             nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Dénormalisé : l'histoire reste lisible si le compte disparaît")
    de: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vers: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    """Journal d'audit : qui a consulté quoi et quand (valorisant pour un PFE)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_user_at", "user_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    resource: Mapped[str | None] = mapped_column(String(255), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class DelegationPassage(Base):
    """Un passage de la délégation autonome : ce que la flotte a proposé, ce qu'elle a confié, à qui,…"""

    __tablename__ = "delegations_auto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    declencheur: Mapped[str] = mapped_column(String(20), nullable=False, default="manuel",
        doc="planifie (chaque jour) | manuel (bouton du directeur) | commande (ligne de commande)")
    jour_planifie: Mapped[str | None] = mapped_column(String(10), nullable=True, unique=True)
    lance_par_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="en_cours")
    moteur: Mapped[str | None] = mapped_column(String(40), nullable=True)
    n_propositions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_creees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_deja_confiees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_recentes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_decisions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_ecartees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    motif: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    briefing: Mapped[str | None] = mapped_column(Text, nullable=True)
    debut: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Reglage(Base):
    """Réglages modifiables depuis l'interface (clé → valeur)."""

    __tablename__ = "reglages"

    cle: Mapped[str] = mapped_column(String(60), primary_key=True)
    valeur: Mapped[str] = mapped_column(String(255), nullable=False)
    modifie_par_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow)
