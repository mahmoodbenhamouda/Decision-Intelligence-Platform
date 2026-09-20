"""
evaluation_ocr/preparation/5_mesurer.py
=======================================
Mesure hors Colab : regles / LayoutLMv3 / hybride sur le jeu annote.

    python evaluation_ocr/preparation/5_mesurer.py            # inference + mesure
    python evaluation_ocr/preparation/5_mesurer.py --rejouer  # mesure seule

Le premier passage enregistre les predictions brutes du modele dans
`evaluation_ocr/layoutlmv3/travail/predictions.json`. Le second les relit :
regler la fusion ne demande alors plus de relancer le modele (quelques
secondes au lieu de plusieurs minutes).

AVERTISSEMENT
-------------
Le modele final a ete entraine sur CES memes factures. Les taux affiches ici
sont donc optimistes : ils ne remplacent pas la validation croisee du carnet.
Ce qui reste comparable, c'est l'ecart entre deux strategies de fusion, les
deux partant des memes predictions.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))

ZIP = RACINE / "evaluation_ocr" / "layoutlmv3" / "layoutlmv3_factures.zip"
TRAVAIL = RACINE / "evaluation_ocr" / "layoutlmv3" / "travail"
PREDICTIONS = TRAVAIL / "predictions.json"

from ml_engine.ocr.layoutlm.champs import (CHAMPS_EVAL, decoder, depuis_regles,
                                           evaluer, fusionner_avec_regles)
from ml_engine.ocr.layoutlm.extracteur import dossier_modele


def charger_jeu():
    z = zipfile.ZipFile(ZIP)
    pages = [json.loads(l) for l in z.open("pages.jsonl").read().decode("utf-8").splitlines() if l.strip()]
    verite = json.loads(z.open("verite.json").read().decode("utf-8"))
    regles = json.loads(z.open("regles.json").read().decode("utf-8"))
    return z, pages, verite, regles


def inferer(z, pages):
    """Predictions du modele, page par page -> {doc: [{mots, etiquettes, probas}]}."""
    import io
    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoProcessor, LayoutLMv3ForTokenClassification

    d = str(dossier_modele())
    print(f"Modele : {d}")
    processor = AutoProcessor.from_pretrained(d, apply_ocr=False)
    modele = LayoutLMv3ForTokenClassification.from_pretrained(d)
    modele.eval()
    id2label = modele.config.id2label

    out = {}
    for i, pg in enumerate(pages, 1):
        mots, boites = pg["mots"], pg["boites"]
        if not mots:
            continue
        im = Image.open(io.BytesIO(z.open(pg["image"]).read())).convert("RGB")
        enc = processor(im, mots, boxes=boites, truncation=True, padding="max_length",
                        max_length=512, stride=128, return_overflowing_tokens=True,
                        return_offsets_mapping=True, return_tensors="pt")
        enc.pop("offset_mapping", None)
        n = enc["input_ids"].shape[0]
        pv = enc["pixel_values"]
        if isinstance(pv, list):
            pv = torch.stack(pv)
        if pv.shape[0] != n:
            pv = pv[enc["overflow_to_sample_mapping"]]
        somme = np.zeros((len(mots), len(id2label)))
        vu = np.zeros(len(mots))
        with torch.no_grad():
            for k in range(n):
                logits = modele(input_ids=enc["input_ids"][k:k + 1],
                                attention_mask=enc["attention_mask"][k:k + 1],
                                bbox=enc["bbox"][k:k + 1],
                                pixel_values=pv[k:k + 1]).logits
                pr = torch.softmax(logits[0].float(), -1).numpy()
                deja = set()
                for t, w in enumerate(enc.word_ids(k)):
                    if w is not None and w not in deja:
                        deja.add(w)
                        somme[w] += pr[t]
                        vu[w] += 1
        pr = somme / np.maximum(vu, 1)[:, None]
        out.setdefault(pg["doc"], []).append(
            {"mots": mots,
             "etiquettes": [id2label[int(x)] for x in pr.argmax(1)],
             "probas": [round(float(x), 4) for x in pr.max(1)]})
        print(f"  {i}/{len(pages)}  {pg['page']}", end="\r", flush=True)
    print()
    return out


def fusion_ancienne(lu, regles_champs):
    """Strategie d'avant le correctif : seuil 0,5 partout + candidats des regles."""
    from ml_engine.ocr.layoutlm.champs import coherence
    scores = lu.get("_scores") or {}
    h = {}
    for k in CHAMPS_EVAL:
        m, r = lu.get(k), regles_champs.get(k)
        if m is None or (r is not None and scores.get(k, 1.0) < 0.5):
            h[k] = r
        else:
            h[k] = m
    cand = {k: list(v) for k, v in (lu.get("_candidats") or {}).items()}
    for k in ("total_ht", "total_tva", "total_ttc"):
        if regles_champs.get(k) is not None:
            cand.setdefault(k, []).append(regles_champs[k])
    h["_candidats"], h["_scores"] = cand, scores
    return coherence(h)


def main():
    rejouer = "--rejouer" in sys.argv
    z, pages, verite, regles = charger_jeu()

    if rejouer:
        if not PREDICTIONS.exists():
            sys.exit("Aucune prediction enregistree : lancez d'abord sans --rejouer.")
        preds_brutes = json.loads(PREDICTIONS.read_text(encoding="utf-8"))
        print(f"Predictions relues : {PREDICTIONS} ({len(preds_brutes)} documents)")
    else:
        preds_brutes = inferer(z, pages)
        TRAVAIL.mkdir(parents=True, exist_ok=True)
        PREDICTIONS.write_text(json.dumps(preds_brutes, ensure_ascii=False), encoding="utf-8")
        print(f"Predictions enregistrees : {PREDICTIONS}")

    docs = [d for d in verite if d in preds_brutes]
    p_regles, p_modele, p_avant, p_apres = {}, {}, {}, {}
    for d in docs:
        lu = decoder(preds_brutes[d])
        rc = depuis_regles(regles[d]["production"])
        p_regles[d] = rc
        p_modele[d] = dict(lu)
        p_avant[d] = fusion_ancienne(dict(lu), dict(rc))
        p_apres[d] = fusionner_avec_regles(dict(lu), dict(rc))

    e_r = evaluer(p_regles, verite)
    e_m = evaluer(p_modele, verite)
    e_av = evaluer(p_avant, verite)
    e_ap = evaluer(p_apres, verite)

    print()
    print(f"{len(docs)} factures  —  taux de champs justes")
    print("=" * 74)
    print(f"{'champ':<14}{'regles':>10}{'modele':>10}{'hybr.avant':>13}{'hybr.apres':>13}{'ecart':>12}")
    print("-" * 74)
    for k in CHAMPS_EVAL:
        if k not in e_ap:
            continue
        av, ap = e_av[k]["taux"], e_ap[k]["taux"]
        d = ap - av
        signe = f"{d:+.1f}" if abs(d) >= 0.05 else "="
        print(f"{k:<14}{e_r.get(k, {}).get('taux', 0):>9.1f}%{e_m[k]['taux']:>9.1f}%"
              f"{av:>12.1f}%{ap:>12.1f}%{signe:>12}")
    print("=" * 74)
    print("Rappel : modele entraine sur ces factures -> taux optimistes.")
    print("Seule la colonne 'ecart' (meme modele, deux fusions) est fiable ici.")


if __name__ == "__main__":
    main()
