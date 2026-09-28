# Lecture des factures par LayoutLMv3

## En bref

La lecture des factures combine désormais trois éléments :

1. **Un OCR renforcé.** Plusieurs lectures Tesseract sont fusionnées. Pour un PDF
   qui contient du vrai texte numérique, on lit directement ce texte, qui est exact.
2. **LayoutLMv3 affiné.** Le modèle lit le texte, sa position et l'image de la
   page. Il indique quel mot est le numéro, la date, le HT, la TVA, le timbre, le
   TTC ou le net à payer.
3. **Les règles existantes et un contrôle arithmétique.** Quand le modèle hésite,
   on garde la valeur trouvée par les règles. Ensuite, on choisit les montants
   qui vérifient HT + TVA (+ timbre) = TTC.

Le modèle est **optionnel**. S'il n'est pas installé, la plateforme fonctionne
comme avant, avec les règles seules.

## Pourquoi

Nous avons évalué la chaîne à règles sur **89 factures réelles de tiers**. Chaque
facture a été relue à la main pour établir les vraies valeurs (vérité terrain) :

| Champ | Règles (production) | Règles + OCR renforcé | Plafond de l'OCR renforcé* |
|---|---|---|---|
| Numéro | 31 % | 46 % | 99 % |
| Date | 57 % | 67 % | 95 % |
| Total HT | 22 % | 41 % | 88 % |
| TVA | 28 % | 48 % | 99 % |
| Timbre | 25 % | 60 % | 76 % |
| Total TTC | 23 % | 35 % | 83 % |
| **Net à payer** | **19 %** | **29 %** | **92 %** |

\* Part des factures où la bonne valeur figure bien parmi les mots lus par l'OCR.
C'est le **maximum** qu'un extracteur peut atteindre avec cet OCR, parce que
LayoutLMv3 classe des mots : il ne peut pas inventer un chiffre que l'OCR n'a pas lu.

Les règles échouent le plus souvent **sur le choix du bon nombre**, et non sur la
lecture : le montant est présent dans le texte, mais c'est un autre nombre qui est
retenu (un numéro de facture à 9 chiffres pris pour le TTC, un total de ligne pris
pour le HT, etc.). C'est exactement ce que LayoutLMv3 apprend à corriger, grâce à
la position des mots et au cadre des totaux.

Les scores de LayoutLMv3 se mesurent en validation croisée, dans le carnet Colab
(voir plus bas). Ils ne sont pas inscrits ici tant que l'entraînement n'a pas été
lancé.

## Deux défauts corrigés dans la chaîne actuelle

- **Couches texte « poubelle ».** Beaucoup de PDF scannés contiennent une couche
  texte produite par le scanner, parfois illisible (« §rxraæsr &Tar&re ef Granit »
  pour « Ennasr Marbre et Granit »). `engine.py` faisait confiance à ce texte. On
  mesure maintenant sa qualité (`qualite_texte`) : en dessous de 0,88, le document
  est relu par notre OCR. Sur 30 PDF mesurés, ces couches se situent entre 0,76 et
  0,81, et le vrai texte numérique est à 0,92 ou plus.
- **Cadres de totaux invisibles.** Une seule passe Tesseract rate des blocs
  entiers, surtout le cadre des totaux lorsqu'il est grisé ou écrit en blanc sur
  fond foncé. L'OCR renforcé fusionne 5 lectures (psm 3, 6, 11, plus psm 6 et 11
  sur une image « dé-inversée » agrandie ×2). Sur ce jeu, cela fait passer le
  plafond du net à payer de 88 à 92 % et celui du numéro de 95 à 99 %.

## Le jeu de données

- 114 documents déposés, dont **89 factures** (88 factures et 1 avoir). Les 25
  autres sont 8 ordres de virement, 7 tickets de restaurant, 3 billets, 3 notes de
  frais, 1 relevé bancaire, 1 ticket de caisse, 1 quittance et 1 bordereau. Ils
  sont exclus de l'entraînement.
- **Vérité terrain.** Chaque facture a été lue à l'œil pour relever le numéro, la
  date, le fournisseur, le client, la devise, le HT, la TVA, le timbre, le TTC et
  le net réellement dû (après retenue à la source). Le TTC vaut `null` lorsqu'il
  n'est pas imprimé.
- **Étiquettes BIO.** Chaque valeur est projetée sur les mots de la page. Un
  montant n'est étiqueté que là où un libellé le justifie : « Total HT », « TVA »,
  « Net à payer », etc., sur la même ligne ou en tête de colonne. Une ligne
  d'article qui aurait la même valeur par hasard n'est pas étiquetée.
- **Confidentialité.** Ce sont des factures de tiers. Le dossier
  `evaluation_ocr/factures/` et le dossier `evaluation_ocr/layoutlmv3/` (vérité
  terrain, jeu de données, zip) sont **exclus de git**. Ils ne sont jamais publiés.

## Entraîner (Google Colab, GPU T4 gratuit)

1. Ouvrir `evaluation_ocr/entrainement_layoutlmv3.ipynb` dans Colab et choisir
   *Exécution › Modifier le type d'exécution › GPU T4*.
2. Tout exécuter. Le carnet demande `evaluation_ocr/layoutlmv3/layoutlmv3_factures.zip`.
3. Le carnet produit :
   - le tableau **règles / LayoutLMv3 / hybride**, champ par champ, en validation
     croisée à 5 plis regroupée par facture ;
   - la liste des désaccords (`desaccords_doc.csv`) ;
   - le modèle final dans Google Drive : `overlyne_layoutlmv3/layoutlmv3_factures/`.
4. Copier ce dossier dans le projet sous `models/layoutlmv3_factures/`
   (dossier exclu de git), puis installer `pip install torch transformers`.
   `GET /api/ocr/status` renvoie alors `"layoutlmv3": true`.

Pour tester sur des mises en page jamais vues, régler `GROUPE = "fournisseur"`.

## Ajouter des factures

```
python evaluation_ocr/preparation/1_preparer.py      # rendu 200 dpi + OCR simple
python evaluation_ocr/preparation/2_ocr_renforce.py  # OCR renforcé (≈ 15 s/page)
python evaluation_ocr/preparation/annoter.py '{"d115": {...}}'   # vérité terrain
python evaluation_ocr/preparation/3_construire.py    # étiquettes + zip pour Colab
```

`1_preparer.py` renumérote les documents dans l'ordre alphabétique des fichiers.
Si l'on ajoute des factures, il faut vérifier la correspondance `manifeste.json`
avant d'annoter.

## Dans la plateforme

`POST /api/ocr/invoice` et `/api/ocr/invoice/import` appellent
`ml_engine.ocr.layoutlm.lire_facture`. La réponse contient
`"moteur": "layoutlmv3+regles"` ou `"regles"`. Chaque champ corrigé par le modèle
est signalé dans `champs_confiance` avec la valeur `"layoutlmv3"`. Quand le modèle
est installé, **une seule** lecture du document sert à la fois aux règles et au
modèle : il n'y a pas de double OCR.

## Limites (à dire en soutenance)

- **Taille du jeu.** 89 factures est peu pour un modèle de 125 M de paramètres.
  La validation croisée évite de surestimer les scores, mais ils restent
  imprécis, à ± 5 à 10 points près.
- **« Parfait » n'existe pas.** Le plafond vient de l'OCR : factures manuscrites,
  scans penchés, petits chiffres en blanc sur fond bleu. Au-delà, il faut un
  meilleur OCR ou une saisie humaine. La plateforme affiche donc la cohérence
  arithmétique : si HT + TVA ≠ TTC, la facture est à vérifier.
- **Fournisseur.** Le nom du fournisseur figure souvent dans le logo, sous forme
  d'image. L'OCR ne le lit pas, d'où un plafond de 73 %.
- **Licence.** LayoutLMv3 est sous licence CC BY-NC-SA 4.0 : l'usage académique
  est autorisé, l'usage commercial ne l'est pas. Pour un usage commercial, il
  faudrait passer à LiLT ou à LayoutLMv1 (MIT).
- **Temps de traitement.** Sur un processeur sans GPU, comptez de 15 à 40 s par
  page scannée (OCR renforcé et modèle). Un PDF numérique est traité en quelques
  secondes.

## Fichiers

| Fichier | Rôle |
|---|---|
| `ml_engine/ocr/layoutlm/champs.py` | Lecture des montants et dates, décodage BIO, contrôle arithmétique, évaluation |
| `ml_engine/ocr/layoutlm/mots.py` | Mots et boîtes : texte PDF exact ou OCR renforcé |
| `ml_engine/ocr/layoutlm/extracteur.py` | Inférence et fusion avec les règles (`lire_facture`) |
| `ml_engine/ocr/engine.py` | `qualite_texte` : détection des couches texte illisibles |
| `evaluation_ocr/preparation/*.py` | Chaîne de préparation du jeu de données |
| `evaluation_ocr/entrainement_layoutlmv3.ipynb` | Entraînement, validation croisée et comparaison (Colab) |
| `tests/test_layoutlm.py` | 55 tests (sans GPU ni modèle) |
