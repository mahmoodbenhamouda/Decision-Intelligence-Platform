"""
api/auth/models.py
==================
Schéma relationnel de l'authentification (normalisé, documenté).

Diagramme entité-association (Mermaid) :

```mermaid
erDiagram
    USERS ||--o{ AUDIT_LOG : "génère"
    USERS ||--o{ TACHES : "est responsable de"
    USERS ||--o{ CLIENT_REQUESTS : "dépose"
    CLIENT_REQUESTS ||--o| TACHES : "déclenche"
    TACHES ||--o{ EVENEMENTS_TACHE : "historise"
    USERS {
        int      id PK
        string   email UK "unique, identifiant de connexion"
        string   password_hash "bcrypt + sel (jamais en clair)"
        string   role "directeur | employe | client"
        string   client_code FK "code client ERP (NULL pour directeur/employé) - lien 1-1 vers l'entrepôt"
        boolean  is_active
        datetime created_at
        datetime last_login
    }
    AUDIT_LOG {
        int      id PK
        int      user_id FK
        string   email "dénormalisé pour lecture rapide"
        string   action "login / login_failed / access / forbidden / logout"
        string   resource "endpoint consulté"
        string   detail
        datetime at
    }
    TACHES {
        int      id PK
        string   client_code "périmètre concerné"
        string   origine_categorie "domaine de l'alerte (Recouvrement, Stock...)"
        string   type "appel | relance_devis | echeancier | visite | commande | reclamation"
        int      assigne_id FK "employé responsable (NULL = à affecter)"
        int      cree_par_id FK
        int      request_id FK "action client à l'origine (NULL si créée par le directeur)"
        float    montant_dt "montant en jeu au moment de la création"
        string   statut "a_affecter | a_faire | en_cours | terminee | bloquee"
        string   resultat "paye | promesse | devis_signe | devis_refuse | client_perdu | sans_reponse"
        float    resultat_montant_dt "montant réellement obtenu"
        datetime echeance
        datetime closed_at
    }
    EVENEMENTS_TACHE {
        int      id PK
        int      tache_id FK
        int      user_id FK
        string   type "creation | affectation | statut | resultat | commentaire"
        string   detail
        datetime at
    }
```

`client_code` est la clé d'ISOLATION : chaque compte `client` est relié 1-à-1 à
un code client de l'entrepôt DuckDB (colonne `cle_client` des ventes). Le rôle
est porté par `users.role` (RBAC à 3 rôles — extensible en tables
roles/permissions si besoin).

## La boucle d'action

Les trois dernières tables ferment la boucle du projet : une alerte produite par
la flotte d'agents devient une TÂCHE confiée à un employé, un client agit depuis
son espace (CLIENT_REQUESTS) ce qui crée à son tour une tâche, et le RÉSULTAT
consigné à la clôture (`resultat`, `resultat_montant_dt`) sert à la fois à
mesurer ce que les actions ont rapporté et à réalimenter les modèles
(`ml_engine/boucle.py`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer,
                        String)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

ROLE_DIRECTEUR = "directeur"
ROLE_EMPLOYE = "employe"
ROLE_CLIENT = "client"
ROLES = (ROLE_DIRECTEUR, ROLE_EMPLOYE, ROLE_CLIENT)

#: Rôles SANS code client (leur périmètre n'est pas un client de l'ERP).
ROLES_INTERNES = (ROLE_DIRECTEUR, ROLE_EMPLOYE)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """Compte utilisateur de la plateforme.

    - `role='directeur'` : accès global (tous clients, flotte, supply) ; c'est
      lui qui confie les tâches.
    - `role='employe'`   : ne voit QUE les tâches qui lui sont confiées (aucun
      accès aux tableaux de bord ni aux données d'un client non concerné).
    - `role='client'`    : accès restreint aux données de SON `client_code`.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True,
                                                  doc="Nom affiché (raison sociale du client ERP)")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=ROLE_CLIENT)
    client_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True,
                                                   doc="Code client ERP (NULL pour directeur)")
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
        return f"<User {self.email} role={self.role} client_code={self.client_code}>"


class RevokedToken(Base):
    """Liste de révocation des JWT (denylist par identifiant unique `jti`).

    Un JWT est stateless : sans cette table, un jeton volé resterait valable
    jusqu'à expiration. Ici, le logout révoque le jeton IMMÉDIATEMENT ; les
    entrées expirées sont purgées opportunément à chaque login.
    """

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LoginAttempt(Base):
    """Tentatives de connexion ÉCHOUÉES (anti-brute-force persistant).

    En base (et non en mémoire) : le compteur survit aux redémarrages et
    fonctionne en multi-instances. Fenêtre glissante purgée à chaque login.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_attempts_key_at", "key", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False,
                                     doc="email OU 'ip:<adresse>'")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


REQUEST_TYPES = ("echeancier", "reclamation", "devis", "contact", "autre",
                 # Actions déclenchées depuis les écrans du portail client :
                 "promesse_paiement",   # « je paie le … » sur une facture en retard
                 "devis_reponse",       # accepte / refuse / demande une modification
                 "interet_produit",     # « ce produit m'intéresse » (retour de recommandation)
                 "reservation_stock")   # réserve une quantité sur un produit tendu
REQUEST_STATUS = ("nouvelle", "en_cours", "traitee", "rejetee")


class ClientRequest(Base):
    """Demande concrète d'un client vers la direction : demande d'échéancier,
    réclamation sur facture, demande de devis, prise de contact.

    C'est le canal d'ACTION du portail client : le client agit, le directeur
    traite (changement de statut + réponse), tout est horodaté et audité.
    """

    __tablename__ = "client_requests"
    __table_args__ = (Index("ix_requests_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="contact")
    sujet: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    invoice_ref: Mapped[str | None] = mapped_column(String(64), nullable=True,
                                                    doc="Référence de facture concernée (optionnel)")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="nouvelle", index=True)
    reponse: Mapped[str | None] = mapped_column(String(2000), nullable=True,
                                                doc="Réponse de la direction")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow,
                                                 onupdate=_utcnow)


TACHE_TYPES = ("appel", "relance_devis", "echeancier", "visite",
               "commande", "reclamation", "autre")
#: Libellés métier (aucun jargon technique : ces mots sont lus par un directeur).
TACHE_TYPE_LABEL = {
    "appel": "Appeler le client",
    "relance_devis": "Relancer le devis",
    "echeancier": "Proposer un échéancier",
    "visite": "Passer voir le client",
    "commande": "Commander / réserver du stock",
    "reclamation": "Traiter une réclamation",
    "autre": "Autre action",
}

#: `a_affecter` est l'entrée du tableau : une tâche née d'une action client y
#: attend son responsable. Les tâches créées par le directeur naissent déjà
#: affectées (`a_faire`).
TACHE_STATUTS = ("a_affecter", "a_faire", "en_cours", "terminee", "bloquee")
STATUTS_OUVERTS = ("a_affecter", "a_faire", "en_cours", "bloquee")

TACHE_RESULTATS = ("paye", "promesse", "devis_signe", "devis_refuse",
                   "commande_passee", "client_retenu", "client_perdu",
                   "sans_reponse", "autre")
#: Résultats qui valent un gain : ils alimentent « ce que les actions ont rapporté ».
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
    """Tâche confiée à un employé au sujet d'un client.

    C'est le maillon qui manquait : le tableau de bord signalait un problème,
    personne n'était nommément chargé de le traiter et rien ne disait ce que
    l'action avait donné. Une tâche porte donc les trois : QUI (`assigne_id`),
    QUOI (`type`, `titre`, `montant_dt`, `origine_*`) et CE QUE ÇA A DONNÉ
    (`resultat`, `resultat_montant_dt`).

    `origine_categorie` / `origine_titre` conservent l'alerte d'où vient la
    tâche : sans cette trace, impossible de mesurer plus tard si les alertes
    d'un domaine mènent à des actions utiles.
    """

    __tablename__ = "taches"
    __table_args__ = (
        Index("ix_taches_assigne_statut", "assigne_id", "statut"),
        Index("ix_taches_client_statut", "client_code", "statut"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Périmètre ──
    client_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client_nom: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Raison sociale au moment de la création (lisible sans requête ERP)")

    # ── Origine ──
    origine_categorie: Mapped[str | None] = mapped_column(String(60), nullable=True,
        doc="Domaine de l'alerte : Recouvrement, Stock, Commercial…")
    origine_titre: Mapped[str | None] = mapped_column(String(255), nullable=True,
        doc="Intitulé de l'alerte d'où vient la tâche")
    request_id: Mapped[int | None] = mapped_column(ForeignKey("client_requests.id"),
        nullable=True, doc="Action du client à l'origine (NULL si créée par le directeur)")

    # ── Contenu ──
    type: Mapped[str] = mapped_column(String(30), nullable=False, default="appel")
    titre: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    montant_dt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0,
        doc="Montant en jeu constaté à la création")
    severite: Mapped[str] = mapped_column(String(20), nullable=False, default="moyenne")

    # ── Responsabilité ──
    assigne_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    cree_par_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    echeance: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Suivi ──
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
    """Histoire d'une tâche : chaque changement laisse une ligne.

    Une tâche ne garde que son état courant ; sans cette table, on ne saurait
    ni qui l'a réaffectée, ni combien de temps elle a réellement pris. C'est
    aussi ce qui permet de calculer un délai moyen de traitement honnête.
    """

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
