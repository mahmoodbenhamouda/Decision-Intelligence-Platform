"""ML Engine — modules d'analyse, de prévision et d'apprentissage.

Ce paquet est volontairement VIDE de logique : chaque sous-module s'importe
directement (`ml_engine.analytics.kpi_engine`, `ml_engine.passerelle`…), ce qui
évite de charger tout le moteur pour un seul calcul.

Organisation :
    analytics/    indicateurs, churn, segmentation, crédit, marge, conversion
    forecasting/  encaissements (carnet d'échéances) et demande
    models/       risque produit, demande mensuelle
    stock/        flux réels, positions, fin de vie, réapprovisionnement
    deep/         recommandation de produits (Wide & Deep, PyTorch optionnel)
    ocr/          extraction de factures et rapprochement ERP
    typologie.py  établissement de santé public ou non (règle unique)
    registre.py   ce qui est servi, refusé ou retiré — et pourquoi
    passerelle.py point d'entrée unique des agents vers les modèles
    boucle.py     retour des résultats du terrain vers les modèles
"""
