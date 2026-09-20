"""
ml_engine/ocr/layoutlm/champs.py
================================
Outils communs à l'entraînement (Colab), à l'évaluation et à l'inférence :

  - lecture robuste des montants, dates et numéros tels qu'imprimés
    (« 2 381,000 », « 1.600,000 », « 6,720.00 », « 14OCTOBER25 »…) ;
  - décodage des prédictions LayoutLMv3 (étiquettes BIO par mot) en champs ;
  - contrôle arithmétique HT + TVA (+ timbre) = TTC ;
  - comparaison d'une extraction avec la vérité terrain.

Aucune dépendance lourde : ce module s'importe sans torch ni transformers.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

CHAMPS = ["NUMERO", "DATE", "FOURNISSEUR", "CLIENT",
          "TOTAL_HT", "TVA", "TIMBRE", "TTC", "NET"]
MONTANTS = ["TOTAL_HT", "TVA", "TIMBRE", "TTC", "NET"]
ETIQUETTES = ["O"] + [f"{p}-{c}" for c in CHAMPS for p in ("B", "I")]
CHAMPS_EVAL = ["numero", "date", "fournisseur", "client", "total_ht", "total_tva",
               "timbre", "total_ttc", "net_a_payer"]
CLE = {"NUMERO": "numero", "DATE": "date", "FOURNISSEUR": "fournisseur",
       "CLIENT": "client", "TOTAL_HT": "total_ht", "TVA": "total_tva",
       "TIMBRE": "timbre", "TTC": "total_ttc", "NET": "net_a_payer"}


# ── lecture des valeurs ─────────────────────────────────────────────────────
def sans_accent(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def lire_montant(s: str) -> Optional[float]:
    """'2 381,000' / '1.600,000' / '6,720.00' / '5891-500' / '2931/000 TND' → float."""
    if s is None:
        return None
    s = re.sub(r"(?<=\d)[-/:;](?=\d{3}\b)", ",", str(s))
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


def lire_date(s: str) -> Optional[date]:
    s = sans_accent(s or "").replace("°", " ")
    s = re.sub(r"(?<=\d)0(?=ct[a-z])", " o", s)          # « 140CTOBER25 » = 14 OCTOBER 25
    s = re.sub(r"(?<=\d)o(?!ct)|o(?=\d)", "0", s)
    try:
        m = re.search(r"(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})\b", s)
        if m:
            return date(_an(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.search(r"(\d{1,2})[\s.\-]*([a-z]{3,9})\.?[\s.\-]*(\d{4}|\d{2})", s)
        if m and m.group(2) in MOIS:
            return date(_an(m.group(3)), MOIS[m.group(2)], int(m.group(1)))
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


def norm_id(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", sans_accent(s or ""))


def nettoyer_numero(s: str) -> str:
    """Retire le préfixe « N° », « No », « n » collé au numéro."""
    s = (s or "").strip()
    return re.sub(r"^(n\s*[°º o]\s*:?|no\.?\s*:?|num[ée]ro\s*:?)\s*", "", s, flags=re.I).strip() or s


VIDES = {"ste", "societe", "sarl", "sa", "suarl", "the", "les", "des", "and", "et"}


def mots_nom(s: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", sans_accent(s or "")) if len(w) > 1 and w not in VIDES]


# ── décodage des prédictions ────────────────────────────────────────────────
def spans(mots: Sequence[str], etiquettes: Sequence[str],
          probas: Optional[Sequence[float]] = None) -> Dict[str, List[Tuple[str, float, int]]]:
    """Mots étiquetés BIO → {champ: [(texte, score moyen, indice du 1er mot)]}."""
    out: Dict[str, List[Tuple[str, float, int]]] = {c: [] for c in CHAMPS}
    cur, txt, sc, debut = None, [], [], 0
    probas = probas if probas is not None else [1.0] * len(mots)

    def fermer():
        if cur:
            out[cur].append((" ".join(txt), sum(sc) / len(sc), debut))

    for i, (m, e) in enumerate(zip(mots, etiquettes)):
        pre, _, ch = e.partition("-")
        if e == "O" or ch not in out:
            fermer(); cur, txt, sc = None, [], []
        elif pre == "B" or ch != cur:
            fermer(); cur, txt, sc, debut = ch, [m], [probas[i]], i
        else:
            txt.append(m); sc.append(probas[i])
    fermer()
    return out


def valeur(champ: str, texte: str):
    if champ in MONTANTS:
        return lire_montant(texte)
    if champ == "DATE":
        d = lire_date(texte)
        return d.isoformat() if d else None
    if champ == "NUMERO":
        return nettoyer_numero(texte) or None
    return texte.strip() or None


def decoder(pages: List[dict]) -> Dict[str, object]:
    """pages : [{mots, etiquettes, probas}] d'UN document → champs extraits.

    Pour chaque champ : le passage le plus sûr dont la valeur est lisible.
    Puis contrôle arithmétique (cohérence HT + TVA + timbre = TTC)."""
    cand: Dict[str, List[Tuple[float, object]]] = {c: [] for c in CHAMPS}
    for p in pages:
        for ch, lst in spans(p["mots"], p["etiquettes"], p.get("probas")).items():
            for texte, score, _ in lst:
                v = valeur(ch, texte)
                if v is not None:
                    cand[ch].append((score, v))
    res: Dict[str, object] = {}
    for ch in CHAMPS:
        cand[ch].sort(key=lambda t: -t[0])
        res[CLE[ch]] = cand[ch][0][1] if cand[ch] else None
    res["_candidats"] = {CLE[c]: [v for _, v in cand[c][:4]] for c in MONTANTS}
    res["_scores"] = {CLE[c]: round(cand[c][0][0], 3) for c in CHAMPS if cand[c]}
    return coherence(res)


# Seuils de confiance par champ, calibrés sur la validation croisée (sept. 2026).
#
# Sous le seuil, l'hybride abandonne le modèle et reprend la valeur des règles.
# Pour HT, TVA et TTC c'est perdant : les règles y sont à 22, 27 et 23 %, le
# modèle à 75, 76 et 60 %. Seuil 0 = on garde toujours le modèle dès qu'il a lu
# une valeur. Ailleurs la bascule à 0,5 fait gagner des points (numéro 86,2 →
# 87,4 ; date 88,6 → 90,9 ; timbre 83,6 → 86,6) : on la garde.
SEUILS_CONFIANCE = {
    "total_ht": 0.0,
    "total_tva": 0.0,
    "total_ttc": 0.0,
}
SEUIL_CONFIANCE = 0.5          # défaut pour les champs absents du tableau


def fusionner_avec_regles(lu: Dict[str, object], regles: Dict[str, object]) -> Dict[str, object]:
    """Hybride : le modèle quand il est sûr de lui, les règles sinon, puis
    l'arithmétique départage les montants (candidats des deux sources).

    `lu` : sortie de `decoder` ; `regles` : même schéma (voir `depuis_regles`)."""
    scores = lu.get("_scores") or {}
    h: Dict[str, object] = {}
    for k in CHAMPS_EVAL:
        m, r = lu.get(k), regles.get(k)
        if m is None or (r is not None and scores.get(k, 1.0) < SEUILS_CONFIANCE.get(k, SEUIL_CONFIANCE)):
            h[k] = r
        else:
            h[k] = m
    cand = {k: list(v) for k, v in (lu.get("_candidats") or {}).items()}
    for k in ("total_ht", "total_tva", "total_ttc"):
        if regles.get(k) is not None and lu.get(k) is None:
            cand.setdefault(k, []).append(regles[k])
    h["_candidats"] = cand
    h["_scores"] = scores
    return coherence(h)


def coherence(res: Dict[str, object], tol: float = 0.011) -> Dict[str, object]:
    """Choisit, parmi les candidats, la combinaison qui « tombe juste ».

    HT + TVA (+ timbre, + éventuels frais) ≈ TTC : si le montant le plus sûr du
    modèle ne respecte pas l'égalité mais qu'un autre candidat la respecte,
    on prend l'autre. Un net à payer manquant reprend le TTC."""
    c = res.get("_candidats") or {}
    hts = [x for x in [res.get("total_ht")] + c.get("total_ht", []) if x is not None]
    tvas = [x for x in [res.get("total_tva")] + c.get("total_tva", []) if x is not None]
    ttcs = [x for x in [res.get("total_ttc")] + c.get("total_ttc", []) if x is not None]
    timbre = res.get("timbre") or 0.0
    trouve = False
    for ht in dict.fromkeys(hts):
        for tva in dict.fromkeys(tvas):
            for ttc in dict.fromkeys(ttcs):
                if abs(ht + tva - ttc) < tol or abs(ht + tva + timbre - ttc) < tol:
                    res["total_ht"], res["total_tva"], res["total_ttc"] = ht, tva, ttc
                    trouve = True
                    break
            if trouve: break
        if trouve: break
    res["coherent"] = trouve
    if res.get("net_a_payer") is None and res.get("total_ttc") is not None:
        res["net_a_payer"] = res["total_ttc"]
    return res


# ── évaluation ──────────────────────────────────────────────────────────────
def juste(champ_cle: str, pred, vrai, devise: str = "TND") -> bool:
    if vrai is None:
        return pred is None or champ_cle in ("timbre",)
    if pred is None:
        return False
    if champ_cle in ("total_ht", "total_tva", "timbre", "total_ttc", "net_a_payer"):
        try:
            return abs(float(pred) - float(vrai)) < (0.006 if devise != "TND" else 0.0015)
        except (TypeError, ValueError):
            return False
    if champ_cle == "date":
        return str(pred)[:10] == str(vrai)[:10]
    if champ_cle == "numero":
        a, b = norm_id(str(pred)), norm_id(str(vrai))
        return a == b or (a.endswith(b) and len(a) - len(b) <= 2)
    # noms : au moins 60 % des mots du vrai nom retrouvés
    v = set(mots_nom(str(vrai))); p = set(mots_nom(str(pred)))
    return bool(v) and len(v & p) / len(v) >= 0.6


def depuis_regles(r: dict) -> dict:
    """Sortie de parse_invoice (règles actuelles) → même schéma que la vérité."""
    return {"numero": r.get("numero"), "date": r.get("date_facture"),
            "fournisseur": None, "client": r.get("tiers"),
            "total_ht": r.get("montant_ht"), "total_tva": r.get("montant_tva"),
            "timbre": r.get("timbre_fiscal"), "total_ttc": r.get("montant_ttc"),
            # « net » des règles = TTC + timbre ; la vérité = somme réellement due
            "net_a_payer": r.get("net_a_payer") if r.get("net_a_payer") is not None
            else r.get("montant_ttc")}


def evaluer(preds: Dict[str, dict], verite: Dict[str, dict]) -> Dict[str, Dict[str, float]]:
    """Taux de champs justes, par champ, sur les documents où le champ existe."""
    out = {}
    for k in CHAMPS_EVAL:
        docs = [d for d in verite if d in preds and verite[d].get(k) is not None]
        if not docs:
            continue
        ok = sum(juste(k, preds[d].get(k), verite[d][k], verite[d].get("devise") or "TND")
                 for d in docs)
        out[k] = {"justes": ok, "n": len(docs), "taux": round(100 * ok / len(docs), 1)}
    return out
