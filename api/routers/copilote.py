"""POST /api/copilot question en langage naturel (+ historique) POST /api/copilot/upload CSV ou PDF…"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from api.auth.database import get_db
from api.auth.deps import require_directeur
from api.auth.journal import audit
from api.auth.models import User
from api.schemas.filtres import CopilotRequest
from api.services import copilote
from api.services.fichiers import EXTENSIONS, TAILLE_MAX

router = APIRouter(tags=["copilote"])


@router.post("/api/copilot")
def copilot(req: CopilotRequest,
            user: User = Depends(require_directeur),
            db: Session = Depends(get_db)):
    audit(db, user=user, action="access", resource="/api/copilot")
    return copilote.repondre(req)


@router.post("/api/copilot/upload")
async def copilot_upload(
    file: UploadFile = File(...),
    question: str = Form(default="Analyse ce document et donne-moi les points clés."),
    filters: str = Form(default="{}"),
    user: User = Depends(require_directeur),
):
    nom = file.filename or "fichier"
    extension = Path(nom).suffix.lower()
    if extension not in EXTENSIONS:
        raise HTTPException(
            415,
            f"Type de fichier non supporté ({extension or 'inconnu'}). Le copilote analyse "
            "les CSV et PDF textuels. Pour une image ou un document scanné "
            "(facture, contrat), utilisez l'onglet « Documents ».")
    contenu = await file.read()
    if len(contenu) > TAILLE_MAX:
        raise HTTPException(413, "Fichier trop volumineux (20 Mo maximum).")
    return copilote.analyser_document(nom, extension, contenu, question, filters, user)
