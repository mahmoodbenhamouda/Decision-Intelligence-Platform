"""Extraction STRUCTURÉE d'une facture à partir du texte OCR."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

_AMOUNT_RE = r"(?<![\w.,])(\d{1,3}(?:[ . ]\d{3})+(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)(?![\w])"

_CURRENCIES = {
    "DT": "TND", "TND": "TND", "DINAR": "TND", "DINARS": "TND", "MILLIME": "TND",
    "€": "EUR", "EUR": "EUR", "EURO": "EUR", "EUROS": "EUR",
    "$": "USD", "USD": "USD", "DOLLAR": "USD",
}


def _fix_ocr_digits(s: str) -> str:
    """Corrige les confusions OCR classiques DANS un nombre (O→0, l/I→1, S→5)."""
    return (s.replace("O", "0").replace("o", "0")
             .replace("l", "1").replace("I", "1").replace("|", "1")
             .replace("S", "5").replace("B", "8"))


def parse_amount(raw: str) -> Optional[float]:
    """« 1 234,567 » → 1234.567 ; « 1,234.56 » → 1234.56 ; robuste OCR."""
    if not raw:
        return None
    s = _fix_ocr_digits(raw.strip()).replace(" ", " ")
    s = re.sub(r"[^\d.,\- ]", "", s).strip()
    if not s:
        return None
    s = s.replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = (s.replace(",", "") if s.count(",") > 1 else s.replace(",", "."))
    try:
        v = float(s)
        return v if -1e12 < v < 1e12 else None
    except ValueError:
        return None


def parse_date(raw: str) -> Optional[date]:
    """Reconnaît jj/mm/aaaa, jj-mm-aa, aaaa-mm-jj et « 12 mars 2026 »."""
    if not raw:
        return None
    s = raw.strip().lower().replace(" ", " ")
    m = re.search(r"(\d{1,2})\s+([a-zéèûôA-Z]+)\s+(\d{4})", s)
    if m and m.group(2) in _MONTHS:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


@dataclass
class InvoiceFields:
    """Champs d'une facture extraits du texte OCR."""
    numero: Optional[str] = None
    date_facture: Optional[str] = None
    date_echeance: Optional[str] = None
    montant_ht: Optional[float] = None
    montant_tva: Optional[float] = None
    montant_ttc: Optional[float] = None
    taux_tva: Optional[float] = None
    timbre_fiscal: Optional[float] = None
    net_a_payer: Optional[float] = None
    devise: str = "TND"
    tiers: Optional[str] = None
    fournisseur: Optional[str] = None
    client: Optional[str] = None
    matricule_fiscal: Optional[str] = None
    champs_confiance: Dict[str, str] = field(default_factory=dict)
    coherence: Optional[str] = None
    avertissements: List[str] = field(default_factory=list)
    is_invoice: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_MOTS_ENTETE = (r"d[ée]signation", r"\bqt[ée]\b", r"\bquantit[ée]\b", r"\bp\.?\s?u\b",
                r"prix\s*unitaire", r"\bref\b", r"\bcode\b", r"\btaux\b", r"\barticle\b")


def _est_entete_de_tableau(ligne: str) -> bool:
    """Vrai si la ligne est un en-tête de colonnes plutôt qu'un libellé de total."""
    low = ligne.lower()
    if sum(1 for p in _MOTS_ENTETE if re.search(p, low)) >= 1 and not re.search(r"\d", low):
        return True
    familles = sum(1 for groupe in (_P_TTC, _P_HT, _P_TVA)
                   if any(re.search(p, low) for p in groupe))
    return familles >= 2 and not re.search(_AMOUNT_RE, ligne)


def _find_labeled_amount(text: str, patterns: List[str]) -> Optional[Tuple[float, str]]:
    """Cherche le montant associé à un libellé."""
    lines = text.split("\n")
    all_labels = _P_TTC + _P_HT + _P_TVA + _P_NET
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        low = line.lower()
        if _est_entete_de_tableau(line):
            continue
        for pat in patterns:
            if not re.search(pat, low):
                continue
            found = re.findall(_AMOUNT_RE, line)
            if found:
                v = parse_amount(found[-1])
                if v is not None:
                    return v, "explicite"
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j]
                if not nxt.strip():
                    continue
                if any(re.search(p, nxt.lower()) for p in all_labels
                       if p not in patterns):
                    break
                found = re.findall(_AMOUNT_RE, nxt)
                if found:
                    v = parse_amount(found[-1])
                    if v is not None:
                        return v, "explicite"
                break
    return None


def _detect_taux_tva(text: str) -> Optional[float]:
    """Taux de TVA affiché (19 %, 13 %, 7 %…), utilisé comme contrôle croisé."""
    taux = [float(m.group(1).replace(",", "."))
            for m in re.finditer(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text)]
    plausibles = [t for t in taux if 0 < t <= 30]
    if not plausibles:
        return None
    return max(set(plausibles), key=plausibles.count)


def _detect_timbre(text: str) -> Optional[float]:
    """Timbre fiscal — spécificité tunisienne, absent des factures européennes."""
    for m in re.finditer(r"timbre[^\n]{0,30}", text, flags=re.IGNORECASE):
        found = re.findall(_AMOUNT_RE, m.group(0))
        if found:
            v = parse_amount(found[-1])
            if v is not None and 0 < v <= 50:
                return v
    return None


_P_TTC = [r"\bmontant\s*t\.?t\.?c\b", r"\btotal\s*t\.?t\.?c\b",
          r"\btotal\s*g[ée]n[ée]ral\b", r"\bt\.?t\.?c\b.*\btotal\b", r"\btotal\s*ttc\b"]
_P_NET = [r"\bnet\s*[àa]\s*payer\b", r"\bnet\s*a\s*payer\b", r"\b[àa]\s*payer\b"]
_P_HT = [r"\bmontant\s*h\.?t\b", r"\btotal\s*h\.?t\b", r"\bbase\s*h\.?t\b",
         r"\btotal\s*hors\s*taxe", r"\bh\.?t\.?\s*net\b"]
_P_TVA = [r"\bt\.?v\.?a\b", r"\btaxe\s*sur\s*la\s*valeur", r"\bmontant\s*tva\b"]


def _detect_currency(text: str) -> str:
    up = text.upper()
    for token, code in _CURRENCIES.items():
        if re.search(rf"(?<![A-Z]){re.escape(token)}(?![A-Z])", up):
            return code
    return "TND"


def _detect_numero(text: str) -> Optional[str]:
    """N° de facture : « Facture N° F-2026-118 », « FACT 2026/0042 »…"""
    pats = [
        r"factur[ea]?\s*(?:n[°ºo]?|num[ée]ro|no)?\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-/_.]{2,24})",
        r"\bn[°ºo]\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-/_.]{2,24})",
        r"\binvoice\s*(?:no|n[°º]|number)?\s*[:.\-]?\s*([A-Z0-9][A-Z0-9\-/_.]{2,24})",
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            num = m.group(1).strip(" .:-/")
            if parse_date(num) is None and not re.fullmatch(r"\d{1,4}", num):
                return num.upper()
    return None


def _detect_tiers(text: str) -> Optional[str]:
    """Nom du client/fournisseur : ligne qui suit « Client », « Doit », « Facturé à »."""
    lines = [l.strip() for l in text.split("\n")]
    labels = [r"^client\b", r"^doit\b", r"^factur[éeé]?[re]?\s*[àa]\b",
              r"^destinataire\b", r"^fournisseur\b", r"^bill\s*to\b", r"^adress[ée]\s*[àa]\b"]
    for i, line in enumerate(lines):
        low = line.lower()
        for pat in labels:
            if not re.search(pat, low):
                continue
            after = re.sub(r"^[^:]*:\s*", "", line).strip()
            candidats = [after] if (len(after) > 2 and after.lower() != low) else []
            candidats += [l for l in lines[i + 1:i + 4]]
            for cand in candidats:
                cand = re.sub(r"^\s*\d{3,10}\s+", "", cand or "").strip(" .:-|")
                if not cand or re.fullmatch(r"[\d\s.,/-]+", cand):
                    continue
                if re.search(r"\b(rue|avenue|tel|t[ée]l|fax|code postal|tva|ht\b|ttc)\b",
                             cand, flags=re.IGNORECASE):
                    continue
                if 2 < len(cand) < 80:
                    return cand
    return None


def _detect_mf(text: str) -> Optional[str]:
    """Matricule fiscal tunisien : 7 chiffres + lettres (ex."""
    m = re.search(r"\b(\d{7}\s*[/\-]?\s*[A-Z]\s*[/\-]?\s*[A-Z]\s*[/\-]?\s*\d{3})\b",
                  text.upper())
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = re.search(r"(?:matricule\s*fiscal|m\.?f\.?)\s*[:.\-]?\s*([A-Z0-9/\-]{6,20})",
                  text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _reconcilier_montants(inv: "InvoiceFields") -> None:
    """Rend les trois montants mutuellement cohérents."""
    ht, tva, ttc, taux = (inv.montant_ht, inv.montant_tva,
                          inv.montant_ttc, inv.taux_tva)

    if ht is None and ttc is not None and tva is not None:
        ht, inv.champs_confiance["montant_ht"] = round(ttc - tva, 3), "calcule"
    if tva is None and ttc is not None and ht is not None:
        tva, inv.champs_confiance["montant_tva"] = round(ttc - ht, 3), "calcule"
    if tva is None and ht is not None and taux:
        tva, inv.champs_confiance["montant_tva"] = round(ht * taux / 100, 3), "calcule"
    if ttc is None and ht is not None and tva is not None:
        ttc, inv.champs_confiance["montant_ttc"] = round(ht + tva, 3), "calcule"
    if ht is None and ttc is not None and taux:
        ht, inv.champs_confiance["montant_ht"] = round(ttc / (1 + taux / 100), 3), "calcule"
        tva, inv.champs_confiance["montant_tva"] = round(ttc - ht, 3), "calcule"

    if None not in (ht, tva, ttc) and taux:
        tol = max(0.05, (ttc or 0) * 0.01)
        if abs((ht + tva) - ttc) > tol:
            attendu = taux / 100
            candidats = [
                ("montant_ht", round(ttc - tva, 3), tva, ttc),
                ("montant_tva", ht, round(ht * attendu, 3), ttc),
                ("montant_ttc", ht, tva, round(ht + tva, 3)),
            ]
            best, ecart_min = None, None
            for champ, h, t, c in candidats:
                if h is None or h <= 0:
                    continue
                ecart = abs((t / h) - attendu)
                if ecart_min is None or ecart < ecart_min:
                    best, ecart_min = (champ, h, t, c), ecart
            if best and ecart_min is not None and ecart_min < 0.01:
                champ, ht, tva, ttc = best
                inv.champs_confiance[champ] = "corrige"
                inv.avertissements.append(
                    f"{champ.replace('montant_', '').upper()} recalculé : la valeur lue "
                    f"contredisait le taux de TVA de {taux:g} % affiché sur la facture.")

    inv.montant_ht, inv.montant_tva, inv.montant_ttc = ht, tva, ttc

    if inv.net_a_payer is None and ttc is not None:
        inv.net_a_payer = round(ttc + (inv.timbre_fiscal or 0), 3)


INVOICE_HINTS = ("facture", "invoice", "net à payer", "net a payer", "tva",
                 "total ttc", "montant ttc", "doit", "bon de livraison")


def parse_invoice(text: str) -> InvoiceFields:
    """Texte OCR → champs structurés + contrôle de cohérence HT + TVA ≈ TTC."""
    inv = InvoiceFields()
    if not text or not text.strip():
        return inv

    low = text.lower()
    inv.is_invoice = sum(1 for h in INVOICE_HINTS if h in low) >= 2
    inv.devise = _detect_currency(text)
    inv.numero = _detect_numero(text)
    inv.tiers = _detect_tiers(text)
    inv.matricule_fiscal = _detect_mf(text)

    for name, pats in (("montant_ttc", _P_TTC), ("montant_ht", _P_HT),
                       ("montant_tva", _P_TVA)):
        hit = _find_labeled_amount(text, pats)
        if hit:
            setattr(inv, name, hit[0])
            inv.champs_confiance[name] = hit[1]

    if (inv.montant_tva is not None and inv.montant_ht is not None
            and abs(inv.montant_tva - inv.montant_ht) < 0.001):
        inv.montant_tva = None
        inv.champs_confiance.pop("montant_tva", None)
        inv.avertissements.append(
            "TVA identique au HT (lecture ambiguë) — recalculée depuis le taux.")

    inv.taux_tva = _detect_taux_tva(text)
    inv.timbre_fiscal = _detect_timbre(text)
    hit_net = _find_labeled_amount(text, _P_NET)
    if hit_net:
        inv.net_a_payer = hit_net[0]
    if inv.montant_ttc is None and inv.net_a_payer is not None:
        inv.montant_ttc = round(inv.net_a_payer - (inv.timbre_fiscal or 0), 3)
        inv.champs_confiance["montant_ttc"] = "calcule"

    if inv.montant_ttc is None:
        amounts = [a for a in (parse_amount(m) for m in re.findall(_AMOUNT_RE, text))
                   if a is not None and a > 0]
        amounts = [a for a in amounts if not (1900 < a < 2100 and float(a).is_integer())]
        if amounts:
            inv.montant_ttc = max(amounts)
            inv.champs_confiance["montant_ttc"] = "deduit"

    _reconcilier_montants(inv)

    lines = text.split("\n")
    for i, line in enumerate(lines):
        low_l = line.lower()
        if inv.date_echeance is None and re.search(r"[ée]ch[ée]ance|due\s*date|payable", low_l):
            d = parse_date(line) or (parse_date(lines[i + 1]) if i + 1 < len(lines) else None)
            if d:
                inv.date_echeance = d.isoformat()
                inv.champs_confiance["date_echeance"] = "explicite"
        if inv.date_facture is None and re.search(r"date|le\s+\d|du\s+\d", low_l) \
                and not re.search(r"[ée]ch[ée]ance", low_l):
            d = parse_date(line)
            if d:
                inv.date_facture = d.isoformat()
                inv.champs_confiance["date_facture"] = "explicite"
    if inv.date_facture is None:
        for line in lines:
            d = parse_date(line)
            if d:
                inv.date_facture = d.isoformat()
                inv.champs_confiance["date_facture"] = "deduit"
                break

    if inv.montant_ht and inv.montant_tva and inv.montant_ttc:
        ecart = abs((inv.montant_ht + inv.montant_tva) - inv.montant_ttc)
        tol = max(0.05, inv.montant_ttc * 0.01)
        inv.coherence = ("HT + TVA = TTC vérifié" if ecart <= tol else
                         f"Incohérence : HT + TVA = {inv.montant_ht + inv.montant_tva:.3f} "
                         f"≠ TTC {inv.montant_ttc:.3f} (écart {ecart:.3f}) — "
                         "OCR à vérifier manuellement")
    return inv
