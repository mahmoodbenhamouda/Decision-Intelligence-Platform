"""
ml_engine/ocr/layoutlm/extracteur.py
====================================
Extraction de factures par LayoutLMv3 affiné — branchée en **complément** des
règles (`parse_invoice`), jamais à leur place :

    1. mots + boîtes du document (texte PDF exact, ou OCR renforcé) ;
    2. LayoutLMv3 étiquette chaque mot (numéro, date, HT, TVA, TTC, net…) ;
    3. les règles comblent les champs que le modèle n'a pas trouvés ;
    4. le contrôle arithmétique (HT + TVA + timbre = TTC) tranche entre
       les candidats.

Le modèle est optionnel : s'il n'est pas installé (`models/layoutlmv3_factures/`
absent, ou `transformers` non installé), la plateforme continue avec les règles
seules — rien ne casse.

Emplacement du modèle : variable `OVERLYNE_LAYOUTLM_DIR`, sinon
`<projet>/models/layoutlmv3_factures/` (dossier produit par le carnet Colab).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .champs import decoder, depuis_regles, fusionner_avec_regles

_RACINE = Path(__file__).resolve().parents[3]
_VERROU = threading.Lock()
_MODELE: Dict[str, Any] = {}


def dossier_modele() -> Path:
    return Path(os.environ.get("OVERLYNE_LAYOUTLM_DIR",
                               _RACINE / "models" / "layoutlmv3_factures"))


def disponible() -> bool:
    """Le modèle affiné est-il présent ET utilisable sur ce serveur ?"""
    d = dossier_modele()
    if not (d / "config.json").exists():
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _charger():
    with _VERROU:
        if "modele" not in _MODELE:
            from transformers import AutoProcessor, LayoutLMv3ForTokenClassification
            d = str(dossier_modele())
            _MODELE["processor"] = AutoProcessor.from_pretrained(d, apply_ocr=False)
            m = LayoutLMv3ForTokenClassification.from_pretrained(d)
            m.eval()
            _MODELE["modele"] = m
    return _MODELE["processor"], _MODELE["modele"]


def _predire_page(image, mots: List[dict]) -> dict:
    import numpy as np
    import torch
    from .mots import boites_normalisees

    processor, modele = _charger()
    id2label = modele.config.id2label
    textes = [m["t"] for m in mots]
    if not textes:
        return {"mots": [], "etiquettes": [], "probas": []}
    boites = boites_normalisees(mots, image.width, image.height)
    enc = processor(image, textes, boxes=boites, truncation=True, padding="max_length",
                    max_length=512, stride=128, return_overflowing_tokens=True,
                    return_offsets_mapping=True, return_tensors="pt")
    enc.pop("offset_mapping", None)
    n = enc["input_ids"].shape[0]
    pv = enc["pixel_values"]
    if isinstance(pv, list):
        pv = torch.stack(pv)
    if pv.shape[0] != n:
        pv = pv[enc["overflow_to_sample_mapping"]]
    somme = np.zeros((len(textes), len(id2label)))
    vu = np.zeros(len(textes))
    with torch.no_grad():
        for i in range(n):
            logits = modele(input_ids=enc["input_ids"][i:i + 1],
                            attention_mask=enc["attention_mask"][i:i + 1],
                            bbox=enc["bbox"][i:i + 1], pixel_values=pv[i:i + 1]).logits
            pr = torch.softmax(logits[0].float(), -1).numpy()
            deja = set()
            for t, w in enumerate(enc.word_ids(i)):
                if w is not None and w not in deja:
                    deja.add(w)
                    somme[w] += pr[t]
                    vu[w] += 1
    pr = somme / np.maximum(vu, 1)[:, None]
    return {"mots": textes,
            "etiquettes": [id2label[int(i)] for i in pr.argmax(1)],
            "probas": pr.max(1).tolist()}


def extraire(content: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """Champs lus par LayoutLMv3 (schéma : numero, date, total_ht, total_tva,
    timbre, total_ttc, net_a_payer, fournisseur, client) ou None si indisponible."""
    if not disponible():
        return None
    from .mots import pages_du_document
    return decoder([_predire_page(im, mots) for im, mots, _ in pages_du_document(content, filename)])


def lire_facture(content: bytes, filename: str):
    """Lecture complète d'une facture → (OCRResult, InvoiceFields, moteur).

    Modèle installé : UNE seule lecture du document (OCR renforcé ou texte PDF
    exact) sert à la fois aux règles et à LayoutLMv3, puis fusion.
    Sinon : chaîne historique `ocr_document` + `parse_invoice`.
    """
    from ml_engine.ocr.engine import OCRResult, clean_text, ocr_document
    from ml_engine.ocr.invoice import parse_invoice

    if not disponible():
        res = ocr_document(content, filename)
        return res, parse_invoice(res.text), "regles"
    try:
        from .mots import pages_du_document, texte_par_lignes
        pages = pages_du_document(content, filename)
        texte = clean_text("\n\n".join(texte_par_lignes(m) for _, m, _ in pages))
        confs = [w["c"] for _, m, _ in pages for w in m if "c" in w]
        natif = all(src == "pdf-texte" for _, _, src in pages)
        res = OCRResult(text=texte, confidence=sum(confs) / len(confs) if confs else 0.0,
                        source="pdf-texte" if natif else
                        ("pdf-ocr" if filename.lower().endswith(".pdf") else "image-ocr"),
                        pages=len(pages), engine="texte PDF" if natif else "tesseract multi-passes")
        fields = parse_invoice(texte)
        lu = decoder([_predire_page(im, mots) for im, mots, _ in pages])
        return res, combiner(fields, lu), "layoutlmv3+regles"
    except Exception as e:                      # jamais bloquant : repli sur l'historique
        res = ocr_document(content, filename)
        fields = parse_invoice(res.text)
        fields.avertissements.append(f"LayoutLMv3 indisponible ({e}) : règles seules.")
        return res, fields, "regles"


# Correspondance schéma LayoutLMv3 → InvoiceFields (règles)
_VERS_REGLES = {"numero": "numero", "date": "date_facture", "total_ht": "montant_ht",
                "total_tva": "montant_tva", "timbre": "timbre_fiscal",
                "total_ttc": "montant_ttc", "net_a_payer": "net_a_payer"}


def combiner(fields, lu: Optional[Dict[str, Any]]):
    """Fusionne la lecture LayoutLMv3 dans un `InvoiceFields` issu des règles.

    Le modèle l'emporte quand il est sûr de lui ; les règles gardent les autres
    champs ; l'arithmétique départage les montants. Modifie et renvoie `fields`.
    """
    if not lu:
        return fields
    h = fusionner_avec_regles(lu, depuis_regles(fields.to_dict()))
    for cle, attr in _VERS_REGLES.items():
        v = h.get(cle)
        if v is not None and v != getattr(fields, attr):
            setattr(fields, attr, v)
            fields.champs_confiance[attr] = "layoutlmv3"
    for cle, v in h.get("_rejetes") or []:
        attr = _VERS_REGLES.get(cle)
        if attr and getattr(fields, attr) == v:   # la valeur absurde venait des règles : on l'efface
            setattr(fields, attr, None)
            fields.champs_confiance[attr] = "ecarte"
        montant = f"{float(v):,.3f}".replace(",", " ").replace(".", ",")
        fields.avertissements.append(
            f"{cle} : {montant} lu par les règles, écarté comme invraisemblable "
            f"face aux autres montants — à saisir.")
    if h.get("coherent"):
        fields.coherence = "ok"
    if lu.get("fournisseur") and not fields.tiers:
        fields.tiers = lu["fournisseur"]
    fields.is_invoice = fields.is_invoice or bool(h.get("total_ttc") or h.get("numero"))
    return fields
