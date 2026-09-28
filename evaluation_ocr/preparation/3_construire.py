"""Étape 3 — projection de la vérité terrain sur les mots (étiquettes BIO).

Usage : python evaluation_ocr/preparation/3_construire.py [dossier_travail] [dossier_factures]
Pré-requis : annotations.json (vérité terrain) dans le dossier de travail.

Construit le jeu d'entraînement LayoutLMv3 à partir :
  - des mots + boîtes (OCR Tesseract, ou couche texte native pour les PDF natifs),
  - des vraies valeurs annotées (annotations.json).

Chaque valeur annotée est « projetée » sur les mots de la page (étiquettes BIO).
La projection est prudente : un montant n'est étiqueté que là où son libellé
le justifie (« Total HT », « TVA », « Net à payer »…), pas sur une ligne d'article
qui aurait la même valeur par hasard.

Sorties : dataset/pages.jsonl (1 ligne par page), dataset/verite.json,
          dataset/images/*.jpg, projection_rapport.json
"""
from __future__ import annotations
import json, re, sys, unicodedata
from datetime import date
from pathlib import Path

_ICI = Path(__file__).resolve().parent
RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else _ICI.parent / "layoutlmv3" / "travail")
SRC = Path(sys.argv[2] if len(sys.argv) > 2 else _ICI.parent / "factures")
DOSSIER_OCR = sys.argv[3] if len(sys.argv) > 3 else "ocr_renforce"
OUT = RACINE / "dataset"
DPI = 200

CHAMPS = ["NUMERO", "DATE", "FOURNISSEUR", "CLIENT",
          "TOTAL_HT", "TVA", "TIMBRE", "TTC", "NET"]
ETIQUETTES = ["O"] + [f"{p}-{c}" for c in CHAMPS for p in ("B", "I")]
CLE = {"NUMERO": "numero", "DATE": "date", "FOURNISSEUR": "fournisseur",
       "CLIENT": "client", "TOTAL_HT": "total_ht", "TVA": "total_tva",
       "TIMBRE": "timbre", "TTC": "total_ttc", "NET": "net_a_payer"}


# ── normalisation ───────────────────────────────────────────────────────────
def sans_accent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def lire_montant(s: str):
    """'2 381,000' / '1.600,000' / '6,720.00' / '5891-500' / '2364,500TND' → float."""
    s = re.sub(r"(?<=\d)[-/:;](?=\d{3}\b)", ",", s)
    s = re.sub(r"[^\d,.]", "", s)
    if not re.search(r"\d", s):
        return None
    s = s.strip(".,")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        mil = "." if dec == "," else ","
        s = s.replace(mil, "").replace(dec, ".")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    elif s.count(",") > 1:
        t = s.split(","); s = "".join(t[:-1]) + "." + t[-1]
    elif s.count(".") > 1:
        t = s.split("."); s = "".join(t[:-1]) + "." + t[-1]
    try:
        return float(s)
    except ValueError:
        return None


MOIS = {"jan": 1, "janv": 1, "janvier": 1, "january": 1, "feb": 2, "fev": 2, "fevr": 2,
        "fevrier": 2, "february": 2, "mar": 3, "mars": 3, "march": 3, "apr": 4, "avr": 4,
        "avril": 4, "april": 4, "may": 5, "mai": 5, "jun": 6, "juin": 6, "june": 6,
        "jul": 7, "juil": 7, "juillet": 7, "july": 7, "aug": 8, "aou": 8, "aout": 8,
        "august": 8, "sep": 9, "sept": 9, "septembre": 9, "september": 9, "oct": 10,
        "octobre": 10, "october": 10, "nov": 11, "novembre": 11, "november": 11,
        "dec": 12, "decembre": 12, "december": 12}


def _an(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def lire_date(s: str, avec_span: bool = False):
    s = sans_accent(s).replace("°", " ")
    s = re.sub(r"(?<=\d)0(?=ct[a-z])", " o", s)          # « 140CTOBER25 » = 14 OCTOBER 25
    s = re.sub(r"(?<=\d)o(?!ct)|o(?=\d)", "0", s)
    res, span = None, None
    try:
        m = re.search(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})\b", s)
        if m:
            res = date(_an(m.group(3)), int(m.group(2)), int(m.group(1)))
        else:
            m = re.search(r"(\d{1,2})[\s.\-]*([a-z]{3,9})\.?[\s.\-]*(\d{4}|\d{2})", s)
            if m and m.group(2) in MOIS:
                res = date(_an(m.group(3)), MOIS[m.group(2)], int(m.group(1)))
            else:
                m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
                if m:
                    res = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        span = m.span() if (m and res) else None
    except ValueError:
        res = None
    return (res, span) if avec_span else res


def date_exacte(textes, cible) -> bool:
    """La date lue sur cette fenêtre de mots est la bonne, ET chaque mot de la
    fenêtre y participe (sinon « FA250853 05/12/25 » serait étiqueté DATE)."""
    txt = " ".join(textes)
    d, span = lire_date(txt, avec_span=True)
    if d != cible or not span:
        return False
    return span[0] < len(textes[0]) and span[1] > len(txt) - len(textes[-1])


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sans_accent(s))


def lev(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 9
    p = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        c = [i]
        for j, cb in enumerate(b, 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (ca != cb)))
        p = c
    return p[-1]


VIDES = {"ste", "societe", "sarl", "sa", "suarl", "the", "les", "des", "and", "et"}


def mots_nom(s: str):
    return [w for w in re.findall(r"[a-z0-9]+", sans_accent(s)) if len(w) > 1 and w not in VIDES]


# ── mots d'une page ─────────────────────────────────────────────────────────
def mots_natifs(pdf_path: Path, k: int):
    """Mots + boîtes depuis la couche texte d'un PDF natif (texte exact)."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(pdf_path))
    page = pdf[k]
    H = page.get_height()
    tp = page.get_textpage()
    n = tp.count_chars()
    echelle = DPI / 72.0
    mots, cur = [], None
    for i in range(n):
        ch = tp.get_text_range(i, 1)
        if not ch or ch.isspace() or ch in "\r\n":
            if cur: mots.append(cur); cur = None
            continue
        l, b, r, t = tp.get_charbox(i)
        box = [l * echelle, (H - t) * echelle, r * echelle, (H - b) * echelle]
        hc = cur["box"][3] - cur["box"][1] if cur else 0
        if cur and -hc < box[0] - cur["box"][2] < 0.35 * max(hc, box[3] - box[1]) + 1 \
                and box[1] < cur["box"][3] and box[3] > cur["box"][1]:
            cur["t"] += ch
            cb = cur["box"]
            cur["box"] = [min(cb[0], box[0]), min(cb[1], box[1]), max(cb[2], box[2]), max(cb[3], box[3])]
        else:
            if cur: mots.append(cur)
            cur = {"t": ch, "box": box}
    if cur: mots.append(cur)
    out = []
    for m in mots:
        x0, y0, x1, y1 = m["box"]
        out.append({"t": m["t"], "x": int(x0), "y": int(y0), "w": max(1, int(x1 - x0)),
                    "h": max(1, int(y1 - y0))})
    return out


def texte_natif_fiable(natifs, ocr) -> bool:
    """Une couche texte peut être du VRAI texte numérique… ou un OCR de scanner
    de mauvaise qualité incrusté dans le PDF. On ne la garde que si ses mots
    sont confirmés par notre propre OCR (≥ 60 % des mots de 3+ lettres)."""
    def ens(ms):
        return {w for m in ms for w in re.findall(r"[a-z]{3,}", sans_accent(m["t"]))}
    n, o = ens(natifs), ens(ocr)
    return bool(n) and len(n & o) / len(n) >= 0.6


def completer(natifs, ocr):
    def recouvre(a, b):
        x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
        x1 = min(a["x"] + a["w"], b["x"] + b["w"]); y1 = min(a["y"] + a["h"], b["y"] + b["h"])
        return x1 > x0 and y1 > y0
    ajout = [{"t": m["t"], "x": m["x"], "y": m["y"], "w": m["w"], "h": m["h"]}
             for m in ocr if m["t"].strip() and m.get("c", 100) >= 50
             and not any(recouvre(m, n) for n in natifs)]
    return sorted(natifs + ajout, key=lambda m: (m["y"], m["x"]))


def lignes(mots):
    """Regroupe en lignes visuelles (centre vertical proche)."""
    ordre = sorted(range(len(mots)), key=lambda i: (mots[i]["y"] + mots[i]["h"] / 2, mots[i]["x"]))
    L = []
    for i in ordre:
        m = mots[i]; cy = m["y"] + m["h"] / 2
        if L and abs(cy - L[-1]["cy"]) < max(8, 0.55 * m["h"]):
            L[-1]["ids"].append(i)
        else:
            L.append({"cy": cy, "ids": [i]})
    for l in L:
        l["ids"].sort(key=lambda i: mots[i]["x"])
    return [l["ids"] for l in L]


# ── mots-clés par champ (sur le texte À GAUCHE du montant, même ligne) ─────
KW = {
    "TOTAL_HT": r"\bh\.?\s?t\b|hors|sous.?total|h\.?\s?taxes|htva|h\.tva|excluding|\bht\b|honoraire h",
    "TVA": r"t\.?\s?v\.?\s?a|\bvat\b|total taxes|\btaxes?\b",
    "TIMBRE": r"timbre",
    "TTC": r"t\.?\s?t\.?\s?c|\btotal\b|general|montant|invoice total|\bttc\b",
    "NET": r"\bnet\b|payer|\bdu\b|reste|amount to|solde|total a payer",
}


def colonne(mots, seg) -> str:
    """Texte des mots situés au-dessus (≤ 4 lignes) ou juste en dessous (≤ 1,5 ligne)
    du passage, dans la même colonne (recouvrement horizontal)."""
    x0 = min(mots[i]["x"] for i in seg); x1 = max(mots[i]["x"] + mots[i]["w"] for i in seg)
    y0 = min(mots[i]["y"] for i in seg); h = max(mots[i]["h"] for i in seg)
    out = []
    for j, m in enumerate(mots):
        if j in seg or m["x"] > x1 + h or m["x"] + m["w"] < x0 - h:
            continue
        if y0 - 4 * h <= m["y"] < y0 - 0.3 * h or y0 + 0.8 * h < m["y"] <= y0 + 2.5 * h:
            out.append(m["t"])
    return sans_accent(" ".join(out))


# Champs dont les bornes se rognent : un montant ou un numéro commence et finit
# par un chiffre. (Pas la date : « Septembre 2025 » commence par une lettre.)
ROGNABLES = {"NUMERO", "TOTAL_HT", "TVA", "TIMBRE", "TTC", "NET"}
# Pour un numéro, un mot sans chiffre peut en faire partie (« Esp 106 »,
# « FAC/2025/00231 ») : on ne retire que les libellés et la ponctuation.
_LIBELLE_NUMERO = re.compile(r"(?i)^(n|n[°ºo]|no|nr|num|num[ée]ro|facture|fact|ref|r[ée]f|[:|#°\-.]+)[.:]?$")


def rogner_etiquettes(mots, etiquettes):
    """Retire des entités de montant et de numéro les mots SANS CHIFFRE en tête ou
    en queue : libellé (« TTC », « TVA », « N° »), ponctuation (« : », « | »),
    devise (« DT »).

    Pourquoi : la projection teste un groupe de mots avec `lire_montant`, qui
    ignore les lettres — « TTC 1 300,350 » vaut donc 1 300,35 et le libellé était
    étiqueté avec le montant (46 TTC sur 71 dans le jeu d'origine). Le modèle
    apprenait à étiqueter les libellés, et le F1, qui exige des bornes exactes,
    en pâtissait. La valeur lue ne change pas : les mots retirés n'ont aucun chiffre.
    Idempotent."""
    etq = list(etiquettes)
    i, n = 0, len(etq)
    while i < n:
        pre, _, ch = etq[i].partition("-")
        if pre != "B":
            i += 1; continue
        j = i + 1
        while j < n and etq[j] == f"I-{ch}":
            j += 1
        if ch in ROGNABLES:
            if ch == "NUMERO":
                idx = [k for k in range(i, j) if not _LIBELLE_NUMERO.match(mots[k])]
            else:
                idx = [k for k in range(i, j) if re.search(r"\d", mots[k])]
            if idx:
                for k in range(i, j):
                    etq[k] = "O"
                a, b = idx[0], idx[-1]
                etq[a] = f"B-{ch}"
                for k in range(a + 1, b + 1):
                    etq[k] = f"I-{ch}"
        i = j
    return etq


def projeter(doc, vrai, pages_mots):
    """Renvoie {page: [étiquette par mot]} + rapport de projection."""
    etq = {p: ["O"] * len(m) for p, m in pages_mots.items()}
    rapport = {}
    fenetres = []   # (page, [ids], texte, texte_gauche_normalisé, y)
    for p, mots in pages_mots.items():
        for ids in lignes(mots):
            for a in range(len(ids)):
                for b in range(a + 1, min(a + 4, len(ids)) + 1):
                    seg = ids[a:b]
                    gauche = " ".join(mots[i]["t"] for i in ids[:a])
                    fenetres.append((p, seg, " ".join(mots[i]["t"] for i in seg),
                                     sans_accent(gauche), mots[seg[0]]["y"]))

    def poser(ch, p, seg):
        if any(etq[p][i] != "O" for i in seg):
            return False
        etq[p][seg[0]] = f"B-{ch}"
        for i in seg[1:]:
            etq[p][i] = f"I-{ch}"
        return True

    # 1) montants — ordre : TIMBRE, TVA, HT, NET, TTC (les plus spécifiques d'abord)
    for ch in ["TIMBRE", "TVA", "TOTAL_HT", "NET", "TTC"]:
        v = vrai.get(CLE[ch])
        if v is None:
            continue
        occ = []
        for p, seg, txt, gauche, y in fenetres:
            if not re.search(r"\d", txt) or re.search(r"[a-zA-Z]{4,}", txt):
                continue
            val = lire_montant(txt)
            if val is not None and abs(val - v) < 0.0015:
                occ.append((p, seg, gauche, y))
        # une occurrence = la fenêtre la plus longue (évite '381,000' dans '2 381,000')
        occ.sort(key=lambda o: -len(o[1]))
        garde = []
        for o in occ:
            if not any(o[0] == g[0] and set(o[1]) & set(g[1]) for g in garde):
                garde.append(o)
        justifiees = [o for o in garde if re.search(KW[ch], o[2])]
        if not justifiees:
            # libellé en tête de colonne (au-dessus) ou juste en dessous
            justifiees = [o for o in garde if re.search(KW[ch], colonne(pages_mots[o[0]], o[1]))]
        if ch == "NET" and vrai.get("total_ttc") is not None and \
                abs(vrai["total_ttc"] - v) < 0.0015:
            # même valeur que le TTC : NET seulement si le libellé dit « net / payer »
            pass
        elif not justifiees and ch != "TIMBRE" and garde:
            justifiees = [max(garde, key=lambda o: (o[0], o[3]))]   # la plus basse
        n = sum(poser(ch, p, seg) for p, seg, _, _ in justifiees)
        rapport[ch] = "trouve" if n else ("ambigu" if garde else "absent_ocr")


    # timbre sans libellé lisible : le « 1,000 » qui est DANS le cadre des totaux
    # (même colonne que les autres totaux, entre le premier et le dernier)
    if rapport.get("TIMBRE") == "ambigu":
        tot = [(p, i) for p in etq for i, e in enumerate(etq[p])
               if e.startswith("B-") and e[2:] in ("TOTAL_HT", "TVA", "TTC", "NET")]
        cands = []
        for p, seg, txt, gauche, y in fenetres:
            if len(seg) > 2 or any(etq[p][i] != "O" for i in seg):
                continue
            if lire_montant(txt) != vrai.get("timbre") or re.search(r"[a-zA-Z]{2,}", txt):
                continue
            ms = pages_mots[p]; x = ms[seg[-1]]["x"] + ms[seg[-1]]["w"]; h = ms[seg[0]]["h"]
            voisins = [ms[i] for q, i in tot if q == p and abs(ms[i]["x"] + ms[i]["w"] - x) < 6 * h]
            if len(voisins) >= 2 and min(v["y"] for v in voisins) - 2 * h < y < max(v["y"] for v in voisins) + 2 * h:
                cands.append((p, seg))
        if len(cands) == 1 and poser("TIMBRE", *cands[0]):
            rapport["TIMBRE"] = "trouve_cadre"

    if rapport.get("NET") in ("ambigu", "absent_ocr") and rapport.get("TTC") == "trouve" and \
            abs((vrai.get("total_ttc") or -1) - (vrai.get("net_a_payer") or -2)) < 0.0015:
        rapport["NET"] = "egal_ttc"   # pas de ligne « net » distincte : le TTC fait foi

    # 2) date — toutes les occurrences de la bonne date
    if vrai.get("date"):
        cible = date.fromisoformat(vrai["date"]); n = 0
        for p, seg, txt, gauche, y in sorted(fenetres, key=lambda f: -len(f[1])):
            if len(seg) <= 3 and date_exacte(txt.split(" "), cible):
                n += poser("DATE", p, seg)
        rapport["DATE"] = "trouve" if n else "absent_ocr"

    # 3) numéro
    if vrai.get("numero"):
        cible = norm_id(vrai["numero"]); n = 0
        for p, seg, txt, gauche, y in sorted(fenetres, key=lambda f: -len(f[1])):
            t = norm_id(txt)
            if not t:
                continue
            ok = t == cible or (t.endswith(cible) and len(t) - len(cible) <= 3 and
                                re.fullmatch(r"(n|no|num|nr|f|fa)", t[:len(t) - len(cible)] or "n"))
            if not ok and len(cible) >= 6 and len(seg) == 1:
                ok = lev(t, cible) <= 1
            if ok and len(cible) < 5 and not re.search(r"fact|n\s?°|num|invoice|avoir|\bno\b|\bn\b", gauche + " " + txt.lower()):
                ok = False
            if ok:
                n += poser("NUMERO", p, seg)
        rapport["NUMERO"] = "trouve" if n else "absent_ocr"

    # 4) noms (fournisseur, client) — meilleure fenêtre contiguë sur une ligne
    for ch in ["FOURNISSEUR", "CLIENT"]:
        cible = mots_nom(vrai.get(CLE[ch]) or "")
        if not cible:
            continue
        meilleurs = []
        for p, mots in pages_mots.items():
            for ids in lignes(mots):
                toks = [mots_nom(mots[i]["t"]) for i in ids]
                for a in range(len(ids)):
                    for b in range(a + 1, min(a + 6, len(ids)) + 1):
                        w = [x for t in toks[a:b] for x in t]
                        if not w or not toks[a] or not toks[b - 1]:
                            continue
                        com = len(set(w) & set(cible))
                        if com == 0 or not (set(toks[a]) & set(cible)) or not (set(toks[b - 1]) & set(cible)):
                            continue
                        score = com / len(set(cible)) - 0.05 * (len(set(w)) - com)
                        gauche = sans_accent(" ".join(mots[i]["t"] for i in ids[:a]))
                        bonus = 0.3 if ch == "CLIENT" and re.search(r"client|doit|factur|faveur|billed|invoice", gauche) else 0
                        meilleurs.append((score + bonus, score, p, ids[a:b], mots[ids[a]]["y"]))
        meilleurs.sort(key=lambda m: (-m[0], m[2], m[4]))
        n = 0
        for tot, score, p, seg, y in meilleurs:
            if score < 0.5:
                break
            if poser(ch, p, seg):
                n = 1; break
        rapport[ch] = "trouve" if n else ("ambigu" if meilleurs else "absent_ocr")
    etq = {p: rogner_etiquettes([m["t"] for m in pages_mots[p]], e) for p, e in etq.items()}
    return etq, rapport


def main():
    from PIL import Image
    ann = json.load(open(RACINE / "annotations.json"))
    man = json.load(open(RACINE / "manifeste.json"))
    pages = json.load(open(RACINE / "pages.json"))
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    lignes_out, verite, rapports = [], {}, {}
    for doc in sorted(ann):
        v = ann[doc]
        if v.get("exclu") or v.get("type") not in ("facture", "avoir"):
            continue
        verite[doc] = {k: v.get(k) for k in ["type", "manuscrite", "numero", "date", "fournisseur",
                                             "client", "devise", "total_ht", "total_tva", "timbre",
                                             "total_ttc", "net_a_payer", "certitude", "note"]}
        fichier = man[doc]
        natif = False
        pages_mots, dims = {}, {}
        for k, p in enumerate(pages[doc]):
            f_ocr = RACINE / DOSSIER_OCR / f"{p}.json"
            o = json.load(open(f_ocr if f_ocr.exists() else RACINE / "ocr" / f"{p}.json"))
            mots = [{"t": m["t"], "x": m["x"], "y": m["y"], "w": m["w"], "h": m["h"]}
                    for m in o["mots"] if m["t"].strip()]
            if fichier.lower().endswith(".pdf"):
                try:
                    nat = mots_natifs(SRC / fichier, k)
                    if sum(len(m["t"]) for m in nat) > 150 and texte_natif_fiable(nat, mots):
                        # texte exact du PDF + ce que seul l'OCR voit (libellés dessinés
                        # en vectoriel ou en image : « TIMBRE : », « TOTAL TTC : »…)
                        mots, natif = completer(nat, json.load(open(RACINE / "ocr" / f"{p}.json"))["mots"]), True
                except Exception:
                    pass
            pages_mots[p] = [mots[i] for ids in lignes(mots) for i in ids]   # ordre de lecture
            dims[p] = (o["largeur"], o["hauteur"])
        etq, rap = projeter(doc, verite[doc], pages_mots)
        rapports[doc] = {"source": "natif" if natif else "ocr", **rap}
        for p, mots in pages_mots.items():
            W, H = dims[p]
            im = Image.open(RACINE / "images" / f"{p}.png").convert("RGB")
            im.thumbnail((1000, 1000)); im.save(OUT / "images" / f"{p}.jpg", quality=85)
            boites = [[max(0, min(1000, int(1000 * m["x"] / W))),
                       max(0, min(1000, int(1000 * m["y"] / H))),
                       max(0, min(1000, int(1000 * (m["x"] + m["w"]) / W))),
                       max(0, min(1000, int(1000 * (m["y"] + m["h"]) / H)))] for m in mots]
            lignes_out.append({"doc": doc, "page": p, "image": f"images/{p}.jpg",
                               "source": "natif" if natif else "ocr",
                               "fournisseur": verite[doc]["fournisseur"],
                               "mots": [m["t"] for m in mots], "boites": boites,
                               "etiquettes": etq[p]})
    with open(OUT / "pages.jsonl", "w") as f:
        for l in lignes_out:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    json.dump(verite, open(OUT / "verite.json", "w"), ensure_ascii=False, indent=1)
    json.dump(ETIQUETTES, open(OUT / "etiquettes.json", "w"))
    json.dump(rapports, open(RACINE / "projection_rapport.json", "w"), ensure_ascii=False, indent=1)
    # synthèse
    from collections import Counter
    for ch in CHAMPS:
        c = Counter(r.get(ch) for r in rapports.values() if ch in r)
        print(f"{ch:12s}", dict(c))
    print(len(verite), "documents,", len(lignes_out), "pages,",
          sum(r["source"] == "natif" for r in rapports.values()), "natifs")
    empaqueter(verite)


def empaqueter(verite):
    """Référence « règles » sur le même OCR + zip prêt pour Colab."""
    import shutil, zipfile
    projet = _ICI.parent.parent
    sys.path.insert(0, str(projet))
    from ml_engine.ocr import parse_invoice
    from ml_engine.ocr.layoutlm.mots import texte_par_lignes
    pages = json.load(open(RACINE / "pages.json"))
    regles = {}
    for doc in verite:
        txt = []
        for p in pages[doc]:
            f = RACINE / DOSSIER_OCR / f"{p}.json"
            o = json.load(open(f if f.exists() else RACINE / "ocr" / f"{p}.json"))
            txt.append(texte_par_lignes(o["mots"]))
        regles[doc] = {"meme_ocr": parse_invoice("\n".join(txt)).to_dict(), "production": {}}
        ref = RACINE / "reference.json"          # facultatif : sortie de la chaîne de production
        if ref.exists():
            r = json.load(open(ref)).get(doc)
            if r:
                regles[doc]["production"] = r["production"]
    json.dump(regles, open(OUT / "regles.json", "w"), ensure_ascii=False, indent=1, default=str)
    shutil.copy(RACINE / "projection_rapport.json", OUT / "projection_rapport.json")
    shutil.copy(projet / "ml_engine" / "ocr" / "layoutlm" / "champs.py", OUT / "champs.py")
    z = RACINE.parent / "layoutlmv3_factures.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ["pages.jsonl", "verite.json", "etiquettes.json", "regles.json",
                  "projection_rapport.json", "champs.py"]:
            zf.write(OUT / f, f)
        for im in sorted((OUT / "images").glob("*.jpg")):
            zf.write(im, f"images/{im.name}")
    print("Jeu prêt pour Colab :", z)


if __name__ == "__main__":
    main()
