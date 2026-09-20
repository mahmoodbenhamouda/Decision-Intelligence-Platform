"""Étape 4 — génère evaluation_ocr/entrainement_layoutlmv3.ipynb (Google Colab, GPU T4)."""
import json, sys
import nbformat as nbf

nb = nbf.v4.new_notebook()
C = []
md = lambda s: C.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: C.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Overlyne — Extraction de factures avec LayoutLMv3

Ce carnet affine **LayoutLMv3** (Microsoft) pour lire les champs d'une facture :
numéro, date, fournisseur, client, total HT, TVA, timbre, TTC, net à payer.

**Pourquoi LayoutLMv3 ?** Les règles actuelles lisent le texte ligne par ligne.
LayoutLMv3 lit à la fois **le texte, sa position sur la page et l'image** : il
apprend qu'un montant en bas à droite, dans un cadre, à côté de « Net à payer »,
est le montant dû — même quand le libellé est mal lu ou placé ailleurs.

**Protocole honnête (89 factures seulement)** : validation croisée à 5 plis,
*regroupée par document* — le modèle n'est jamais évalué sur une facture vue à
l'entraînement. Option : regroupement *par fournisseur* (mise en page jamais vue).
Comparaison, sur la même vérité terrain, avec les règles actuelles.

**Avant de commencer** : `Exécution › Modifier le type d'exécution › GPU T4`.

> ⚠️ Données : factures de tiers. Ne partagez pas ce carnet exécuté ni le zip.
> Licence LayoutLMv3 : CC BY-NC-SA 4.0 — usage académique (PFE) autorisé,
> usage commercial non.
""")

code("""
!pip -q install "transformers>=4.44" seqeval accelerate
import torch, json, os, random, zipfile, numpy as np
print("GPU :", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "AUCUN — activez le GPU")
""")

md("## 1. Charger le jeu de données\nDéposez `layoutlmv3_factures.zip` (dossier `evaluation_ocr/layoutlmv3/` du projet).")
code("""
from google.colab import files
if not os.path.exists("layoutlmv3_factures.zip"):
    files.upload()
with zipfile.ZipFile("layoutlmv3_factures.zip") as z:
    z.extractall("data")
import sys; sys.path.insert(0, "data")
# SEUILS_CONFIANCE n'existe que dans le champs.py corrige : si le zip depose
# est perime, l'import echoue ici plutot qu'apres 45 minutes d'entrainement.
from champs import (ETIQUETTES, CHAMPS, CHAMPS_EVAL, decoder, evaluer, juste,
                    depuis_regles, fusionner_avec_regles, SEUILS_CONFIANCE)
PAGES = [json.loads(l) for l in open("data/pages.jsonl")]
VERITE = json.load(open("data/verite.json"))
REGLES = json.load(open("data/regles.json"))          # sortie des règles actuelles
COUVERTURE = json.load(open("data/projection_rapport.json"))
DOCS = sorted(VERITE)
L2I = {l: i for i, l in enumerate(ETIQUETTES)}
print(len(DOCS), "factures,", len(PAGES), "pages,", len(ETIQUETTES), "étiquettes")
print("fusion en vigueur :", SEUILS_CONFIANCE)
""")

md("""
## 2. Plafond de l'OCR
LayoutLMv3 **classe des mots** ; il ne peut pas inventer un chiffre que l'OCR n'a
pas lu. Ce tableau montre, pour chaque champ, la part des factures où la bonne
valeur est présente dans les mots OCR : c'est le **maximum atteignable**.
""")
code("""
import pandas as pd
from collections import Counter
lig = []
for ch in CHAMPS:
    c = Counter(r.get(ch) for r in COUVERTURE.values() if ch in r)
    n = sum(c.values()); lisible = c["trouve"] + c["trouve_cadre"] + c["egal_ttc"]
    lig.append({"champ": ch, "factures": n, "lisible par l'OCR": lisible,
                "plafond %": round(100 * lisible / n, 1) if n else None})
pd.DataFrame(lig)
""")

md("## 3. Encodage LayoutLMv3 (fenêtres de 512 jetons, chevauchement 128)")
code("""
from transformers import AutoProcessor, LayoutLMv3ForTokenClassification
from PIL import Image
MODELE = "microsoft/layoutlmv3-base"
processor = AutoProcessor.from_pretrained(MODELE, apply_ocr=False)

def encoder(page, avec_labels=True):
    im = Image.open("data/" + page["image"]).convert("RGB")
    enc = processor(im, page["mots"], boxes=page["boites"],
                    word_labels=[L2I[e] for e in page["etiquettes"]] if avec_labels else None,
                    truncation=True, padding="max_length", max_length=512, stride=128,
                    return_overflowing_tokens=True, return_offsets_mapping=True,
                    return_tensors="pt")
    enc.pop("offset_mapping")
    n = enc["input_ids"].shape[0]
    pv = enc["pixel_values"]
    if isinstance(pv, list):
        pv = torch.stack(pv)
    if pv.shape[0] != n:                      # une image par fenêtre
        pv = pv[enc["overflow_to_sample_mapping"]]
    fen = []
    for i in range(n):
        f = {k: enc[k][i] for k in ("input_ids", "attention_mask", "bbox")}
        f["pixel_values"] = pv[i]
        if avec_labels:
            f["labels"] = enc["labels"][i]
        f["word_ids"] = enc.word_ids(i)
        fen.append(f)
    return fen

ENC = {p["page"]: encoder(p) for p in PAGES}
print(sum(len(v) for v in ENC.values()), "fenêtres")
""")

md("""
## 4. Entraînement et prédiction
Boucle simple (AdamW, préchauffage linéaire, précision mixte). La classe « O »
(mot sans intérêt) est sous-pondérée : sinon le modèle apprend à tout ignorer.
""")
code("""
from torch.utils.data import DataLoader
from transformers import get_linear_schedule_with_warmup
DEV = "cuda"
EPOQUES, LR, LOT, POIDS_O, GRAINE = 30, 3e-5, 2, 0.3, 42

def collate(b):
    return {k: torch.stack([x[k] for x in b]) for k in b[0] if k != "word_ids"}

def entrainer(pages_train, verbeux=False, pages_val=None):
    random.seed(GRAINE); np.random.seed(GRAINE); torch.manual_seed(GRAINE)
    modele = LayoutLMv3ForTokenClassification.from_pretrained(
        MODELE, num_labels=len(ETIQUETTES),
        id2label=dict(enumerate(ETIQUETTES)), label2id=L2I).to(DEV)
    fen = [f for p in pages_train for f in ENC[p]]
    dl = DataLoader(fen, batch_size=LOT, shuffle=True, collate_fn=collate)
    fen_val = [f for q in (pages_val or []) for f in ENC[q]]
    dl_val = DataLoader(fen_val, batch_size=LOT, shuffle=False, collate_fn=collate) if fen_val else None
    opt = torch.optim.AdamW(modele.parameters(), lr=LR, weight_decay=0.01)
    pas = EPOQUES * len(dl)
    sch = get_linear_schedule_with_warmup(opt, int(0.1 * pas), pas)
    poids = torch.ones(len(ETIQUETTES), device=DEV); poids[0] = POIDS_O
    perte = torch.nn.CrossEntropyLoss(weight=poids, ignore_index=-100)
    scaler = torch.cuda.amp.GradScaler()
    hist = []
    for ep in range(EPOQUES):
        modele.train()
        tot = 0
        for b in dl:
            b = {k: v.to(DEV) for k, v in b.items()}
            lab = b.pop("labels")
            with torch.autocast("cuda", dtype=torch.float16):
                logits = modele(**b).logits
                l = perte(logits.view(-1, logits.shape[-1]), lab.view(-1))
            opt.zero_grad(); scaler.scale(l).backward()
            scaler.unscale_(opt); torch.nn.utils.clip_grad_norm_(modele.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sch.step(); tot += l.item()
        pt = tot / len(dl)
        pv = None
        if dl_val is not None:                      # perte sur le pli de test
            modele.eval()
            s = 0.0
            with torch.no_grad():
                for b in dl_val:
                    b = {k: v.to(DEV) for k, v in b.items()}
                    lab = b.pop("labels")
                    with torch.autocast("cuda", dtype=torch.float16):
                        lg = modele(**b).logits
                        s += perte(lg.view(-1, lg.shape[-1]), lab.view(-1)).item()
            pv = s / len(dl_val)
        hist.append({"epoque": ep + 1, "train": pt, "val": pv})
        if verbeux and (ep % 5 == 4 or ep == EPOQUES - 1):
            print(f"  époque {ep+1}/{EPOQUES}  perte {pt:.4f}"
                  + (f"   validation {pv:.4f}" if pv is not None else ""))
    modele._historique = hist
    return modele

@torch.no_grad()
def predire_page(modele, page):
    modele.eval()
    n = len(page["mots"]); somme = np.zeros((n, len(ETIQUETTES))); vu = np.zeros(n)
    for f in ENC[page["page"]]:
        b = {k: f[k].unsqueeze(0).to(DEV) for k in ("input_ids", "attention_mask", "bbox", "pixel_values")}
        pr = torch.softmax(modele(**b).logits[0].float(), -1).cpu().numpy()
        deja = set()
        for t, w in enumerate(f["word_ids"]):
            if w is not None and w not in deja:     # 1er sous-mot de chaque mot
                deja.add(w); somme[w] += pr[t]; vu[w] += 1
    pr = somme / np.maximum(vu, 1)[:, None]
    lab = [ETIQUETTES[i] for i in pr.argmax(1)]
    return {"mots": page["mots"], "etiquettes": lab, "probas": pr.max(1).tolist()}

def predire_doc(modele, doc):
    return decoder([predire_page(modele, p) for p in PAGES if p["doc"] == doc])
""")

md("""
## 5. Validation croisée (5 plis)
`GROUPE = "doc"` : chaque facture n'est testée que par un modèle qui ne l'a jamais vue.
`GROUPE = "fournisseur"` : test plus dur — fournisseurs (donc mises en page) jamais vus.
Compter ~8 min par pli sur T4.
""")
code("""
from sklearn.model_selection import GroupKFold
GROUPE = "doc"          # ou "fournisseur"
groupes = [d if GROUPE == "doc" else (VERITE[d]["fournisseur"] or d).split()[0].lower() for d in DOCS]
PRED, PRED_PAGES, HISTO = {}, {}, []
for k, (itr, ite) in enumerate(GroupKFold(n_splits=5).split(DOCS, groups=groupes), 1):
    dtr = {DOCS[i] for i in itr}; dte = [DOCS[i] for i in ite]
    print(f"Pli {k}/5 : {len(dtr)} factures d'entraînement, {len(dte)} de test")
    modele = entrainer([p["page"] for p in PAGES if p["doc"] in dtr], verbeux=True,
                       pages_val=[p["page"] for p in PAGES if p["doc"] in set(dte)])
    HISTO.append(modele._historique)
    for d in dte:
        pages_d = [p for p in PAGES if p["doc"] == d]
        sorties = [predire_page(modele, p) for p in pages_d]
        for p, s in zip(pages_d, sorties):
            PRED_PAGES[p["page"]] = s      # etiquettes BIO par mot, pour le F1
        PRED[d] = decoder(sorties)
    del modele; torch.cuda.empty_cache()
json.dump(PRED, open(f"predictions_cv_{GROUPE}.json", "w"), ensure_ascii=False, indent=1, default=str)
""")

md("""
## 6. Perte de validation

La perte d'entraînement seule ne dit rien de la généralisation : avec 125 M de
paramètres pour 71 factures, elle tend vers zéro quoi qu'il arrive. On mesure
donc aussi la perte sur le **pli de test**, à chaque époque, moyennée sur les
5 plis. Si elle remonte pendant que celle d'entraînement descend, le modèle
mémorise au lieu d'apprendre.
""")
code("""
import matplotlib.pyplot as plt
H = (pd.DataFrame([h for pli in HISTO for h in pli])
       .groupby('epoque')[['train', 'val']].mean())

fig, ax = plt.subplots(figsize=(7.5, 4.2))
ax.plot(H.index, H['train'], color='#2563eb', lw=2, label='entraînement')
ax.plot(H.index, H['val'], color='#ea580c', lw=2, label='validation (pli de test)')
bas = int(H['val'].idxmin())
ax.axvline(bas, color='#94a3b8', lw=1, ls='--', zorder=0)
ax.annotate(f'minimum : époque {bas}', (bas, H['val'].min()),
            textcoords='offset points', xytext=(8, 12), color='#475569', fontsize=9)
ax.set_xlabel('époque'); ax.set_ylabel('perte')
ax.set_title('Perte moyenne sur les 5 plis', loc='left', fontsize=12)
ax.grid(axis='y', color='#e2e8f0', lw=0.8); ax.set_axisbelow(True)
for c in ('top', 'right'):
    ax.spines[c].set_visible(False)
ax.legend(frameon=False)
plt.tight_layout(); plt.show()

print(f"validation minimale : {H['val'].min():.4f}  (époque {bas})")
print(f"validation finale   : {H['val'].iloc[-1]:.4f}  (époque {int(H.index[-1])})")
print(f"entraînement final  : {H['train'].iloc[-1]:.4f}")
H.round(4)
""")

md("""
## 7. Qualité de l'étiquetage (F1)

L'exactitude par champ dit si la bonne valeur ressort ; le F1 dit si le modèle
sait **étiqueter**, et surtout *où* il se trompe. Un F1 faible sur `TTC` désigne
une confusion d'étiquettes, pas un défaut de lecture — les deux se corrigent
très différemment. Calculé avec seqeval sur les étiquettes BIO de la validation
croisée, donc sur des pages jamais vues à l'entraînement.
""")
code("""
from seqeval.metrics import classification_report, f1_score
pages_vues = [p for p in PAGES if p['page'] in PRED_PAGES]
y_vrai = [p['etiquettes'] for p in pages_vues]
y_pred = [PRED_PAGES[p['page']]['etiquettes'] for p in pages_vues]

print(classification_report(y_vrai, y_pred, digits=3, zero_division=0))
print('F1 micro :', round(f1_score(y_vrai, y_pred, average='micro', zero_division=0), 3))
print('F1 macro :', round(f1_score(y_vrai, y_pred, average='macro', zero_division=0), 3))
""")

md("### Où partent les erreurs (matrice de confusion par mot, paires O→O retirées)")
code("""
champ = lambda e: e.split('-')[-1] if e != 'O' else 'O'
paires = [(champ(a), champ(b)) for p in pages_vues
          for a, b in zip(p['etiquettes'], PRED_PAGES[p['page']]['etiquettes'])]
paires = [(a, b) for a, b in paires if not (a == 'O' and b == 'O')]
pd.crosstab(pd.Series([a for a, _ in paires], name='vérité'),
            pd.Series([b for _, b in paires], name='prédit'))
""")

md("""
## 8. Hybride LayoutLMv3 + règles + contrôle arithmétique
Pour le numéro, la date, le fournisseur, le client et le timbre : le modèle
l'emporte quand il est sûr de lui (probabilité ≥ 0,5), sinon les règles
reprennent la main. Pour **HT, TVA et TTC le modèle est toujours conservé**
dès qu'il a lu une valeur — les règles y sont à 22-27 % et les reprendre
faisait perdre jusqu'à 20 points.

L'arithmétique départage ensuite les montants candidats, mais seuls ceux du
modèle sont mis en jeu (sauf pour un champ qu'il n'a pas lu). Sans cette
restriction, un triplet de règles faux mais cohérent l'emportait sur le bon :
157 610 700 + 101 296 = 157 711 996 tombe juste, et écrasait 1 416,123 /
269,063 / 1 855,276.
""")
code("""
def hybride(p, r):
    return fusionner_avec_regles(p, depuis_regles(r))

REG = {d: depuis_regles(REGLES[d]["meme_ocr"]) for d in DOCS}
PROD = {d: depuis_regles(REGLES[d]["production"]) for d in DOCS}   # avant correctifs
HYB = {d: hybride(PRED[d], REGLES[d]["meme_ocr"]) for d in DOCS}

def tableau(**systemes):
    lig = []
    for k in CHAMPS_EVAL:
        row = {"champ": k}
        for nom, pr in systemes.items():
            e = evaluer(pr, VERITE).get(k)
            row[nom] = f'{e["taux"]}% ({e["justes"]}/{e["n"]})' if e else "—"
        lig.append(row)
    return pd.DataFrame(lig)

tableau(regles_production=PROD, regles_meme_ocr=REG, layoutlmv3=PRED, hybride=HYB)
""")

md("### Montant à payer juste, facture entière juste")
code("""
def global_(pr):
    ok_net = sum(juste("net_a_payer", pr[d].get("net_a_payer"), VERITE[d]["net_a_payer"], VERITE[d]["devise"]) for d in DOCS)
    tout = sum(all(juste(k, pr[d].get(k), VERITE[d][k], VERITE[d]["devise"])
                   for k in ("numero", "date", "total_ttc", "net_a_payer") if VERITE[d].get(k) is not None) for d in DOCS)
    return {"net à payer juste": f"{ok_net}/{len(DOCS)}", "n°+date+TTC+net justes": f"{tout}/{len(DOCS)}"}
pd.DataFrame({n: global_(p) for n, p in [("règles (prod)", PROD), ("règles", REG), ("LayoutLMv3", PRED), ("hybride", HYB)]})
""")

md("""
## 9. Ce qu'on peut automatiser

En production il n'y a pas de vérité terrain : le seul signal disponible pour
juger une facture est le **contrôle arithmétique** (HT + TVA + timbre = TTC).
La question qui décide du déploiement est donc : *parmi les factures où il tombe
juste, combien sont réellement correctes ?*

Si ce groupe est massivement juste, il passe sans relecture et seul le reste part
en vérification. Sinon, la cohérence ne discrimine rien et tout doit être relu.
""")
code("""
def entiere(pr, d):
    return all(juste(k, pr[d].get(k), VERITE[d][k], VERITE[d]['devise'])
               for k in ('numero', 'date', 'total_ttc', 'net_a_payer')
               if VERITE[d].get(k) is not None)

lig = []
for nom, pr in [('LayoutLMv3', PRED), ('hybride', HYB)]:
    for etat, cond in [('cohérente', True), ('non cohérente', False)]:
        sous = [d for d in DOCS if bool(pr[d].get('coherent')) is cond]
        if not sous:
            continue
        net = sum(juste('net_a_payer', pr[d].get('net_a_payer'),
                        VERITE[d]['net_a_payer'], VERITE[d]['devise']) for d in sous)
        tout = sum(entiere(pr, d) for d in sous)
        lig.append({'système': nom, 'arithmétique': etat,
                    'factures': f'{len(sous)}  ({100 * len(sous) / len(DOCS):.0f}% du jeu)',
                    'net à payer juste': f'{net}/{len(sous)}  ({100 * net / len(sous):.1f}%)',
                    'facture entière juste': f'{tout}/{len(sous)}  ({100 * tout / len(sous):.1f}%)'})
pd.DataFrame(lig)
""")

md("## 10. Désaccords à vérifier (vérité vs modèle vs règles)")
code("""
lig = []
for d in DOCS:
    for k in CHAMPS_EVAL:
        v = VERITE[d].get(k)
        if v is None: continue
        okm = juste(k, HYB[d].get(k), v, VERITE[d]["devise"]); okr = juste(k, REG[d].get(k), v, VERITE[d]["devise"])
        if not (okm and okr):
            lig.append({"doc": d, "champ": k, "vérité": v, "hybride": HYB[d].get(k),
                        "règles": REG[d].get(k), "hybride_ok": okm, "règles_ok": okr})
DES = pd.DataFrame(lig); DES.to_csv(f"desaccords_{GROUPE}.csv", index=False)
DES.head(40)
""")

md("""
## 11. Modèle final (toutes les factures) → Google Drive
À copier ensuite dans le projet : `models/layoutlmv3_factures/`
(la plateforme l'utilise automatiquement s'il est présent).
""")
code("""
from google.colab import drive
drive.mount("/content/drive")
final = entrainer([p["page"] for p in PAGES], verbeux=True)
DEST = "/content/drive/MyDrive/overlyne_layoutlmv3/layoutlmv3_factures"
final.save_pretrained(DEST); processor.save_pretrained(DEST)
for f in [f"predictions_cv_{GROUPE}.json", f"desaccords_{GROUPE}.csv"]:
    if os.path.exists(f): os.system(f'cp "{f}" "/content/drive/MyDrive/overlyne_layoutlmv3/"')
print("Modèle enregistré :", DEST)
""")

nb["cells"] = C
nb["metadata"] = {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                  "kernelspec": {"name": "python3", "display_name": "Python 3"}}
import os
nbf.write(nb, sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "entrainement_layoutlmv3.ipynb"))
print("ok")
