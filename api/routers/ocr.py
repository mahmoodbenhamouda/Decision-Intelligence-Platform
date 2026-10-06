"""Service OCR transversal exposé en API — utilisable par tout le projet."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.models import User
from api.services import ocr as service

router = APIRouter(prefix="/api/ocr", tags=["ocr"])


async def _lire_fichier(file: UploadFile) -> tuple[bytes, str]:
    """Contenu et nom d'un document reçu : format, présence et taille contrôlés."""
    name = file.filename or "document"
    ext = Path(name).suffix.lower()
    if ext not in service.FORMATS:
        raise HTTPException(415, f"Format non supporté ({ext or 'inconnu'}). "
                                 f"Acceptés : {', '.join(sorted(service.FORMATS))}.")
    content = await file.read()
    if not content:
        raise HTTPException(422, "Fichier vide.")
    if len(content) > service.TAILLE_MAX:
        raise HTTPException(413, "Fichier trop volumineux (20 Mo maximum).")
    return content, name


@router.get("/status")
def status(user: User = Depends(require_directeur)):
    return service.etat(user)


@router.post("/extract")
async def extract(file: UploadFile = File(...),
                  user: User = Depends(require_directeur),
                  db: Session = Depends(get_db)):
    content, name = await _lire_fichier(file)
    return service.extraire_texte(db, user, content, name)


@router.post("/invoice")
async def invoice(file: UploadFile = File(...),
                  reconcile: bool = Form(default=True),
                  user: User = Depends(require_directeur),
                  db: Session = Depends(get_db)):
    content, name = await _lire_fichier(file)
    return service.lire_une_facture(db, user, content, name, rapprocher=reconcile)


@router.post("/rapprocher")
async def rapprocher(lecture_id: str = Form(...),
                     sens: str = Form(...),
                     facture: Optional[str] = Form(default=None),
                     user: User = Depends(require_directeur)):
    return service.rapprocher_lecture(user, lecture_id, sens, facture)


@router.post("/invoice/import")
async def invoice_import(file: Optional[UploadFile] = File(default=None),
                         lecture_id: Optional[str] = Form(default=None),
                         facture: Optional[str] = Form(default=None),
                         sens: Optional[str] = Form(default=None),
                         client_code: Optional[str] = Form(default=None),
                         tiers_code: Optional[str] = Form(default=None),
                         creer_client: bool = Form(default=True),
                         user: User = Depends(require_directeur),
                         db: Session = Depends(get_db)):
    content: Optional[bytes] = None
    name: Optional[str] = None
    if not lecture_id and file is not None:
        content, name = await _lire_fichier(file)
    return service.importer(db, user, contenu=content, nom_fichier=name,
                            lecture_id=lecture_id, facture=facture, sens=sens,
                            client_code=client_code, tiers_code=tiers_code,
                            creer_client=creer_client)


@router.get("/imports")
def imports(client_code: Optional[str] = None, sens: Optional[str] = None,
            rapprochement: Optional[str] = None,
            user: User = Depends(require_directeur)):
    return service.factures_importees(user, client_code, sens, rapprochement)


@router.post("/imports/rerapprocher")
def imports_rerapprocher(seulement: Optional[str] = Form(default=None),
                         admin: User = Depends(require_directeur),
                         db: Session = Depends(get_db)):
    return service.rerapprocher(db, admin, seulement)


@router.get("/echeancier")
def echeancier_ocr(sens: Optional[str] = None, user: User = Depends(require_directeur)):
    return service.echeancier(user, sens)


@router.post("/imports/{facture_id}/reglement")
def reglement(facture_id: int, le: Optional[str] = Form(default=None),
              annuler: bool = Form(default=False),
              admin: User = Depends(require_directeur),
              db: Session = Depends(get_db)):
    return service.marquer_reglement(db, admin, facture_id, le, annuler)


@router.get("/qualite")
def qualite(depuis: Optional[str] = None, admin: User = Depends(require_directeur)):
    return service.qualite_en_production(depuis)


@router.get("/entreprise")
def entreprise(user: User = Depends(require_directeur)):
    return service.identite_entreprise()


@router.put("/entreprise")
def entreprise_maj(nom: str = Form(...), alias: str = Form(default=""),
                   mf: Optional[str] = Form(default=None),
                   admin: User = Depends(require_directeur),
                   db: Session = Depends(get_db)):
    return service.declarer_entreprise(db, admin, nom, alias, mf)


@router.post("/to-rag")
async def to_rag(file: UploadFile = File(...),
                 reindex: bool = Form(default=True),
                 admin: User = Depends(require_directeur),
                 db: Session = Depends(get_db)):
    content, name = await _lire_fichier(file)
    return service.indexer_pour_le_copilote(db, admin, content, name, reindexer=reindex)
