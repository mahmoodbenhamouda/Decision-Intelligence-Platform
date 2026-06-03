# Product Backlog - Decision Intelligence Platform (DIP)

Ce document liste l'ensemble des tâches et fonctionnalités à implémenter pour le projet DIP, organisées par Epics et priorisées pour un développement en 3 phases.

---

## Epic 1 : Infrastructure & Isolation (Foundation)
*Priorité : Cruciale (Phase 1)*

| ID | Titre | Description | Priorité |
| :--- | :--- | :--- | :--- |
| **ST-01** | Stack Docker-Compose | Mise en place de l'environnement conteneurisé (PostgreSQL, n8n, RabbitMQ, Ollama). | High |
| **ST-02** | Base de Données Multi-Schema | Script d'automatisation de création de schémas par Tenant dans PostgreSQL. | High |
| **ST-03** | API Gateway (FastAPI) | Initialisation de l'API avec authentification JWT et middleware de détection de Tenant. | High |
| **ST-04** | Tenant Manager Service | Service CRUD pour gérer l'onboarding des PME et leurs métadonnées. | Medium |

---

## Epic 2 : Sovereign Data Pipeline (ETL)
*Priorité : Haute (Phase 1)*

| ID | Titre | Description | Priorité |
| :--- | :--- | :--- | :--- |
| **ETL-01** | Connecteur Vues SSMS | Configuration de n8n pour extraire les données depuis les vues sécurisées (Filtering SQL). | High |
| **ETL-02** | Portail d'Upload & Générateur | Interface d'upload CSV et script d'enrichissement de données synthétiques. | High |
| **ETL-03** | Workflow n8n Multi-Source | Orchestration de l'ingestion hybride (Vues SQL + Fichiers) vers RabbitMQ. | High |
| **ETL-04** | Normalisation Modèle Pivot | Mapping des schémas restreints vers le modèle de données pivot du DWH. | Medium |

---

## Epic 3 : Intelligence Core (Agents & LLM)
*Priorité : Haute (Phase 1 & 2)*

| ID | Titre | Description Détaillée | Rôles & Outils | Statut |
| :--- | :--- | :--- | :--- | :--- |
| **AI-01** | Inférence Ollama | Déploiement local de Llama 3 / Mistral. | **Infra** | En cours |
| **AI-02** | **Agent Finance (CFO)** | **Analyse de Trésorerie** : Calcule le flux de cash, identifie les clients en retard de paiement. <br> **Outils** : `read_postgres_table`, `calculate_dso_tool`. | **CrewAI Agent** | **Prototype Ready** |
| **AI-06** | **Générateur Financier** | **Simulation Réaliste** : Génération de données synthétiques (PME) avec anomalies injectées. | **Python/Faker** | **Complété** |
| **AI-03** | **Agent Inventory (Stock)** | **Optimisation Stock** : Détecte le surstockage et prédit les ruptures basées sur l'historique de ventes. <br> **Outils** : `query_inventory_levels`, `forecast_demand_tool`. | **CrewAI Agent** |
| **AI-04** | **Agent Scribe (Report)** | **Storytelling Narratif** : Synthétise les trouvailles des agents CFO et Stock en un résumé "Exécutif" pour le manager. | **CrewAI Agent** |
| **AI-05** | RAG Engine (Memory) | Mise en place de `pgvector`. Permet aux agents de chercher des contextes historiques ou des documents PDF/CSV spécifiques au tenant. | **LangChain/PG** |

---

## 🚀 Détails des Étapes Primordiales

### 1. La "Graine" Multi-Tenant (Isolation)
C'est l'étape la plus critique. Sans elle, le projet n'est qu'un chatbot classique.
*   **Tâche :** Créer un `Tenant Context Manager` en Python.
*   **Détail :** Chaque requête arrivant à l'API doit porter un `X-Tenant-ID`. Le code doit automatiquement diriger les requêtes SQL vers le schéma `PME_A` ou `PME_B`.
*   **Risque :** Si mal fait, la PME A pourrait voir les factures de la PME B.

### 2. Le Pont n8n (Le "Souverain" ETL)
Au lieu de coder des scripts complexes pour chaque ERP, on utilise n8n comme interface visuelle.
*   **Tâche :** Créer un Workflow n8n générique.
*   **Détail :** 
    1. Node SQL Server (SSMS) : `SELECT * FROM Invoices`.
    2. Node JS Function : Transformation vers le format pivot.
    3. Node HTTP Request : Envoi vers notre API de Gateway.
*   **Pourquoi primordial ?** Cela permet d'ajouter une nouvelle PME en 10 minutes en changeant juste l'IP de la base source dans n8n.

### 3. Orchestration CrewAI (Le "Cerveau")
Définir comment les agents se parlent.
*   **Tâche :** Configurer le `Process.hierarchical`.
*   **Détail :** Un agent "Manager" reçoit la question de l'utilisateur. Il délègue à l'Agent Finance pour les chiffres, puis à l'Agent Scribe pour rédiger la réponse.
*   **Innovation :** Les agents n'utilisent que le schéma PostgreSQL de leur tenant assigné.

### 4. La Couche Aggregator (Benchmarking)
L'étape qui justifie le projet pour le "Groupement".
*   **Tâche :** Pipeline d'anonymisation.
*   **Détail :** Un script périodique calcule la moyenne du DSO de toutes les PME et la stocke dans un schéma `public_bench`. 
*   **Résultat :** Mourad (PME A) voit : "Votre délai de paiement est de 45 jours. La moyenne des PME industrielles du groupement est de 32 jours. Vous avez une marge de progression."

---

## Epic 4 : Frontend & User Experience
*Priorité : Moyenne (Phase 1 & 2)*

| ID | Titre | Description | Priorité |
| :--- | :--- | :--- | :--- |
| **UI-01** | Dashboard Multi-Tenant | Vue React permettant de switcher entre les données des différents tenants (pour le groupement). | High |
| **UI-02** | Module Storytelling | Composant d'affichage des rapports narratifs générés par les agents IA. | Medium |
| **UI-03** | Interface de Configuration ETL | Formulaires pour configurer les accès SSMS/n8n pour un nouveau tenant. | Low |
| **UI-04** | Visualisation XAI | Graphiques expliquant pourquoi l'agent a recommandé une action spécifique. | Medium |

---

## Epic 5 : Aggregator & Benchmarking (Advanced)
*Priorité : Basse (Phase 3)*

| ID | Titre | Description | Priorité |
| :--- | :--- | :--- | :--- |
| **AGG-01** | Collecteur Anonymisé | Service d'extraction des indicateurs clés (KPIs) vers un schéma "global" anonymisé. | Medium |
| **AGG-02** | Dashboard de Groupement | Vue macro-économique comparant les performances des PME du portefeuille. | Low |
| **AGG-03** | Moteur de recommandation inter-PME | IA suggérant des synergies ou meilleures pratiques basées sur les benchmarks. | Low |

---

## Roadmap d'Exécution (Gantt Simplifié)

1.  **Mois 1 : Foundation & Ingestion** (Epics 1 & 2) -> Livrable : Pipeline de données fonctionnel de SSMS vers PG.
2.  **Mois 2 : IA & MAS Core** (Epic 3) -> Livrable : Agents financiers capables d'analyser les données du tenant.
3.  **Mois 3 : UX & Dashboarding** (Epic 4) -> Livrable : Interface web unifiée et visualisations.
4.  **Mois 4 : Benchmarking & Finalisation** (Epic 5) -> Livrable : Couche intelligente globale et rapport final de PME.
