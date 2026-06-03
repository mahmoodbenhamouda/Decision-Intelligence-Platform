# Plan de Réalisation PFE : Plateforme de Decision Intelligence (6 mois, 100% Gratuit)

## 1. Stack Technologique (Open Source & Gratuit)
Pour respecter la contrainte de gratuité et de rapidité de mise en œuvre :
*   **Base de Données / DW :** PostgreSQL (Robuste, gratuit, supporte le partitionnement et JSONB).
*   **ETL & Transformation :** Python (Pandas/SQLAlchemy) + dbt Core (version gratuite en ligne de commande).
*   **Orchestration :** Prefect (Self-hosted) ou simple Cron/Scripts Python pour la phase 1.
*   **BI / Visualisation :** Apache Superset (Alternative gratuite et puissante à Power BI) ou Metabase (Open Source).
*   **IA / Science des Données :** Scikit-learn, XGBoost, Statsmodels.
*   **LLM / Agents :** Ollama (pour faire tourner des modèles comme Llama 3 ou Mistral localement gratuitement) + LangChain.
*   **Conteneurisation :** Docker & Docker Compose.

## 2. Planning Réaliste (6 mois)

### Mois 1 : Analyse & Infrastructure
*   Installation de l'environnement Docker.
*   Modélisation de la base PostgreSQL (Schéma en étoile simplifié).
*   Validation des sources de données (fichiers CSV, bases existantes).

### Mois 2 : ETL & Entrepôt de Données
*   Développement des scripts Python pour charger les données dans PostgreSQL.
*   Mise en place de **dbt Core** pour les transformations SQL (création des tables de faits et dimensions).
*   Historisation basique (SCD Type 1 ou 2 sur les clients critiques).

### Mois 3 : Business Intelligence & KPIs
*   Installation et configuration d'**Apache Superset**.
*   Création des premiers tableaux de bord : Ventes, Retards de paiement, Stocks.
*   Mise en place de filtres interactifs pour les utilisateurs métiers.

### Mois 4 : Intelligence Artificielle (Modèles)
*   Développement du modèle de prédiction des ventes (Séries temporelles avec Statsmodels/Prophet).
*   Développement du modèle de risque de retard de paiement (Classification XGBoost).
*   Génération des prédictions et stockage dans une table PostgreSQL dédiée.

### Mois 5 : Agents IA & Assistant
*   Installation d'**Ollama** pour le LLM en local.
*   Création d'un assistant RAG simple avec LangChain capable de lire les KPIs de la base de données.
*   Prototype de chat "Text-to-SQL" pour poser des questions en langage naturel sur les données.

### Mois 6 : Finalisation, Tests & Mémoire
*   Intégration finale des composants.
*   Tests de performance et validation des résultats avec les utilisateurs.
*   Rédaction du mémoire de PFE et préparation de la soutenance.

## 3. Optimisations pour le PFE
*   **Priorité à la Valeur Métier :** Ne pas essayer de tout automatiser. Si une source de données est trop complexe, faire un import manuel propre pour le prototype.
*   **Local-First :** Tout faire tourner sur une machine locale puissante ou un petit serveur gratuit (type Oracle Cloud Free Tier) pour éviter les coûts cloud d'AWS/Azure.
*   **Focus Jury :** Mettre l'accent sur l'intégration "IA + Data" qui est très valorisée, même si le volume de données n'est pas colossal.
