"""
ml_engine/ocr/entreprise.py
===========================
Qui est « nous » ? — et donc : une facture lue est-elle un ACHAT ou une VENTE ?

Pourquoi c'est indispensable
----------------------------
Une facture reçue d'un fournisseur et une facture émise à un client se lisent
exactement de la même façon. Les confondre est grave : un achat compté comme
une vente gonfle le chiffre d'affaires, fausse l'encours d'un « client » qui
n'en est pas un, et crée une fausse fiche client. Le seul moyen de trancher est
de savoir de quel côté de la facture se trouve l'entreprise.

L'identité est lue, dans cet ordre :
  1. variables d'environnement ENTREPRISE_NOM, ENTREPRISE_ALIAS (séparés par des
     virgules), ENTREPRISE_MF ;
  2. le fichier `entreprise.json` à côté de l'entrepôt (écrit par l'API).

La détection ne décide jamais seule : elle PROPOSE un sens avec un motif et un
niveau de confiance, et l'utilisateur confirme avant l'enregistrement.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Même seuil que le rattachement des tiers (importer.SEUIL_RATTACHEMENT).
SEUIL_IDENTITE = 0.88


def _fichier() -> Path:
    from ml_engine.analytics.kpi_engine import STORE_PATH
    return Path(STORE_PATH).parent / "entreprise.json"


def identite() -> Dict[str, Any]:
    """{"nom", "alias": [...], "mf", "configuree": bool, "source"}"""
    nom = os.environ.get("ENTREPRISE_NOM", "").strip()
    if nom:
        alias = [a.strip() for a in os.environ.get("ENTREPRISE_ALIAS", "").split(",") if a.strip()]
        return {"nom": nom, "alias": alias, "mf": os.environ.get("ENTREPRISE_MF", "").strip() or None,
                "configuree": True, "source": "environnement"}
    f = _fichier()
    if f.exists():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if (d.get("nom") or "").strip():
                return {"nom": d["nom"].strip(), "alias": [a for a in d.get("alias", []) if a],
                        "mf": d.get("mf") or None, "configuree": True, "source": str(f.name)}
        except (OSError, ValueError):
            pass
    return {"nom": None, "alias": [], "mf": None, "configuree": False, "source": None}


def enregistrer_identite(nom: str, alias: Optional[List[str]] = None,
                         mf: Optional[str] = None) -> Dict[str, Any]:
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("la raison sociale est obligatoire")
    d = {"nom": nom, "alias": [a.strip() for a in (alias or []) if a and a.strip()],
         "mf": (mf or "").strip() or None}
    f = _fichier()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return identite()


def noyau_mf(mf: Optional[str]) -> Optional[str]:
    """Matricule fiscal tunisien → noyau comparable : 7 chiffres + clé.

    « 1234567/A/M/000 », « 1234567 A M 000 », « 1234567AAM000 » → « 1234567A »."""
    m = re.search(r"(\d{7})\s*[/\-. ]?\s*([A-Za-z])", mf or "")
    return (m.group(1) + m.group(2).upper()) if m else None


def _est_nous(nom: Optional[str], ident: Dict[str, Any]) -> float:
    from .importer import _similarite
    if not (nom or "").strip():
        return 0.0
    return max(_similarite(nom, n) for n in [ident["nom"], *ident["alias"]])


def detecter_sens(fournisseur: Optional[str], client: Optional[str],
                  texte: str = "", ident: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Propose le sens d'une facture du point de vue de l'entreprise.

    Retour : {"sens": "achat" | "vente" | "inconnu", "confiance": "haute" |
    "faible" | None, "motif": str}. « achat » = nous sommes le client.
    """
    ident = ident or identite()
    if not ident["configuree"]:
        return {"sens": "inconnu", "confiance": None,
                "motif": "identité de l'entreprise non configurée : choisissez achat ou vente"}

    s_cli, s_fou = _est_nous(client, ident), _est_nous(fournisseur, ident)
    cli_nous, fou_nous = s_cli >= SEUIL_IDENTITE, s_fou >= SEUIL_IDENTITE
    if cli_nous and fou_nous:
        return {"sens": "inconnu", "confiance": None,
                "motif": "l'entreprise semble être à la fois fournisseur et client : à préciser"}
    if cli_nous:
        return {"sens": "achat", "confiance": "haute",
                "motif": f"« {client} » (client de la facture) correspond à {ident['nom']}"}
    if fou_nous:
        return {"sens": "vente", "confiance": "haute",
                "motif": f"« {fournisseur} » (émetteur de la facture) correspond à {ident['nom']}"}

    # Aucun des noms lus n'est le nôtre. Le matricule fiscal peut dire que nous
    # figurons sur la facture, mais pas de quel côté : on n'en tire pas de sens.
    mf = noyau_mf(ident.get("mf"))
    present = bool(mf and mf in (noyau_mf(x) for x in re.findall(
        r"\d{7}\s*[/\-. ]?\s*[A-Za-z]", texte or "")))
    if client and not fournisseur:
        return {"sens": "vente", "confiance": "faible",
                "motif": f"client lu : « {client} », qui n'est pas {ident['nom']} — "
                         "l'entreprise serait donc l'émetteur (à confirmer)"}
    if fournisseur and not client:
        return {"sens": "achat", "confiance": "faible",
                "motif": f"émetteur lu : « {fournisseur} », qui n'est pas {ident['nom']} — "
                         "l'entreprise serait donc le client (à confirmer)"}
    return {"sens": "inconnu", "confiance": None,
            "motif": ("votre matricule fiscal figure sur la facture, mais aucun des noms lus "
                      "ne correspond : choisissez achat ou vente") if present else
                     (f"ni « {fournisseur or '?'} » ni « {client or '?'} » ne correspondent à "
                      f"{ident['nom']} : cette facture vous concerne-t-elle ?")}
