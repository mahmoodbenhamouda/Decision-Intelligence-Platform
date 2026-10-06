"""Mots + boîtes d'un document, tels que LayoutLMv3 les attend."""
from __future__ import annotations

import io
import re
from typing import Dict, List, Tuple

DPI = 200
LANG = "fra+eng"


def desinverser(im):
    import numpy as np
    from PIL import Image, ImageFilter
    a = np.asarray(im, dtype=np.uint8)
    fond = np.asarray(im.filter(ImageFilter.BoxBlur(20)), dtype=np.uint8)
    sombre = fond < 110
    b = a.copy()
    b[sombre] = 255 - a[sombre]
    return Image.fromarray(b)


def _lecture(im, psm: int, facteur: int = 1) -> List[dict]:
    import pytesseract
    d = pytesseract.image_to_data(im, lang=LANG, config=f"--oem 3 --psm {psm}",
                                  output_type=pytesseract.Output.DICT)
    mots = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        c = float(d["conf"][i])
        if not t or c < 0:
            continue
        mots.append({"t": t, "x": d["left"][i] // facteur, "y": d["top"][i] // facteur,
                     "w": d["width"][i] // facteur, "h": d["height"][i] // facteur,
                     "c": c, "psm": psm})
    return mots


def _recouvre(a, b) -> bool:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"])
    y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    if x1 <= x0 or y1 <= y0:
        return False
    return (x1 - x0) * (y1 - y0) / max(1, min(a["w"] * a["h"], b["w"] * b["h"])) > 0.4


def fusion(passes: List[List[dict]]) -> List[dict]:
    """Pour chaque zone de la page, le mot le plus sûr ; sans doublon."""
    chiffres = lambda t: re.sub(r"\D", "", t)
    tous = sorted((m for p in passes for m in p if m["c"] >= 25 or m["psm"] == 3),
                  key=lambda m: -m["c"])
    gardes: List[dict] = []
    for m in tous:
        conflits = [g for g in gardes if _recouvre(m, g)]
        if not conflits:
            gardes.append(m)
            continue
        cm = chiffres(m["t"])
        cg = "".join(chiffres(g["t"]) for g in sorted(conflits, key=lambda g: g["x"]))
        if (m["c"] >= 30 and len(cm) > len(cg) >= 2 and cm.startswith(cg)) or \
                (len(conflits) > 1 and m["c"] >= 30 and len(cm) >= 4 and
                 len(cm) >= 0.6 * len(m["t"]) and
                 all(len(chiffres(g["t"])) >= 0.6 * len(g["t"]) for g in conflits)):
            for g in conflits:
                gardes.remove(g)
            gardes.append(m)
    return sorted(gardes, key=lambda m: (m["y"], m["x"]))


def ocr_renforce(image) -> List[dict]:
    from PIL import Image
    im = image.convert("L")
    di2 = desinverser(im)
    di2 = di2.resize((di2.width * 2, di2.height * 2), Image.LANCZOS)
    return fusion([_lecture(im, 3), _lecture(im, 6), _lecture(im, 11),
                   _lecture(di2, 6, 2), _lecture(di2, 11, 2)])


def mots_natifs(page) -> List[dict]:
    """Mots + boîtes (en pixels à 200 dpi) depuis la couche texte d'une page PDF."""
    H = page.get_height()
    tp = page.get_textpage()
    e = DPI / 72.0
    mots, cur = [], None
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if not ch or ch.isspace():
            if cur:
                mots.append(cur); cur = None
            continue
        l, b, r, t = tp.get_charbox(i)
        box = [l * e, (H - t) * e, r * e, (H - b) * e]
        hc = cur["box"][3] - cur["box"][1] if cur else 0
        if cur and -hc < box[0] - cur["box"][2] < 0.35 * max(hc, box[3] - box[1]) + 1 \
                and box[1] < cur["box"][3] and box[3] > cur["box"][1]:
            cb = cur["box"]
            cur["t"] += ch
            cur["box"] = [min(cb[0], box[0]), min(cb[1], box[1]),
                          max(cb[2], box[2]), max(cb[3], box[3])]
        else:
            if cur:
                mots.append(cur)
            cur = {"t": ch, "box": box}
    if cur:
        mots.append(cur)
    return [{"t": m["t"], "x": int(m["box"][0]), "y": int(m["box"][1]),
             "w": max(1, int(m["box"][2] - m["box"][0])),
             "h": max(1, int(m["box"][3] - m["box"][1]))} for m in mots]


def completer(natifs: List[dict], ocr: List[dict]) -> List[dict]:
    """Ajoute aux mots natifs ceux que seul l'OCR lit (sans recouvrement)."""
    def touche(a, b):
        return (min(a["x"] + a["w"], b["x"] + b["w"]) > max(a["x"], b["x"]) and
                min(a["y"] + a["h"], b["y"] + b["h"]) > max(a["y"], b["y"]))
    ajout = [{k: m[k] for k in ("t", "x", "y", "w", "h")} for m in ocr
             if m["t"].strip() and m.get("c", 100) >= 50 and not any(touche(m, n) for n in natifs)]
    return natifs + ajout


def pages_du_document(content: bytes, filename: str, max_pages: int = 4
                      ) -> List[Tuple[object, List[dict], str]]:
    """[(image PIL RGB, mots, source)] pour chaque page — source « pdf-texte » (couche texte exacte) ou…"""
    from PIL import Image
    from ml_engine.ocr.engine import SEUIL_QUALITE_TEXTE_PDF, qualite_texte

    if filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(io.BytesIO(content))
        out = []
        for k in range(min(len(pdf), max_pages)):
            page = pdf[k]
            im = page.render(scale=DPI / 72.0).to_pil().convert("RGB")
            natifs = mots_natifs(page)
            texte = " ".join(m["t"] for m in natifs)
            if len(texte) > 150 and qualite_texte(texte) >= SEUIL_QUALITE_TEXTE_PDF:
                mots, src = completer(natifs, _lecture(im.convert("L"), 3)), "pdf-texte"
            else:
                mots, src = ocr_renforce(im), "ocr"
            out.append((im, ordre_de_lecture(mots), src))
        return out
    im = Image.open(io.BytesIO(content))
    if max(im.size) < 1600:
        f = 2200 / max(im.size)
        im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
    im = im.convert("RGB")
    return [(im, ordre_de_lecture(ocr_renforce(im)), "ocr")]


def ordre_de_lecture(mots: List[dict]) -> List[dict]:
    """Ligne par ligne, de gauche à droite — l'ordre vu à l'entraînement."""
    ordre = sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"]))
    lignes: List[Dict] = []
    for m in ordre:
        cy = m["y"] + m["h"] / 2
        if lignes and abs(cy - lignes[-1]["cy"]) < max(8, 0.55 * m["h"]):
            lignes[-1]["m"].append(m)
        else:
            lignes.append({"cy": cy, "m": [m]})
    return [x for l in lignes for x in sorted(l["m"], key=lambda x: x["x"])]


def boites_normalisees(mots: List[dict], largeur: int, hauteur: int) -> List[List[int]]:
    """Boîtes en coordonnées 0-1000 (format LayoutLMv3)."""
    c = lambda v: max(0, min(1000, int(v)))
    return [[c(1000 * m["x"] / largeur), c(1000 * m["y"] / hauteur),
             c(1000 * (m["x"] + m["w"]) / largeur), c(1000 * (m["y"] + m["h"]) / hauteur)]
            for m in mots]


def texte_par_lignes(mots: List[dict]) -> str:
    """Reconstitue un texte ligne par ligne (pour les règles)."""
    ordre = sorted(mots, key=lambda m: (m["y"] + m["h"] / 2, m["x"]))
    lignes: List[List[dict]] = []
    cy_prec = None
    for m in ordre:
        cy = m["y"] + m["h"] / 2
        if lignes and abs(cy - cy_prec) < max(8, 0.55 * m["h"]):
            lignes[-1].append(m)
        else:
            lignes.append([m]); cy_prec = cy
    return "\n".join(" ".join(x["t"] for x in sorted(l, key=lambda x: x["x"])) for l in lignes)
