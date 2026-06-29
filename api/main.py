import html as _html
import logging
import mimetypes
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

# Enregistrement explicite des MIME types — nécessaire sur Windows où le registre
# ne les déclare pas toujours (sans cela, X-Content-Type-Options: nosniff bloque les scripts)
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".jsx")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/plain", ".md")

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.routers.chat import router as chat_router
from api.routers.ingest import router as ingest_router
from api.routers.legacykb import router as legacykb_router
from api.routers.sources import router as sources_router
from api.services.retriever import Retriever
from api.services.generator import Generator
from api.services import session_store

# Chemin explicite -- sans argument, find_dotenv() remonte depuis le dossier de CE
# fichier (api/), pas depuis le cwd : il trouve api/.env (legacy, désynchronisé) avant
# d'atteindre le .env racine généré par deploy.ps1, qui ne serait alors jamais chargé.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Middleware : headers de sécurité HTTP ─────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # AUDIT-2026-06 : neo4j-legacykb n'a plus d'IP publique -- le frontend local appelle
        # ca-api (NOTEBOOKLM_API_URL) en direct pour /api/legacykb/* (cf. Header.jsx,
        # LegacyKbPage.jsx). Sans cet ajout à connect-src, le navigateur bloque ces appels
        # même une fois le JS à jour chargé (CSP, pas juste CORS). N'a d'effet qu'en local :
        # cette route/middleware ne s'exécute jamais en production (pas de frontend déployé).
        legacykb_api_url = os.environ.get("NOTEBOOKLM_API_URL", "")
        connect_src = "connect-src 'self'" + (f" {legacykb_api_url}" if legacykb_api_url else "") + "; "
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            # 'unsafe-inline' requis par Babel standalone (transpilation dans le navigateur).
            # 'unsafe-eval' requis par Babel standalone (new Function() pour exécuter le code transpilé).
            # Les CDNs externes (unpkg, jsdelivr) ont été retirés — toutes les dépendances sont vendorisées.
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            + connect_src +
            "frame-ancestors 'none';"
        )
        # HSTS : force HTTPS pour les navigateurs qui ont déjà chargé la page en HTTPS.
        # Ignoré silencieusement sur HTTP (dev local) — envoyé en production (Azure).
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ── Middleware : authentification par API Key ─────────────────────────────────

_UNPROTECTED_PREFIXES = ("/health",)
_STATIC_PREFIX = "/api/"


def _running_in_azure() -> bool:
    return bool(os.environ.get("WEBSITE_INSTANCE_ID") or os.environ.get("CONTAINER_APP_NAME"))


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Préflight CORS : toujours laissé passer sans auth (ne transporte aucune donnée,
        # le navigateur l'envoie avant la vraie requête). APIKeyMiddleware s'exécute avant
        # CORSMiddleware (Starlette empile les middlewares dans l'ordre inverse de
        # add_middleware -- le dernier ajouté est le plus interne) : sans ce contournement,
        # le navigateur reçoit un 401 au lieu des en-têtes CORS et bloque la vraie requête
        # (AUDIT-2026-06, découvert en activant CORS pour la première fois).
        if request.method == "OPTIONS":
            return await call_next(request)

        # Liveness probe et assets statiques ne nécessitent pas d'auth
        if not path.startswith(_STATIC_PREFIX) or any(
            path.startswith(p) for p in _UNPROTECTED_PREFIXES
        ):
            return await call_next(request)

        # Lecture lazily à chaque requête — permet que Key Vault ait chargé la clé au startup
        api_key = os.environ.get("API_KEY", "")
        if not api_key:
            # Fail-closed en production (AUDIT-2026-06 finding critique : un échec silencieux
            # du chargement Key Vault ouvrait auparavant l'API sans authentification). En local,
            # on garde le fail-open pour le confort de développement (cf. avertissement au démarrage).
            if _running_in_azure():
                return JSONResponse(status_code=503, content={"detail": "Service indisponible (clé API non chargée)."})
            return await call_next(request)

        # Accepte Authorization: Bearer <key> ou X-API-Key: <key>
        auth_header = request.headers.get("Authorization", "")
        x_api_key = request.headers.get("X-API-Key", "")
        provided = ""
        if auth_header.startswith("Bearer "):
            provided = auth_header[7:]
        elif x_api_key:
            provided = x_api_key

        if not provided or not secrets.compare_digest(provided, api_key):
            # Lever HTTPException ici ne serait pas converti en réponse JSON propre :
            # BaseHTTPMiddleware.dispatch() est en dehors du middleware de gestion
            # d'exceptions de Starlette, donc l'exception remonterait en 500 brut.
            return JSONResponse(status_code=401, content={"detail": "Non autorisé."})

        return await call_next(request)


# ── Key Vault ─────────────────────────────────────────────────────────────────

def _load_secrets_from_keyvault():
    kv_uri = os.environ.get("AZURE_KEYVAULT_URI")
    if not kv_uri:
        logger.info("AZURE_KEYVAULT_URI non défini — utilisation des variables d'environnement locales.")
        return

    try:
        client_id = os.environ.get("AZURE_CLIENT_ID")
        if client_id and _running_in_azure():
            credential = ManagedIdentityCredential(client_id=client_id)
        else:
            credential = DefaultAzureCredential()
        kv_client = SecretClient(vault_url=kv_uri, credential=credential)

        secret_map = {
            "openai-endpoint": "AZURE_OPENAI_ENDPOINT",
            "search-endpoint": "AZURE_SEARCH_ENDPOINT",
            "docint-endpoint": "AZURE_DOCINT_ENDPOINT",
            "storage-account-name": "AZURE_STORAGE_ACCOUNT_NAME",
            "neo4j-legacykb-password": "NEO4J_LEGACYKB_PASSWORD",
            "api-key": "API_KEY",
        }

        for secret_name, env_var in secret_map.items():
            if not os.environ.get(env_var):
                try:
                    value = kv_client.get_secret(secret_name).value
                    os.environ[env_var] = value
                    logger.info(f"Secret '{secret_name}' chargé depuis Key Vault.")
                except Exception as e:
                    logger.warning(f"Impossible de charger '{secret_name}': {e}")
    except Exception as e:
        logger.warning(f"Key Vault non accessible: {e}")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_secrets_from_keyvault()
    if not os.environ.get("API_KEY"):
        if _running_in_azure():
            logger.warning("API_KEY non chargée — l'API refusera toutes les requêtes /api/* (fail-closed) jusqu'à résolution.")
        else:
            logger.warning("API_KEY non défini — authentification désactivée (mode développement local).")
    session_store.init_db()

    client_id = os.environ.get("AZURE_CLIENT_ID")
    if client_id and _running_in_azure():
        credential = ManagedIdentityCredential(client_id=client_id)
    else:
        credential = DefaultAzureCredential()

    app.state.credential = credential
    app.state.retriever = Retriever(credential)
    app.state.generator = Generator(credential)
    logger.info("API NotebookLM Azure démarrée.")
    yield
    logger.info("Arrêt de l'API.")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(title="NotebookLM Azure — API RAG", version="1.0.0", lifespan=lifespan)

# Ordre important : SecurityHeaders en premier, puis APIKey, puis CORS
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(APIKeyMiddleware)

# CORS restreint à l'origine propre du frontend (pas de wildcard)
_allowed_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]
if _allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )

app.include_router(chat_router,        prefix="/api")
app.include_router(ingest_router,      prefix="/api")
app.include_router(legacykb_router,    prefix="/api")
app.include_router(sources_router,     prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notebooklm-api"}


frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")

if os.path.exists(frontend_dir):
    @app.get("/", response_class=Response, include_in_schema=False)
    async def index():
        """Sert index.html avec l'API key injectée comme <meta>.
        N'existe qu'en local : l'image Docker déployée sur Azure ne contient
        pas frontend/ (cf. api/Dockerfile), donc cette route et le mount
        StaticFiles ci-dessous ne sont jamais actifs en production — le
        Container App ne sert que l'API JSON, jamais de page web publique."""
        index_path = os.path.join(frontend_dir, "index.html")
        with open(index_path, encoding="utf-8") as f:
            content = f.read()
        api_key = os.environ.get("API_KEY", "")
        meta = f'  <meta name="nlaz-api-key" content="{_html.escape(api_key, quote=True)}">\n'
        # AUDIT-2026-06 : neo4j-legacykb n'a plus d'IP publique -- ce backend local ne peut
        # plus l'atteindre directement. Le frontend appelle ca-api (intégré au VNet) en
        # direct pour les routes /api/legacykb/* (cf. Header.jsx, LegacyKbPage.jsx).
        legacykb_api_url = os.environ.get("NOTEBOOKLM_API_URL", "")
        if legacykb_api_url:
            meta += f'  <meta name="nlaz-legacykb-api-url" content="{_html.escape(legacykb_api_url, quote=True)}">\n'
        content = content.replace("</head>", meta + "</head>", 1)
        return Response(content=content, media_type="text/html")

    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
