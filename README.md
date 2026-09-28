# Decision-Intelligence-Platform
un système de multi-agents IA, une architecture Data Warehouse robuste. Passer de la réaction à l'anticipation stratégique, tout en garantissant la souveraineté des données.

## Démarrage rapide (application multi-comptes)

```bash
pip install -r requirements.txt
cp .env.example .env              # renseigner JWT_SECRET_KEY (et AUTH_DATABASE_URL pour PostgreSQL)
python -m etl.construire          # construit l'entrepôt de données (≈ 6 s, automatique ensuite)
python -m api.auth.seed           # crée directeur@overlyne.tn + comptes clients (codes ERP réels)
python api/main.py                # API :9000
cd frontend && npm install && npm run dev   # UI :4000 → écran /login
```

Rôles : `directeur` (vue globale), `employe` (uniquement les tâches qui lui sont
confiées, aucun accès aux tableaux de bord) et `client` (isolation stricte de ses
données, forcée côté serveur). Détails : `docs/SECURITY.md`.

La plateforme ne s'arrête pas au constat : une alerte devient une **tâche
confiée**, le client **agit** depuis son espace, et le résultat obtenu est mesuré
puis renvoyé vers les modèles — voir `docs/BOUCLE_ACTION.md`.

Identifiants de démonstration (dérivés du nom de l'établissement) :

| Compte | Identifiant | Mot de passe |
|---|---|---|
| Direction | `directeur@overlyne.tn` | `Directeur#2026` |
| Recouvrement (employé) | `recouvrement@overlyne.tn` | `Employe#2026` |
| Commercial (employé) | `commercial@overlyne.tn` | `Employe#2026` |
| Logistique (employé) | `logistique@overlyne.tn` | `Employe#2026` |
| Hôpital Militaire de Tunis | `hopital-militaire-de-tunis@overlyne.tn` | `Client#20261` |
| C.H.U. Charles Nicolle | `chu-charles-nicolle@overlyne.tn` | `Client#20262` |
| C.H.U. Habib Bourguiba | `chu-habib-bourguiba@overlyne.tn` | `Client#20263` |

## Déploiement conteneurisé (stack complète)

```bash
cp .env.example .env && docker compose up -d --build   # PostgreSQL + API + frontend
docker compose exec api python -m api.auth.seed        # comptes de démo
```

CI GitHub Actions (`.github/workflows/ci.yml`) : suite de tests backend, typecheck TypeScript strict, build Next.js et build de l'image Docker à chaque push.

## Science des données — ce que servent les agents

Onze modules mesurés hors période, tous branchés sur la flotte d'agents par une passerelle
unique qui consulte le registre (`ml_engine/passerelle.py`) :

| Module | Méthode | Métrique hors période | Accuracy (classe majoritaire) · balanced | Agent |
|---|---|---|---|---|
| Décrochage client | régression logistique | AUC 0,922 | 93,0 % (90,8 %) · 72,2 % | Risque client |
| Segmentation | KMeans k=5 | silhouette 0,468 | — | Risque client |
| Conversion des devis | régression logistique | AUC 0,717 | 77,5 % (90,6 %) · 64,0 % | Commercial |
| Érosion de marge | gradient boosting | AUC 0,797 | 77,7 % (78,3 %) · 67,6 % | Commercial |
| Recommandation de produits | LightGBM servi · **Wide & Deep (PyTorch)** challenger | NDCG@10 0,344 · 0,350 | — | Commercial |
| Conditions de crédit | règle mesurée | AUC 0,920 | 90,4 % (59,2 %) · 91,9 % | Recouvrement |
| Échéancier 1 mois | carnet d'échéances | MAPE 1,27 % | — | Trésorerie |
| Demande mensuelle | médiane robuste | MAPE 15,71 % | — | Stock & Approvisionnement |
| Demande par référence (réactifs) | médiane 12 mois servie · LightGBM challenger refusé (−1,57 pt) — 31 méthodes comparées | WAPE 38,3 % (test 18 mois) | — | Stock & Approvisionnement |
| Réapprovisionnement | refusé → repli | AUC 0,930 | 83,5 % (65,1 %) · 84,5 % | Stock & Approvisionnement |
| Fin de commercialisation | refusé → règle servie | AUC 0,835 | 95,9 % (97,0 %) · 57,3 % | Stock & Approvisionnement |
| Risque stock | **retiré** (cible simulée) | AUC 0,856 | 89,0 % (88,0 %) · 55,2 % | Volet fiabilité (surveillance) |
| Lecture de factures | LayoutLMv3 affiné | exactitude par champ 79,9 % (règles 24,4 %) | — | chaîne OCR (hors flotte) |

Tableau à jour : `python scripts/tableau_metriques.py` · registre : `python -m ml_engine.registre`.

## Organisation du dépôt

```text
api/          API FastAPI en couches : routes (HTTP) → services → accès aux données
etl/          construction de l'entrepôt Kimball (python -m etl.construire)
ml_engine/    modèles, registre et passerelle agents ↔ modèles, OCR
agents/       flotte d'agents LangGraph et copilote FinBot (agents/copilote/)
rag/          base documentaire du copilote
frontend/     interface Next.js (architecture MVVM, frontend/ARCHITECTURE.md)
tests/        suite pytest (python -m pytest -q)
scripts/      maintenance, générateurs de documents, analyses (docs/SCRIPTS.md)
notebooks/    exploration des données (compréhension des données, CRISP-DM phase 2)
evaluation_demande/, evaluation_ocr/   études reproductibles de la demande et de l'OCR
docs/         documentation, Gantt et dictionnaire des données
config/       paramètres (lus depuis .env)
```

Non versionnés (`.gitignore`) : les exports ERP (`data_pfe/`), les sorties
régénérables (`output/`, `reports/` sauf `METRICS_REPORT.md`, `models/`) et les
archives locales `_sauvegarde_*.zip` faites avant chaque refonte.

## Documentation

- `docs/METHODOLOGIE.md` — **méthodologie de travail** : démarche itérative et incrémentale inspirée de Scrum, CRISP-DM pour chaque modèle, incréments reliés au Gantt (`docs/Gantt_PFE_Overlyne_27avril-27octobre_2026.xlsx`)
- `frontend/ARCHITECTURE.md` — **architecture MVVM du frontend** : Model (types, services, règles), ViewModel (hooks), View (composants), organisation par fonctionnalité
- `docs/DATA_WAREHOUSE.md` — **entrepôt de données (Kimball)** : faits au grain déclaré, dimensions conformes, marts, vues de présentation, contrôles ; ETL `etl/` (`python -m etl.construire`)
- `docs/ARCHITECTURE_API.md` — **architecture en couches de l'API** : routes (HTTP), services (logique, sans FastAPI), accès aux données ; règles vérifiées par les tests
- `docs/KPI_FORMULES.md` — **formule exacte de chaque KPI** (fidèle au code), limites assumées, valeurs de référence
- `docs/DONNEES_MANQUANTES.md` — absence de dates de règlement : preuve, impact par indicateur, scénarios en réponse, demande technique à l'entreprise
- `docs/DEMO.md` — **kit de soutenance** : scénario minuté, plans B, questions/réponses du jury
- `docs/STOCK_SIMULE.md` — module de gestion de stock sur **données simulées** : modèle, marquage, tests
- `docs/OCR.md` — service OCR transversal : extraction, facture structurée, rapprochement ERP, base documentaire
- `docs/SECURITY.md` — authentification (bcrypt, JWT, rate limiting), schéma BDD, RBAC & preuves d'isolation
- `docs/AVATAR_3D.md` — avatar 3D Ready Player Me/Three.js (visèmes, émotions, replis)
- `docs/ARCHITECTURE_AGENTS.md` — schéma de la flotte d'agents et **quel agent consomme quel modèle**
- `docs/XAI.md` — **explicabilité** : pourquoi ce client, ce devis, ce produit — décomposition exacte, SHAP, règles, et ce que le module refuse de faire
- `docs/TESTS.md` — **ce que les tests démontrent** : une famille par ligne, et les 20 tests à citer (`python -m pytest -m vitrine`)
- `docs/SCRIPTS.md` — à quoi sert chacun des scripts : trois commandes au quotidien, le reste étant des pièces justificatives
- `docs/BOUCLE_ACTION.md` — **la boucle d'action** : tâches confiées, actions des clients, mesure de l'impact et retour des résultats vers les modèles
- `docs/DEEP_LEARNING.md` — **recommandation de produits par réseau Wide & Deep (PyTorch)** : protocole, résultats, décision
- `reports/METRICS_REPORT.md` — métriques ML consolidées (méthodologie, CV, ablations, limites, **accuracy §0 bis**, **deep learning §8**)
- Tests : `python -m pytest -q` — **642 tests** (intégrité, entrepôt, sémantique ERP, modèles, passerelle agents ↔ modèles, flotte, copilote, stock, OCR, auth/RBAC, admin/portail, boucle d'action). Synthèse lisible : `docs/TESTS.md`. Démonstration rapide : `python -m pytest -m vitrine -v` (20 tests emblématiques, moins d'une minute).
- Deep learning : `python -m ml_engine.deep.recommandation` (PyTorch requis pour mesurer le Wide & Deep ; l'API n'en dépend pas)
- Avant une démo : `python scripts/preflight_demo.py` (contrôle tous les points de panne)
- Après une mise à jour de scikit-learn : `python scripts/retrain_all.py` (ré-aligne les modèles **et rapatrie les résultats du terrain** dans l'entrepôt)
- Démarrage sans rechargement automatique (recommandé en démo) : `API_RELOAD=0 python api/main.py`
