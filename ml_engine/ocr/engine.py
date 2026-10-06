"""Moteur OCR réutilisable : bytes d'un document → texte exploitable."""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_PSM_MODES = (6, 4, 3, 11)

_LOCAL_TESSDATA = Path(__file__).resolve().parents[2] / "models" / "tessdata"


def _system_tessdata_dirs() -> List[Path]:
    """Emplacements usuels du tessdata système (Windows, Linux, macOS)."""
    cands: List[Path] = []
    env = (os.environ.get("TESSDATA_PREFIX") or "").strip()
    if env:
        p = Path(env)
        cands += [p, p / "tessdata"]
    cands += [
        Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
        Path("/usr/share/tesseract-ocr/5/tessdata"),
        Path("/usr/share/tesseract-ocr/4.00/tessdata"),
        Path("/usr/share/tesseract-ocr/tessdata"),
        Path("/usr/local/share/tessdata"),
        Path("/opt/homebrew/share/tessdata"),
        Path("/usr/share/tessdata"),
    ]
    out, seen = [], set()
    for c in cands:
        try:
            if c.is_dir() and c.resolve() != _LOCAL_TESSDATA.resolve() and c not in seen:
                seen.add(c)
                out.append(c)
        except Exception:
            continue
    return out


def _mirror_system_tessdata() -> None:
    """Recopie eng/osd du système vers le tessdata local (une seule fois)."""
    import shutil
    for src_dir in _system_tessdata_dirs():
        copied = False
        for name in ("eng.traineddata", "osd.traineddata"):
            src, dst = src_dir / name, _LOCAL_TESSDATA / name
            try:
                if src.exists() and not dst.exists():
                    shutil.copy2(src, dst)
                    copied = True
            except Exception:
                continue
        if copied or (_LOCAL_TESSDATA / "eng.traineddata").exists():
            return


def _use_local_tessdata() -> None:
    """Active le dossier tessdata du projet s'il contient des packs de langue."""
    try:
        if not _LOCAL_TESSDATA.is_dir():
            return
        if not any(_LOCAL_TESSDATA.glob("*.traineddata")):
            return
        current = os.environ.get("TESSDATA_PREFIX", "")
        if current and Path(current).resolve() == _LOCAL_TESSDATA.resolve():
            return
        _mirror_system_tessdata()
        os.environ["TESSDATA_PREFIX"] = str(_LOCAL_TESSDATA)
    except Exception:
        pass
_MIN_WIDTH = 1000
_MAX_PDF_OCR_PAGES = 10


@dataclass
class OCRResult:
    """Résultat d'extraction, avec les métadonnées de qualité."""
    text: str = ""
    confidence: float = 0.0
    source: str = ""
    pages: int = 1
    engine: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text.strip())

    @property
    def quality(self) -> str:
        """Étiquette lisible de la qualité (affichée à l'utilisateur)."""
        if self.source == "pdf-texte":
            return "texte natif (fiable)"
        if self.confidence >= 85:
            return "excellente"
        if self.confidence >= 70:
            return "bonne"
        if self.confidence >= 50:
            return "moyenne — à vérifier"
        return "faible — vérification manuelle nécessaire"

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "confidence": round(self.confidence, 1),
                "source": self.source, "pages": self.pages, "engine": self.engine,
                "quality": self.quality, "warnings": self.warnings}


def ocr_available() -> bool:
    """True si Tesseract est réellement utilisable (binaire + wrapper)."""
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
        pytesseract.get_tesseract_version()
        _use_local_tessdata()
        return True
    except Exception:
        return False


def install_hint() -> str:
    return ("Tesseract OCR n'est pas installé. Windows : "
            "https://github.com/UB-Mannheim/tesseract/wiki (cocher le pack "
            "de langue « French »), puis ajouter le dossier au PATH. "
            "Linux : apt install tesseract-ocr tesseract-ocr-fra. "
            "Enfin : pip install pytesseract Pillow")


def _languages() -> str:
    """`fra+eng` si le pack français est présent, sinon `eng`."""
    try:
        import pytesseract
        _use_local_tessdata()
        langs = set(pytesseract.get_languages(config=""))
        if "fra" in langs:
            return "fra+eng" if "eng" in langs else "fra"
        return "eng"
    except Exception:
        return "fra+eng"


def clean_text(raw: str) -> str:
    """Supprime les artefacts OCR sans détruire le contenu utile."""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
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


def _preprocess(img):
    """Niveaux de gris + autocontraste + agrandissement (+ Otsu si OpenCV)."""
    from PIL import Image, ImageOps

    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    if img.width < _MIN_WIDTH:
        ratio = _MIN_WIDTH / max(1, img.width)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)),
                         Image.LANCZOS)
    try:
        import cv2
        import numpy as np
        arr = np.array(img)
        _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return Image.fromarray(th)
    except Exception:
        return img


def _ocr_image_obj(img, warnings: List[str]) -> tuple[str, float]:
    """OCR d'une image PIL : teste plusieurs `--psm`, garde le meilleur score."""
    import pytesseract

    lang = _languages()
    if lang == "eng":
        warnings.append("Pack de langue française absent — OCR en anglais "
                        "(installez tesseract-ocr-fra pour de meilleurs résultats).")
    prepared = _preprocess(img)

    best_text, best_conf = "", -1.0
    for psm in _PSM_MODES:
        config = f"--oem 3 --psm {psm}"
        try:
            data = pytesseract.image_to_data(
                prepared, lang=lang, config=config,
                output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        confs = [float(c) for c in data.get("conf", []) if str(c) not in ("-1", "")]
        words = [w for w in data.get("text", []) if str(w).strip()]
        if not words:
            continue
        conf = sum(confs) / len(confs) if confs else 0.0
        score = conf + min(len(words), 400) / 40.0
        if score > best_conf:
            best_conf = score
            best_text = pytesseract.image_to_string(prepared, lang=lang, config=config)
            best_conf_real = conf
    if best_conf < 0:
        return "", 0.0
    return best_text, locals().get("best_conf_real", 0.0)


_SYMBOLES_PARASITES = re.compile(r"[§æûôÆ¤¢£¥|\\{}~^*]")


def qualite_texte(texte: str) -> float:
    """Part des « mots » d'un texte qui ressemblent à de vrais mots ou nombres."""
    toks = texte.split()
    if not toks:
        return 0.0
    ok = sum(1 for t in toks
             if not _SYMBOLES_PARASITES.search(t)
             and re.fullmatch(r"[\w°'’/.,:;%()\-]+", t))
    return ok / len(toks)


SEUIL_QUALITE_TEXTE_PDF = 0.88


def _pdf_native_text(content: bytes) -> tuple[str, int, str]:
    """Texte natif d'un PDF (sans OCR)."""
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(content))
        pages = len(reader.pages)
        txt = "\n".join((p.extract_text() or "") for p in reader.pages)
        return txt, pages, "pypdf"
    except Exception:
        pass
    try:
        from pdfminer.high_level import extract_text
        return extract_text(io.BytesIO(content)), 0, "pdfminer"
    except Exception:
        return "", 0, ""


def _pdf_ocr(content: bytes, warnings: List[str]) -> tuple[str, float, int]:
    """OCR d'un PDF scanné : rendu des pages en images puis Tesseract."""
    try:
        import pypdfium2 as pdfium
    except Exception:
        warnings.append("PDF scanné détecté : installez `pypdfium2` "
                        "(pip install pypdfium2) pour l'OCR des PDF images.")
        return "", 0.0, 0
    try:
        pdf = pdfium.PdfDocument(io.BytesIO(content))
    except Exception as e:
        warnings.append(f"PDF illisible : {e}")
        return "", 0.0, 0

    n = min(len(pdf), _MAX_PDF_OCR_PAGES)
    if len(pdf) > _MAX_PDF_OCR_PAGES:
        warnings.append(f"Document long : seules les {_MAX_PDF_OCR_PAGES} "
                        f"premières pages sur {len(pdf)} ont été traitées.")
    texts, confs = [], []
    for i in range(n):
        try:
            img = pdf[i].render(scale=2.5).to_pil()
            t, c = _ocr_image_obj(img, warnings)
            if t.strip():
                texts.append(t)
                confs.append(c)
        except Exception:
            continue
    conf = sum(confs) / len(confs) if confs else 0.0
    return "\n\n".join(texts), conf, n


def ocr_document(content: bytes, filename: str = "document") -> OCRResult:
    """Extrait le texte d'un document (image ou PDF), avec métadonnées."""
    ext = Path(filename).suffix.lower()
    warnings: List[str] = []

    if ext == ".pdf":
        native, pages, engine = _pdf_native_text(content)
        cleaned = clean_text(native)
        per_page = len(cleaned) / max(1, pages or 1)
        fiable = qualite_texte(cleaned) >= SEUIL_QUALITE_TEXTE_PDF
        if cleaned and per_page > 120 and fiable:
            return OCRResult(text=cleaned, confidence=0.0, source="pdf-texte",
                             pages=pages or 1, engine=engine, warnings=warnings)
        if not ocr_available():
            warnings.append(install_hint())
            return OCRResult(text=cleaned, confidence=0.0,
                             source="pdf-texte" if cleaned else "pdf-vide",
                             pages=pages or 1, engine=engine or "aucun",
                             warnings=warnings)
        ocr_txt, conf, n = _pdf_ocr(content, warnings)
        ocr_clean = clean_text(ocr_txt)
        if cleaned and not fiable and ocr_clean:
            warnings.append("Couche texte du PDF de mauvaise qualité (OCR du scanner) : "
                            "document relu par notre OCR.")
            return OCRResult(text=ocr_clean, confidence=conf, source="pdf-ocr",
                             pages=n or pages or 1, engine="tesseract",
                             warnings=warnings)
        if len(ocr_clean) > len(cleaned):
            return OCRResult(text=ocr_clean, confidence=conf, source="pdf-ocr",
                             pages=n or pages or 1, engine="tesseract",
                             warnings=warnings)
        return OCRResult(text=cleaned, confidence=0.0, source="pdf-texte",
                         pages=pages or 1, engine=engine or "aucun",
                         warnings=warnings)

    if not ocr_available():
        return OCRResult(text="", confidence=0.0, source="image-ocr",
                         engine="aucun", warnings=[install_hint()])
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(content))
    except Exception as e:
        return OCRResult(warnings=[f"Image illisible : {e}"], source="image-ocr")
    raw, conf = _ocr_image_obj(img, warnings)
    text = clean_text(raw)
    if not text:
        warnings.append("Aucun texte détecté — vérifiez la netteté, le cadrage "
                        "et l'éclairage du document.")
    return OCRResult(text=text, confidence=conf, source="image-ocr", pages=1,
                     engine="tesseract", warnings=warnings)
