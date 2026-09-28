"""
ETL de l'entrepôt de données (modèle en étoile, Kimball).

    sources.py       catalogue des exports CSV de l'ERP
    regles.py        règles de nettoyage partagées (dates, signe, libellés)
    staging.py       extraction : sources projetées et typées (temporaires)
    faits.py         faits au grain déclaré, règles métier appliquées
    dimensions.py    dimensions conformes, membres déduits des faits
    marts.py         agrégats matérialisés
    presentation.py  vues aux noms lus par l'application
    qualite.py       contrôles : unicité, intégrité, calendrier, volumes
    construire.py    orchestration — `python -m etl.construire`

Voir docs/DATA_WAREHOUSE.md.
"""
