"""Sécurité et comptes de la plateforme.

Base relationnelle (PostgreSQL en production, SQLite en repli/démo/tests),
séparée de l'entrepôt analytique DuckDB :

- `database.py` : moteur SQLAlchemy + session (URL via AUTH_DATABASE_URL)
- `models.py`   : tables (comptes, audit, demandes clients, tâches, jetons révoqués)
- `security.py` : hachage bcrypt, JWT signés, politique de mot de passe,
                  anti-brute-force (rate limiting)
- `deps.py`     : dépendances FastAPI (utilisateur courant, rôles)
- `journal.py`  : journal d'audit
- `emails.py`   : adresses de connexion dérivées du nom d'un établissement
- `seed.py`     : création du schéma + comptes de démonstration

Les routes /api/auth/* sont dans `api/routers/auth.py`, la logique de
connexion dans `api/services/auth.py`.
"""
