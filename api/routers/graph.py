import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()
logger = logging.getLogger(__name__)

# fn-adgm-graph (Azure Function, authLevel: anonymous) ne peut pas être appelée
# directement depuis le navigateur : la CSP du frontend est connect-src 'self' et le
# CORS n'autorise que sa propre origine. Ce proxy relaie donc /api/graph/* vers la
# Function en server-to-server (pas de souci CORS/CSP) ; il surfe sur l'APIKeyMiddleware
# déjà en place pour /api/* et n'ajoute aucune auth supplémentaire vers la Function,
# qui est déjà anonyme.
_BASE_URL = os.environ.get(
    "ADGM_GRAPH_API_URL",
    "https://modernagent-adgm-dev.azurewebsites.net/api/graph",
).rstrip("/")

# Seuls GET (consultation : health, nodes, arcs, clusters, impact) et PATCH
# (qualification 7R) sont relayés — POST /admin/analyze n'est pas exposé via ce proxy,
# il est déclenché en server-to-server par api/routers/extract.py à la fin du job
# d'extraction (bouton "Mettre à jour"), pas directement par le frontend.


async def _forward(method: str, path: str, request: Request) -> Response:
    url = f"{_BASE_URL}/{path}"
    body = await request.body()
    headers = {}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.request(
                method,
                url,
                params=request.query_params,
                content=body or None,
                headers=headers or None,
            )
    except httpx.RequestError:
        logger.exception("fn-adgm-graph injoignable (%s %s)", method, url)
        raise HTTPException(502, detail="Service graphe ADG-M injoignable.")

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@router.get("/graph/{path:path}")
async def proxy_graph_get(path: str, request: Request):
    return await _forward("GET", path, request)


@router.patch("/graph/{path:path}")
async def proxy_graph_patch(path: str, request: Request):
    return await _forward("PATCH", path, request)


@router.delete("/graph/{path:path}")
async def proxy_graph_delete(path: str, request: Request):
    return await _forward("DELETE", path, request)
