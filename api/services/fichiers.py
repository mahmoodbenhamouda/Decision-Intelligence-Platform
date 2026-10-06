"""Lecture des fichiers TEXTUELS joints au copilote : CSV et PDF natifs."""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List

import pandas as pd

from api.services.erreurs import DonneesInvalides, ErreurInterne

EXTENSIONS = {".csv", ".pdf"}
TAILLE_MAX = 20 * 1024 * 1024
MAX_CHARS = 3000


def _clean_text(raw: str) -> str:
    """Supprime les artefacts de conversion en conservant accents et montants."""
    if not raw:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw.replace("\r", "\n"))
    lines: List[str] = []
    for line in text.split("\n"):
        stripped = re.sub(r"[ \t]{2,}", " ", line).strip()
        if not stripped:
            lines.append("")
            continue
        if len(re.sub(r"[\W_]", "", stripped, flags=re.UNICODE)) < 2:
            continue
        lines.append(stripped)
    out: List[str] = []
    for line in lines:
        if line == "" and out and out[-1] == "":
            continue
        out.append(line)
    return "\n".join(out).strip()


def extract_from_csv(content: bytes, filename: str) -> Dict[str, Any]:
    """Charge un CSV et calcule des statistiques financières de base."""
    df = None
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            df = pd.read_csv(io.BytesIO(content), encoding=enc, low_memory=False)
            break
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise DonneesInvalides(f"Erreur de lecture du CSV : {e}")
    if df is None:
        raise DonneesInvalides("Impossible de décoder ce fichier CSV.")

    rows, cols = df.shape
    num_cols = df.select_dtypes(include="number").columns.tolist()
    stats: List[str] = [
        f"**Fichier** : {filename}",
        f"**Dimensions** : {rows} lignes × {cols} colonnes",
        f"**Colonnes** : {', '.join(df.columns.astype(str).tolist()[:15])}"
        f"{'…' if cols > 15 else ''}",
    ]
    for col in num_cols[:6]:
        s = df[col].dropna()
        if s.empty:
            continue
        stats.append(f"**{col}** : total={s.sum():,.2f} | moy={s.mean():,.2f} "
                     f"| min={s.min():,.2f} | max={s.max():,.2f}")
    date_cols = [c for c in df.columns
                 if any(k in str(c).lower() for k in ("date", "period"))]
    if date_cols:
        dates = pd.to_datetime(df[date_cols[0]], errors="coerce").dropna()
        if not dates.empty:
            stats.append(f"**Période couverte** : {dates.min().date()} → {dates.max().date()}")

    return {
        "extracted_text": "\n".join(stats),
        "summary": (f"CSV analysé : {rows} lignes, {cols} colonnes. "
                    f"Colonnes numériques : {', '.join(map(str, num_cols[:5]))}."),
        "rows": rows, "cols": cols,
    }


def extract_from_pdf(content: bytes, filename: str) -> Dict[str, Any]:
    """Extrait le texte d'un PDF natif (PyPDF2, repli pdfminer)."""
    raw = ""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(content))
        raw = "\n".join((p.extract_text() or "") for p in reader.pages)
    except ImportError:
        try:
            from pdfminer.high_level import extract_text
            raw = extract_text(io.BytesIO(content))
        except ImportError:
            raise ErreurInterne("Librairie PDF absente : pip install PyPDF2 pdfminer.six")
    except Exception as e:
        raise DonneesInvalides(f"Erreur de lecture du PDF : {e}")

    cleaned = _clean_text(raw)
    if not cleaned:
        return {"extracted_text": "", "scanned": True,
                "summary": "PDF sans texte extractible (document scanné)."}
    truncated = cleaned[:MAX_CHARS] + ("\n\n[… document tronqué …]"
                                       if len(cleaned) > MAX_CHARS else "")
    return {"extracted_text": truncated,
            "summary": f"PDF {filename} — {len(cleaned)} caractères extraits."}

