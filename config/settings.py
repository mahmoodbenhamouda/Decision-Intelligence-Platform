"""
config/settings.py
==================
Configuration centralisée de la plateforme Finance AI Agent.
Utilise Pydantic Settings pour la validation et la gestion des variables d'environnement.

Usage :
    from config.settings import settings
    print(settings.llm_provider)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

try:
    from pydantic_settings import BaseSettings
    from pydantic import Field, validator
except ImportError:
    from pydantic import BaseSettings, Field, validator  # type: ignore


# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """Configuration principale de la plateforme Finance AI Agent."""

    # ── Application ───────────────────────────────────────────────────────────
    app_name: str = "Finance AI Agent"
    app_version: str = "2.0.0"
    app_description: str = "Plateforme Intelligence Artificielle Agentique pour l'Analyse Financière"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"

    # ── Paths ─────────────────────────────────────────────────────────────────
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data_pfe"
    models_dir: Path = BASE_DIR / "models"
    reports_dir: Path = BASE_DIR / "reports"
    output_dir: Path = BASE_DIR / "output"
    rag_dir: Path = BASE_DIR / "rag"
    plots_dir: Path = BASE_DIR / "reports" / "plots"

    # ── LLM Configuration ─────────────────────────────────────────────────────
    llm_provider: Literal["openai", "anthropic", "groq", "ollama", "google"] = "groq"
    llm_model: str = "openai/gpt-oss-120b"              # Groq — modèle production courant (2026)
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096
    llm_timeout: int = 60

    # OpenAI
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-3-haiku-20240307"

    # Groq (API gratuite — recommandée pour PFE)
    # NB : Groq a retiré llama-3.1/3.3 en 2026 → modèle production courant = openai/gpt-oss-120b
    groq_api_key: Optional[str] = None
    groq_model: str = "openai/gpt-oss-120b"

    # Google Gemini
    google_api_key: Optional[str] = None
    google_model: str = "gemini-1.5-flash"

    # Ollama (modèle local — 0 coût)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "mistral:7b-instruct"

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_provider: Literal["openai", "huggingface", "ollama"] = "huggingface"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dimension: int = 384

    # ── RAG ───────────────────────────────────────────────────────────────────
    rag_enabled: bool = True
    rag_vectorstore: Literal["faiss", "chroma"] = "faiss"
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_top_k: int = 4
    rag_score_threshold: float = 0.5

    # ── Memory ────────────────────────────────────────────────────────────────
    memory_enabled: bool = True
    memory_backend: Literal["sqlite", "redis"] = "sqlite"
    memory_db_path: Path = BASE_DIR / "memory" / "sessions.db"
    memory_max_history: int = 20
    redis_url: str = "redis://localhost:6379"

    # ── ML Pipeline ───────────────────────────────────────────────────────────
    ml_n_cv_folds: int = 5
    ml_optuna_trials: int = 30
    ml_optuna_timeout: int = 120
    ml_run_dl: bool = True
    ml_run_optuna: bool = True
    ml_run_shap: bool = True
    ml_n_test_periods: int = 12

    # ── Agent Configuration ───────────────────────────────────────────────────
    agent_max_iterations: int = 10
    agent_verbose: bool = True
    agent_handle_parsing_errors: bool = True
    supervisor_temperature: float = 0.0
    confidence_threshold: float = 0.7     # Sous ce seuil → human review
    human_in_loop_enabled: bool = False   # Activer en production

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    api_secret_key: str = "finance-ai-agent-secret-change-in-production-2026"
    api_algorithm: str = "HS256"
    api_token_expire_minutes: int = 480
    cors_origins: List[str] = ["http://localhost:8501", "http://localhost:3000"]

    # ── Monitoring ────────────────────────────────────────────────────────────
    langsmith_enabled: bool = False
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "finance-ai-agent"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ── Cache ─────────────────────────────────────────────────────────────────
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600         # 1 heure
    llm_cache_enabled: bool = True

    # ── Business Context ──────────────────────────────────────────────────────
    default_currency: str = "DT"          # Dinar Tunisien
    default_locale: str = "fr_TN"
    fiscal_year_start_month: int = 1
    late_payment_threshold_days: int = 30
    critical_payment_threshold_days: int = 90

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: Optional[Path] = BASE_DIR / "logs" / "finance_agent.log"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retourne l'instance singleton des settings."""
    return Settings()


# Instance globale
settings = get_settings()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def ensure_dirs() -> None:
    """Crée tous les répertoires nécessaires s'ils n'existent pas."""
    dirs = [
        settings.models_dir,
        settings.reports_dir,
        settings.output_dir,
        settings.plots_dir,
        settings.rag_dir,
        settings.memory_db_path.parent,
        settings.base_dir / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def get_llm(model: Optional[str] = None):
    """
    Instancie le LLM configuré.
    Lit les clés API depuis os.environ à chaque appel (bypass du cache Settings)
    pour que les clés définies dans .env ou via la sidebar Streamlit soient toujours prises en compte.
    `model` permet de forcer un modèle précis (utile pour un repli si un modèle est déprécié).
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)  # recharge .env sans écraser les vars déjà définies

    # Lire depuis os.environ directement (pas depuis le singleton caché)
    provider     = os.environ.get("LLM_PROVIDER", settings.llm_provider)
    groq_key     = os.environ.get("GROQ_API_KEY", "") or settings.groq_api_key or ""
    openai_key   = os.environ.get("OPENAI_API_KEY", "") or settings.openai_api_key or ""
    anthropic_key= os.environ.get("ANTHROPIC_API_KEY", "") or settings.anthropic_api_key or ""
    google_key   = os.environ.get("GOOGLE_API_KEY", "") or settings.google_api_key or ""

    # Modèle Groq : override explicite > variable d'env GROQ_MODEL > défaut settings
    groq_model   = model or os.environ.get("GROQ_MODEL", "") or settings.groq_model
    openai_model = model or settings.openai_model

    temperature  = settings.llm_temperature
    max_tokens   = settings.llm_max_tokens

    if provider == "groq" and groq_key:
        try:
            from langchain_groq import ChatGroq
            return ChatGroq(
                api_key=groq_key,
                model=groq_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except ImportError:
            pass

    if provider == "openai" and openai_key:
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                api_key=openai_key,
                model=openai_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except ImportError:
            pass

    if provider == "anthropic" and anthropic_key:
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                api_key=anthropic_key,
                model=settings.anthropic_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except ImportError:
            pass

    if provider == "google" and google_key:
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                google_api_key=google_key,
                model=settings.google_model,
                temperature=temperature,
            )
        except ImportError:
            pass

    # Essai auto : Groq si une clé est présente (peu importe le provider déclaré)
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            return ChatGroq(
                api_key=groq_key,
                model=groq_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            pass

    # Fallback : Ollama local (0 coût)
    try:
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=temperature,
        )
    except ImportError:
        pass

    # Fallback ultime : mode mock pour développement sans LLM
    class MockChatModel:
        def invoke(self, *args, **kwargs):
            class MockResponse:
                content = "[Mode mock — aucune clé API valide trouvée. Configurez GROQ_API_KEY dans .env]"
            return MockResponse()

    return MockChatModel()


def get_embeddings():
    """Instancie le modèle d'embeddings configuré."""
    provider = settings.embedding_provider

    if provider == "openai" and settings.openai_api_key:
        try:
            from langchain_openai import OpenAIEmbeddings
            return OpenAIEmbeddings(
                api_key=settings.openai_api_key,
                model="text-embedding-3-small",
            )
        except ImportError:
            pass

    # HuggingFace local (gratuit, multilingue)
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=settings.embedding_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
    except ImportError:
        pass

    # Fallback : Ollama embeddings
    try:
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(
            base_url=settings.ollama_base_url,
            model="nomic-embed-text",
        )
    except ImportError:
        raise RuntimeError("Aucun modèle d'embeddings disponible. Installez langchain-huggingface.")
