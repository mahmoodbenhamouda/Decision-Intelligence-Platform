# ── Image API FastAPI (backend) ─────────────────────────────────────────────
# Build  : docker build -t overlyne-api .
# Run    : voir docker-compose.yml (recommandé)
FROM python:3.12-slim

# Dépendances système minimales (psycopg2-binary est autoportant)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Couche dépendances (mise en cache tant que requirements-api.txt ne change pas)
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Code applicatif
COPY config/ config/
COPY etl/ etl/
COPY ml_engine/ ml_engine/
COPY agents/ agents/
COPY rag/ rag/
COPY api/ api/
COPY scripts/ scripts/

# Artefacts d'exécution : modèles entraînés + entrepôt analytique + sorties
COPY models/ models/
COPY reports/ reports/
COPY output/ output/

# Utilisateur non-root (bonne pratique sécurité)
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=10 --start-period=60s \
  CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
