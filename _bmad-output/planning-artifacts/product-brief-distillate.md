# LLM Distillate: Decision Intelligence Platform (Tunisia SME)

## Strategic Core
- **Concept:** "Action Layer" for SMEs.
- **Wedge:** El Fatoora (e-invoicing) as a high-quality data ingestion vector.
- **Moat:** Sovereign local AI (Ollama), XAI (Explainability), and deep integration with regional ERPs (Odoo, Sage, SAP B1).

## Technical Requirements for PRD
- **Architecture:** Modular Monolith (PostgreSQL, dbt).
- **Orchestration:** n8n (visual workflow) + **Collaborative Multi-Agent System (MAS)** where agents share context (e.g., Stock agent informs Finance agent).
- **AI Stack:** Ollama (local LLM inference), Vector database for RAG (Retrieval Augmented Generation).
- **Interoperability:** REST APIs + Webhooks for ERP-agnostic connectivity.
- **XAI Specs:** Confidence scores, SHAP/LIME-like visual explanations, and lineage from Data Warehouse to build trust for automation.

## Persona/UX Details
- **Tone:** Proactive, authoritative yet collaborative.
- **Interface:** Natural Language Interface (NLI) first. Intelligent assistants > Static dashboards.
- **Automation Roadmap:**
    - **V1 (Recommendation):** Human-in-the-loop for all decisions.
    - **V2 (Semi-Autonomous):** Automated execution for low-risk/routine tasks under predefined rules and human supervision.

## Constraints
- **Infrastructure:** Must support on-premise or local cloud deployment (Tunisian data laws).
- **Performance:** Real-time recommendation updates from ERP streams.
- **Cost:** Low operational overhead for SMEs (Open Source priority).
