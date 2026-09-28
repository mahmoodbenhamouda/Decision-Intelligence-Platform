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
!pip -q install "transformers>=4.44" accelerate
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

def _charger(pages, melange):
    fen = [f for p in (pages or []) for f in ENC[p]]
    return DataLoader(fen, batch_size=LOT, shuffle=melange, collate_fn=collate) if fen else None

@torch.no_grad()
def _perte_moyenne(modele, dl, perte):
    if dl is None:
        return None
    modele.eval(); s = 0.0
    for b in dl:
        b = {k: v.to(DEV) for k, v in b.items()}
        lab = b.pop("labels")
        with torch.autocast("cuda", dtype=torch.float16):
            lg = modele(**b).logits
            s += perte(lg.view(-1, lg.shape[-1]), lab.view(-1)).item()
    return s / len(dl)

def entrainer(pages_train, verbeux=False, pages_val=None, epoques=None,
              pages_arret=None, patience=3):
    # pages_val   : pli de TEST. Observé seulement, aucune décision n'en dépend.
    # pages_arret : validation INTERNE, prélevée sur l'entraînement. Si elle est
    #               fournie, on s'arrête après `patience` époques sans progrès
    #               et on restaure les poids de la meilleure époque.
    ep_max = epoques or EPOQUES
    random.seed(GRAINE); np.random.seed(GRAINE); torch.manual_seed(GRAINE)
    modele = LayoutLMv3ForTokenClassification.from_pretrained(
        MODELE, num_labels=len(ETIQUETTES),
        id2label=dict(enumerate(ETIQUETTES)), label2id=L2I).to(DEV)
    dl = _charger(pages_train, True)
    dl_val = _charger(pages_val, False)
    dl_arret = _charger(pages_arret, False)
    opt = torch.optim.AdamW(modele.parameters(), lr=LR, weight_decay=0.01)
    pas = ep_max * len(dl)
    sch = get_linear_schedule_with_warmup(opt, int(0.1 * pas), pas)
    poids = torch.ones(len(ETIQUETTES), device=DEV); poids[0] = POIDS_O
    perte = torch.nn.CrossEntropyLoss(weight=poids, ignore_index=-100)
    scaler = torch.cuda.amp.GradScaler()
    hist, meilleure, meilleure_ep, sans_progres, meilleurs_poids = [], float("inf"), None, 0, None
    for ep in range(ep_max):
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
        pv = _perte_moyenne(modele, dl_val, perte)      # pli de test : observation
        pa = _perte_moyenne(modele, dl_arret, perte)    # validation interne : décision
        hist.append({"epoque": ep + 1, "train": pt, "val": pv, "arret": pa})
        if verbeux and (ep % 5 == 4 or ep == ep_max - 1):
            print(f"  époque {ep+1}/{ep_max}  perte {pt:.4f}"
                  + (f"   test {pv:.4f}" if pv is not None else "")
                  + (f"   val. interne {pa:.4f}" if pa is not None else ""))
        if pa is not None:
            if pa < meilleure - 1e-4:
                meilleure, meilleure_ep, sans_progres = pa, ep + 1, 0
                meilleurs_poids = {k: v.detach().to("cpu", copy=True)
                                   for k, v in modele.state_dict().items()}
            else:
                sans_progres += 1
                if sans_progres >= patience:
                    if verbeux:
                        print(f"  arrêt précoce après l'époque {ep+1}"
                              f" — meilleure : {meilleure_ep} ({meilleure:.4f})")
                    break
    if meilleurs_poids is not None:
        modele.load_state_dict(meilleurs_poids)
    modele._historique = hist
    modele._arret = {"epoques_faites": len(hist), "meilleure_epoque": meilleure_ep or len(hist),
                     "meilleure_perte": None if meilleure_ep is None else round(meilleure, 4)}
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
    # les boîtes servent au recollage du chiffre des milliers dans decoder()
    return {"mots": page["mots"], "etiquettes": lab, "probas": pr.max(1).tolist(),
            "boites": page["boites"]}

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
cle_groupe = lambda d: d if GROUPE == "doc" else (VERITE[d]["fournisseur"] or d).split()[0].lower()

def croiser(epoques=None, part_arret=0.0, patience=3, graine_arret=7,
            verbeux=True, etiquette=""):
    # Validation croisée à 5 plis. `part_arret` > 0 prélève, DANS l'entraînement de
    # chaque pli, une validation interne pour l'arrêt précoce ; elle n'est jamais
    # prise dans le pli de test — choisir le moment d'arrêt sur les données qui
    # servent à annoncer le résultat serait une fuite.
    groupes = [cle_groupe(d) for d in DOCS]
    pred, pred_pages, histo, journal = {}, {}, [], []
    pg = lambda ds: [p["page"] for p in PAGES if p["doc"] in set(ds)]
    for k, (itr, ite) in enumerate(GroupKFold(n_splits=5).split(DOCS, groups=groupes), 1):
        dtr = [DOCS[i] for i in itr]; dte = [DOCS[i] for i in ite]; darr = []
        if part_arret:                       # découpe interne, par groupe elle aussi
            cles = sorted({cle_groupe(d) for d in dtr})
            random.Random(graine_arret + k).shuffle(cles)
            pris, cible, n = set(), max(1, round(part_arret * len(dtr))), 0
            for c in cles:
                if n >= cible:
                    break
                pris.add(c); n += sum(cle_groupe(d) == c for d in dtr)
            darr = [d for d in dtr if cle_groupe(d) in pris]
            dtr = [d for d in dtr if cle_groupe(d) not in pris]
        print(f"{etiquette}Pli {k}/5 : {len(dtr)} factures d'entraînement"
              + (f", {len(darr)} de validation interne" if darr else "")
              + f", {len(dte)} de test")
        modele = entrainer(pg(dtr), verbeux=verbeux, pages_val=pg(dte),
                           epoques=epoques, pages_arret=pg(darr) or None, patience=patience)
        histo.append(modele._historique); journal.append(modele._arret)
        for d in dte:
            pages_d = [p for p in PAGES if p["doc"] == d]
            sorties = [predire_page(modele, p) for p in pages_d]
            for p, s in zip(pages_d, sorties):
                pred_pages[p["page"]] = s      # etiquettes BIO par mot, pour le F1
            pred[d] = decoder(sorties)
        del modele; torch.cuda.empty_cache()
    return pred, pred_pages, histo, journal

PRED, PRED_PAGES, HISTO, JOURNAL = croiser()      # variante A : 30 époques
json.dump(PRED, open(f"predictions_cv_{GROUPE}.json", "w"), ensure_ascii=False, indent=1, default=str)
""")

md("""
### Mesurer un correctif de décodage sans réentraîner

L'entraînement sur GPU **n'est pas reproductible au bit près** : deux exécutions
de la même configuration ne donnent pas les mêmes poids, et l'écart observé sur
l'exactitude atteint 1 point. Comparer deux exécutions ne dit donc rien d'un
correctif qui vaut moins que ça.

La bonne méthode, pour tout ce qui touche au **décodage** (et non au modèle) :
redécoder les **mêmes prédictions** deux fois. C'est exact, instantané et gratuit.
On enregistre aussi les étiquettes par mot, pour pouvoir refaire cette mesure
plus tard sans repasser sur le GPU.
""")
code("""
json.dump(PRED_PAGES, open(f"predictions_mots_{GROUPE}.json", "w"),
          ensure_ascii=False, default=str)

def exactitude(pred):
    e = evaluer(pred, VERITE)
    j = sum(e[k]["justes"] for k in CHAMPS_EVAL if k in e)
    n = sum(e[k]["n"] for k in CHAMPS_EVAL if k in e)
    return 100 * j / n

# meme predictions, mais boites retirees => recoller_milliers ne peut pas agir
SANS = {d: decoder([{**PRED_PAGES[q["page"]], "boites": None}
                    for q in PAGES if q["doc"] == d and q["page"] in PRED_PAGES])
        for d in DOCS}
a, b = exactitude(PRED), exactitude(SANS)
print(f"avec recollage des milliers : {a:.2f} %")
print(f"sans recollage des milliers : {b:.2f} %")
print(f"ecart : {a - b:+.2f} point(s) - sur les memes predictions, donc exact")
print()
for d in DOCS:
    for k in CHAMPS_EVAL:
        if PRED[d].get(k) != SANS[d].get(k):
            v = VERITE[d].get(k)
            ok = lambda x: "OK " if juste(k, x, v, VERITE[d]["devise"]) else "faux"
            print(f"  {d:>5} {k:<12} sans={SANS[d].get(k)} ({ok(SANS[d].get(k))}) "
                  f"avec={PRED[d].get(k)} ({ok(PRED[d].get(k))})  verite={v}")
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
très différemment. Calculé sur les étiquettes BIO de la validation croisée,
donc sur des pages jamais vues à l'entraînement.

Définition identique à seqeval / conlleval : une entité n'est juste que si son
type **et** ses bornes sont exacts. (seqeval n'est plus installable sur Colab :
il n'existe qu'en source et ne compile plus avec setuptools récent. Ce calcul
redonne ses chiffres à l'identique, vérifié sur 300 tirages aléatoires.)
""")
code("""
def entites(seq, page):
    # (page, type, debut, fin) de chaque entite d'une sequence BIO
    out, typ, deb = set(), None, None
    for i, e in enumerate(list(seq) + ['O']):
        pre, _, t = e.partition('-')
        if typ is not None and (e == 'O' or pre == 'B' or t != typ):
            out.add((page, typ, deb, i)); typ = None
        if e != 'O' and typ is None:
            typ, deb = t, i
    return out

def prf(v, p):
    tp = len(v & p)
    pr = tp / len(p) if p else 0.0
    rc = tp / len(v) if v else 0.0
    return pr, rc, (2 * pr * rc / (pr + rc) if pr + rc else 0.0)

pages_vues = [p for p in PAGES if p['page'] in PRED_PAGES]
ENT_V, ENT_P = set(), set()
for p in pages_vues:
    ENT_V |= entites(p['etiquettes'], p['page'])
    ENT_P |= entites(PRED_PAGES[p['page']]['etiquettes'], p['page'])

lig = []
for t in sorted({e[1] for e in ENT_V | ENT_P}):
    pr, rc, f = prf({e for e in ENT_V if e[1] == t}, {e for e in ENT_P if e[1] == t})
    lig.append({'champ': t, 'précision': round(pr, 3), 'rappel': round(rc, 3),
                'F1': round(f, 3), 'entités': sum(e[1] == t for e in ENT_V)})
TAB_F1 = pd.DataFrame(lig).set_index('champ').sort_values('F1')
pr, rc, f = prf(ENT_V, ENT_P)
print(f'F1 micro : {f:.3f}   (précision {pr:.3f}, rappel {rc:.3f})')
print(f"F1 macro : {TAB_F1['F1'].mean():.3f}")
TAB_F1
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
## 11. Combien d'époques ? (A : 30, B : 15, C : arrêt précoce)

La perte de validation du §6 touche son minimum vers l'époque 15 puis remonte :
au-delà, le modèle apprend par cœur. Trois façons d'en tenir compte, comparées
sur la **même validation croisée**, donc directement comparables :

* **A — 30 époques** : la référence actuelle, déjà calculée au §5. Le taux
  d'apprentissage décroît jusqu'à zéro à l'époque 30.
* **B — 15 époques** : on coupe, et le taux d'apprentissage décroît jusqu'à zéro
  à l'époque 15. Deux fois moins de calcul.
* **C — arrêt précoce** : 30 époques au planning, mais on surveille une validation
  **interne** (≈ 15 % des factures d'entraînement de chaque pli) et on s'arrête
  après 3 époques sans progrès, en restaurant les poids de la meilleure époque.

B et C ne sont pas la même chose, même si toutes deux s'arrêtent vers 15 : B
termine le recuit de son taux d'apprentissage, C s'arrête alors qu'il vaut encore
la moitié. Et C paie son honnêteté — il entraîne sur une dizaine de factures de
moins, celles mises de côté pour décider de l'arrêt.

**Pourquoi ne pas s'arrêter sur la courbe du §6 ?** Parce qu'elle est mesurée sur
le pli de test. Choisir le moment d'arrêt en la regardant reviendrait à régler le
modèle sur les données qui servent ensuite à annoncer le résultat : le chiffre
publié serait optimiste. C'est exactement ce que la validation interne évite, et
c'est aussi pourquoi C peut très bien finir **en dessous** de B.

Compter environ 20 min pour B et 30 min pour C sur T4 (A est déjà calculé).
""")
code("""
VARIANTES = {"A \u2014 30 \u00e9poques": (PRED, PRED_PAGES, JOURNAL)}

pr, pp, _, jr = croiser(epoques=15, verbeux=False, etiquette="B ")
VARIANTES["B \u2014 15 \u00e9poques"] = (pr, pp, jr)

pr, pp, _, jr = croiser(part_arret=0.15, patience=3, verbeux=False, etiquette="C ")
VARIANTES["C \u2014 arr\u00eat pr\u00e9coce"] = (pr, pp, jr)
""")

md("### Le verdict, sur les mêmes 89 factures")
code("""
def resume(pr, pp, jrn):
    e = evaluer(pr, VERITE)
    justes = sum(e[k]['justes'] for k in CHAMPS_EVAL if k in e)
    total = sum(e[k]['n'] for k in CHAMPS_EVAL if k in e)
    V, P = set(), set()
    for q in PAGES:
        if q['page'] in pp:
            V |= entites(q['etiquettes'], q['page'])
            P |= entites(pp[q['page']]['etiquettes'], q['page'])
    _, _, f1 = prf(V, P)
    net = lambda ds: sum(juste('net_a_payer', pr[d].get('net_a_payer'),
                               VERITE[d]['net_a_payer'], VERITE[d]['devise']) for d in ds)
    coh = [d for d in DOCS if pr[d].get('coherent')]
    return {'exactitude par champ %': round(100 * justes / total, 1),
            'F1 micro': round(f1, 3),
            'net \u00e0 payer juste': f'{net(DOCS)}/{len(DOCS)}',
            'facture enti\u00e8re juste': f'{sum(entiere(pr, d) for d in DOCS)}/{len(DOCS)}',
            'coh\u00e9rentes (automatisables)': f'{len(coh)}/{len(DOCS)}',
            'dont net juste': f'{net(coh)}/{len(coh)}' if coh else '\u2014',
            '\u00e9poques faites par pli': '/'.join(str(x['epoques_faites']) for x in jrn)}

COMPARAISON = pd.DataFrame({n: resume(*v) for n, v in VARIANTES.items()})
COMPARAISON
""")

md("""Et, pour la variante C, où l'arrêt s'est déclenché pli par pli — si les cinq
plis s'arrêtent à des époques très différentes, c'est que le minimum est plat et
que le nombre d'époques importe peu.""")
code("""
pd.DataFrame(VARIANTES["C \u2014 arr\u00eat pr\u00e9coce"][2],
             index=[f"pli {i}" for i in range(1, 6)])
""")

md("""
## 12. Modèle final (toutes les factures) → Google Drive
Fixez d'abord `EPOQUES_RETENUES` d'après le tableau du §11 : ce modèle-là est
celui qui partira en production, il doit être entraîné comme la variante retenue.
À copier ensuite dans le projet : `models/layoutlmv3_factures/` — la plateforme
ne le sert que si `reports/layoutlmv3_metrics.json` l'autorise (registre des
modèles) ; pensez à y reporter les chiffres de ce carnet.
""")
code("""
from google.colab import drive
drive.mount("/content/drive")
EPOQUES_RETENUES = 30      # ← à fixer d'après le tableau du §11
final = entrainer([p["page"] for p in PAGES], verbeux=True, epoques=EPOQUES_RETENUES)
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
