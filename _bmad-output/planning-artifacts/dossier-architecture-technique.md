# Dossier d'Architecture Technique Complet (DIP)

**Projet :** Decision Intelligence Platform (DIP) pour PME Multi-Tenant
**Date :** 21 Mai 2026
**Auteur :** Mahmoud

---

## 1. Diagramme de Contexte
Le diagramme de contexte définit les frontières du système et ses interactions avec les acteurs externes.

```mermaid
graph TD
    UserPME([Utilisateurs PME]) <--> DIP[Plateforme DIP]
    UserGroupement([Gestionnaire Groupement]) <--> DIP
    SSMS_Views[SSMS: Vues Sécurisées] --> |Extraction n8n| DIP
    Files[Exports: CSV, XLSX, JSON] --> |Upload| DIP
    DataGen[Générateur Données Synthétiques] --> |Enrichissement| DIP
    Ollama[Inférence Ollama Locale] <--> |Inférence| DIP
    DIP --> |Actions| ProactiveOutput[Emails, Notifications, Dashboards]
```

---

## 2. Architecture des Composants (Component Architecture)
Une vue modulaire des briques logicielles composant le système.

```mermaid
graph TD
    subgraph UI_Layer [Frontend]
        ReactApp[React SPA]
    end

    subgraph API_Orchestration [Orchestrateur]
        Gateway[API Gateway / Auth]
        TenantMgr[Tenant Manager]
        MAS_Orch[MAS Orchestrator]
    end

    subgraph Ingestion_Pipeline [Ingestion & Simulation]
        n8n[n8n File Processor]
        DataGen[Synthetic Data Generator]
        RMQ[RabbitMQ Broker]
        SyncWorker[Sync Worker]
    end

    subgraph Data_Layer [Data Storage]
        PG[(PostgreSQL Multi-Schema)]
        DropZone[(File Drop Zone / S3-like)]
        VectorStore[(pgvector / Chroma)]
    end

    subgraph Intelligence_Core [IA Core]
        OllamaLocal[Ollama Instance]
        AgentEngine[CrewAI Framework]
    end

    ReactApp <--> Gateway
    Gateway --> TenantMgr
    TenantMgr --> MAS_Orch
    MAS_Orch --> AgentEngine
    AgentEngine --> OllamaLocal
    AgentEngine --> Data_Layer

    SSMS --> |Extraction| n8n
    n8n --> |Sync/Transformation| RMQ
    RMQ --> SyncWorker
    SyncWorker --> PG
```

---

## 3. Diagramme des Composants (Détaillé)
Détaille les interfaces et les dépendances entre sous-systèmes.

```mermaid
graph TD
    UI[React Frontend]
    
    subgraph API_Logic [Orchestrateur]
        GW[FastAPI Gateway]
        TM[Tenant Manager]
    end
    
    subgraph Intelligence [IA & MAS]
        MAS[CrewAI Manager]
        LLM[Ollama Inference]
    end
    
    subgraph Data [Persistance]
        DB_PG[(PostgreSQL Schema Isolation)]
        VS[(pgvector Store)]
        FILES[(Stockage Fichiers)]
    end
    
    subgraph Pipeline [Ingestion & Simulation]
        ING[n8n Multi-Source Orchestrator]
        GEN[Synthetic Data Generator]
        RMQ[RabbitMQ Broker]
        WKR[Sync Worker]
    end

    SSMS_V[(SSMS Secure Views)] --> ING
    FILES --> ING
    GEN --> RMQ
    ING --> RMQ
    RMQ --> WKR
    WKR --> DB_PG
```

---

## 4. Diagramme de Classes (Domaine)
Représentation des entités principales du modèle de données pivot.

```mermaid
classDiagram
    class Tenant {
        +int id
        +string name
        +string schema_name
        +string industry
    }
    class User {
        +int id
        +string role
        +int tenant_id
    }
    class Invoice {
        +int id
        +date date
        +float total_amount
        +string customer_name
        +string status
    }
    class StockItem {
        +int id
        +string sku
        +int quantity
        +float unit_cost
    }
    class AgentSession {
        +string session_id
        +int tenant_id
        +json memory_context
    }

    Tenant "1" -- "*" User
    Tenant "1" -- "*" Invoice
    Tenant "1" -- "*" StockItem
    Tenant "1" -- "*" AgentSession
```

---

## 5. Diagrammes de Séquence (Flux critiques)

### 5.1 Ingestion et Orchestration ETL (SQL Server -> n8n -> PostgreSQL)
```mermaid
sequenceDiagram
    participant SQL as SQL Server (SSMS)
    participant N8N as n8n (Self-hosted)
    participant RMQ as RabbitMQ
    participant Worker as Sync Worker
    participant DB as Postgres (DWH)
    participant MAS as Agents IA

    SQL->>N8N: Extraction automatique des données métier
    N8N->>N8N: Transformation & Synchronisation
    N8N->>RMQ: Publication des données normalisées
    RMQ-->>Worker: Dispatch
    Worker->>DB: UPSERT (Schema isolation)
    N8N->>MAS: Déclenchement Workflow Intelligent (Alertes/Analyse)
```

### 5.2 Requête Agent IA
```mermaid
sequenceDiagram
    participant User
    participant GW as API Gateway
    participant MAS as CrewAI Manager
    participant LLM as Ollama
    participant DB as Postgres (Schema)

    User->>GW: "Calculer mon risque de cash-flow"
    GW->>MAS: Initialize Agents (Tenant Context)
    MAS->>DB: Fetch Recent Invoices (Schema Filtered)
    DB-->>MAS: Financial Data
    MAS->>LLM: Analyze Trends & Predict
    LLM-->>MAS: Narrative Report + Actions
    MAS->>GW: Formatted Insight (XAI)
    GW->>User: Display Proactive Action
```

---

## 6. Diagramme d'Activités Global
Processus de transformation de la donnée brute en intelligence actionnable.

```mermaid
graph TD
    Start(Source SSMS Views / Fichiers) --> Extract[Extraction & Lecture n8n]
    Extract --> Sim[Enrichissement Synthétique / Simulation]
    Sim --> Trans[Validation & Normalisation]
    Trans --> Buffer[RabbitMQ Queue]
    Buffer --> Store[Stockage Isolé PostgreSQL]
    
    subgraph IA_Cycle [Cycle d'Intelligence]
        Store --> AgentScan[Agents Scannent les Anomalies]
        AgentScan --> LLM_Analysis[Analyse Ollama]
        LLM_Analysis --> GenerateAction[Génération de Recommandations]
    end
    
    GenerateAction --> UserNotify[Notification Proactive]
    GenerateAction --> Bench[Agrégation Anonymisée vers Global]
    Bench --> GlobalView[Dashboard Groupement]
```

---

## 7. Modèle Entité-Association (ERD)
Schéma détaillé des relations en base de données.

```mermaid
erDiagram
    TENANT ||--o{ USER : "has"
    TENANT ||--o{ INVOICE : "owns"
    TENANT ||--o{ STOCK_ITEM : "owns"
    TENANT ||--o{ AI_INSIGHT : "receives"
    INVOICE }|--|| CUSTOMER : "billed to"
    TENANT ||--o{ BENCHMARK : "contributes to"
    AI_INSIGHT }|--|| AGENT : "generated by"
    
    TENANT {
        uuid id PK
        string name
        string schema_name
        string sector
    }
    
    AI_INSIGHT {
        uuid id PK
        string type "Risk, Opportunity, Prediction"
        string message
        float confidence_score
        timestamp created_at
    }

    BENCHMARK {
        string sector PK
        date period PK
        float avg_payment_days
        float stock_turnover
    }
```

---

## 8. Diagramme de Déploiement
Infrastructure physique et conteneurisation.

```mermaid
graph TD
    subgraph Local_Server [Serveur Central Groupement / Edge]
        subgraph Docker_Network
            API[FastAPI Container]
            DB_PG[(PostgreSQL / pgvector)]
            N8N_C[n8n Container]
            Worker_C[Worker Container]
            RMQ_C[RabbitMQ Container]
            MAS_C[CrewAI Container]
        end
        
        subgraph GPU_Node
            Ollama_C[Ollama Container]
        end
    end
    
    Internet((Internet)) --> |SSL/TLS| API
    Inputs[Fichiers d'Exports / Upload] --> |Multipart/POST| API
    Inputs --> |File Move| N8N_C
    API <--> MAS_C
    MAS_C <--> Ollama_C
    MAS_C <--> DB_PG
```

---

## 9. Stack Technologique (Tech Stack)

Le choix des technologies est guidé par les principes de **souveraineté**, de **modularité** et de **performance locale**.

| Couche | Technologie(s) | Justification |
| :--- | :--- | :--- |
| **Frontend** | React, TailwindCSS, Shadcn/UI | UX moderne, réactive et composants réutilisables pour les dashboards. |
| **Backend / API** | Python (FastAPI), Pydantic | Performance élevée (async), documentation automatique et typage fort. |
| **IA / LLM Local** | Ollama, Llama 3 / Mistral | Inférence locale pour la confidentialité des données et la souveraineté. |
| **MAS Framework** | CrewAI | Orchestration d'agents autonomes avec gestion de rôle et processus. |
| **Base de Données** | PostgreSQL (Multischema), pgvector | Isolation forte par schéma et stockage vectoriel intégré pour le RAG. |
| **Source de Données** | SQL Server (SSMS) | Centralisation des données métier existantes. |
| **Orchestration ETL** | n8n (Self-hosted) | Orchestrateur ETL entre SQL Server et la plateforme. Automatise l'extraction, la transformation, la synchronisation et déclenche les workflows IA. |
| **Message Broker** | RabbitMQ | Résilience et lissage des flux d'ingestion asynchrones. |
| **Déploiement** | Docker, Docker Compose | Portabilité et isolation des services sur infrastructure locale. |
| **Observabilité** | Langfuse | Monitoring des performances des agents et traçabilité des coûts d'inférence. |

---

## 10. Synthèse des Stratégies Techniques

*   **Isolation :** Utilisation de schémas PostgreSQL pour garantir l'étanchéité totale entre PME.
*   **Agnosticisme & Confidentialité :** Couche de transformation n8n exploitant des Vues SQL filtrées. Le système ne manipule que les métadonnées nécessaires à la décision, préservant le secret industriel original.
*   **Intelligence Hybride :** Utilisation de données synthétiques pour compenser les restrictions d'accès, garantissant que les agents CrewAI disposent d'un historique d'entraînement suffisant.
*   **Intelligence Souveraine :** Déploiement local d'Ollama via Docker pour assurer que les informations extraites des vues sécurisées ne quittent jamais l'infrastructure du groupement.
*   **Scalabilité :** Utilisation de RabbitMQ pour lisser les flux d'ingestion et supporter des centaines de PME simultanément.
