"""Étape 1 — Rendu (200 dpi) + OCR simple (mots et boîtes) des factures PDF.

Usage : python evaluation_ocr/preparation/1_preparer.py [dossier_factures] [dossier_travail]

Rendu + OCR (mots et boîtes) des factures — base commune pour l'annotation,
la référence à battre et LayoutLMv3 : tout le monde voit le même OCR."""
import glob, json, os, sys
from multiprocessing import Pool
import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps

ICI = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ICI, "..", "factures")
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ICI, "..", "layoutlmv3", "travail")
DPI = 200

def traiter(args):
    doc_id, chemin = args
    pdf = pdfium.PdfDocument(chemin)
    pages = []
    for k in range(len(pdf)):
        img = pdf[k].render(scale=DPI / 72).to_pil().convert("RGB")
        nom = f"{doc_id}_p{k+1}"
        img.save(f"{OUT}/images/{nom}.png")
        prep = ImageOps.autocontrast(img.convert("L"))
        d = pytesseract.image_to_data(prep, lang="fra+eng", config="--oem 3 --psm 3",
                                      output_type=pytesseract.Output.DICT)
        mots = []
        for i, t in enumerate(d["text"]):
            if not str(t).strip():
                continue
            mots.append({"t": t, "x": d["left"][i], "y": d["top"][i],
                         "w": d["width"][i], "h": d["height"][i],
                         "c": float(d["conf"][i]),
                         "b": d["block_num"][i], "p": d["par_num"][i], "l": d["line_num"][i]})
        json.dump({"page": nom, "largeur": img.width, "hauteur": img.height, "mots": mots},
                  open(f"{OUT}/ocr/{nom}.json", "w"), ensure_ascii=False)
        pages.append(nom)
    return doc_id, pages

if __name__ == "__main__":
    os.makedirs(f"{OUT}/images", exist_ok=True); os.makedirs(f"{OUT}/ocr", exist_ok=True)
    fichiers = sorted(glob.glob(f"{SRC}/*.pdf"))
    manifeste = {f"d{i+1:03d}": os.path.basename(f) for i, f in enumerate(fichiers)}
    json.dump(manifeste, open(f"{OUT}/manifeste.json", "w"), ensure_ascii=False, indent=1)
    with Pool(2) as pool:
        res = dict(pool.map(traiter, [(k, f"{SRC}/{v}") for k, v in manifeste.items()]))
    json.dump(res, open(f"{OUT}/pages.json", "w"), indent=1)
    print("OK", len(res), "documents,", sum(len(v) for v in res.values()), "pages")
