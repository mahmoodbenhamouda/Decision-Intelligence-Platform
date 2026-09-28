# Service OCR transversal

> **Mise à jour (sept. 2026)** — lecture des factures par **LayoutLMv3** affiné
> (optionnel), OCR renforcé multi-passes et détection des couches texte PDF
> illisibles : voir [LAYOUTLMV3.md](LAYOUTLMV3.md). Les mesures sur 89 factures
> réelles y sont détaillées.

## Pourquoi ce module

L'OCR était auparavant enfermé dans l'endpoint d'upload du copilote et se contentait de produire du texte brut à donner au LLM. Il est désormais un **service réutilisable dans tout le projet**, qui transforme un document papier en **information exploitable** : champs de facture structurés, rapprochement automatique avec l'ERP, et alimentation de la base documentaire.

## Architecture

```
ml_engine/ocr/
├── engine.py      moteur d'extraction (images + PDF), pré-traitement, score de qualité
├── invoice.py     texte → champs structurés (n°, dates, HT/TVA/TTC, tiers, MF)
└── reconcile.py   champs → rapprochement avec l'entrepôt DuckDB

api/routers/ocr.py   exposition HTTP (authentification, contrôle du fichier reçu)
api/services/ocr.py  qui peut lire, rapprocher et enregistrer quoi (un client : ses ventes)
frontend/src/features/ocr/  onglet « Documents & OCR » (vue DocumentsOCR.tsx, ViewModel useDocumentsOCR.ts, service ocr.service.ts)
```

Usage direct depuis n'importe quel script, agent ou notebook :

```python
from ml_engine.ocr import ocr_document, parse_invoice, reconcile_invoice

res = ocr_document(open("facture.png", "rb").read(), "facture.png")
inv = parse_invoice(res.text)
rap = reconcile_invoice(inv)            # ou client_code="CE000017" pour restreindre
```

## Endpoints

| Endpoint | Rôle | Fonction |
|---|---|---|
| `GET /api/ocr/status` | tous | moteur disponible ? version, langues, consigne d'installation |
| `POST /api/ocr/extract` | tous | texte brut + **score de qualité** de lecture |
| `POST /api/ocr/invoice` | tous | facture structurée + **rapprochement ERP** (périmètre forcé pour un client) |
| `POST /api/ocr/to-rag` | directeur | document océrisé → indexé dans le RAG, interrogeable via `doc:` |

## 1. Moteur d'extraction (`engine.py`)

- **Formats** : PNG, JPG, TIFF, BMP, WEBP et PDF. Pour un PDF, le texte natif est tenté d'abord (rapide et exact) ; si le document s'avère être un scan (moins de 120 caractères par page), bascule automatique vers l'OCR page par page.
- **Pré-traitement** : niveaux de gris, autocontraste, agrandissement des petites images, binarisation Otsu si OpenCV est présent. Sur une facture photographiée, cela change radicalement le taux de reconnaissance.
- **Sélection du meilleur résultat** : quatre modes de segmentation Tesseract (`--psm 6/4/3/11`) sont testés et départagés par la **confiance moyenne** rendue par Tesseract (`image_to_data`), pas par la simple longueur du texte.
- **Score de qualité exposé** : « excellente » (≥85 %), « bonne » (≥70 %), « moyenne — à vérifier », « faible — vérification manuelle nécessaire ». Un OCR à 45 % ne doit jamais être présenté comme une vérité.
- **Dégradation propre** : sans Tesseract, le module ne casse pas — `ocr_available()` renvoie `False`, le message d'installation est explicite, et les PDF natifs restent lisibles.
- **Langues** : `fra+eng`, repli automatique sur `eng` si le pack français est absent (signalé à l'utilisateur).

## 2. Extraction structurée (`invoice.py`)

Passer de « voici du texte » à « facture n° F-2026-118 du 12/03/2026, 14 280,000 DT TTC dont 2 280,000 de TVA ». Méthode **déterministe** (règles, pas de LLM) : testable, reproductible, fonctionne hors-ligne.

Points d'ingénierie notables :

- **Format tunisien** : la virgule est le séparateur décimal et les montants portent 3 décimales (millimes). `330,000` vaut **330 DT**, pas 330 000 — la virgule n'est traitée comme séparateur de milliers que dans un format manifestement anglo-saxon (`1,234,567`).
- **Mise en page en colonnes** : Tesseract insère souvent une ligne vide entre un libellé et son montant. Le parseur explore jusqu'à 3 lignes en aval, mais **s'arrête sur un autre libellé** pour ne pas attribuer à « Total HT » le montant de la ligne « TVA ».
- **Tolérance aux fautes OCR** dans les nombres (O↔0, l↔1, S↔5).
- **Confiance par champ** : « libellé trouvé » (explicite) > « calculé » > « déduit » (ex. plus gros montant du document faute de libellé). Affiché dans l'interface.
- **Contrôle de cohérence** : HT + TVA ≈ TTC. Une incohérence signale une erreur de lecture et invite à la vérification manuelle.
- Champs extraits : n° de facture, date, échéance, HT, TVA, TTC, devise, tiers, matricule fiscal.

## 3. Rapprochement ERP (`reconcile.py`)

Le cœur de l'utilité métier. Une facture papier arrive, on la photographie, la plateforme répond :

| Statut | Signification |
|---|---|
| `rapprochee` | facture retrouvée dans l'ERP, montants identiques |
| `ecart_detecte` | facture proche trouvée mais écart de montant → litige à instruire |
| `doublon_probable` | plusieurs factures identiques (même client, même montant) |
| `introuvable` | non saisie dans l'ERP, montant mal lu, ou tiers hors périmètre |
| `montant_absent` | OCR insuffisant pour rapprocher |

**Scoring explicable** (un utilisateur doit pouvoir contester la décision) : montant jusqu'à 60 points (tolérance : 1 % ou 1 DT), date jusqu'à 25 points (fenêtre de 45 jours), similarité du nom du tiers jusqu'à 15 points. Chaque candidat affiche son explication : *« montant identique · même date · nom similaire (100 %) »*.

**Isolation** : pour un compte `client`, la recherche est restreinte côté serveur à son propre `client_code` — impossible de rapprocher une facture sur les données d'un autre.

## 4. Base documentaire (RAG)

`POST /api/ocr/to-rag` océrise un contrat ou une notice scannée, l'écrit dans `rag/documents/` avec un en-tête de provenance (source, date de numérisation, qualité d'extraction), puis réindexe. Le document devient interrogeable dans le copilote avec le préfixe `doc:`. Réservé au directeur, car ces documents sont visibles de tous les utilisateurs du RAG.

## Ce qui reste dans le copilote

Le copilote conserve l'analyse des fichiers **textuels** (CSV, PDF natifs) — ceux qu'on veut *discuter* avec l'agent. Un PDF scanné y est détecté et l'utilisateur est explicitement redirigé vers l'onglet « Documents & OCR ».

## Installation de Tesseract

```bash
# 1. Le moteur (une fois)
# Windows : https://github.com/UB-Mannheim/tesseract/wiki
#           puis ajouter C:\Program Files\Tesseract-OCR au PATH
# Linux :   sudo apt install tesseract-ocr
pip install pytesseract Pillow pypdfium2   # pypdfium2 = OCR des PDF scannés

# 2. Le pack de langue français — SANS droits administrateur
python scripts/setup_tesseract_fr.py
```

**Pourquoi un script dédié au pack français ?** Ajouter une langue à Tesseract demande normalement d'écrire dans `C:\Program Files\Tesseract-OCR\tessdata`, ce qui exige les droits administrateur. Le script installe `fra.traineddata` dans **`models/tessdata/`** (dans le projet), y recopie les packs système nécessaires (`eng`, `osd`), et le moteur pointe automatiquement dessus via `TESSDATA_PREFIX`. Aucune configuration manuelle, aucun droit admin, et le pack voyage avec le projet.

Sans le pack français, l'OCR confond les accents et le vocabulaire des factures (« Échéance », « Société », « Payé ») — l'extraction des champs s'en trouve dégradée.

L'application fonctionne sans Tesseract du tout : le statut est affiché dans l'onglet et les PDF natifs restent exploitables.

## Tests

`tests/test_ocr.py` — 32 tests, dont : parsing de montants (dont le piège `330,000`), dates en 5 formats, extraction complète, cohérence HT+TVA=TTC, détection d'incohérence, mise en page en colonnes, non-vol de montant entre libellés, similarité de noms, rapprochement sur une **facture réelle de l'entrepôt** (score 100). Les tests de parsing n'exigent pas Tesseract : ils restent verts en CI.

Validation de bout en bout effectuée : OCR d'une facture réelle à **92,2 % de confiance**, tous les champs extraits, cohérence vérifiée, rapprochement ERP au score **100/100**.
