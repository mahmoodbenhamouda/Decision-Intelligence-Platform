# evaluation_ocr/

Évaluation et entraînement de la lecture de factures (voir `docs/LAYOUTLMV3.md`).

| Élément | Suivi par git ? |
|---|---|
| `factures/` : factures de tiers (données sources) | **non** (confidentiel) |
| `layoutlmv3/` : vérité terrain, jeu étiqueté, zip Colab | **non** (dérivé des factures) |
| `preparation/` : scripts de la chaîne | oui |
| `entrainement_layoutlmv3.ipynb` : carnet Colab | oui (à ne pas committer une fois exécuté) |
