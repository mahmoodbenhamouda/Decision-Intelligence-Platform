# Architecture de l'API — en couches

L'API FastAPI suit une **architecture en couches** : chaque couche a une seule
responsabilité et ne connaît que la couche du dessous.

```
            ┌──────────────────────────── routers/ ────────────────────────────┐
            │  couche HTTP : chemin, méthode, droits d'accès, fichier reçu,     │
            │  journal des accès — puis UN appel de service                     │
            └───────────────────────────────┬──────────────────────────────────┘
                                            │ schémas Pydantic (schemas/)
            ┌──────────────────────────── services/ ───────────────────────────┐
            │  logique applicative : périmètre de données, chaîne de repli,     │
            │  règles métier — sans FastAPI ; lève des erreurs métier           │
            └──────────┬────────────────────┬─────────────────────┬────────────┘
                       │                    │                     │
            ┌──────────▼─────────┐ ┌────────▼─────────┐ ┌─────────▼──────────────┐
            │ auth/ (SQLAlchemy) │ │ donnees/ (DuckDB)│ │ ml_engine : passerelle │
            │ comptes, tâches,   │ │ entrepôt, lecture│ │ + moteur KPI, agents   │
            │ demandes, audit    │ │ seule            │ │                        │
            └────────────────────┘ └──────────────────┘ └────────────────────────┘
```

Avant cette organisation, `api/main.py` faisait 1 145 lignes : application,
16 routes, calcul pandas de secours, rédaction de la synthèse, règles de
périmètre, lecture directe de fonctions privées du moteur KPI. Les routes
d'administration, du portail et des tâches se trouvaient dans le paquet
`api/auth/`, mêlées à la sécurité, et contenaient leurs requêtes SQL.
`api/main.py` fait désormais une centaine de lignes et ne déclare aucune route.

## Organisation des dossiers

```
api/
  main.py                assemblage : CORS, gestion des erreurs, routeurs, cycle de vie
  core/                  socle
    config.py            variables d'environnement (CORS, hôte, port, rechargement)
    demarrage.py         journal de démarrage (affiché une fois), contrôle des modèles
    moteurs.py           moteur KPI et copilote, chargés sans bloquer le démarrage
    erreurs.py           erreur métier → code HTTP ; base injoignable → 503
  schemas/               contrats d'entrée et de sortie (Pydantic), un fichier par domaine
    filtres.py           FilterRequest, CopilotRequest
    auth.py  admin.py  portail.py  taches.py
  routers/               un routeur par fonctionnalité du frontend
    sante.py             GET  /api/health
    auth.py              /api/auth/login, /logout, /me
    tableau_de_bord.py   POST /api/dashboard, /api/ai_insight
    tresorerie.py        POST /api/forecast, /api/payment-scenarios
    briefing.py          POST /api/fleet/briefing
    copilote.py          POST /api/copilot, /api/copilot/upload
    churn.py             GET  /api/churn
    commercial.py        GET  /api/commercial/devis, /marge, /recommandations
    stock.py             GET  /api/stock, /stock/risk, /stock/forecast, /api/supply
    modeles.py           GET  /api/models/metrics
    taches.py            /api/taches/*
    portail.py           /api/portal/*
    admin.py             /api/admin/*
    ocr.py               /api/ocr/*
  services/              logique applicative, un module par domaine (mêmes noms)
    erreurs.py           erreurs métier : DonneesInvalides, AccesRefuse, Introuvable…
    perimetre.py         isolation des données par rôle
    filtres.py           filtres → dictionnaire du moteur, résumé pour l'écran
    tableau_de_bord.py   agent → moteur d'indicateurs, sinon erreur explicite
    rapport.py           synthèse écrite déterministe (sans LLM)
    fichiers.py          lecture des CSV et PDF joints au copilote
    serialisation.py     numpy / pandas → JSON
    auth.py  admin.py  portail.py  taches.py  ocr.py  copilote.py  briefing.py
    tresorerie.py  churn.py  commercial.py  stock.py  modeles.py
  donnees/
    entrepot.py          les rares lectures SQL directes de l'entrepôt (lecture seule)
  auth/                  sécurité et comptes
    database.py  models.py      base relationnelle (PostgreSQL, repli SQLite)
    security.py                 bcrypt, JWT, politique de mot de passe, anti-force brute
    deps.py                     dépendances FastAPI : utilisateur courant, rôles
    journal.py                  journal d'audit
    emails.py  seed.py
```

La correspondance avec le frontend est directe : `frontend/src/features/stock/`
appelle `api/routers/stock.py`, qui appelle `api/services/stock.py`.

## Règles

Chaque règle est vérifiée par un test (`tests/test_architecture_api.py`),
pas seulement décrite.

1. **Une route ne calcule rien et n'interroge aucune base.** Elle n'importe ni
   `ml_engine`, ni `agents`, ni `pandas`, ni `duckdb`, ni `sqlalchemy` (la
   session de base lui arrive par `Depends(get_db)` et est transmise telle
   quelle au service). Elle contrôle ce qui relève du transport — format et
   taille d'un fichier reçu (415, 413) — puis appelle un service.
2. **Un service ne connaît pas FastAPI.** Il reçoit des valeurs Python (schéma,
   utilisateur, session) et renvoie des données prêtes à sérialiser. Une
   situation anormale se signale par une **erreur métier**, jamais par un code
   HTTP.
3. **L'API passe par la passerelle des modèles.** Aucun module de l'API
   n'importe un module de modèle (décrochage, conversion, marge, crédit,
   segmentation, réapprovisionnement, fin de vie, recommandation, risque stock,
   prévision d'encaissements, registre) ni un nom privé du moteur KPI : tout
   passe par `ml_engine/passerelle.py`, qui applique les décisions du registre.
   C'est la même règle que pour les agents.
4. **Toute erreur métier a un code HTTP**, défini à un seul endroit
   (`api/core/erreurs.py`), et la réponse garde la forme habituelle de FastAPI,
   `{"detail": …}`.
5. **Le périmètre de données est décidé côté serveur**, dans les services
   (règle ci-dessous), jamais seulement masqué à l'écran.
6. **Le journal d'audit est écrit par la couche qui connaît l'événement** : la
   route pour un accès en lecture (`action="access"`, avec son chemin), le
   service pour une action métier (connexion, création, modification, refus).

### Erreurs métier et codes HTTP

| Erreur (`api/services/erreurs.py`) | Sens | Code |
|---|---|---|
| `DonneesInvalides` | valeur hors liste, date illisible, mot de passe trop faible | 422 |
| `IdentifiantsInvalides` | adresse ou mot de passe incorrect | 401 |
| `AccesRefuse` | authentifié, mais pas autorisé pour cette opération | 403 |
| `Introuvable` | l'objet n'existe pas — ou n'est pas visible par cet utilisateur | 404 |
| `Conflit` | doublon, alerte déjà confiée, modèle retiré | 409 |
| `TropDeTentatives` | limite de connexions atteinte | 429 |
| `ErreurInterne` | dépendance serveur absente, listes désalignées | 500 |

Une base d'authentification injoignable reste un **503** avec la cause et la
marche à suivre, sans trace technique (voir `api/core/erreurs.py`).

### Périmètre de données

`api/services/perimetre.py` porte la règle, une seule fois :

| Rôle | Filtres analytiques |
|---|---|
| `directeur` | les siens, sans restriction |
| `employe` | **refus** : un employé travaille sur des tâches, aucun périmètre de données ne lui est ouvert |
| `client` | `selected_clients` **réécrit** avec son `client_code`, quoi que la requête contienne ; sans code, refus |

Elle s'applique au tableau de bord, à la synthèse, au copilote (question **et
fichier joint**), au briefing, aux scénarios d'encaissement et aux
recommandations. Les options de filtre renvoyées à un client ne contiennent
que lui-même. Le décrochage, le portail et l'OCR, dont le filtrage porte sur
des lignes précises, appliquent la même règle dans leur propre service.

## Parcours d'une requête : `POST /api/dashboard`

1. `routers/tableau_de_bord.py` — FastAPI valide le corps (`FilterRequest`) et
   résout l'utilisateur (`get_current_user`, JWT en cookie httpOnly ou Bearer).
2. La route réduit la requête au périmètre (`perimetre.restreindre`), journalise
   l'accès, puis appelle `tableau_de_bord.indicateurs(req, user)`.
3. Le service essaie le **copilote**, puis le **moteur d'indicateurs**
   direct ; si l'entrepôt est indisponible, il le dit (voir « Un seul
   entrepôt » ci-dessous) plutôt que d'afficher des chiffres calculés autrement.
4. La réponse est rendue telle quelle ; si le service lève `AccesRefuse`,
   `core/erreurs.py` la traduit en 403.

## Ajouter une route

1. Le contrat : un schéma dans `api/schemas/<domaine>.py` si la route reçoit un
   corps JSON.
2. La logique : une fonction dans `api/services/<domaine>.py`, qui lève une
   erreur métier en cas de problème et passe par `ml_engine.passerelle` pour
   toute sortie de modèle.
3. La route : quelques lignes dans `api/routers/<domaine>.py` — dépendance de
   rôle, journal d'accès, appel du service. Un nouveau domaine s'ajoute à la
   liste des routeurs de `api/main.py`.
4. Les tests : `tests/test_architecture_api.py` vérifie les règles ; un test
   de la route vérifie les droits (401 sans jeton, 403 hors rôle).

## Vérification de la réorganisation

La réorganisation ne change pas le contrat de l'API. Pour le démontrer :

* **même table des routes** : les 54 opérations (méthode, chemin, paramètres,
  corps, codes de réponse) et les schémas publiés par OpenAPI sont identiques
  avant et après ;
* **mêmes réponses** : un harnais a appelé 115 fois l'API — chaque route, avec
  les trois rôles, plus un parcours complet d'écritures (tâche confiée,
  affectée, close ; action client ; demande traitée ; compte créé, modifié,
  désactivé, supprimé ; déconnexion) — sur la même copie de l'entrepôt, avec
  l'ancien puis le nouveau code. Les 115 réponses sont identiques (statut et
  corps, horodatages exclus), sauf les deux changements voulus ci-dessous ;
* **tests** : à l'issue de cette refonte, la suite comptait 577 tests, dont 44 nouveaux : 43 sur
  les règles d'architecture et le périmètre, 1 sur le fichier joint au
  copilote.

### Deux changements de comportement, voulus

1. **Fichier joint au copilote** (`POST /api/copilot/upload`) : les filtres
   envoyés avec le fichier n'étaient pas réduits au périmètre du compte. Un
   client pouvait donc faire lire au copilote les indicateurs d'un autre
   client. Ils passent maintenant par la même règle que toutes les routes
   analytiques (test : `test_fichier_joint_au_copilote_reste_dans_le_perimetre`).
2. **Compte employé** : la documentation annonçait qu'un employé n'avait accès
   à aucun tableau de bord, mais la fonction qui l'appliquait
   (`enforce_client_scope`) n'était appelée nulle part. L'employé était refusé
   par hasard, avec le message « Compte client sans code client associé » — et
   un employé auquel on aurait attribué un code client aurait vu les données
   de ce client. La règle est maintenant appliquée : 403, « Un compte employé
   n'a pas accès aux tableaux de bord. »

### Un seul entrepôt

La première version de cette réorganisation gardait, en dernier repli du
tableau de bord, un calcul pandas sur un second entrepôt chargé depuis les CSV
(`connectors/`, `ml_engine/preprocessing/`). Ce second entrepôt appliquait
d'autres règles — il comptait notamment les avoirs comme des ventes — et ne
servait qu'en cas de panne. Il a été retiré avec la mise en place de l'ETL
(docs/DATA_WAREHOUSE.md) : si le moteur d'indicateurs ne répond pas, l'API
renvoie « Entrepôt de données indisponible » au lieu de chiffres faux.
