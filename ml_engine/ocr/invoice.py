"""
ml_engine/ocr/invoice.py
========================
Extraction STRUCTURÉE d'une facture à partir du texte OCR.

Passer de « voici du texte » à « voici une facture n° F-2026-118 du 12/03/2026,
14 250,000 DT TTC dont 2 275,000 DT de TVA » : c'est ce qui rend l'OCR
exploitable par le rapprochement ERP.

Méthode : règles linguistiques robustes (pas de LLM — déterministe, testable,
fonctionne hors-ligne) adaptées aux factures tunisiennes/françaises :
- montants au format « 1 234,567 » (3 décimales en Tunisie) ou « 1,234.56 » ;
- libellés variables (« Total TTC », « Net à payer », « Montant TTC »…) ;
- tolérance aux fautes OCR courantes (O↔0, l↔1, S↔5 dans les nombres) ;
- dates en jj/mm/aaaa, jj-mm-aa, « 12 mars 2026 ».

Chaque champ extrait porte un indicateur de confiance : un champ trouvé via un
libellé explicite est plus sûr qu'un champ déduit du plus gros montant trouvé.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

# ── Normalisation ───────────────────────────────────────────────────────────
_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "août": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12,
}

# Un montant : 1 234,567 · 1.234,56 · 14250.00 · 1 234
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
        # le séparateur décimal est le DERNIER rencontré
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # CONTEXTE MÉTIER : factures tunisiennes/françaises → la virgule est le
        # séparateur DÉCIMAL, et les montants portent 3 décimales (millimes).
        # « 330,000 » vaut donc 330.000 DT, pas 330 000.
        # La virgule n'est traitée comme séparateur de milliers que si le
        # format est manifestement anglo-saxon : plusieurs virgules
        # (« 1,234,567 ») ou une virgule suivie d'un point décimal.
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


# ── Structure de sortie ─────────────────────────────────────────────────────
@dataclass
class InvoiceFields:
    """Champs d'une facture extraits du texte OCR."""
    numero: Optional[str] = None
    date_facture: Optional[str] = None       # ISO
    date_echeance: Optional[str] = None      # ISO
    montant_ht: Optional[float] = None
    montant_tva: Optional[float] = None
    montant_ttc: Optional[float] = None
    taux_tva: Optional[float] = None         # taux affiché (19, 13, 7…) — contrôle croisé
    timbre_fiscal: Optional[float] = None    # spécificité tunisienne, hors HT+TVA
    net_a_payer: Optional[float] = None      # TTC + timbre = montant réellement dû
    devise: str = "TND"
    tiers: Optional[str] = None              # client ou fournisseur détecté
    # Les deux parties, séparées (LayoutLMv3 les distingue) : c'est ce qui
    # permet de savoir si la facture est un achat ou une vente (entreprise.py).
    fournisseur: Optional[str] = None
    client: Optional[str] = None
    matricule_fiscal: Optional[str] = None
    # "explicite" (libellé trouvé) | "calcule" | "deduit" | "corrige"
    champs_confiance: Dict[str, str] = field(default_factory=dict)
    coherence: Optional[str] = None          # contrôle HT + TVA ≈ TTC
    avertissements: List[str] = field(default_factory=list)
    is_invoice: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Détection des libellés ──────────────────────────────────────────────────
# Mots de COLONNE : leur présence signale un en-tête de tableau, pas un total.
_MOTS_ENTETE = (r"d[ée]signation", r"\bqt[ée]\b", r"\bquantit[ée]\b", r"\bp\.?\s?u\b",
                r"prix\s*unitaire", r"\bref\b", r"\bcode\b", r"\btaux\b", r"\barticle\b")


def _est_entete_de_tableau(ligne: str) -> bool:
    """Vrai si la ligne est un en-tête de colonnes plutôt qu'un libellé de total.

    C'est LA cause du défaut constaté sur la facture Forevermo : l'en-tête
    « DÉSIGNATION | QTÉ | TVA % | P.U. HT | TOTAL HT » contient à la fois
    « TVA » et « HT ». Les deux recherches y répondaient, puis prenaient le
    montant de la première ligne d'article — d'où un HT et une TVA **identiques**
    (6 300,000 chacun) au lieu de 10 000,000 et 1 900,000.
    """
    low = ligne.lower()
    if sum(1 for p in _MOTS_ENTETE if re.search(p, low)) >= 1 and not re.search(r"\d", low):
        return True
    # Deux familles de libellés de montant sur une même ligne sans chiffre :
    # c'est une ligne de titres de colonnes.
    familles = sum(1 for groupe in (_P_TTC, _P_HT, _P_TVA)
                   if any(re.search(p, low) for p in groupe))
    return familles >= 2 and not re.search(_AMOUNT_RE, ligne)


def _find_labeled_amount(text: str, patterns: List[str]) -> Optional[Tuple[float, str]]:
    """Cherche le montant associé à un libellé.

    Trois dispositions rencontrées en OCR de facture :
      1. « Total HT   12 000,000 »            → même ligne ;
      2. « Total HT » / « 12 000,000 »        → ligne suivante ;
      3. « Total HT » / «  » / « 12 000,000 » → Tesseract insère une ligne vide
         quand les colonnes sont éloignées (cas très fréquent).
    On explore donc jusqu'à 3 lignes en aval, en ignorant les lignes vides,
    et on s'arrête dès qu'une ligne contient un AUTRE libellé (pour ne pas
    attribuer à « Total HT » le montant de la ligne « TVA »).

    Le parcours se fait EN REMONTANT depuis le bas : le bloc des totaux se
    trouve après le tableau des articles, et c'est lui qui fait foi.
    """
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
            # 1) même ligne : dernier montant (colonne de droite)
            found = re.findall(_AMOUNT_RE, line)
            if found:
                v = parse_amount(found[-1])
                if v is not None:
                    return v, "explicite"
            # 2-3) lignes suivantes, en sautant les vides
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j]
                if not nxt.strip():
                    continue
                # stop si on tombe sur un autre libellé de montant
                if any(re.search(p, nxt.lower()) for p in all_labels
                       if p not in patterns):
                    break
                found = re.findall(_AMOUNT_RE, nxt)
                if found:
                    v = parse_amount(found[-1])
                    if v is not None:
                        return v, "explicite"
                break   # première ligne non vide sans montant → on abandonne
    return None


def _detect_taux_tva(text: str) -> Optional[float]:
    """Taux de TVA affiché (19 %, 13 %, 7 %…), utilisé comme contrôle croisé.

    Le taux permet de vérifier — et au besoin de reconstruire — la TVA à partir
    du HT, sans dépendre d'une seule lecture OCR."""
    taux = [float(m.group(1).replace(",", "."))
            for m in re.finditer(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text)]
    # Taux de TVA plausibles en Tunisie : 7, 13, 19 (et 0 pour les exonérés).
    plausibles = [t for t in taux if 0 < t <= 30]
    if not plausibles:
        return None
    return max(set(plausibles), key=plausibles.count)


def _detect_timbre(text: str) -> Optional[float]:
    """Timbre fiscal — spécificité tunisienne, absent des factures européennes.

    Il n'entre PAS dans le calcul HT + TVA = TTC, mais s'ajoute au TTC pour
    former le net à payer. Ne pas l'extraire faisait apparaître un écart d'un
    dinar entre le TTC lu et le montant réellement dû."""
    for m in re.finditer(r"timbre[^\n]{0,30}", text, flags=re.IGNORECASE):
        found = re.findall(_AMOUNT_RE, m.group(0))
        if found:
            v = parse_amount(found[-1])
            if v is not None and 0 < v <= 50:      # le timbre est de l'ordre du dinar
                return v
    return None


# « Net à payer » N'EST PAS le TTC : en Tunisie il vaut TTC + timbre fiscal.
# Les confondre décalait le TTC d'un dinar (11 901 au lieu de 11 900) et faisait
# échouer le contrôle HT + TVA = TTC. Les deux libellés sont donc distincts, et
# le net sert de repli au TTC seulement si aucun total TTC n'est trouvé.
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
            # éviter de capturer une date ou un simple nombre de 4 chiffres
            if parse_date(num) is None and not re.fullmatch(r"\d{1,4}", num):
                return num.upper()
    return None


def _detect_tiers(text: str) -> Optional[str]:
    """Nom du client/fournisseur : ligne qui suit « Client », « Doit », « Facturé à »."""
    lines = [l.strip() for l in text.split("\n")]
    # « facturer à » couvre la variante rencontrée en OCR (« FACTURER A »), que
    # « facturé à » seul ne reconnaissait pas — le tiers restait alors vide.
    labels = [r"^client\b", r"^doit\b", r"^factur[éeé]?[re]?\s*[àa]\b",
              r"^destinataire\b", r"^fournisseur\b", r"^bill\s*to\b", r"^adress[ée]\s*[àa]\b"]
    for i, line in enumerate(lines):
        low = line.lower()
        for pat in labels:
            if not re.search(pat, low):
                continue
            # nom sur la même ligne après « : », sinon sur les lignes suivantes
            after = re.sub(r"^[^:]*:\s*", "", line).strip()
            candidats = [after] if (len(after) > 2 and after.lower() != low) else []
            candidats += [l for l in lines[i + 1:i + 4]]
            for cand in candidats:
                # Le bloc « facturé à » commence souvent par un code compte
                # (« 184707  ling and consulting ») : on le retire pour ne
                # garder que la raison sociale.
                cand = re.sub(r"^\s*\d{3,10}\s+", "", cand or "").strip(" .:-|")
                if not cand or re.fullmatch(r"[\d\s.,/-]+", cand):
                    continue
                # Une ligne d'adresse ou un libellé de montant n'est pas un nom.
                if re.search(r"\b(rue|avenue|tel|t[ée]l|fax|code postal|tva|ht\b|ttc)\b",
                             cand, flags=re.IGNORECASE):
                    continue
                if 2 < len(cand) < 80:
                    return cand
    return None


def _detect_mf(text: str) -> Optional[str]:
    """Matricule fiscal tunisien : 7 chiffres + lettres (ex. 1234567/A/M/000)."""
    m = re.search(r"\b(\d{7}\s*[/\-]?\s*[A-Z]\s*[/\-]?\s*[A-Z]\s*[/\-]?\s*\d{3})\b",
                  text.upper())
    if m:
        return re.sub(r"\s+", "", m.group(1))
    m = re.search(r"(?:matricule\s*fiscal|m\.?f\.?)\s*[:.\-]?\s*([A-Z0-9/\-]{6,20})",
                  text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def _reconcilier_montants(inv: "InvoiceFields") -> None:
    """Rend les trois montants mutuellement cohérents.

    Une facture obéit à deux identités vérifiables :
        HT + TVA = TTC          et, si un taux est affiché,   TVA = HT × taux

    L'OCR se trompe rarement sur les trois montants à la fois. On complète donc
    ce qui manque, puis — si le trio reste incohérent — on détermine QUEL
    montant est fautif en cherchant lequel des trois, une fois recalculé depuis
    les deux autres, satisfait le taux affiché. C'est cette étape qui manquait :
    l'ancienne version se contentait de signaler l'écart sans jamais chercher
    d'où il venait.
    """
    ht, tva, ttc, taux = (inv.montant_ht, inv.montant_tva,
                          inv.montant_ttc, inv.taux_tva)

    # 1) Complétion des trous par les identités.
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

    # 2) Arbitrage si le trio est incohérent ET qu'un taux est affiché.
    if None not in (ht, tva, ttc) and taux:
        tol = max(0.05, (ttc or 0) * 0.01)
        if abs((ht + tva) - ttc) > tol:
            attendu = taux / 100
            # Trois hypothèses : un seul des trois montants est mal lu.
            candidats = [
                ("montant_ht", round(ttc - tva, 3), tva, ttc),
                ("montant_tva", ht, round(ht * attendu, 3), ttc),
                ("montant_ttc", ht, tva, round(ht + tva, 3)),
            ]
            # On retient l'hypothèse dont le taux implicite colle au taux affiché.
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

    # 3) Net à payer = TTC + timbre fiscal (usage tunisien), s'il n'a pas déjà
    #    été lu explicitement sur la facture.
    if inv.net_a_payer is None and ttc is not None:
        inv.net_a_payer = round(ttc + (inv.timbre_fiscal or 0), 3)


# ── API publique ────────────────────────────────────────────────────────────
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

    # ── Montants ──
    for name, pats in (("montant_ttc", _P_TTC), ("montant_ht", _P_HT),
                       ("montant_tva", _P_TVA)):
        hit = _find_labeled_amount(text, pats)
        if hit:
            setattr(inv, name, hit[0])
            inv.champs_confiance[name] = hit[1]

    # Une TVA ne peut pas égaler le HT (cela supposerait un taux de 100 %).
    # Symptôme classique d'un même nombre capté deux fois : on écarte la TVA,
    # que la réconciliation ci-dessous reconstruira.
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
    # Facture sans ligne « Total TTC » : le net à payer en tient lieu, timbre déduit.
    if inv.montant_ttc is None and inv.net_a_payer is not None:
        inv.montant_ttc = round(inv.net_a_payer - (inv.timbre_fiscal or 0), 3)
        inv.champs_confiance["montant_ttc"] = "calcule"

    # TTC manquant → repli sur le plus gros montant du document (déduit)
    if inv.montant_ttc is None:
        amounts = [a for a in (parse_amount(m) for m in re.findall(_AMOUNT_RE, text))
                   if a is not None and a > 0]
        # on écarte les valeurs qui ressemblent à des années ou des quantités
        amounts = [a for a in amounts if not (1900 < a < 2100 and float(a).is_integer())]
        if amounts:
            inv.montant_ttc = max(amounts)
            inv.champs_confiance["montant_ttc"] = "deduit"

    _reconcilier_montants(inv)

    # ── Dates ──
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
    if inv.date_facture is None:                       # repli : 1re date du document
        for line in lines:
            d = parse_date(line)
            if d:
                inv.date_facture = d.isoformat()
                inv.champs_confiance["date_facture"] = "deduit"
                break

    # ── Contrôle de cohérence (signal de qualité pour l'utilisateur) ──
    if inv.montant_ht and inv.montant_tva and inv.montant_ttc:
        ecart = abs((inv.montant_ht + inv.montant_tva) - inv.montant_ttc)
        tol = max(0.05, inv.montant_ttc * 0.01)
        inv.coherence = ("HT + TVA = TTC vérifié" if ecart <= tol else
                         f"Incohérence : HT + TVA = {inv.montant_ht + inv.montant_tva:.3f} "
                         f"≠ TTC {inv.montant_ttc:.3f} (écart {ecart:.3f}) — "
                         "OCR à vérifier manuellement")
    return inv
