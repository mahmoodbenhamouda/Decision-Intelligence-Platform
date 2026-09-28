# -*- coding: utf-8 -*-
"""Facture de test FICTIVE pour éprouver la chaîne OCR + LayoutLMv3.

Produit, dans le dossier de sortie :
  - FV-2026-0142_numerique.pdf : PDF avec vraie couche texte (chemin « texte PDF »)
  - FV-2026-0142_scan.pdf      : même facture rastérisée, penchée, bruitée (chemin OCR)
  - FV-2026-0142_verite.json   : les bonnes valeurs, pour comparer

Pièges volontaires : deux taux de TVA (19 % et 7 %), net à payer ≠ TTC
(retenue à la source), bandeau blanc sur fond foncé, RIB et téléphone pleins de
chiffres, montant en toutes lettres.
"""
import io, json, sys
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SORTIE = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SORTIE.mkdir(parents=True, exist_ok=True)
M3 = D("0.001")

def dt(x: D) -> str:
    """1995.000 -> '1 995,000' (espace fine insécable en milliers)."""
    return f"{x.quantize(M3):,.3f}".replace(",", " ").replace(".", ",")

# ── contenu (entièrement fictif) ──────────────────────────────────────────
FOURN = {"nom": "ATELIER NOVALUX", "forme": "SARL au capital de 50.000 Dinars",
         "adr": ["Zone industrielle El Bosten, lot 17", "3052 Sfax - Tunisie"],
         "tel": "Tél : 74 000 318  -  Fax : 74 000 319",
         "mf": "MF : 0000000/X/A/M/000"}
CLIENT = {"nom": "STE DELTA COMPOSITES", "adr": ["12, rue du Lac Toba", "1053 Les Berges du Lac - Tunis"],
          "mf": "MF : 0000001/Y/B/M/000"}
NUMERO, DATE, ECHEANCE = "FV-2026-0142", "14/09/2026", "14/10/2026"
LIGNES = [  # désignation, quantité, PU HT, taux TVA
    ("Moule en résine époxy - réf. MR-240", D(4), D("312.500"), D(19)),
    ("Prestation de finition (heures)", D(12), D("45.000"), D(19)),
    ("Livraison et manutention", D(1), D("85.000"), D(19)),
    ("Documentation technique imprimée", D(1), D("120.000"), D(7)),
]
TIMBRE = D("1.000")
TAUX_RS = D("0.01")

# ── calculs ───────────────────────────────────────────────────────────────
bases = {}
for _, q, pu, t in LIGNES:
    bases[t] = bases.get(t, D(0)) + q * pu
HT = sum(bases.values())
TVA_PAR_TAUX = {t: (b * t / 100).quantize(M3, ROUND_HALF_UP) for t, b in bases.items()}
TVA = sum(TVA_PAR_TAUX.values())
TTC = HT + TVA + TIMBRE
RS = (TTC * TAUX_RS).quantize(M3, ROUND_HALF_UP)
NET = TTC - RS
assert HT == D("1995.000") and TVA == D("364.650") and TTC == D("2360.650") and NET == D("2337.043"), (HT, TVA, TTC, NET)
EN_LETTRES = "Deux mille trois cent trente-sept dinars et quarante-trois millimes"

# ── dessin ────────────────────────────────────────────────────────────────
ENCRE, GRIS, BANDEAU, FOND_TOT = HexColor("#1f2937"), HexColor("#6b7280"), HexColor("#1e3a5f"), HexColor("#e5e7eb")

def dessiner(c):
    W, H = A4
    g = 40
    # bandeau fournisseur : blanc sur fond foncé
    c.setFillColor(BANDEAU); c.rect(0, H - 95, W, 95, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 22); c.drawString(g, H - 45, FOURN["nom"])
    c.setFont("Helvetica", 9)
    c.drawString(g, H - 62, FOURN["forme"])
    c.drawString(g, H - 75, "  ·  ".join(FOURN["adr"]))
    c.drawString(g, H - 88, FOURN["tel"] + "     " + FOURN["mf"])

    # titre + références
    c.setFillColor(ENCRE)
    c.setFont("Helvetica-Bold", 20); c.drawString(g, H - 140, "FACTURE")
    c.setFont("Helvetica", 10)
    y = H - 162
    for lib, val in (("Facture N° :", NUMERO), ("Date :", DATE), ("Échéance :", ECHEANCE),
                     ("Mode de règlement :", "Virement bancaire")):
        c.drawString(g, y, lib); c.setFont("Helvetica-Bold", 10); c.drawString(g + 105, y, val)
        c.setFont("Helvetica", 10); y -= 15

    # bloc client
    bx, by, bw, bh = W - g - 230, H - 225, 230, 90
    c.setStrokeColor(GRIS); c.setLineWidth(0.8); c.rect(bx, by, bw, bh, stroke=1, fill=0)
    c.setFillColor(GRIS); c.setFont("Helvetica", 8); c.drawString(bx + 8, by + bh - 14, "FACTURÉ À")
    c.setFillColor(ENCRE); c.setFont("Helvetica-Bold", 11); c.drawString(bx + 8, by + bh - 30, CLIENT["nom"])
    c.setFont("Helvetica", 9)
    for k, l in enumerate(CLIENT["adr"] + [CLIENT["mf"]]):
        c.drawString(bx + 8, by + bh - 46 - 13 * k, l)

    # tableau des lignes
    cols = [g, g + 250, g + 305, g + 385, g + 430]   # désignation, qté, PU, TVA, total
    y = H - 265
    c.setFillColor(FOND_TOT); c.rect(g, y - 5, W - 2 * g, 20, stroke=0, fill=1)
    c.setFillColor(ENCRE); c.setFont("Helvetica-Bold", 9)
    for x, t in zip(cols, ("Désignation", "Qté", "P.U. HT", "TVA", "Total HT")):
        c.drawString(x + 4, y + 1, t)
    c.setFont("Helvetica", 9)
    for des, q, pu, t in LIGNES:
        y -= 20
        c.drawString(cols[0] + 4, y, des)
        c.drawRightString(cols[1] + 40, y, str(q))
        c.drawRightString(cols[2] + 70, y, dt(pu))
        c.drawRightString(cols[3] + 35, y, f"{t} %")
        c.drawRightString(W - g - 4, y, dt(q * pu))
        c.setStrokeColor(FOND_TOT); c.line(g, y - 6, W - g, y - 6)

    # récapitulatif TVA (deux taux)
    y -= 45
    c.setFont("Helvetica-Bold", 9); c.drawString(g, y, "Récapitulatif TVA")
    c.setFont("Helvetica", 9)
    for i, (lib, x) in enumerate((("Taux", g), ("Base HT", g + 60), ("Montant TVA", g + 150))):
        c.drawString(x, y - 16, lib)
    yy = y - 32
    for t in sorted(TVA_PAR_TAUX, reverse=True):
        c.drawString(g, yy, f"{t} %"); c.drawString(g + 60, yy, dt(bases[t])); c.drawString(g + 150, yy, dt(TVA_PAR_TAUX[t]))
        yy -= 14

    # cadre des totaux : fond gris
    tx, tw = W - g - 215, 215
    lignes_tot = [("Total HT", HT), ("Total TVA", TVA), ("Timbre fiscal", TIMBRE),
                  ("Total TTC", TTC), ("Retenue à la source 1 %", -RS)]
    top = y + 10
    hauteur = 18 * len(lignes_tot) + 32
    c.setFillColor(FOND_TOT); c.rect(tx, top - hauteur, tw, hauteur, stroke=0, fill=1)
    c.setFillColor(ENCRE); c.setFont("Helvetica", 10)
    ty = top - 18
    for lib, v in lignes_tot:
        c.drawString(tx + 10, ty, lib); c.drawRightString(tx + tw - 10, ty, dt(v)); ty -= 18
    c.setFillColor(BANDEAU); c.rect(tx, top - hauteur, tw, 26, stroke=0, fill=1)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 11)
    c.drawString(tx + 10, top - hauteur + 9, "NET À PAYER"); c.drawRightString(tx + tw - 10, top - hauteur + 9, dt(NET) + " DT")

    # montant en lettres
    c.setFillColor(ENCRE); c.setFont("Helvetica-Oblique", 9)
    c.drawString(g, top - hauteur - 30, "Arrêtée la présente facture à la somme de :")
    c.setFont("Helvetica-BoldOblique", 9); c.drawString(g, top - hauteur - 43, EN_LETTRES + ".")

    # pied : banque (chiffres pièges) + mention fictive
    c.setStrokeColor(GRIS); c.line(g, 80, W - g, 80)
    c.setFillColor(GRIS); c.setFont("Helvetica", 8)
    c.drawString(g, 66, "Banque : Banque Fictive de Test  -  RIB : 00 000 0000000000000 00  -  IBAN : TN59 0000 0000 0000 0000 0000")
    c.drawString(g, 54, "Registre de commerce : B000000002026  -  Code douane : 000000X")
    c.setFont("Helvetica-Oblique", 7)
    c.drawString(g, 36, "Document fictif généré pour tester l'extraction OCR - aucune valeur commerciale.")

def pdf_numerique() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Facture {NUMERO}"); c.setAuthor("Test OCR"); dessiner(c); c.showPage(); c.save()
    return buf.getvalue()

def pdf_scan(pdf: bytes) -> bytes:
    """Imprimé puis scanné : 200 dpi, gris, penché de 0,9°, flou léger, bruit, JPEG 55."""
    import numpy as np, pypdfium2 as pdfium
    from PIL import Image, ImageFilter
    im = pdfium.PdfDocument(pdf)[0].render(scale=200 / 72).to_pil().convert("L")
    im = im.rotate(-0.9, resample=Image.BICUBIC, expand=False, fillcolor=247)
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    a = np.asarray(im, dtype=np.float32)
    rng = np.random.default_rng(142)
    a = a * 0.93 + 12 + rng.normal(0, 7, a.shape)              # papier légèrement gris + grain
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    j = io.BytesIO(); im.save(j, "JPEG", quality=55); j.seek(0)
    out = io.BytesIO(); Image.open(j).save(out, "PDF", resolution=200.0)
    return out.getvalue()

if __name__ == "__main__":
    num = pdf_numerique()
    (SORTIE / f"{NUMERO}_numerique.pdf").write_bytes(num)
    (SORTIE / f"{NUMERO}_scan.pdf").write_bytes(pdf_scan(num))
    verite = {"numero": NUMERO, "date": "2026-09-14", "fournisseur": FOURN["nom"],
              "client": CLIENT["nom"], "devise": "TND",
              "total_ht": float(HT), "total_tva": float(TVA), "timbre": float(TIMBRE),
              "total_ttc": float(TTC), "net_a_payer": float(NET),
              "_pieges": ["deux taux de TVA (19 % et 7 %) : ne pas prendre 356,250 ni 8,400",
                          "net a payer != TTC (retenue a la source 1 % = 23,607)",
                          "fournisseur en blanc sur fond fonce",
                          "RIB, IBAN, telephone, registre de commerce : chiffres a ne pas lire comme montants"]}
    (SORTIE / f"{NUMERO}_verite.json").write_text(json.dumps(verite, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HT", dt(HT), "| TVA", dt(TVA), "| TTC", dt(TTC), "| RS", dt(RS), "| NET", dt(NET))
