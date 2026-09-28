"""Étape 2 — OCR renforcé (même algorithme que ml_engine/ocr/layoutlm/mots.py).

Usage : python evaluation_ocr/preparation/2_ocr_renforce.py [dossier_travail]

OCR renforcé : plusieurs lectures Tesseract fusionnées.

Constat sur le jeu de factures : une seule passe (psm 3) rate des blocs entiers —
typiquement le cadre des totaux quand il est grisé ou en blanc sur fond sombre
(ex. « Total TTC 2 931,000 » invisible sur d060). Chaque mode voit des choses
différentes ; on les combine :

  psm 3  (mise en page automatique)      — le texte courant
  psm 6  (bloc uniforme)                  — les tableaux
  psm 11 (texte épars)                    — les étiquettes isolées, les cadres
  psm 6 et 11 sur image « dé-inversée » agrandie ×2 — texte clair sur fond foncé,
                                            petits chiffres des cadres de totaux

Fusion : on garde, pour chaque zone de la page, le mot le plus sûr (confiance
Tesseract), sans doublon (recouvrement de boîtes).
"""
import json, os, sys
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageFilter
import pytesseract

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "layoutlmv3", "travail")
LANG = "fra+eng"


def desinverser(im: Image.Image) -> Image.Image:
    a = np.asarray(im, dtype=np.uint8)
    fond = np.asarray(im.filter(ImageFilter.BoxBlur(20)), dtype=np.uint8)
    sombre = fond < 110
    b = a.copy(); b[sombre] = 255 - a[sombre]
    return Image.fromarray(b)


def lecture(im, psm):
    d = pytesseract.image_to_data(im, lang=LANG, config=f"--oem 3 --psm {psm}",
                                  output_type=pytesseract.Output.DICT)
    mots = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        c = float(d["conf"][i])
        if not t or c < 0:
            continue
        mots.append({"t": t, "x": d["left"][i], "y": d["top"][i], "w": d["width"][i],
                     "h": d["height"][i], "c": c, "psm": psm})
    return mots


def demi(mots):
    for m in mots:
        for k in ("x", "y", "w", "h"):
            m[k] = m[k] // 2
    return mots


def recouvre(a, b) -> bool:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1 = min(a["x"] + a["w"], b["x"] + b["w"]); y1 = min(a["y"] + a["h"], b["y"] + b["h"])
    if x1 <= x0 or y1 <= y0:
        return False
    inter = (x1 - x0) * (y1 - y0)
    return inter / max(1, min(a["w"] * a["h"], b["w"] * b["h"])) > 0.4


def fusion(passes):
    tous = [m for p in passes for m in p if m["c"] >= 25 or m["psm"] == 3]
    # bonus léger au mot confirmé par une autre passe (même texte, même endroit)
    tous.sort(key=lambda m: -m["c"])
    gardes = []
    import re
    chiffres = lambda t: re.sub(r"\D", "", t)
    for m in tous:
        conflits = [g for g in gardes if recouvre(m, g)]
        if not conflits:
            gardes.append(m)
            continue
        # « 2931/000 » (41 %) complète « 2931.0 » (73 %) : on garde le plus complet
        # (un mot peut aussi recoller deux morceaux : « 2931.0 » + « 000 »)
        cm = chiffres(m["t"])
        cg = "".join(chiffres(g["t"]) for g in sorted(conflits, key=lambda g: g["x"]))
        if m["c"] >= 30 and len(cm) > len(cg) >= 2 and cm.startswith(cg) or \
                (len(conflits) > 1 and m["c"] >= 30 and len(cm) >= 4 and
                 len(cm) >= 0.6 * len(m["t"]) and
                 all(len(chiffres(g["t"])) >= 0.6 * len(g["t"]) for g in conflits)):
            for g in conflits:
                gardes.remove(g)
            gardes.append(m)
    return sorted(gardes, key=lambda m: (m["y"], m["x"]))


def traiter(page):
    dest = f"{OUT}/ocr_renforce/{page}.json"
    if os.path.exists(dest):
        return page
    im = Image.open(f"{OUT}/images/{page}.png").convert("L")
    di = desinverser(im)
    di2 = di.resize((di.width * 2, di.height * 2), Image.LANCZOS)   # petits chiffres
    passes = [lecture(im, 3), lecture(im, 6), lecture(im, 11),
              demi(lecture(di2, 6)), demi(lecture(di2, 11))]
    w, h = im.size
    json.dump({"page": page, "largeur": w, "hauteur": h, "mots": fusion(passes),
               "n_par_passe": [len(p) for p in passes]},
              open(dest, "w"), ensure_ascii=False)
    return page


if __name__ == "__main__":
    os.makedirs(f"{OUT}/ocr_renforce", exist_ok=True)
    pages = sorted(p for ps in json.load(open(f"{OUT}/pages.json")).values() for p in ps)
    if len(sys.argv) > 2:
        pages = sys.argv[2].split(",")
    with Pool(2) as pool:
        for i, p in enumerate(pool.imap_unordered(traiter, pages), 1):
            print(i, p, flush=True)
