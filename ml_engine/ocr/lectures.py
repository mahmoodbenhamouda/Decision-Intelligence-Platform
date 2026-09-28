"""
ml_engine/ocr/lectures.py
=========================
Conserver une lecture pour l'enregistrer plus tard, sans relire le document.

Avant : « Lire » puis « Enregistrer » envoyaient deux fois le fichier, qui était
relu deux fois (15 à 40 s chacune pour un scan), et c'était la SECONDE lecture
qui était enregistrée — pas celle que l'utilisateur avait vue, ni ses
corrections, puisqu'il ne pouvait rien corriger.

Maintenant : la lecture est conservée sous un identifiant (l'empreinte SHA-256
du document), avec le document lui-même. L'enregistrement envoie cet
identifiant et les valeurs validées ; les écarts deviennent des corrections.

Le document est gardé sur disque (`output/factures_ocr/`, hors git) : c'est la
preuve de ce qui a été enregistré, et c'est lui qui servira à réentraîner
LayoutLMv3 à partir des corrections.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_ID = re.compile(r"^[0-9a-f]{64}$")


def dossier() -> Path:
    from ml_engine.analytics.kpi_engine import STORE_PATH
    d = Path(STORE_PATH).parent / "factures_ocr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def empreinte(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def conserver_lecture(content: bytes, filename: str, ocr: Dict[str, Any],
                      facture: Dict[str, Any], moteur: str) -> Dict[str, str]:
    """Enregistre le document et sa lecture. Renvoie {lecture_id, chemin}."""
    sha = empreinte(content)
    ext = (Path(filename).suffix.lower() or ".bin")[:6]
    doc = dossier() / f"{sha}{re.sub(r'[^a-z0-9.]', '', ext) or '.bin'}"
    if not doc.exists():
        doc.write_bytes(content)
    (dossier() / f"{sha}.json").write_text(json.dumps({
        "lecture_id": sha, "fichier": filename, "chemin": str(doc),
        "moteur": moteur, "ocr": ocr, "facture": facture,
        "lu_le": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, default=str), encoding="utf-8")
    return {"lecture_id": sha, "chemin": str(doc)}


def charger_lecture(lecture_id: str) -> Optional[Dict[str, Any]]:
    """La lecture conservée, ou None. L'identifiant est vérifié (64 hexadécimaux) :
    il ne peut pas servir à lire un autre fichier du serveur."""
    if not _ID.match(lecture_id or ""):
        return None
    f = dossier() / f"{lecture_id}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))
