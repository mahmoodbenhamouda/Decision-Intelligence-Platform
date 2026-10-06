"""Délégation autonome : du classement de l'arbitre aux tâches à confier."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

POSTE_RECOUVREMENT = "recouvrement"
POSTE_COMMERCIAL = "commercial"
POSTE_LOGISTIQUE = "logistique"
POSTES = (POSTE_RECOUVREMENT, POSTE_COMMERCIAL, POSTE_LOGISTIQUE)

TYPES_ACTION = ("appel", "relance_devis", "echeancier", "visite",
                "commande", "reclamation", "autre")

GRAVITES_DELEGUEES = ("critique", "haute")

MAX_PAR_PASSAGE = 12

# Une carte de constat peut concerner des dizaines de clients : la flotte confie
# les premiers, UN PAR TÂCHE, plutôt qu'une tâche « relancer la liste ».
MAX_PAR_CONSTAT = 3

_HORS_METIER = ("Qualité des modèles", "Pilotage")

_POSTE_DU_DOMAINE = (
    ("Recouvrement", POSTE_RECOUVREMENT),
    ("Commercial", POSTE_COMMERCIAL),
    ("Risque client", POSTE_COMMERCIAL),
    ("Stock", POSTE_LOGISTIQUE),
    ("Approvisionnement", POSTE_LOGISTIQUE),
)


def execution(poste: str, type_action: str) -> Dict[str, str]:
    """Déclaration « un employé peut mener cette action » d'un constat."""
    if poste not in POSTES:
        raise ValueError(f"poste inconnu : {poste}")
    if type_action not in TYPES_ACTION:
        raise ValueError(f"type d'action inconnu : {type_action}")
    return {"poste": poste, "type": type_action}


def origine_cible(titre_constat: str, nom: str) -> str:
    """Clé stable d'une tâche issue d'une ligne de constat (déduplication) : ne
    contient pas de montant, qui varie d'un jour à l'autre."""
    return f"{titre_constat} — {nom}"[:255]


def titre_point_client(nom: str) -> str:
    """Intitulé de l'alerte « ce compte cumule plusieurs signaux »."""
    return f"Faire le point avec {nom}"


def domaine_designe(domaines: List[str]) -> Optional[str]:
    """Parmi les domaines qui signalent un même client, celui qui le prend en charge : le premier dans…"""
    return next((d for d, _ in _POSTE_DU_DOMAINE if d in domaines), None)


def execution_multi_signaux(domaines: List[str]) -> Optional[Dict[str, str]]:
    """Qui traite un client signalé par plusieurs domaines, et à quel titre."""
    d = domaine_designe(domaines)
    return execution(dict(_POSTE_DU_DOMAINE)[d], "appel") if d else None


@dataclass
class Proposition:
    """Une tâche que la flotte propose de confier."""
    origine_titre: str
    origine_categorie: str
    titre: str
    type: str
    poste: str
    severite: str
    montant_dt: float
    details: str
    rang: int
    client_nom: Optional[str] = None
    client_code: Optional[str] = None
    motif: str = ""

    def en_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Plan:
    """Ce que la flotte propose, et ce qu'elle laisse — chaque choix motivé."""
    propositions: List[Proposition] = field(default_factory=list)
    decisions_direction: List[Dict[str, str]] = field(default_factory=list)
    ecartes: List[Dict[str, str]] = field(default_factory=list)
    classement_disponible: bool = True

    def en_dict(self) -> Dict[str, Any]:
        return {
            "propositions": [p.en_dict() for p in self.propositions],
            "decisions_direction": list(self.decisions_direction),
            "ecartes": list(self.ecartes),
            "classement_disponible": self.classement_disponible,
        }


def _synthese(findings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next((f for f in findings if f.get("classement")), None)


def _cle(nom: Any) -> str:
    return str(nom or "").strip().upper()


def planifier(findings: List[Dict[str, Any]],
              max_par_passage: int = MAX_PAR_PASSAGE) -> Plan:
    """Transforme les constats d'un briefing en propositions de tâches."""
    plan = Plan()
    synthese = _synthese(findings or [])
    if synthese is None:
        plan.classement_disponible = False
        return plan

    candidates: List[Proposition] = []

    multi = synthese.get("clients_multi_signaux") or []
    deja_couverts: Dict[str, str] = {}
    for c in multi:
        nom = str(c.get("client") or "").strip()
        ex = c.get("execution")
        if not nom or not ex:
            continue
        domaines = [str(d) for d in (c.get("domaines") or [])]
        titre = titre_point_client(nom)
        signaux = ", ".join(f"« {s.get('titre')} » ({s.get('domaine')})"
                            for s in (c.get("signaux") or []) if s.get("titre"))
        pourquoi = ("Une créance sur un client qui s'éloigne devient douteuse : le "
                    "levier commercial qui permettrait de négocier disparaît avec "
                    "la relation."
                    if "Recouvrement" in domaines else
                    "Chaque signal aggrave l'autre : un seul interlocuteur doit "
                    "reprendre ce compte.")
        candidates.append(Proposition(
            origine_titre=titre,
            origine_categorie=str(c.get("categorie") or (domaines[0] if domaines else "Clients")),
            titre=titre,
            type=ex["type"], poste=ex["poste"],
            severite="haute",
            montant_dt=round(float(c.get("montant_cumule_dt") or 0), 0),
            details=((f"Ce compte apparaît dans plusieurs constats : {signaux}. "
                      if signaux else
                      f"Ce compte apparaît dans plusieurs domaines : {', '.join(domaines)}. ")
                     + pourquoi),
            rang=0, client_nom=nom,
            motif="signalé par plusieurs domaines — l'arbitre le place en tête",
        ))
        deja_couverts[_cle(nom)] = nom

    for c in synthese.get("classement") or []:
        titre = str(c.get("titre") or "").strip()
        if not titre or c.get("categorie") in _HORS_METIER:
            continue
        sev = str(c.get("severite") or "moyenne")
        if "execution" not in c:
            plan.ecartes.append({"titre": titre,
                                 "raison": "le constat ne déclare pas qui peut l'exécuter"})
            continue
        ex = c.get("execution")
        if ex is None:
            plan.decisions_direction.append({"titre": titre, "action": str(c.get("action") or "")})
            continue
        if sev not in GRAVITES_DELEGUEES:
            plan.ecartes.append({"titre": titre,
                                 "raison": f"gravité « {sev} » : laissée à l'appréciation du directeur"})
            continue

        montant = round(float(c.get("enjeu_court_terme_dt") or c.get("montant_dt") or 0), 0)
        motif = f"rang {c.get('rang', '?')} du classement de l'arbitre, gravité {sev}"
        clients = c.get("clients_concernes") or []
        cibles = [x for x in (clients or c.get("produits_concernes") or [])
                  if x.get("tache") and x.get("nom") and _cle(x.get("nom")) not in deja_couverts]
        if cibles:
            for x in cibles[:MAX_PAR_CONSTAT]:
                nom = str(x["nom"]).strip()
                candidates.append(Proposition(
                    origine_titre=origine_cible(titre, nom),
                    origine_categorie=str(c.get("categorie") or ""),
                    titre=str(x["tache"].get("titre") or titre),
                    type=str(x["tache"].get("type") or ex["type"]), poste=ex["poste"],
                    severite=sev,
                    # Même échelle que la carte : la part de son enjeu à court terme.
                    montant_dt=round(float(x.get("enjeu_dt", x.get("montant_dt")) or 0), 0),
                    details=(f"{x.get('motif') or ''}. Contexte : {titre}.").strip(". "),
                    rang=0,
                    client_nom=nom if clients else None,
                    client_code=(x.get("code") or None) if clients else None,
                    motif=motif,
                ))
            continue

        details = str(c.get("action") or "").strip()
        doublons = [deja_couverts[_cle(x.get("nom"))]
                    for x in clients if _cle(x.get("nom")) in deja_couverts]
        if doublons:
            details += (" Déjà couverts par une tâche dédiée : " + ", ".join(doublons)
                        + " — ne pas les contacter une seconde fois à ce titre.")
        candidates.append(Proposition(
            origine_titre=titre,
            origine_categorie=str(c.get("categorie") or ""),
            titre=titre,
            type=ex["type"], poste=ex["poste"],
            severite=sev,
            montant_dt=montant,
            details=details,
            rang=0,
            motif=motif,
        ))

    for i, p in enumerate(candidates, 1):
        if i > max_par_passage:
            plan.ecartes.append({"titre": p.origine_titre,
                                 "raison": f"plafond de {max_par_passage} tâches par passage atteint"})
            continue
        p.rang = i
        plan.propositions.append(p)
    return plan
