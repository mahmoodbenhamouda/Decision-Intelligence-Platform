"""
api/routers/upload.py
=====================
Endpoint d'upload de fichiers pour le copilote financier.
Supporte : CSV, PDF, PNG, JPG, JPEG (OCR Tesseract).

Endpoint : POST /api/copilot/upload
  - ParamÃƒÂ¨tre : file (UploadFile) + question (str) + filtres JSON optionnels
  - Retour    : {answer, via, file_type, extracted_text, radar, active_filters}
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter()

# Ã¢â€â‚¬Ã¢â€â‚¬ Helpers Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def _clean_text(raw: str) -> str:
    """Nettoie le texte extrait (OCR/PDF) : supprime espaces superflus,
    symboles parasites, lignes vides en excÃƒÂ¨s, artefacts OCR courants."""
    if not raw:
        return ""
    # Supprimer les caractÃƒÂ¨res non imprimables sauf \n
    text = re.sub(r"[^\x20-\x7EÃƒÂ ÃƒÂ¢ÃƒÂ¤ÃƒÂ©ÃƒÂ¨ÃƒÂªÃƒÂ«ÃƒÂ®ÃƒÂ¯ÃƒÂ´ÃƒÂ¹ÃƒÂ»ÃƒÂ¼ÃƒÂ§Ã…â€œÃƒÂ¦\nÃ¢â€šÂ¬Ã‚Â°Ã‚Â²Ã‚Â³Ã‚Âµ]", " ", raw)
    # Supprimer les lignes composÃƒÂ©es uniquement de symboles/tirets/points
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # Ignorer les lignes de moins de 2 caractÃƒÂ¨res significatifs
        if len(re.sub(r"[\W_]", "", stripped)) < 2:
            continue
        # Normaliser les espaces multiples dans la ligne
        stripped = re.sub(r" {2,}", " ", stripped)
        cleaned_lines.append(stripped)
    # Supprimer les sÃƒÂ©quences de plus de 2 lignes vides consÃƒÂ©cutives
    result_lines: List[str] = []
    blank_count = 0
    for line in cleaned_lines:
        if line:
            blank_count = 0
            result_lines.append(line)
        else:
            blank_count += 1
            if blank_count <= 1:
                result_lines.append(line)
    return "\n".join(result_lines).strip()


# Ã¢â€â‚¬Ã¢â€â‚¬ Extracteurs par type de fichier Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

def extract_from_csv(content: bytes, filename: str) -> Dict[str, Any]:
    """Charge un CSV et calcule des statistiques financiÃƒÂ¨res basiques."""
    try:
        # Essai UTF-8, puis latin-1
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(io.BytesIO(content), encoding=enc, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Impossible de dÃƒÂ©coder le fichier CSV.")

        rows, cols = df.shape
        # Colonnes numÃƒÂ©riques
        num_cols = df.select_dtypes(include="number").columns.tolist()
        # Stats sommaires
        stats: List[str] = [
            f"**Fichier** : {filename}",
            f"**Dimensions** : {rows} lignes Ãƒâ€” {cols} colonnes",
            f"**Colonnes** : {', '.join(df.columns.tolist()[:15])}{'...' if cols > 15 else ''}",
        ]
        for col in num_cols[:6]:
            series = df[col].dropna()
            if series.empty:
                continue
            stats.append(
                f"**{col}** : total={series.sum():,.2f} | moy={series.mean():,.2f} "
                f"| min={series.min():,.2f} | max={series.max():,.2f}"
            )
        # Colonnes date
        date_cols = [c for c in df.columns if any(kw in c.lower() for kw in ["date", "period"])]
        if date_cols:
            dc = date_cols[0]
            dates = pd.to_datetime(df[dc], errors="coerce").dropna()
            if not dates.empty:
                stats.append(f"**PÃƒÂ©riode couverte** : {dates.min().date()} Ã¢â€ â€™ {dates.max().date()}")

        extracted = "\n".join(stats)
        summary = f"Fichier CSV analysÃƒÂ© : {rows} lignes, {cols} colonnes. " \
                  f"Colonnes numÃƒÂ©riques : {', '.join(num_cols[:5])}."
        return {"extracted_text": extracted, "summary": summary, "rows": rows, "cols": cols}

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur lecture CSV : {e}")


def extract_from_pdf(content: bytes, filename: str) -> Dict[str, Any]:
    """Extrait le texte d'un PDF avec PyPDF2 ou pdfminer."""
    raw = ""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(content))
        for page in reader.pages:
            raw += (page.extract_text() or "") + "\n"
    except ImportError:
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            raw = pdfminer_extract(io.BytesIO(content))
        except ImportError:
            raise HTTPException(
                status_code=500,
                detail="Librairie PDF non installÃƒÂ©e. ExÃƒÂ©cutez : pip install PyPDF2 pdfminer.six"
            )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur lecture PDF : {e}")

    cleaned = _clean_text(raw)
    if not cleaned:
        return {"extracted_text": "Aucun texte extractible dans ce PDF (peut-ÃƒÂªtre scannÃƒÂ©).", "summary": "PDF vide ou scannÃƒÂ©."}

    # Tronquer pour le prompt (max 3000 caractÃƒÂ¨res)
    truncated = cleaned[:3000] + ("\n\n[... document tronquÃƒÂ© ...]" if len(cleaned) > 3000 else "")
    summary = f"PDF {filename} Ã¢â‚¬â€ {len(cleaned)} caractÃƒÂ¨res extraits."
    return {"extracted_text": truncated, "summary": summary}


def extract_from_image(content: bytes, filename: str) -> Dict[str, Any]:
    """Extrait le texte d'une image (PNG/JPG) via Tesseract OCR."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Librairies OCR non installÃƒÂ©es. ExÃƒÂ©cutez : pip install pytesseract Pillow"
        )

    try:
        img = Image.open(io.BytesIO(content))

        # PrÃƒÂ©-traitement image pour amÃƒÂ©liorer l'OCR
        img = img.convert("RGB")

        # Tentative avec plusieurs configurations Tesseract
        # psm 6 = bloc de texte uniforme (tableaux, factures)
        # psm 11 = texte ÃƒÂ©pars (images avec peu de texte)
        raw = ""
        for psm in (6, 3, 11):
            try:
                config = f"--oem 3 --psm {psm} -l fra+eng"
                candidate = pytesseract.image_to_string(img, config=config)
                if len(candidate.strip()) > len(raw.strip()):
                    raw = candidate
            except Exception:
                continue

        if not raw.strip():
            # Essai sur image en niveaux de gris (meilleur contraste)
            try:
                import numpy as np
                import cv2
                np_img = np.array(img)
                gray = cv2.cvtColor(np_img, cv2.COLOR_RGB2GRAY)
                _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                pil_thresh = Image.fromarray(thresh)
                raw = pytesseract.image_to_string(pil_thresh, config="--oem 3 --psm 6 -l fra+eng")
            except ImportError:
                pass  # opencv optionnel

        cleaned = _clean_text(raw)

        if not cleaned:
            return {
                "extracted_text": "Aucun texte dÃƒÂ©tectÃƒÂ© dans l'image. "
                                  "VÃƒÂ©rifiez que l'image est nette et bien ÃƒÂ©clairÃƒÂ©e.",
                "summary": "Image sans texte dÃƒÂ©tectable."
            }

        truncated = cleaned[:3000] + ("\n\n[... texte tronquÃƒÂ© ...]" if len(cleaned) > 3000 else "")
        summary = f"Image {filename} Ã¢â‚¬â€ OCR Tesseract : {len(cleaned)} caractÃƒÂ¨res extraits."
        return {"extracted_text": truncated, "summary": summary}

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Erreur OCR : {e}")


# Ã¢â€â‚¬Ã¢â€â‚¬ Endpoint principal Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬

@router.post("/api/copilot/upload")
async def copilot_upload(
    file: UploadFile = File(...),
    question: str = Form(default="Analyse ce document financiÃƒÂ¨rement et donne-moi les points clÃƒÂ©s."),
    filters: str = Form(default="{}"),
):
    """
    Analyse un fichier uploadÃƒÂ© (CSV, PDF, PNG, JPG) et rÃƒÂ©pond ÃƒÂ  la question
    posÃƒÂ©e en s'appuyant sur le contenu extrait + les KPIs de la plateforme.
    """
    # Validation type de fichier
    filename = file.filename or "fichier"
    ext = Path(filename).suffix.lower()
    allowed = {".csv", ".pdf", ".png", ".jpg", ".jpeg"}
    if ext not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Type de fichier non supportÃƒÂ© ({ext}). Formats acceptÃƒÂ©s : CSV, PDF, PNG, JPG."
        )

    # Lecture du contenu
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB max
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 20 MB).")

    # Parsing des filtres JSON
    try:
        filters_dict: Dict[str, Any] = json.loads(filters) if filters.strip() else {}
    except json.JSONDecodeError:
        filters_dict = {}

    # Ã¢â€â‚¬Ã¢â€â‚¬ Extraction selon le type Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    file_type = ext.lstrip(".")
    if ext == ".csv":
        extraction = extract_from_csv(content, filename)
    elif ext == ".pdf":
        extraction = extract_from_pdf(content, filename)
    else:
        extraction = extract_from_image(content, filename)

    extracted_text = extraction.get("extracted_text", "")
    file_summary = extraction.get("summary", "")

    # Ã¢â€â‚¬Ã¢â€â‚¬ Enrichissement avec les KPIs de la plateforme Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    kpis: Dict[str, Any] = {}
    radar: List[Any] = []
    try:
        from ml_engine.analytics import kpi_engine
        kpis = kpi_engine.compute_dashboard(filters_dict) or {}
        radar = kpis.get("finance_radar", [])
    except Exception:
        pass

    # â”€â”€ RÃ©ponse LLM ancrÃ©e sur le document extrait â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    answer = ""
    via = "regles"
    try:
        from agents.finance_agent import detect_theme, build_thematic_context
        themes = detect_theme(question)
        thematic_ctx = build_thematic_context(themes, kpis)

        # get_llm() charge .env lui-mÃªme. Il faut donc l'appeler avant de conclure
        # qu'aucune clÃ© LLM n'est disponible.
        from config.settings import get_llm
        llm = get_llm()
        prompt = (
            "Tu es FinBot, le copilote financier expert d'Overlyne (Tunisie). "
            "Un utilisateur t'a soumis un document financier. Analyse-le et rÃ©ponds "
            "Ã  sa question de maniÃ¨re prÃ©cise, chiffrÃ©e et actionnable.\n\n"
            f"## FICHIER SOUMIS ({file_type.upper()})\n"
            f"{file_summary}\n\n"
            f"## CONTENU EXTRAIT DU FICHIER\n{extracted_text}\n\n"
            f"## DONNÃ‰ES KPI DE LA PLATEFORME (contexte)\n{thematic_ctx}\n\n"
            f"## QUESTION\n{question}\n\n"
            "## INSTRUCTIONS\n"
            "1. Analyse le contenu du fichier et rÃ©ponds Ã  la question.\n"
            "2. Croise avec les KPIs de la plateforme si pertinent.\n"
            "3. Cite les montants dÃ©tectÃ©s dans le document dans leur devise d'origine.\n"
            "4. Si tu convertis ou compares avec les KPIs, prÃ©cise la devise et l'hypothÃ¨se.\n"
            "5. Structure avec du Markdown (titres ##, listes -, **gras**).\n"
            "6. Conclus par une recommandation actionnable.\n"
            "7. Si le fichier contient des donnÃ©es financiÃ¨res, fournis une synthÃ¨se clÃ©.\n"
        )
        res = llm.invoke(prompt)
        txt = getattr(res, "content", str(res))
        if txt and "[Mode mock" not in txt:
            answer = txt.strip()
            via = "llm"
    except Exception as e:
        print(f"[upload] LLM indisponible pour l'analyse fichier : {e}")
    # Repli si LLM indisponible : analyse locale propre et lisible.
    # Objectif demo : ne jamais afficher de mojibake ni demander a l'utilisateur
    # de connecter un LLM alors que l'OCR a deja produit du contenu exploitable.
    if not answer:
        via = "regles"
        excerpt = extracted_text[:1500]

        if ext == ".csv":
            rows = extraction.get("rows", 0)
            cols = extraction.get("cols", 0)
            answer = (
                f"## Analyse du fichier CSV : `{filename}`\n\n"
                f"{extracted_text}\n\n"
                f"**Synthese locale** : fichier charge avec **{rows} lignes** et **{cols} colonnes**.\n"
                "L'agent a extrait les dimensions, les colonnes et les premiers indicateurs numeriques disponibles."
            )
        elif ext == ".pdf":
            answer = (
                f"## Analyse du PDF : `{filename}`\n\n"
                "### Contenu extrait\n"
                f"```text\n{excerpt}\n```\n\n"
                "### Synthese locale\n"
                "- Le texte du document a ete extrait et nettoye.\n"
                "- Les montants, dates et libelles visibles peuvent maintenant etre utilises par le copilote.\n"
                "- Si le document est financier, verifiez les totaux, taxes, remises et comptes mentionnes."
            )
        else:
            upper_text = extracted_text.upper()
            amounts = re.findall(r"\d[\d\s]*,\d{2}", extracted_text)
            unique_amounts = []
            for amount in amounts:
                normalized = re.sub(r"\s+", " ", amount).strip()
                if normalized not in unique_amounts:
                    unique_amounts.append(normalized)

            is_invoice = "FACTURE" in upper_text or "TVA" in upper_text or "NET A PAYER" in upper_text
            is_accounting = any(token in upper_text for token in ["707", "4457", "7085", "411", "COMPT"])

            synthesis = [
                f"## Analyse OCR de l'image : `{filename}`",
                "",
                "### Texte extrait",
                f"```text\n{excerpt}\n```",
                "",
                "### Synthese locale",
            ]
            if is_invoice:
                synthesis.append("- Document detecte : facture ou exemple de facture.")
            if unique_amounts:
                synthesis.append("- Montants detectes : " + ", ".join(unique_amounts[:10]) + ".")
            if "TVA" in upper_text:
                synthesis.append("- TVA detectee : le document contient une ligne de taxe a controler.")
            if "REMISE" in upper_text:
                synthesis.append("- Remise detectee : le net commercial doit etre verifie apres reduction.")
            if "NET A PAYER" in upper_text:
                synthesis.append("- Net a payer detecte : c'est le montant final du document.")
            if is_accounting:
                synthesis.extend([
                    "- Ecriture comptable detectee cote vendeur :",
                    "  - 707 : vente de marchandises, au credit.",
                    "  - 4457 : TVA collectee, au credit.",
                    "  - 7085 : frais de port sur vente, au credit.",
                    "  - 411 : creance client, au debit.",
                ])
            if not (is_invoice or unique_amounts or is_accounting):
                synthesis.append("- Le contenu OCR est disponible, mais aucun schema financier standard n'a ete reconnu automatiquement.")
            synthesis.append("")
            synthesis.append("### Controle recommande")
            synthesis.append("- Comparer les totaux OCR avec l'image originale, surtout les montants et les numeros de comptes.")
            answer = "\n".join(synthesis)
    return JSONResponse({
        "answer": answer,
        "via": via,
        "file_type": file_type,
        "filename": filename,
        "extracted_text": extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text,
        "radar": [
            {k: v for k, v in r.items() if k in ("titre", "categorie", "severite", "montant_dt", "montant_label")}
            for r in (radar or [])[:4]
        ],
    })

