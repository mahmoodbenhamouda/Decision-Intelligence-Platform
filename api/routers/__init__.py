"""
Couche HTTP : un routeur par domaine, calqué sur les fonctionnalités du
frontend (`frontend/src/features/`).

Une route déclare son chemin, ses droits (dépendances `get_current_user`,
`require_directeur`, `require_interne`), valide le transport (taille et format
d'un fichier), journalise l'accès en lecture, puis appelle UN service. Elle ne
calcule rien et n'interroge aucune base.
"""
