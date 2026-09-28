"""
API FastAPI de la plateforme — architecture en couches.

    routers/   couche HTTP : chemins, méthodes, droits d'accès, codes de retour.
               Aucun calcul, aucune requête SQL.
    schemas/   contrats d'entrée et de sortie (Pydantic).
    services/  logique applicative : périmètre de données, enchaînement des
               moteurs, règles métier. Ne connaît pas FastAPI : il lève des
               erreurs métier (services/erreurs.py), traduites en codes HTTP
               par core/erreurs.py.
    donnees/   accès en lecture à l'entrepôt DuckDB.
    auth/      sécurité et comptes : base relationnelle (SQLAlchemy), JWT,
               mots de passe, dépendances d'authentification, journal d'audit.
    core/      socle : configuration, journal de démarrage, moteurs optionnels,
               gestion des erreurs.
    main.py    assemblage de l'application.

Le détail et les règles sont dans docs/ARCHITECTURE_API.md.
"""
