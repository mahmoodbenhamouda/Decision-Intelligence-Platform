"""
Extraction de factures par LayoutLMv3 affiné (texte + position + image).

- `champs.py`     : lecture des montants/dates/numéros, décodage, contrôle
                    arithmétique, évaluation (sans dépendance lourde) ;
- `mots.py`       : mots + boîtes d'un document (texte PDF exact ou OCR renforcé) ;
- `extracteur.py` : inférence + fusion avec les règles ; optionnel (le modèle
                    s'entraîne sur Colab : notebooks/entrainement_layoutlmv3.ipynb).
"""
from .extracteur import etat, disponible, dossier_modele, lire_facture  # noqa: F401

__all__ = ["lire_facture", "disponible", "etat", "dossier_modele"]
