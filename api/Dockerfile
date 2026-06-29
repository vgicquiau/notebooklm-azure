FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
# Le frontend n'est jamais copié dans l'image déployée : il ne tourne qu'en
# local (start-dev.ps1). api/main.py ne monte la racine "/" que si frontend/
# existe sur disque -- absent ici, le conteneur ne sert donc que l'API JSON
# (pas de page web publique, pas de fuite de l'API Key via une page HTML).

# ingest/indexer.py est importé par api/main.py (ensure_index() au démarrage,
# auto-réparation de l'index Azure AI Search) et par api/routers/ingest.py.
# N'a besoin que d'azure-search-documents/azure-identity (déjà dans
# api/requirements.txt) -- les autres modules d'ingest/ (chunkers, embedder,
# CLI ingest.py) ne sont pas utilisables ici, leurs dépendances propres
# (ingest/requirements.txt) ne sont pas installées dans cette image.
COPY ingest/__init__.py ./ingest/__init__.py
COPY ingest/indexer.py ./ingest/indexer.py

# Utilisé uniquement par api/scripts/import_legacykb.py (Container Apps Job,
# AUDIT-2026-06) -- même image que ca-api, réutilisée pour l'import legacykb
# désormais exécuté depuis l'intérieur du VNet plutôt que depuis le poste de
# l'opérateur (cf. import-neo4j-legacykb.ps1).
COPY fix_utf8.cypher ./fix_utf8.cypher

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
