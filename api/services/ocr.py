"""Documents & OCR : lecture de factures scannées, enregistrement du bon côté (achat ou vente),…"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from api.auth.journal import audit
from api.auth.models import ROLE_DIRECTEUR, User
from api.services.erreurs import (Conflit, DonneesInvalides, ErreurInterne,
                                  Introuvable)
from ml_engine.ocr import ocr_document, reconcile_invoice
from ml_engine.ocr.engine import install_hint, ocr_available
from ml_engine.ocr.layoutlm import etat as layoutlm_etat, lire_facture

FORMATS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
TAILLE_MAX = 20 * 1024 * 1024


def _est_directeur(user: User) -> bool:
    return user.role == ROLE_DIRECTEUR


def _saisie_json(facture: str) -> Dict[str, Any]:
    """Valeurs validées par l'utilisateur, envoyées en JSON dans un formulaire."""
    try:
        saisie = json.loads(facture)
    except ValueError:
        raise DonneesInvalides("`facture` doit être un objet JSON.")
    return saisie


def etat(user: User) -> Dict[str, Any]:
    """Le moteur OCR est-il opérationnel sur ce serveur ?"""
    dispo = ocr_available()
    e = layoutlm_etat()
    info: Dict[str, Any] = {"disponible": dispo, "formats": sorted(FORMATS),
                            "layoutlmv3": e["disponible"],
                            **({"layoutlmv3_motif": e["motif"], "layoutlmv3_cause": e["cause"]}
                               if _est_directeur(user) else {})}
    if dispo:
        try:
            import pytesseract
            info["version"] = str(pytesseract.get_tesseract_version())
            info["langues"] = sorted(pytesseract.get_languages(config=""))
        except Exception:
            pass
    else:
        info["installation"] = install_hint()
    return info


def extraire_texte(db: Session, user: User, contenu: bytes, nom: str) -> Dict[str, Any]:
    """Extraction de texte brute, avec indicateur de qualité de lecture."""
    res = ocr_document(contenu, nom)
    audit(db, user=user, action="ocr_extract", resource="/api/ocr/extract",
          detail=f"{nom} ({res.source}, {len(res.text)} car.)")
    if not res.ok and res.warnings:
        return {"filename": nom, **res.to_dict(),
                "message": " ".join(res.warnings)}
    return {"filename": nom, **res.to_dict()}


def _rapprocher(facture: Dict[str, Any], sens: Optional[str], user: User) -> Dict[str, Any]:
    if sens not in ("achat", "vente"):
        return {"statut": "sens_a_choisir", "candidats": [],
                "message": "Choisissez « achat » ou « vente » pour rapprocher la facture de vos écritures."}
    return reconcile_invoice(facture, client_code=None, sens=sens)


def lire_une_facture(db: Session, user: User, contenu: bytes, nom: str,
                     rapprocher: bool) -> Dict[str, Any]:
    """Facture scannée → champs structurés + sens proposé + rapprochement ERP."""
    from ml_engine.ocr.entreprise import detecter_sens, identite
    from ml_engine.ocr.lectures import conserver_lecture

    res, fields, moteur = lire_facture(contenu, nom)
    if not res.ok:
        raise DonneesInvalides(" ".join(res.warnings) or
                               "Aucun texte exploitable n'a pu être extrait du document.")

    lecture = conserver_lecture(contenu, nom, res.to_dict(), fields.to_dict(), moteur)
    sens = detecter_sens(fields.fournisseur, fields.client or fields.tiers, res.text)

    rapprochement: Optional[Dict[str, Any]] = None
    if rapprocher:
        rapprochement = _rapprocher(fields.to_dict(), sens["sens"], user)

    audit(db, user=user, action="ocr_invoice", resource="/api/ocr/invoice",
          detail=(f"{nom} → n°{fields.numero or '?'} "
                  f"{fields.montant_ttc or '?'} {fields.devise} · sens {sens['sens']} · "
                  f"{(rapprochement or {}).get('statut', 'sans rapprochement')}"))
    ident = identite()
    return {
        "filename": nom,
        "lecture_id": lecture["lecture_id"],
        "ocr": res.to_dict(),
        "facture": fields.to_dict(),
        "moteur": moteur,
        "sens": sens,
        "entreprise": {"configuree": ident["configuree"], "nom": ident["nom"]},
        "rapprochement": rapprochement,
    }


def rapprocher_lecture(user: User, lecture_id: str, sens: str,
                       facture: Optional[str]) -> Dict[str, Any]:
    """Refait le rapprochement d'une lecture conservée, dans le sens choisi et sur les valeurs…"""
    from ml_engine.ocr import nettoyer_saisie
    from ml_engine.ocr.lectures import charger_lecture
    lec = charger_lecture(lecture_id)
    if not lec:
        raise Introuvable("Lecture introuvable : relisez le document.")
    valeurs = dict(lec["facture"])
    if facture:
        saisie = _saisie_json(facture)
        if isinstance(saisie, dict):
            valeurs.update(nettoyer_saisie(saisie))
    return _rapprocher(valeurs, sens, user)


def importer(db: Session, user: User, *, contenu: Optional[bytes], nom_fichier: Optional[str],
             lecture_id: Optional[str], facture: Optional[str], sens: Optional[str],
             client_code: Optional[str], tiers_code: Optional[str],
             creer_client: bool) -> Dict[str, Any]:
    """ENREGISTRE une facture lue, du bon côté (achat ou vente)."""
    from ml_engine.ocr import detecter_sens, importer_facture, nettoyer_saisie
    from ml_engine.ocr.layoutlm.extracteur import message_coherence
    from ml_engine.ocr.lectures import charger_lecture, conserver_lecture

    if lecture_id:
        lec = charger_lecture(lecture_id)
        if not lec:
            raise Introuvable("Lecture introuvable : relisez le document.")
        lu, ocr, name, moteur = lec["facture"], lec["ocr"], lec["fichier"], lec["moteur"]
        sha, chemin = lec["lecture_id"], lec["chemin"]
    elif contenu is not None:
        name = nom_fichier or "document"
        res, fields, moteur = lire_facture(contenu, name)
        if not res.ok:
            raise DonneesInvalides(" ".join(res.warnings) or
                                   "Aucun texte exploitable n'a pu être extrait du document.")
        lu, ocr = fields.to_dict(), res.to_dict()
        c = conserver_lecture(contenu, name, ocr, lu, moteur)
        sha, chemin = c["lecture_id"], c["chemin"]
    else:
        raise DonneesInvalides("Envoyez `lecture_id` (document déjà lu) ou le fichier.")

    valide = dict(lu)
    relue = facture is not None
    if relue:
        saisie = _saisie_json(facture)
        if not isinstance(saisie, dict):
            raise DonneesInvalides("`facture` doit être un objet JSON.")
        valide.update(nettoyer_saisie(saisie))
        valide["coherence"] = message_coherence(SimpleNamespace(
            montant_ht=valide.get("montant_ht"), montant_tva=valide.get("montant_tva"),
            montant_ttc=valide.get("montant_ttc"), timbre_fiscal=valide.get("timbre_fiscal")))

    if sens not in (None, "", "achat", "vente"):
        raise DonneesInvalides("`sens` doit valoir 'achat' ou 'vente'.")
    if not sens:
        d = detecter_sens(valide.get("fournisseur"), valide.get("client") or valide.get("tiers"))
        if d["sens"] == "inconnu":
            raise Conflit({
                "statut_client": "sens_inconnu", "erreur": d["motif"], "facture": valide,
                "action_requise": "Précisez s'il s'agit d'un achat ou d'une vente."})
        sens = d["sens"]

    rapprochement = _rapprocher(valide, sens, user)
    resultat = importer_facture(
        valide, ocr=ocr, fichier=name,
        utilisateur=getattr(user, "username", "") or "",
        client_code=client_code, creer_client=creer_client,
        sens=sens, tiers_code=tiers_code,
        lecture=lu if relue else None,
        moteur=moteur, fichier_sha256=sha, fichier_chemin=chemin,
        rapprochement=rapprochement)

    audit(db, user=user, action="ocr_import", resource="/api/ocr/invoice/import",
          detail=(f"{name} → {sens} n°{valide.get('numero') or '?'} "
                  f"{valide.get('montant_ttc') or '?'} {valide.get('devise') or 'TND'} · "
                  f"{'importée' if resultat.get('ok') else 'refusée'} · "
                  f"{resultat.get('tiers_nom') or resultat.get('erreur', '')} · "
                  f"{resultat.get('n_corrections', 0)} correction(s)"))

    if not resultat.get("ok"):
        raise Conflit({"facture": valide, "ocr": ocr, "lecture_id": sha, **resultat})
    return {"filename": name, "ocr": ocr, "moteur": moteur, "lecture_id": sha,
            "facture": valide, "import": resultat, "rapprochement": rapprochement}


def factures_importees(user: User, client_code: Optional[str], sens: Optional[str],
                       rapprochement: Optional[str]) -> Dict[str, Any]:
    """Factures importées par OCR, filtrables par client, sens et statut de rapprochement."""
    from ml_engine.ocr import factures_importees as lister, stats_import
    return {"factures": lister(client_code=client_code, sens=sens,
                               rapprochement=rapprochement),
            "stats": stats_import()}


def rerapprocher(db: Session, admin: User, seulement: Optional[str]) -> Dict[str, Any]:
    """Refait le rapprochement des factures importées, après une mise à jour des écritures."""
    from ml_engine.ocr import rerapprocher_imports
    statuts: Optional[List[str]] = ([x.strip() for x in seulement.split(",")]
                                    if seulement else None)
    r = rerapprocher_imports(statuts)
    audit(db, user=admin, action="ocr_rerapprocher", resource="/api/ocr/imports/rerapprocher",
          detail=f"{r['n_revus']} revue(s), {r['n_changes']} changement(s)")
    return r


def echeancier(user: User, sens: Optional[str]) -> Dict[str, Any]:
    """Ce qu'il reste à payer (achats) et à encaisser (ventes) sur les factures lues par OCR, absentes…"""
    from ml_engine.ocr import echeancier as calculer
    return calculer(sens=sens)


def marquer_reglement(db: Session, admin: User, facture_id: int, le: Optional[str],
                      annuler: bool) -> Dict[str, Any]:
    """Marque une facture importée comme réglée : elle sort de l'échéancier."""
    from ml_engine.ocr import marquer_reglee
    try:
        quand = date.fromisoformat(le) if le else None
    except ValueError:
        raise DonneesInvalides("`le` doit être une date AAAA-MM-JJ.")
    r = marquer_reglee(facture_id, quand, annuler=annuler)
    if not r["ok"]:
        raise Introuvable(r["erreur"])
    audit(db, user=admin, action="ocr_reglement",
          resource=f"/api/ocr/imports/{facture_id}/reglement",
          detail=f"{r['numero']} → {'règlement annulé' if annuler else 'réglée le ' + r['reglee_le']}")
    return r


def qualite_en_production(depuis: Optional[str]) -> Dict[str, Any]:
    """Exactitude RÉELLE du modèle en production, mesurée sur les corrections faites à l'écran de…"""
    from ml_engine.ocr import mesure_production
    return mesure_production(depuis)


def identite_entreprise() -> Dict[str, Any]:
    """Sert à savoir si une facture est un achat ou une vente."""
    from ml_engine.ocr import identite
    return identite()


def declarer_entreprise(db: Session, admin: User, nom: str, alias: str,
                        mf: Optional[str]) -> Dict[str, Any]:
    """Raison sociale, variantes et matricule fiscal."""
    from ml_engine.ocr import enregistrer_identite
    try:
        ident = enregistrer_identite(nom, [a for a in alias.split(",")], mf)
    except ValueError as e:
        raise DonneesInvalides(str(e))
    audit(db, user=admin, action="ocr_entreprise", resource="/api/ocr/entreprise",
          detail=f"identité : {ident['nom']} (alias {', '.join(ident['alias']) or '—'})")
    return ident


def _safe_slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")
    return s[:80] or "document"


def indexer_pour_le_copilote(db: Session, admin: User, contenu: bytes, nom: str,
                             reindexer: bool) -> Dict[str, Any]:
    """Océrise un document et l'ajoute à la base documentaire du copilote (RAG)."""
    res = ocr_document(contenu, nom)
    if not res.ok:
        raise DonneesInvalides(" ".join(res.warnings) or
                               "Aucun texte exploitable : document non indexé.")

    try:
        from rag.rag_engine import DOCS_DIR, build_index
    except Exception as e:
        raise ErreurInterne(f"Moteur RAG indisponible : {e}")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = DOCS_DIR / f"ocr-{stamp}-{_safe_slug(Path(nom).stem)}.txt"
    entete = (f"# Source : {nom} (numérisé le "
              f"{datetime.now().strftime('%d/%m/%Y')} — extraction {res.source}, "
              f"qualité {res.quality})\n\n")
    dest.write_text(entete + res.text, encoding="utf-8")

    passages = None
    if reindexer:
        try:
            passages = build_index()
        except Exception as e:
            audit(db, user=admin, action="ocr_to_rag", resource="/api/ocr/to-rag",
                  detail=f"{nom} ajouté mais réindexation échouée : {e}")
            return {"ok": True, "fichier": dest.name, "indexe": False,
                    "message": f"Document ajouté, mais la réindexation a échoué : {e}"}

    audit(db, user=admin, action="ocr_to_rag", resource="/api/ocr/to-rag",
          detail=f"{nom} → {dest.name} ({passages} passages)")
    return {
        "ok": True, "fichier": dest.name, "indexe": bool(reindexer),
        "passages_indexes": passages,
        "caracteres": len(res.text), "qualite": res.quality,
        "message": (f"Document numérisé et indexé ({passages} passages). "
                    "Interrogez-le dans le copilote avec le préfixe « doc: »."),
    }
